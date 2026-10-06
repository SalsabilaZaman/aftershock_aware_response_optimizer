import requests, pandas as pd, json, time
from shapely.geometry import Polygon
from pyproj import Transformer

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {
    "User-Agent": "earthquake_response/1.0 (+https://github.com/earthquake_response)",
    "Accept": "application/json, text/plain, */*",
}

UTM_EPSG = 32637  # UTM zone 37N — matches config.yaml study_area.utm_epsg

# ─────────────────────────────────────────────────────
# TIGHT BBOX FOR KAHRAMANMARAŞ PROVINCE
# This covers the entire province but excludes Gaziantep, Malatya, etc.
# ─────────────────────────────────────────────────────
BBOX = "36.9,36.2,38.5,37.8"  # south,west,north,east

QUERY = (
    "[out:json][timeout:90];\n"
    "(\n"
    f"  node[\"amenity\"=\"hospital\"]({BBOX});\n"
    f"  way[\"amenity\"=\"hospital\"]({BBOX});\n"
    f"  node[\"amenity\"=\"school\"]({BBOX});\n"
    f"  way[\"amenity\"=\"school\"]({BBOX});\n"
    f"  node[\"amenity\"=\"university\"]({BBOX});\n"
    f"  way[\"amenity\"=\"university\"]({BBOX});\n"
    f"  node[\"leisure\"=\"sports_centre\"]({BBOX});\n"
    f"  way[\"leisure\"=\"sports_centre\"]({BBOX});\n"
    f"  node[\"leisure\"=\"stadium\"]({BBOX});\n"
    f"  way[\"leisure\"=\"stadium\"]({BBOX});\n"
    ");\n"
    "out geom tags;"
)

def build_query(bbox_str: str) -> str:
    return (
        "[out:json][timeout:90];\n"
        "(\n"
        f"  node[\"amenity\"=\"hospital\"]({bbox_str});\n"
        f"  way[\"amenity\"=\"hospital\"]({bbox_str});\n"
        f"  node[\"amenity\"=\"school\"]({bbox_str});\n"
        f"  way[\"amenity\"=\"school\"]({bbox_str});\n"
        f"  node[\"amenity\"=\"university\"]({bbox_str});\n"
        f"  way[\"amenity\"=\"university\"]({bbox_str});\n"
        f"  node[\"leisure\"=\"sports_centre\"]({bbox_str});\n"
        f"  way[\"leisure\"=\"sports_centre\"]({bbox_str});\n"
        f"  node[\"leisure\"=\"stadium\"]({bbox_str});\n"
        f"  way[\"leisure\"=\"stadium\"]({bbox_str});\n"
        ");\n"
        "out geom tags;"
    )


