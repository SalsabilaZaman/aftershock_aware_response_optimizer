# extract_07_hospitals.py
#
# Hospital capacity is NOT extractable from any API — there is no public
# per-facility dataset for Turkey. The source of truth is a hand-curated,
# source-cited CSV (data_raw/hospitals/hospital_capacity_curated.csv) whose
# every row carries a capacity_confidence label:
#   official  — figure published by the facility / Ministry of Health
#   reported  — figure from a secondary source (aggregator, press)
#   estimated — no published figure; a labeled assumption
# This script validates and enriches that file; it never invents capacity.
#
# Steps:
#   1. load the curated CSV
#   2. cross-check each row's coordinates against the cached OSM hospital
#      query (data_raw/osm/hospitals_osm.json) — flags typo'd coordinates,
#      which corrupted the distance matrix in the previous hand-made file
#   3. derive the remaining columns downstream expects (general beds,
#      outpatient capacity, staffing estimates)
#   4. write data_processed/hospitals/hospital_data.csv

import json
import math
import unicodedata
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
CURATED_CSV = REPO_ROOT / "data_raw" / "hospitals" / "hospital_capacity_curated.csv"
OSM_CACHE = REPO_ROOT / "data_raw" / "osm" / "hospitals_osm.json"
OUT_CSV = REPO_ROOT / "data_processed" / "hospitals" / "hospital_data.csv"

# Study-area bounds (same province bbox used across the pipeline)
LAT_MIN, LAT_MAX = 36.5, 38.5
LON_MIN, LON_MAX = 35.5, 38.5

# A curated point further than this from its OSM name-match is suspicious.
# 2 km tolerates campus size + OSM centroid placement; the errors this check
# exists to catch were 30-100 km.
COORD_TOLERANCE_KM = 2.0

# Staffing ratios (estimates — Turkey has no public per-facility staffing
# data; ratios follow the original project convention and are labeled as
# estimates in the output)
DOCTORS_PER_BED = 0.20
NURSES_PER_BED = 0.50
OUTPATIENT_PER_BED = 3


def _normalize(name: str) -> str:
    """Lowercase, strip accents and boilerplate words for fuzzy matching."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().replace("ı", "i")
    for word in ("hastanesi", "hastane", "devlet", "ozel", "özel", "kahramanmaras"):
        name = name.replace(word, " ")
    return " ".join(name.split())


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_osm_hospitals(path: Path) -> list:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if tags.get("amenity") != "hospital":
            continue
        name = tags.get("name")
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if name and lat and lon:
            out.append({"name": name, "norm": _normalize(name), "lat": lat, "lon": lon})
    return out


def cross_check_coords(df: pd.DataFrame, osm: list) -> list:
    """Return list of warning strings for rows whose coordinates disagree
    with a same-named OSM hospital. Only rows with coord_source == 'osm'
    are expected to match tightly."""
    warnings = []
    for _, row in df.iterrows():
        norm = _normalize(row["hospital_name"])
        # token-overlap match: best OSM candidate sharing the most words
        best, best_score, best_dist = None, 0, float("inf")
        for cand in osm:
            score = len(set(norm.split()) & set(cand["norm"].split()))
            dist = _haversine_km(row["latitude"], row["longitude"], cand["lat"], cand["lon"])
            # equal name overlap → prefer the geographically nearer candidate
            if score > best_score or (score == best_score and score > 0 and dist < best_dist):
                best, best_score, best_dist = cand, score, dist
        if best is None or best_score == 0:
            if row["coord_source"] == "osm":
                warnings.append(f"{row['hospital_id']} {row['hospital_name']}: no OSM name match found")
            continue
        dist = _haversine_km(row["latitude"], row["longitude"], best["lat"], best["lon"])
        if dist > COORD_TOLERANCE_KM and row["coord_source"] == "osm":
            warnings.append(
                f"{row['hospital_id']} {row['hospital_name']}: {dist:.1f} km from OSM match '{best['name']}'"
            )
    return warnings


def run(config: dict | None = None) -> pd.DataFrame:
    df = pd.read_csv(CURATED_CSV, encoding="utf-8")

    required = [
        "hospital_id", "hospital_name", "latitude", "longitude", "facility_type",
        "bed_capacity_total", "bed_capacity_icu", "capacity_confidence",
        "coord_source", "capacity_source", "operational_postquake",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"curated CSV missing columns: {missing}")

    # hard checks — a bad curated row should stop the pipeline, not flow through
    assert df["hospital_id"].is_unique, "duplicate hospital_id in curated CSV"
    in_bounds = df["latitude"].between(LAT_MIN, LAT_MAX) & df["longitude"].between(LON_MIN, LON_MAX)
    assert in_bounds.all(), f"out-of-bbox rows: {df.loc[~in_bounds, 'hospital_id'].tolist()}"
    assert (df["bed_capacity_total"] > 0).all(), "non-positive bed capacity"
    assert df["capacity_confidence"].isin(["official", "reported", "estimated"]).all()

    coord_warnings = cross_check_coords(df, load_osm_hospitals(OSM_CACHE))

    out = pd.DataFrame({
        "hospital_id": df["hospital_id"],
        "hospital_name": df["hospital_name"],
        "latitude": df["latitude"],
        "longitude": df["longitude"],
        "facility_type": df["facility_type"],
        "bed_capacity_icu": df["bed_capacity_icu"].astype(int),
        "bed_capacity_general": (df["bed_capacity_total"] - df["bed_capacity_icu"]).astype(int),
        "bed_capacity_total": df["bed_capacity_total"].astype(int),
        "outpatient_capacity": (OUTPATIENT_PER_BED * df["bed_capacity_total"]).astype(int),
        "n_doctors_pre": (DOCTORS_PER_BED * df["bed_capacity_total"]).astype(int),
        "n_nurses_pre": (NURSES_PER_BED * df["bed_capacity_total"]).astype(int),
        # post-quake operating fraction (0.0 = closed by earthquake damage);
        # the deterministic solver currently caps on bed_capacity_total only —
        # effective post-quake capacity is what the model should use
        "operational_capacity": df["operational_postquake"],
        "effective_capacity_postquake": (df["bed_capacity_total"] * df["operational_postquake"]).astype(int),
        "capacity_confidence": df["capacity_confidence"],
        "capacity_source": df["capacity_source"],
    })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8")

    print("=" * 70)
    print("HOSPITAL DATA (curated + validated)")
    print("=" * 70)
    print(f"Facilities: {len(out)}")
    print(f"Total beds (pre-quake): {out['bed_capacity_total'].sum()}")
    print(f"Total beds (post-quake effective): {out['effective_capacity_postquake'].sum()}")
    print("Confidence mix:", dict(out["capacity_confidence"].value_counts()))
    if coord_warnings:
        print("\nCOORDINATE WARNINGS (review needed):")
        for w in coord_warnings:
            print("  -", w)
    else:
        print("\nAll OSM-sourced coordinates confirmed within "
              f"{COORD_TOLERANCE_KM} km of OSM hospital positions.")
    print(f"\nSaved to: {OUT_CSV}")
    return out


if __name__ == "__main__":
    run()
