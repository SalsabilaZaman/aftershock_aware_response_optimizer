import sys
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import pandas as pd


def haversine_km(lat1, lon1, lat2, lon2):
    """Duplicated from deterministic_current/prep_support.py rather than
    imported: that module's own settings import falls back to a bare
    `from settings import ...` when run as a direct script, and since this
    package's settings.py is also importable under the bare name "settings"
    (same direct-script convention), a cross-package import would silently
    pick up the wrong settings module. Not worth a sys.modules hack for a
    5-line pure function."""
    radius_km = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return radius_km * 2 * asin(sqrt(a))

try:
    from .settings import (
        CASUALTY_PROJECTIONS_PATH,
        DAMAGE_INDICATORS_PATH,
        DETERMINISTIC_INPUT_DIR,
        DETERMINISTIC_OUTPUT_DIR,
        HOSPITAL_DAMAGE_MAX_FRACTION,
        HOSPITAL_DATA_PATH,
        PERIODS,
        ROAD_DAMAGE_RATIO_MAX,
        SCENARIOS_USED,
        SCENARIO_PROB,
        TMC_OUTPATIENT_CAPACITY_MULTIPLIER,
        TOPSIS_RANKING_PATH,
        TMC_CANDIDATE_LIMIT,
        TRIAGE,
    )
except ImportError:  # pragma: no cover - allows direct script execution
    from settings import (
        CASUALTY_PROJECTIONS_PATH,
        DAMAGE_INDICATORS_PATH,
        DETERMINISTIC_INPUT_DIR,
        DETERMINISTIC_OUTPUT_DIR,
        HOSPITAL_DAMAGE_MAX_FRACTION,
        HOSPITAL_DATA_PATH,
        PERIODS,
        ROAD_DAMAGE_RATIO_MAX,
        SCENARIOS_USED,
        SCENARIO_PROB,
        TMC_OUTPATIENT_CAPACITY_MULTIPLIER,
        TOPSIS_RANKING_PATH,
        TMC_CANDIDATE_LIMIT,
        TRIAGE,
    )


def load_fixed_network():
    """Load existing hospitals, the full TMC candidate set, and demand sites."""
    tmc_path = DETERMINISTIC_INPUT_DIR / "candidates_jt.csv"
    jh_path = DETERMINISTIC_INPUT_DIR / "hospitals_jh.csv"
    demand_path = DETERMINISTIC_INPUT_DIR / "demand_points.csv"
    for p in (tmc_path, jh_path, demand_path):
        if not p.exists():
            sys.exit(
                f"\n[ERROR] {p} not found. Run pipelines/deterministic_current/"
                f"step1_prepare_data.py and step2_solve_model.py (MODEL_MODE=risk_aware) first "
                f"-- stochastic optimization requires the prepared candidate set."
            )

    jt_df = pd.read_csv(tmc_path)
    jh_df = pd.read_csv(jh_path)
    demand_df = pd.read_csv(demand_path)

    hospitals = pd.read_csv(
        HOSPITAL_DATA_PATH,
        usecols=["hospital_id", "n_doctors_pre", "n_nurses_pre", "outpatient_capacity"],
    )
    jh_df = jh_df.merge(hospitals, on="hospital_id", how="left")
    return jh_df, jt_df, demand_df


def load_scenario_casualties():
    """New-casualty inflow per (sub_district, triage, period, scenario).

    casualty_projections.csv's per-period T1/T2/T3 counts already sum to the
    PDF's own periodisation rates rho=(0.60,0.25,0.10,0.05) -- confirmed by
    inspection, e.g. SD001 scenario 1's four periods are 5493/2287/914/456,
    which is (0.600, 0.250, 0.100, 0.050) of the 9150 total. These are
    per-period NEW casualty inflows (PDF eq. 42-45's T1^s_ip / T2^s_ip /
    T3^s_ip terms), not cumulative totals.
    """
    cas = pd.read_csv(CASUALTY_PROJECTIONS_PATH)
    cas = cas[cas["scenario_id"].isin(SCENARIOS_USED)]
    cas = cas[cas["period"].isin(PERIODS)]
    long = cas.melt(
        id_vars=["sub_district_id", "scenario_id", "period"],
        value_vars=["T1_count", "T2_count", "T3_count"],
        var_name="triage",
        value_name="new_casualties",
    )
    long["triage"] = long["triage"].str.replace("_count", "", regex=False)
    return {
        (r.sub_district_id, r.triage, int(r.period), int(r.scenario_id)): float(r.new_casualties)
        for r in long.itertuples()
    }


def severity_factor(scenario_id, dead_count_by_scenario):
    """Scenario severity in [0, 1], scaled by total dead_count relative to
    the most severe scenario retained in SCENARIOS_USED. Used for both
    ROAD_DAMAGE_RATIO_MAX and HOSPITAL_DAMAGE_MAX_FRACTION scaling."""
    worst = max(dead_count_by_scenario.values())
    return dead_count_by_scenario[scenario_id] / worst if worst > 0 else 0.0


def load_severity_by_scenario():
    cas = pd.read_csv(CASUALTY_PROJECTIONS_PATH, usecols=["scenario_id", "dead_count"])
    cas = cas[cas["scenario_id"].isin(SCENARIOS_USED)]
    return cas.groupby("scenario_id")["dead_count"].sum().to_dict()


