"""
One validator per dataset. Each returns (result_dict, cleaned_df).

result_dict = {
    "dataset": str,
    "status": "pass" | "warn" | "fail",
    "row_count": int,
    "issues": [{"severity": "fixable" | "review_needed", "message": str,
                "fixed": bool}],
}

Severity policy:
  fixable       — mechanical and safe to auto-correct (out-of-bbox points,
                  duplicate rows, below-threshold events, wrong dtypes).
                  Corrected in cleaned_df ONLY when fix=True.
  review_needed — requires a human judgment call (missing values, implausible
                  physical values, row counts >tolerance off the documented
                  expectation). NEVER auto-dropped, interpolated or fabricated.

Status: fail = file missing/unreadable or a review_needed issue that makes the
dataset unusable; warn = any open issue; pass = clean.
"""

import os

import numpy as np
import pandas as pd


def _issue(severity, message, fixed=False):
    return {"severity": severity, "message": message, "fixed": fixed}


def _result(dataset, df, issues, failed=False):
    if failed:
        status = "fail"
    elif any(not i["fixed"] for i in issues):
        status = "warn"
    else:
        status = "pass"
    return {
        "dataset": dataset,
        "status": status,
        "row_count": 0 if df is None else len(df),
        "issues": issues,
    }


def _load(path, dataset):
    if not os.path.exists(path):
        return None, _result(dataset, None,
                             [_issue("review_needed", f"output file missing: {path}")],
                             failed=True)
    return pd.read_csv(path), None


def _check_row_count(issues, df, expected, tolerance, label):
    if expected is None:
        return
    dev = abs(len(df) - expected) / expected
    if dev > tolerance:
        issues.append(_issue(
            "review_needed",
            f"row count {len(df)} deviates {dev:.0%} from documented "
            f"expectation {expected} ({label}) — verify before use",
        ))


def _check_bbox(issues, df, bbox, fix, lat_col="latitude", lon_col="longitude"):
    """Out-of-bbox points are mechanical errors (bad geocode) — fixable."""
    mask = (
        df[lat_col].between(bbox["south"], bbox["north"])
        & df[lon_col].between(bbox["west"], bbox["east"])
    )
    n_bad = int((~mask).sum())
    if n_bad:
        issues.append(_issue("fixable", f"{n_bad} rows outside study bbox", fixed=fix))
        if fix:
            df = df[mask].copy()
    return df

def _check_duplicates(issues, df, subset, fix):
    n_dup = int(df.duplicated(subset=subset).sum())
    if n_dup:
        issues.append(_issue("fixable", f"{n_dup} duplicate rows on {subset}", fixed=fix))
        if fix:
            df = df.drop_duplicates(subset=subset).copy()
    return df


def _check_missing(issues, df, cols):
    for col in cols:
        if col not in df.columns:
            issues.append(_issue("review_needed", f"required column missing: {col}"))
            continue
        n = int(df[col].isna().sum())
        if n:
            issues.append(_issue("review_needed", f"{n} missing values in '{col}'"))


def validate_aftershock_catalog(config, fix=False):
    ds = "aftershock_catalog"
    df, err = _load(config["paths"]["out_catalog"], ds)
    if err:
        return err, None
    issues = []
    ev = config["event"]

    _check_missing(issues, df, ["latitude", "longitude", "magnitude", "time_utc"])
    df = _check_bbox(issues, df, config["study_area"]["bbox"], fix)
    df = _check_duplicates(issues, df, ["event_id"], fix)

    # below-completeness events are mechanical filter leakage — fixable
    n_small = int((df["magnitude"] < ev["min_magnitude"]).sum())
    if n_small:
        issues.append(_issue("fixable",
                             f"{n_small} events below Mc={ev['min_magnitude']}", fixed=fix))
        if fix:
            df = df[df["magnitude"] >= ev["min_magnitude"]].copy()

    # events at/after the mainshock only
    t0 = pd.to_datetime(ev["mainshock_utc"], utc=True)
    # USGS timestamps mix fractional and whole seconds — ISO8601 handles both
    times = pd.to_datetime(df["time_utc"], utc=True, format="ISO8601")
    n_pre = int((times <= t0).sum())
    if n_pre:
        issues.append(_issue("fixable", f"{n_pre} events at/before mainshock", fixed=fix))
        if fix:
            df = df[times > t0].copy()

    if (df["magnitude"] > ev["max_aftershock_magnitude"]).any():
        issues.append(_issue("review_needed",
                             "events above max aftershock magnitude present "
                             "(mainshock leakage?)"))
    return _result(ds, df, issues), df


