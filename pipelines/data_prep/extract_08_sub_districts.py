import requests
import pandas as pd
import os

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Fallback population figures for districts whose OSM relation has no
# population tag (approximate 2022 TÜİK values)
FALLBACK_POPULATIONS = {
    "Çağlayancerit": 22000,
    "Nurhak":        11000,
    "Ekinözü":       10000,
    "Pazarcık":      75000,
}

# Hardcoded fallback if Overpass returns nothing: the 11 official districts
# of Kahramanmaraş province (approximate 2022 TÜİK populations). The earlier
# 13-entry list wrongly included Göynük and Başkonuş, which are towns (belde),
# not districts.
FALLBACK_DISTRICTS = [
    {"sub_district_id": "SD001", "name": "Afşin",        "population": 98000},
    {"sub_district_id": "SD002", "name": "Andırın",      "population": 28000},
    {"sub_district_id": "SD003", "name": "Çağlayancerit","population": 22000},
    {"sub_district_id": "SD004", "name": "Dulkadiroğlu", "population": 310000},
    {"sub_district_id": "SD005", "name": "Ekinözü",      "population": 10000},
    {"sub_district_id": "SD006", "name": "Elbistan",     "population": 170000},
    {"sub_district_id": "SD007", "name": "Göksun",       "population": 48000},
    {"sub_district_id": "SD008", "name": "Nurhak",       "population": 11000},
    {"sub_district_id": "SD009", "name": "Onikişubat",   "population": 420000},
    {"sub_district_id": "SD010", "name": "Pazarcık",     "population": 75000},
    {"sub_district_id": "SD011", "name": "Türkoğlu",     "population": 65000},
]


def extract_sub_districts(province_name: str = "Kahramanmaraş",
                          out_csv: str = "data_processed/casualties/sub_districts_raw.csv"):
    district_query = f"""
    [out:json][timeout:120];
    area["name"="{province_name}"]["admin_level"="4"]->.province;
    (
      relation["admin_level"="6"](area.province);
    );
    out tags;
    """

    print(f"Fetching districts (ilçe level) for {province_name}...")
    try:
        r = requests.post(OVERPASS_URL, data={"data": district_query}, timeout=150)
        r.raise_for_status()
        district_data = r.json()
    except requests.RequestException as e:
        print(f"[WARN] Overpass request failed ({e}) — using hardcoded fallback")
        district_data = {"elements": []}
    print(f"Found {len(district_data['elements'])} districts")

    rows = []
    for i, el in enumerate(district_data["elements"]):
        tags = el.get("tags", {})
        rows.append({
            "sub_district_id": f"SD{i+1:03d}",
            "osm_id": el.get("id"),
            "name": tags.get("name", f"District_{i+1}"),
            "name_tr": tags.get("name:tr", ""),
            "admin_level": tags.get("admin_level"),
            "population": tags.get("population", None)
        })

    if rows:
        df = pd.DataFrame(rows)
        # OSM returns population as strings; fill gaps from the fallback table
        df["population"] = pd.to_numeric(df["population"], errors="coerce")
        df["population"] = df["population"].combine_first(
            df["name"].map(FALLBACK_POPULATIONS)
        )
    else:
        print("Overpass empty — falling back to known Kahramanmaraş districts")
        df = pd.DataFrame(FALLBACK_DISTRICTS)

    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"\nSaved {len(df)} sub-districts to {out_csv}")
    print(df[[c for c in ("name", "admin_level", "population") if c in df.columns]].to_string())
    return df


def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    return extract_sub_districts(
        province_name=config["study_area"]["province_name"],
        out_csv=config["paths"]["out_sub_districts"],
    )


if __name__ == "__main__":
    extract_sub_districts()
