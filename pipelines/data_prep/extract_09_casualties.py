import requests, json, pandas as pd

USGS_EVENT_API = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# Kahramanmaraş mainshock event ID (confirmed real USGS ID)
EVENT_ID = "us6000jllz"

def fetch_event_geojson(event_id: str, out_json: str) -> dict:
    r = requests.get(USGS_EVENT_API,
                     params={"eventid": event_id, "format": "geojson"},
                     timeout=30)
    r.raise_for_status()
    data = r.json()
    with open(out_json, "w") as f:
        json.dump(data, f, indent=2)

    # ── INSPECT the products field ──
    products = data.get("properties", {}).get("products", {})
    print("Available products:", list(products.keys()))
    # ↑ Check if 'losspager' is present before proceeding

    if "losspager" in products:
        pager = products["losspager"][0]  # first (most recent) version
        print("PAGER properties:", list(pager.get("properties", {}).keys()))
        # ↑ Inspect these keys — do NOT assume field names
    else:
        print("[NOTE] No losspager product for this event")

    return data
# ── STEP 2: EXTRACT PAGER ESTIMATES ──
def extract_pager_estimates(json_path: str) -> dict:
    """
    Extract PAGER casualty estimates from saved GeoJSON.
    IMPORTANT: field names inside losspager.properties are
    not documented in a stable public spec. Inspect the actual
    response before writing field access code.
    Returns a dict with whatever loss fields are present.
    """
    with open(json_path) as f:
        data = json.load(f)

    products = data["properties"]["products"]
    if "losspager" not in products:
        print("[WARN] No PAGER product available for this event.")
        print("Fallback: use official government reports or academic papers.")
        return {}

    pager = products["losspager"][0]
    props = pager.get("properties", {})

    # ── Print all available fields ──
    print("[INSPECT] All PAGER property keys and values:")
    for k, v in props.items():
        print(f"  {k}: {v}")
    # ↑ READ THIS before using any field below

    # Return all fields as-is for you to use after inspection
    return props


def build_casualty_table(
        total_injured: int,
        total_dead: int,
        sub_district_csv: str,
        out_csv: str,
        n_scenarios: int = 20,
        uncertainty_cv: float = 0.30,
        period_rates=None,
        triage_splits=None,
):
    """
    Generate stochastic casualty scenarios for the MILP.

    total_injured / total_dead: from PAGER or official reports
    sub_district_csv: needs columns sub_district_id, population
    """
    import numpy as np
    subs = pd.read_csv(sub_district_csv)
    rng  = np.random.default_rng(seed=42)

    PERIOD_RATES  = period_rates or [0.60, 0.25, 0.10, 0.05]
    TRIAGE_SPLITS = triage_splits or {"T1": 0.20, "T2": 0.30, "T3": 0.50}

    rows = []
    pop_weights = subs["population"] / subs["population"].sum()

    for s in range(n_scenarios):
        scale = rng.lognormal(0, uncertainty_cv)
        s_inj = int(total_injured * scale)
        s_ded = int(total_dead * scale)
        zone_inj = (pop_weights * s_inj).round().astype(int)
        zone_ded = (pop_weights * s_ded).round().astype(int)

        for idx, zrow in subs.iterrows():
            inj = int(zone_inj.iloc[idx])
            ded = int(zone_ded.iloc[idx])
            for p_idx, rate in enumerate(PERIOD_RATES, 1):
                pi = int(inj * rate)
                rows.append({
                    "sub_district_id": zrow["sub_district_id"],
                    "scenario_id":    s + 1,
                    "period":         p_idx,
                    "T1_count":       int(pi * TRIAGE_SPLITS["T1"]),
                    "T2_count":       int(pi * TRIAGE_SPLITS["T2"]),
                    "T3_count":       int(pi * TRIAGE_SPLITS["T3"]),
                    "dead_count":     int(ded * rate),
                    "scenario_prob":  1.0 / n_scenarios
                })
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"[FINAL] {len(df)} casualty scenario rows → {out_csv}")
    return df

def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    import os
    paths, cas, ev = config["paths"], config["casualties"], config["event"]
    if config.get("force_refetch") or not os.path.exists(paths["raw_pager"]):
        fetch_event_geojson(ev["usgs_event_id"], paths["raw_pager"])
    else:
        print(f"[SKIP] Using cached {paths['raw_pager']}")
    extract_pager_estimates(paths["raw_pager"])
    return build_casualty_table(
        total_injured=cas["total_injured"],
        total_dead=cas["total_dead"],
        sub_district_csv=paths["out_sub_districts"],
        out_csv=paths["out_casualties"],
        n_scenarios=cas["n_scenarios"],
        uncertainty_cv=cas["uncertainty_cv"],
        period_rates=cas["period_rates"],
        triage_splits=cas["triage_splits"],
    )


if __name__ == "__main__":
    data = fetch_event_geojson(EVENT_ID, "data_raw/usgs/pager_us6000jllz.json")
    props = extract_pager_estimates("data_raw/usgs/pager_us6000jllz.json")
    # After inspecting props, get your total_injured and total_dead
    # For Kahramanmaraş, AFAD official: 107,204 injured, 50,783 dead
    build_casualty_table(
        total_injured=107204,
        total_dead=50783,
        sub_district_csv="data_processed\\casualties\\sub_districts_raw.csv",
        out_csv="data_processed\\casualties\\casualty_projections.csv"
    )