def build_road_damage_ratios():
    """f^s_ij (PDF eq. 34) -- one scalar per scenario, applied uniformly to
    every (i,j) pair in that scenario (see settings.ROAD_DAMAGE_RATIO_MAX
    docstring for why this is a documented per-scenario, not per-edge,
    approximation)."""
    dead_by_scenario = load_severity_by_scenario()
    return {
        s: ROAD_DAMAGE_RATIO_MAX * severity_factor(s, dead_by_scenario)
        for s in SCENARIOS_USED
    }


def build_hospital_damage_factors(jh_df):
    """g^s_j (PDF eq. 40) per hospital per scenario, combining the real
    damage_indicators_per_site.csv damage_score (via each hospital's
    matched_site_id from the deterministic prep step) with per-scenario
    severity scaling."""
    dead_by_scenario = load_severity_by_scenario()
    damage = pd.read_csv(DAMAGE_INDICATORS_PATH, usecols=["site_id", "damage_score"])
    jh_damage = jh_df[["site_id", "matched_site_id"]].merge(
        damage, left_on="matched_site_id", right_on="site_id", how="left", suffixes=("", "_matched")
    )
    jh_damage["damage_score"] = jh_damage["damage_score"].fillna(1.0)  # unmatched: assume undamaged area
    site_local_damage = dict(zip(jh_damage["site_id"], 1.0 - jh_damage["damage_score"]))

    factors = {}
    for j, local_damage in site_local_damage.items():
        for s in SCENARIOS_USED:
            factors[(j, s)] = local_damage * HOSPITAL_DAMAGE_MAX_FRACTION * severity_factor(s, dead_by_scenario)
    return factors


def build_capacity(jh_df, jt_df, damage_factors, scenario_ids=None):
    """Cap^1s_jk (PDF eq. 39-40) -- post-disaster capacity per facility per
    scenario. Held constant across all 4 periods within a scenario (the
    per-period bed-occupancy recursion of eq. 41 is not modelled -- see
    docs/STOCHASTIC_MODEL.md simplification S2).

    Returns cap1 (T1+T2 pool) and cap2 (T3/outpatient pool), both
    {(site_id, scenario_id): float}.
    """
    scenario_ids = list(scenario_ids or SCENARIOS_USED)
    cap1, cap2 = {}, {}
    for _, r in jh_df.iterrows():
        for s in scenario_ids:
            g = damage_factors.get((r["site_id"], s), 0.0)
            cap1[(r["site_id"], s)] = r["cap_j"] * (1 - g)
            outpatient = r["outpatient_capacity"] if pd.notna(r["outpatient_capacity"]) else r["cap_j"] * TMC_OUTPATIENT_CAPACITY_MULTIPLIER
            cap2[(r["site_id"], s)] = outpatient * (1 - g)
    for _, r in jt_df.iterrows():
        for s in scenario_ids:
            # TMCs are newly sited post-quake tented facilities, not
            # pre-existing structures with earthquake damage exposure --
            # capacity is not scaled by g^s (see settings.py TMC_OUTPATIENT_
            # CAPACITY_MULTIPLIER docstring).
            cap1[(r["site_id"], s)] = r["cap_j"]
            cap2[(r["site_id"], s)] = r["cap_j"] * TMC_OUTPATIENT_CAPACITY_MULTIPLIER
    return cap1, cap2


def build_distance_lookup(demand_df, jh_df, jt_df):
    all_fac = pd.concat(
        [jh_df[["site_id", "latitude", "longitude"]], jt_df[["site_id", "latitude", "longitude"]]],
        ignore_index=True,
    )
    dist = {}
    for _, d in demand_df.iterrows():
        for _, f in all_fac.iterrows():
            dist[(d["sub_district_id"], f["site_id"])] = haversine_km(
                d["latitude"], d["longitude"], f["latitude"], f["longitude"]
            )
    return dist


def screen_tmc_candidates(jt_df, limit=None):
    """Keep top CC_i TOPSIS sites; ties are broken by stable site_id order."""
    if not TOPSIS_RANKING_PATH.exists():
        raise FileNotFoundError(
            f"TOPSIS ranking not found: {TOPSIS_RANKING_PATH}. "
            "Run pipelines/psaha/step5_ahp_topsis.py first."
        )
    ranking = pd.read_csv(TOPSIS_RANKING_PATH, usecols=["site_id", "CC_i"])
    ranked = jt_df.merge(ranking, on="site_id", how="inner")
    if ranked.empty:
        raise ValueError("TOPSIS ranking has no overlap with prepared TMC candidates")
    return (ranked.sort_values(["CC_i", "site_id"], ascending=[False, True])
            .head(TMC_CANDIDATE_LIMIT if limit is None else int(limit))
            .drop(columns="CC_i")
            .reset_index(drop=True))


def select_tmc_candidates(jt_df, candidate_pool="topsis"):
    """Return either all prepared TMCs or the configured TOPSIS shortlist."""
    if candidate_pool == "all":
        return jt_df.copy().reset_index(drop=True)
    if candidate_pool == "topsis":
        return screen_tmc_candidates(jt_df)
    raise ValueError("candidate_pool must be 'all' or 'topsis'")
