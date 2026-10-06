import json
import os
import sys
import time
from math import asin, cos, radians, sin, sqrt

import pandas as pd

try:
    from .settings import (
        APPLY_PGA_FILTER,
        CACHE_FILE,
        DATA_DIR,
        DATA_FILE_CANDIDATES,
        HOSPITAL_MATCH_RADIUS_KM,
        INPUT_DIR,
        PERIODS,
        PGA_MAX,
        PSAHA_OUTPUT_DIR,
        SCENARIO_ID,
        OPENING_PENALTY_CASUALTY_KM,
        SHELTER_AREA_PER_PERSON_M2,
        TMC_CAPACITY_BY_TYPE,
        TMC_MAX_CAPACITY,
        TMC_MIN_CAPACITY,
    )
except ImportError:  # pragma: no cover - allows direct script execution
    from settings import (
        APPLY_PGA_FILTER,
        CACHE_FILE,
        DATA_DIR,
        DATA_FILE_CANDIDATES,
        HOSPITAL_MATCH_RADIUS_KM,
        INPUT_DIR,
        PERIODS,
        PGA_MAX,
        PSAHA_OUTPUT_DIR,
        SCENARIO_ID,
        OPENING_PENALTY_CASUALTY_KM,
        SHELTER_AREA_PER_PERSON_M2,
        TMC_CAPACITY_BY_TYPE,
        TMC_MAX_CAPACITY,
        TMC_MIN_CAPACITY,
    )


def haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return radius_km * 2 * asin(sqrt(a))


def load_data_csv(filename, required_cols=None):
    candidates = []
    if DATA_DIR:
        candidates.append(os.path.join(DATA_DIR, filename))
    for candidate in DATA_FILE_CANDIDATES.get(filename, []):
        candidates.append(str(candidate))
    for candidate in candidates:
        if os.path.exists(candidate):
            path = candidate
            break
    else:
        sys.exit(f"\n[ERROR] File not found: {filename}. Tried: {candidates}")
    df = pd.read_csv(path)
    missing = [c for c in (required_cols or []) if c not in df.columns]
    if missing:
        sys.exit(f"\n[ERROR] {filename} missing columns: {missing}\nFound: {list(df.columns)}")
    return df


def assert_unique(df, column, label):
    duplicates = df[df[column].duplicated(keep=False)]
    if not duplicates.empty:
        raise ValueError(f"{label} has duplicate {column} values:\n{duplicates.sort_values(column)}")


def load_raw_inputs():
    return {
        "sub_districts": load_data_csv("sub_districts_raw.csv", ["sub_district_id", "name", "population"]),
        "casualties": load_data_csv(
            "casualty_projections.csv",
            ["sub_district_id", "scenario_id", "period", "T1_count", "T2_count", "T3_count"],
        ),
        "sites": load_data_csv("candidate_sites.csv", ["site_id", "latitude", "longitude", "facility_type"]),
        "site_area": load_data_csv("site_area_per_site.csv", ["site_id", "site_area_m2"]),
        "hospitals": load_data_csv(
            "hospital_data.csv",
            ["hospital_id", "hospital_name", "latitude", "longitude", "bed_capacity_total"],
        ),
    }


def load_optional_psaha():
    psaha_path = os.path.join(PSAHA_OUTPUT_DIR, "psaha_output_per_site.csv")
    if not os.path.exists(psaha_path):
        return None, None
    psaha = pd.read_csv(psaha_path)
    pga_col = next((c for c in psaha.columns if "pga" in c.lower()), None)
    return psaha, pga_col


def geocode_district(name, cache):
    if name in cache:
        return cache[name]["lat"], cache[name]["lon"]
    try:
        from geopy.geocoders import Nominatim

        geolocator = Nominatim(user_agent="facility_location_v2")
        query = f"{name}, Kahramanmaras, Turkey"
        time.sleep(1.1)
        loc = geolocator.geocode(query, timeout=10)
        if loc:
            cache[name] = {"lat": loc.latitude, "lon": loc.longitude}
            return loc.latitude, loc.longitude
    except Exception as exc:
        print(f"  Geocoding error for {name}: {exc}; using province centre")

    cache[name] = {"lat": 37.575, "lon": 36.937}
    return 37.575, 36.937