def validate_candidate_sites(config, fix=False):
    ds = "candidate_sites"
    df, err = _load(config["paths"]["out_sites"], ds)
    if err:
        return err, None
    issues = []
    exp = config["expected_counts"]

    _check_missing(issues, df, ["site_id", "latitude", "longitude", "facility_type"])
    df = _check_bbox(issues, df, config["study_area"]["province_bbox"], fix)
    df = _check_duplicates(issues, df, ["latitude", "longitude"], fix)
    if df["site_id"].duplicated().any():
        issues.append(_issue("review_needed", "duplicate site_id values — downstream "
                                              "joins will collapse rows"))
    _check_row_count(issues, df, exp["candidate_sites"], exp["row_count_tolerance"], ds)
    return _result(ds, df, issues), df


def validate_sites_aoi04(config, fix=False):
    ds = "sites_aoi04"
    df, err = _load(config["paths"]["out_sites_aoi04"], ds)
    if err:
        return err, None
    issues = []
    exp = config["expected_counts"]
    _check_missing(issues, df, ["site_id", "latitude", "longitude"])
    _check_row_count(issues, df, exp["sites_aoi04"], exp["row_count_tolerance"], ds)
    return _result(ds, df, issues), df


def _validate_per_site_table(config, ds, path, value_checks, fix=False):
    """Shared shape for the per-site attribute tables (vs30/slope/roads):
    must cover every candidate site exactly once."""
    df, err = _load(path, ds)
    if err:
        return err, None
    issues = []
    df = _check_duplicates(issues, df, ["site_id"], fix)

    sites_path = config["paths"]["out_sites"]
    if os.path.exists(sites_path):
        site_ids = set(pd.read_csv(sites_path)["site_id"])
        missing = site_ids - set(df["site_id"])
        extra = set(df["site_id"]) - site_ids
        if missing:
            issues.append(_issue("review_needed",
                                 f"{len(missing)} candidate sites have no row here — "
                                 "re-run this extractor after sites changed"))
        if extra:
            issues.append(_issue("review_needed",
                                 f"{len(extra)} rows reference unknown site_ids"))

    for col, lo, hi in value_checks:
        if col not in df.columns:
            issues.append(_issue("review_needed", f"required column missing: {col}"))
            continue
        n_nan = int(df[col].isna().sum())
        if n_nan:
            issues.append(_issue("review_needed", f"{n_nan} missing values in '{col}'"))
        bad = df[col].dropna()
        n_bad = int(((bad < lo) | (bad > hi)).sum())
        if n_bad:
            issues.append(_issue("review_needed",
                                 f"{n_bad} physically implausible '{col}' values "
                                 f"(outside [{lo}, {hi}])"))
    return _result(ds, df, issues), df


def validate_vs30(config, fix=False):
    lo, hi = config["vs30"]["plausible_range_ms"]
    return _validate_per_site_table(config, "vs30_by_site",
                                    config["paths"]["out_vs30"],
                                    [("vs30_ms", lo, hi)], fix)


def validate_topography(config, fix=False):
    # Elevation: Dead Sea to well above regional peaks; slope 0–60°
    return _validate_per_site_table(config, "slope_by_site",
                                    config["paths"]["out_topography"],
                                    [("elevation_m", -100, 4000), ("slope_deg", 0, 60)], fix)


def validate_accessibility(config, fix=False):
    # 20 km to the nearest road inside a city bbox means the road graph
    # didn't cover the site — review, don't fabricate
    return _validate_per_site_table(config, "road_network",
                                    config["paths"]["out_accessibility"],
                                    [("dist_to_road_m", 0, 20000)], fix)


def validate_damage(config, fix=False):
    ds = "building_damage"
    df, err = _load(config["paths"]["out_damage"], ds)
    if err:
        return err, None
    issues = []
    df = _check_duplicates(issues, df, ["site_id"], fix)

    if "in_aoi" in df.columns:
        # damage grades are only valid inside AOI04 — outside must stay NaN
        outside = df[~df["in_aoi"].astype(bool)]
        fabricated = int(outside["damage_score"].notna().sum())
        if fabricated:
            issues.append(_issue("review_needed",
                                 f"{fabricated} sites OUTSIDE AOI04 carry damage values — "
                                 "these are not covered by Copernicus and must be NaN"))
        inside = df[df["in_aoi"].astype(bool)]
        n_nan = int(inside["damage_score"].isna().sum())
        if n_nan:
            issues.append(_issue("review_needed",
                                 f"{n_nan} in-AOI sites missing damage_score"))
    else:
        issues.append(_issue("review_needed", "required column missing: in_aoi"))
    return _result(ds, df, issues), df


