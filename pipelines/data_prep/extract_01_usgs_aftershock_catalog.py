import requests, pandas as pd, time
from io import StringIO

# USGS FDSN Event API — confirmed real endpoint
USGS_API = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# ── Study area: Kahramanmaraş Mw 7.8, 6 Feb 2023 ──
PARAMS = {
    "format":        "csv",
    "starttime":     "2023-02-06",
    "endtime":       "2023-03-08",   # 30 days
    "minmagnitude":  2.0,
    "minlatitude":   36.5,
    "maxlatitude":   38.5,
    "minlongitude":  35.5,
    "maxlongitude":  38.5,
    "orderby":       "time-asc"
}

def extract_usgs_catalog(params: dict, out_raw: str = "data_raw/usgs/usgs_raw.csv"):
    try:
        r = requests.get(USGS_API, params=params, timeout=60)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df.to_csv(out_raw, index=False)
        print(f"[RAW] Saved {len(df)} rows → {out_raw}")
        return df
    except requests.HTTPError as e:
        # API returns 400 if result set > 20,000 events — narrow your window
        print(f"[ERROR] HTTP {r.status_code}: {r.text[:300]}")
        raise

def clean_catalog(raw_path: str, mainshock_utc: str, out_clean: str):
    df = pd.read_csv(raw_path)
    print(f"[CLEAN] Raw columns: {list(df.columns)}")
    # ↑ Print and verify — do not assume column names beyond those listed above

    # Parse times
    df["time"] = pd.to_datetime(df["time"], utc=True)
    t0 = pd.to_datetime(mainshock_utc, utc=True)

    # Keep only true aftershocks (after mainshock, mag < 7.5)
    df = df[(df["time"] > t0) & (df["mag"] < 7.5)].copy()

    # Only keep earthquake events (exclude quarry blasts, etc.)
    if "type" in df.columns:
        df = df[df["type"] == "earthquake"]

    # Compute elapsed time (days) — needed for Omori Law fitting
    df["t_days"] = (df["time"] - t0).dt.total_seconds() / 86400.0

    # Drop rows with NaN in critical columns
    df = df.dropna(subset=["latitude", "longitude", "mag"])

    out_df = df.rename(columns={
        "time": "time_utc", "depth": "depth_km",
        "mag": "magnitude", "id": "event_id"
    })
    out_df.to_csv(out_clean, index=False)
    print(f"[CLEAN] {len(out_df)} aftershocks saved → {out_clean}")
    return out_df

def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    import os
    bbox, ev, paths = config["study_area"]["bbox"], config["event"], config["paths"]
    params = {
        "format": "csv",
        "starttime": ev["window_start"],
        "endtime": ev["window_end"],
        "minmagnitude": ev["min_magnitude"],
        "minlatitude": bbox["south"], "maxlatitude": bbox["north"],
        "minlongitude": bbox["west"], "maxlongitude": bbox["east"],
        "orderby": "time-asc",
    }
    if config.get("force_refetch") or not os.path.exists(paths["raw_usgs_catalog"]):
        extract_usgs_catalog(params, paths["raw_usgs_catalog"])
    else:
        print(f"[SKIP] Using cached {paths['raw_usgs_catalog']}")
    return clean_catalog(paths["raw_usgs_catalog"], ev["mainshock_utc"], paths["out_catalog"])


if __name__ == "__main__":
    # extract_usgs_catalog(PARAMS)
    clean_catalog(
        raw_path="data_raw/usgs/usgs_raw.csv",
        mainshock_utc="2023-02-06T01:17:35",
        out_clean="data_processed/seismic/aftershock_catalog.csv"
    )