def add_demand_coordinates(sub_districts):
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        print(f"  Cache entries: {len(cache)}")

    rows = sub_districts.copy()
    coords = [geocode_district(row["name"], cache) for _, row in rows.iterrows()]
    rows["latitude"] = [lat for lat, _ in coords]
    rows["longitude"] = [lon for _, lon in coords]
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    return rows


def build_demand_points(sub_districts, casualties):
    cas_s = casualties[casualties["scenario_id"] == SCENARIO_ID].copy()
    if PERIODS is not None:
        cas_s = cas_s[cas_s["period"].isin(PERIODS)]
    cas_s["total_casualties"] = cas_s["T1_count"] + cas_s["T2_count"] + cas_s["T3_count"]
    pop_agg = (
        cas_s.groupby("sub_district_id")["total_casualties"]
        .sum()
        .reset_index()
        .rename(columns={"total_casualties": "pop_i"})
    )
    demand = sub_districts.merge(pop_agg, on="sub_district_id", how="left")
    demand["pop_i"] = demand["pop_i"].fillna(0).astype(int)
    return demand[["sub_district_id", "name", "latitude", "longitude", "population", "pop_i"]]


def match_quality(distance_km):
    if distance_km == float("inf"):
        return "unmatched"
    if distance_km <= 2:
        return "direct"
    if distance_km <= HOSPITAL_MATCH_RADIUS_KM:
        return "broad_radius"
    return "outside_radius"


def find_nearest_osm_hospital(hosp, osm_hosps):
    best_dist, best_sid = float("inf"), ""
    for _, osite in osm_hosps.iterrows():
        dist = haversine_km(hosp["latitude"], hosp["longitude"], osite["latitude"], osite["longitude"])
        if dist < best_dist:
            best_dist = dist
            best_sid = osite["site_id"]
    quality = match_quality(best_dist)
    if quality not in {"direct", "broad_radius"}:
        best_sid = ""
    return best_sid, best_dist, quality


def hospital_source_row(hosp, cap_j):
    # carry provenance through from the curated hospital dataset when present
    return {
        "hospital_id": hosp["hospital_id"],
        "hospital_name": hosp["hospital_name"],
        "bed_capacity_total": cap_j,
        "source_url_or_note": hosp.get(
            "capacity_source",
            "data_processed/hospitals/hospital_data.csv; no official replacement verified during this run",
        ),
        "confidence": hosp.get("capacity_confidence", "local_existing"),
    }


def audit_row(facility_id, facility_set, facility_type, cap_j, source_class, reason, matched_site_id="", match_quality=""):
    return {
        "facility_id": facility_id,
        "facility_set": facility_set,
        "facility_type": facility_type,
        "cap_j": cap_j,
        "source_class": source_class,
        "reason": reason,
        "matched_site_id": matched_site_id,
        "match_quality": match_quality,
    }


def build_hospitals_jh(hospitals, sites):
    osm_hosps = sites[sites["facility_type"] == "hospital"].copy()
    jh_rows, source_rows, audit_rows = [], [], []
    matched_osm_site_ids = set()

    for _, hosp in hospitals.iterrows():
        matched_sid, match_dist, quality = find_nearest_osm_hospital(hosp, osm_hosps)
        if matched_sid:
            matched_osm_site_ids.add(matched_sid)

        facility_id = f"JH_{hosp['hospital_id']}"
        # post-quake effective capacity (0 for facilities closed by earthquake
        # damage, e.g. Pazarcık DH) — fall back to pre-quake total if the
        # hospital file predates the curated dataset
        if "effective_capacity_postquake" in hospitals.columns:
            cap_j = int(hosp["effective_capacity_postquake"])
        else:
            cap_j = int(hosp["bed_capacity_total"])
        if cap_j <= 0:
            # closed by earthquake damage — cannot receive casualties
            audit_rows.append(
                audit_row(
                    facility_id,
                    "EXCLUDED",
                    hosp.get("facility_type", "Hospital"),
                    0,
                    "excluded",
                    "hospital closed post-quake (effective_capacity_postquake=0)",
                    matched_sid,
                    quality,
                )
            )
            continue
        jh_rows.append(
            {
                "site_id": facility_id,
                "hospital_id": hosp["hospital_id"],
                "hospital_name": hosp["hospital_name"],
                "latitude": hosp["latitude"],
                "longitude": hosp["longitude"],
                "cap_j": cap_j,
                "F_j": 0.0,
                "set": "JH",
                "matched_site_id": matched_sid,
                "match_dist_km": round(match_dist, 3) if matched_sid else "",
                "match_quality": quality,
            }
        )
        source_rows.append(hospital_source_row(hosp, cap_j))
        audit_rows.append(
            audit_row(
                facility_id,
                "JH",
                hosp.get("facility_type", "Hospital"),
                cap_j,
                "local_existing",
                "existing hospital capacity from data_processed/hospitals/hospital_data.csv",
                matched_sid,
                quality,
            )
        )

    jh_df = pd.DataFrame(jh_rows)
    assert_unique(jh_df, "site_id", "JH")
    return jh_df, matched_osm_site_ids, source_rows, audit_rows