def fetch_osm_sites(out_raw: str = "data_raw/osm/osm_sites_raw.json", query: str = None):
    try:
        r = requests.post(OVERPASS_URL,
                          data={"data": query or QUERY},
                          headers=HEADERS,
                          timeout=120)
        r.raise_for_status()
        data = r.json()
        with open(out_raw, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[RAW] {len(data['elements'])} OSM elements saved")
        return data
    except requests.HTTPError:
        print(f"[ERROR] Overpass API returned {r.status_code}")
        print("If 429 Too Many Requests: wait 60s and retry")
        raise

def filter_by_kahramanmaras(df, bounds=None):
    """Remove sites clearly outside Kahramanmaraş Province"""
    if bounds is None:
        lat_min, lat_max = 36.9, 38.5
        lon_min, lon_max = 36.2, 37.8
    else:
        lat_min, lat_max = bounds["south"], bounds["north"]
        lon_min, lon_max = bounds["west"], bounds["east"]

    filtered = df[
        (df['latitude'] >= lat_min) & 
        (df['latitude'] <= lat_max) & 
        (df['longitude'] >= lon_min) & 
        (df['longitude'] <= lon_max)
    ]
    print(f"[FILTER] Removed {len(df) - len(filtered)} sites outside province bounds")
    return filtered

def _way_polygon_area_m2(geometry, transformer):
    """Project a way's node-ring (WGS84 lat/lon) into metric UTM and return
    (area_m2, centroid_lat, centroid_lon). None if the ring is degenerate."""
    if not geometry or len(geometry) < 3:
        return None, None, None
    xs, ys = transformer.transform(
        [pt["lon"] for pt in geometry], [pt["lat"] for pt in geometry]
    )
    poly = Polygon(zip(xs, ys))
    if not poly.is_valid or poly.area == 0:
        poly = poly.buffer(0)  # fixes self-intersecting/unclosed rings
    if poly.is_empty:
        return None, None, None
    inv = Transformer.from_crs(f"EPSG:{UTM_EPSG}", "EPSG:4326", always_xy=True)
    clon, clat = inv.transform(poly.centroid.x, poly.centroid.y)
    return poly.area, clat, clon


def parse_osm_elements(raw_path: str, out_clean: str, out_site_area: str, bounds=None):
    with open(raw_path) as f:
        data = json.load(f)

    if data["elements"]:
        print("[INSPECT] Sample element structure:")
        print(json.dumps(data["elements"][0], indent=2)[:1500])

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{UTM_EPSG}", always_xy=True)

    rows, area_rows = [], []
    for i, el in enumerate(data["elements"]):
        tags = el.get("tags", {})

        site_area_m2 = None
        if el["type"] == "node":
            lat = el.get("lat")
            lon = el.get("lon")
        elif el["type"] == "way":
            site_area_m2, lat, lon = _way_polygon_area_m2(el.get("geometry"), transformer)
            if lat is None:  # degenerate ring — fall back to Overpass's own center if present
                center = el.get("center", {})
                lat, lon = center.get("lat"), center.get("lon")
        else:
            continue

        if lat is None or lon is None:
            continue

        facility_type = (tags.get("amenity") or
                         tags.get("leisure") or
                         tags.get("healthcare") or
                         "unknown")
        name = tags.get("name") or tags.get("name:en") or f"Site_{i}"

        rows.append({
            "osm_id":        el["id"],
            "osm_type":      el["type"],
            "name":          name,
            "latitude":      lat,
            "longitude":     lon,
            "facility_type": facility_type,
        })
        area_rows.append({"osm_id": el["id"], "site_area_m2": site_area_m2})

    df = pd.DataFrame(rows)
    area_df = pd.DataFrame(area_rows)

    # ✅ NEW: Filter to Kahramanmaraş Province
    keep_mask = df.index.isin(filter_by_kahramanmaras(df, bounds).index)
    df, area_df = df[keep_mask], area_df[keep_mask]

    # Remove near-duplicates
    dup_mask = ~df.duplicated(subset=["latitude", "longitude"])
    df, area_df = df[dup_mask].reset_index(drop=True), area_df[dup_mask].reset_index(drop=True)
    df.insert(0, "site_id", [f"S{i+1:03d}" for i in range(len(df))])
    area_df.insert(0, "site_id", df["site_id"].values)

    df.to_csv(out_clean, index=False)
    print(f"[CLEAN] {len(df)} candidate sites → {out_clean}")

    # For "way" elements this is almost always the OSM site/campus boundary
    # (schoolyard, university grounds, stadium grounds), NOT a building
    # footprint — most amenity=school/university ways in this catalog carry
    # no building=* tag, so there's no reliable way to isolate an indoor
    # footprint from the polygon alone. Used deliberately as OUTDOOR usable
    # site area (see settings.SHELTER_AREA_PER_PERSON_M2): a post-earthquake
    # TMC is treated as a tented/field facility on this ground, not people
    # sheltering inside a structure the PGA filter may have just flagged as
    # unsafe. Node-type sites (~8% of candidates) have no polygon at all —
    # imputed with the type median; area_source records which is which.
    area_df = area_df.merge(df[["site_id", "facility_type"]], on="site_id")
    area_df["area_source"] = area_df["site_area_m2"].notna().map(
        {True: "osm_way_geometry", False: "type_median_imputed"})
    type_medians = area_df.groupby("facility_type")["site_area_m2"].median()
    missing = area_df["site_area_m2"].isna()
    area_df.loc[missing, "site_area_m2"] = area_df.loc[missing, "facility_type"].map(type_medians)
    area_df = area_df[["site_id", "site_area_m2", "area_source"]]
    area_df.to_csv(out_site_area, index=False)
    print(f"[CLEAN] {len(area_df)} site-area rows → {out_site_area} "
          f"({(area_df['area_source'] == 'osm_way_geometry').sum()} measured, "
          f"{(area_df['area_source'] == 'type_median_imputed').sum()} imputed)")
    return df

def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    import os
    pb, paths = config["study_area"]["province_bbox"], config["paths"]
    bbox_str = f"{pb['south']},{pb['west']},{pb['north']},{pb['east']}"  # Overpass s,w,n,e
    if config.get("force_refetch") or not os.path.exists(paths["raw_osm_sites"]):
        fetch_osm_sites(paths["raw_osm_sites"], build_query(bbox_str))
    else:
        print(f"[SKIP] Using cached {paths['raw_osm_sites']}")
    return parse_osm_elements(paths["raw_osm_sites"], paths["out_sites"], paths["out_site_area"], pb)


if __name__ == "__main__":
    fetch_osm_sites()
    parse_osm_elements("data_raw/osm/osm_sites_raw.json",
                       "data_processed/sites/candidate_sites.csv",
                       "data_processed/sites/site_area_per_site.csv")