# 1. Go to: https://earthquake.usgs.gov/data/vs30/
# 2. Find and download the global_vs30.tif or regional GeoTIFF
# 3. Save it to:  data_raw/vs30/global_vs30.tif
# 4. Then run the extraction below
# ── STEP 2: EXTRACT Vs30 AT SITE LOCATIONS ──
import rasterio, pandas as pd, numpy as np
from rasterio.transform import rowcol

def extract_vs30(tif_path: str, sites_csv: str, out_csv: str, soil_threshold: float = 360):
    sites = pd.read_csv(sites_csv)

    with rasterio.open(tif_path) as src:
        print(f"[INSPECT] Vs30 CRS: {src.crs}")
        print(f"[INSPECT] Vs30 nodata: {src.nodata}")
        print(f"[INSPECT] Vs30 dtype: {src.dtypes}")
        # ↑ Check these before proceeding — nodata value and dtype vary by version

        arr       = src.read(1).astype(float)
        transform = src.transform
        nodata    = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        # Also clip physically implausible values
        arr[(arr <= 0) | (arr > 5000)] = np.nan

        vs30_vals = []
        for _, row in sites.iterrows():
            r, c = rowcol(transform, row["longitude"], row["latitude"])
            r = int(np.clip(r, 0, arr.shape[0]-1))
            c = int(np.clip(c, 0, arr.shape[1]-1))
            vs30_vals.append(float(arr[r, c]))

    result = sites[["site_id"]].copy()
    result["vs30_ms"]    = vs30_vals
    # Binary soil class: 0=rock (Vs30>threshold), 1=soil — for GMPE input
    result["soil_class"] = (result["vs30_ms"] <= soil_threshold).astype(int)
    result.to_csv(out_csv, index=False)
    print(f"[FINAL] Vs30 extracted → {out_csv}")
    return result

def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    import os
    paths = config["paths"]
    if not os.path.exists(paths["raw_vs30"]):
        # Manual one-time download — there is no API for the global Vs30 grid
        raise FileNotFoundError(
            f"{paths['raw_vs30']} missing. Download the global Vs30 grid from "
            "https://earthquake.usgs.gov/data/vs30/ and place it there."
        )
    return extract_vs30(paths["raw_vs30"], paths["out_sites"], paths["out_vs30"],
                        config["vs30"]["soil_threshold_ms"])


if __name__ == "__main__":
    extract_vs30("data_raw/vs30/global_vs30.grd",
                 "data_processed/sites/candidate_sites.csv",
                 "data_processed/sites/site_condition_per_site.csv")