def excluded_site_audit_rows(excluded, matched_osm_site_ids):
    rows = []
    for _, row in excluded.iterrows():
        rows.append(
            audit_row(
                row["site_id"],
                "EXCLUDED",
                row["facility_type"],
                "",
                "excluded",
                row["exclusion_reason"],
                row["site_id"] if row["site_id"] in matched_osm_site_ids else "",
                "",
            )
        )
    return rows


def assign_opening_penalty(jt_candidates):
    """Flat opening penalty (casualty-km equivalent) for every TMC candidate.

    Previously this scaled by a TOPSIS composite score when available, but
    TOPSIS was dropped by decision (see docs/CURRENT_PIPELINE.md) and
    topsis_ranking.csv is never produced, so that branch was dead code —
    every candidate always received the flat OPENING_PENALTY_CASUALTY_KM.
    """
    jt_candidates["F_j"] = OPENING_PENALTY_CASUALTY_KM
    return jt_candidates, f"uniform={OPENING_PENALTY_CASUALTY_KM}"


def build_tmc_candidates(sites, matched_osm_site_ids, site_area, psaha=None, pga_col=None):
    audit_rows = []
    jt_candidates = sites.copy()
    jt_candidates["exclusion_reason"] = ""
    jt_candidates.loc[jt_candidates["site_id"].isin(matched_osm_site_ids), "exclusion_reason"] = (
        "matched_existing_hospital"
    )
    hospital_mask = jt_candidates["facility_type"] == "hospital"
    jt_candidates.loc[hospital_mask, "exclusion_reason"] = jt_candidates.loc[
        hospital_mask, "exclusion_reason"
    ].replace("", "hospital_facility_excluded_from_tmc")

    excluded = jt_candidates[jt_candidates["exclusion_reason"] != ""].copy()
    audit_rows.extend(excluded_site_audit_rows(excluded, matched_osm_site_ids))
    jt_candidates = jt_candidates[jt_candidates["exclusion_reason"] == ""].copy()

    if psaha is not None and pga_col:
        jt_candidates = jt_candidates.merge(
            psaha[["site_id", pga_col]].rename(columns={pga_col: "pga"}),
            on="site_id",
            how="left",
        )
        jt_candidates["pga"] = jt_candidates["pga"].fillna(0.0)
        if APPLY_PGA_FILTER:
            hazardous = jt_candidates[jt_candidates["pga"] > PGA_MAX].copy()
            for _, row in hazardous.iterrows():
                audit_rows.append(
                    audit_row(row["site_id"], "EXCLUDED", row["facility_type"], "", "excluded", f"pga_above_{PGA_MAX}")
                )
            jt_candidates = jt_candidates[jt_candidates["pga"] <= PGA_MAX].copy()
        # risk_blind mode keeps hazardous candidates (the comparison baseline)
        # but still records their pga for the dashboard's delta view
    else:
        jt_candidates["pga"] = 0.0

    jt_candidates, opening_cost_note = assign_opening_penalty(jt_candidates)

    jt_candidates = jt_candidates.merge(site_area[["site_id", "site_area_m2"]], on="site_id", how="left")
    area_derived = jt_candidates["site_area_m2"].notna()
    jt_candidates["cap_j"] = jt_candidates["facility_type"].map(TMC_CAPACITY_BY_TYPE).astype(float)  # fallback default
    jt_candidates.loc[area_derived, "cap_j"] = (
        jt_candidates.loc[area_derived, "site_area_m2"] / SHELTER_AREA_PER_PERSON_M2
    ).clip(lower=TMC_MIN_CAPACITY, upper=TMC_MAX_CAPACITY)
    missing_capacity_types = sorted(jt_candidates[jt_candidates["cap_j"].isna()]["facility_type"].unique())
    if missing_capacity_types:
        raise ValueError(f"Missing TMC capacity assumptions for facility types: {missing_capacity_types}")

    jt_candidates["cap_j"] = jt_candidates["cap_j"].round().astype(int)
    jt_candidates["set"] = "JT"
    jt_df = jt_candidates[["site_id", "latitude", "longitude", "facility_type", "cap_j", "F_j", "set"]].copy()
    assert_unique(jt_df, "site_id", "JT")

    for _, row in jt_candidates.iterrows():
        reason = (
            f"site_area_m2={row['site_area_m2']:.0f} / {SHELTER_AREA_PER_PERSON_M2:.0f} m2/person, "
            f"clipped [{TMC_MIN_CAPACITY},{TMC_MAX_CAPACITY}]"
            if pd.notna(row["site_area_m2"])
            else f"fallback: TMC capacity by facility type: {row['facility_type']}"
        )
        audit_rows.append(
            audit_row(
                row["site_id"],
                "JT",
                row["facility_type"],
                int(row["cap_j"]),
                "area_derived_capacity" if pd.notna(row["site_area_m2"]) else "assumed_type_capacity",
                reason,
            )
        )

    return jt_df, audit_rows, len(excluded), opening_cost_note