def validate_hospitals(config, fix=False):
    ds = "hospitals"
    df, err = _load(config["paths"]["out_hospitals"], ds)
    if err:
        return err, None
    issues = []
    exp = config["expected_counts"]

    _check_missing(issues, df, ["hospital_id", "hospital_name", "latitude",
                                "longitude", "bed_capacity_total"])
    df = _check_bbox(issues, df, config["study_area"]["bbox"], fix)
    if df["hospital_id"].duplicated().any():
        issues.append(_issue("review_needed", "duplicate hospital_id values"))

    if (df["bed_capacity_total"] <= 0).any():
        issues.append(_issue("review_needed", "non-positive bed capacities present"))

    if "capacity_confidence" in df.columns:
        n_est = int((df["capacity_confidence"] == "estimated").sum())
        if n_est:
            issues.append(_issue("review_needed",
                                 f"{n_est} facilities have ESTIMATED capacity (no published "
                                 "figure) — see data_raw/hospitals/hospital_capacity_curated.csv"))
    else:
        issues.append(_issue("review_needed",
                             "no capacity_confidence column — capacity provenance unknown"))

    if "effective_capacity_postquake" in df.columns:
        n_closed = int((df["effective_capacity_postquake"] == 0).sum())
        if n_closed:
            issues.append(_issue("review_needed",
                                 f"{n_closed} facility(ies) closed by earthquake damage — "
                                 "solver must use effective_capacity_postquake, not "
                                 "bed_capacity_total"))
    _check_row_count(issues, df, exp["hospitals"], exp["row_count_tolerance"], ds)
    return _result(ds, df, issues), df


def validate_sub_districts(config, fix=False):
    ds = "sub_districts"
    df, err = _load(config["paths"]["out_sub_districts"], ds)
    if err:
        return err, None
    issues = []
    exp = config["expected_counts"]
    _check_missing(issues, df, ["sub_district_id", "name", "population"])
    df = _check_duplicates(issues, df, ["name"], fix)
    if "population" in df.columns and (pd.to_numeric(df["population"], errors="coerce") <= 0).any():
        issues.append(_issue("review_needed", "non-positive populations present"))
    _check_row_count(issues, df, exp["sub_districts"], exp["row_count_tolerance"], ds)
    return _result(ds, df, issues), df


def validate_casualties(config, fix=False):
    ds = "casualties"
    df, err = _load(config["paths"]["out_casualties"], ds)
    if err:
        return err, None
    issues = []
    count_cols = ["T1_count", "T2_count", "T3_count", "dead_count"]
    _check_missing(issues, df, ["sub_district_id", "scenario_id", "period"] + count_cols)
    for col in count_cols:
        if col in df.columns and (df[col] < 0).any():
            issues.append(_issue("review_needed", f"negative values in '{col}'"))
    if "scenario_prob" in df.columns:
        per_scenario = df.groupby("scenario_id")["scenario_prob"].first()
        if not np.isclose(per_scenario.sum(), 1.0, atol=1e-6):
            issues.append(_issue("review_needed",
                                 f"scenario probabilities sum to {per_scenario.sum():.4f}, "
                                 "expected 1.0"))
    return _result(ds, df, issues), df


# dataset name -> (validator, output path key) — the output path is where the
# fixed dataframe is written back when --fix is active
VALIDATORS = {
    "earthquake_catalog": (validate_aftershock_catalog, "out_catalog"),
    "candidate_sites": (validate_candidate_sites, "out_sites"),
    "sites_aoi04": (validate_sites_aoi04, "out_sites_aoi04"),
    "slope_by_site": (validate_topography, "out_topography"),
    "road_network": (validate_accessibility, "out_accessibility"),
    "vs30_by_site": (validate_vs30, "out_vs30"),
    "building_damage": (validate_damage, "out_damage"),
    "hospitals": (validate_hospitals, "out_hospitals"),
    "sub_districts": (validate_sub_districts, "out_sub_districts"),
    "casualties": (validate_casualties, "out_casualties"),
}