def build_distance_matrix(demand, jh_df, jt_df):
    all_fac = pd.concat(
        [
            jh_df[["site_id", "latitude", "longitude", "cap_j", "F_j", "set"]],
            jt_df[["site_id", "latitude", "longitude", "cap_j", "F_j", "set"]],
        ],
        ignore_index=True,
    )
    assert_unique(all_fac, "site_id", "all facilities")

    i_coord = {r["sub_district_id"]: (r["latitude"], r["longitude"]) for _, r in demand.iterrows()}
    j_coord = {r["site_id"]: (r["latitude"], r["longitude"]) for _, r in all_fac.iterrows()}
    return pd.DataFrame(
        [
            {
                "demand_point": i,
                "facility": j,
                "distance_km": round(haversine_km(*i_coord[i], *j_coord[j]), 4),
            }
            for i in demand["sub_district_id"]
            for j in all_fac["site_id"]
        ]
    )


def validate_prepared_inputs(jh_df, jt_df):
    if set(jh_df["site_id"]) & set(jt_df["site_id"]):
        raise ValueError("JH/JT facility ID overlap detected")
    if (jh_df["cap_j"] <= 0).any() or (jt_df["cap_j"] <= 0).any():
        raise ValueError("All capacities must be positive")


def write_prepared_outputs(demand, jh_df, jt_df, dist_df, source_rows, audit_rows):
    os.makedirs(INPUT_DIR, exist_ok=True)
    demand.to_csv(os.path.join(INPUT_DIR, "demand_points.csv"), index=False)
    jh_df.to_csv(os.path.join(INPUT_DIR, "hospitals_jh.csv"), index=False)
    jt_df.to_csv(os.path.join(INPUT_DIR, "candidates_jt.csv"), index=False)
    dist_df.to_csv(os.path.join(INPUT_DIR, "distance_matrix.csv"), index=False)
    pd.DataFrame(source_rows).to_csv(os.path.join(INPUT_DIR, "hospital_capacity_sources.csv"), index=False)
    pd.DataFrame(audit_rows).to_csv(os.path.join(INPUT_DIR, "capacity_audit.csv"), index=False)
