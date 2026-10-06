import requests, os, numpy as np, pandas as pd
import rasterio
from rasterio.transform import rowcol

OT_API_KEY = os.environ.get("OPENTOPO_API_KEY")

OT_API_URL = "https://portal.opentopography.org/API/globaldem"

# Bounding box for KahramanmaraÅŸ area
BBOX = {"south": 36.5, "north": 38.5,
        "west":  35.5, "east":  38.5}

def download_dem(out_path: str = "data_raw/dem/srtm_tile.tif",
                 bbox: dict = None, dem_type: str = "SRTMGL1",
                 api_key: str = None):
    """
    Download SRTM GL1 (30m) DEM from OpenTopography API.
    API docs: https://opentopography.org/developers
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bbox = bbox or BBOX
    params = {
        "demtype":  dem_type,    # SRTM 30m â€” confirmed valid demtype value
        "south":    bbox["south"],
        "north":    bbox["north"],
        "west":     bbox["west"],
        "east":     bbox["east"],
        "outputFormat": "GTiff",
        "API_Key":  api_key or OT_API_KEY
    }
    print("Requesting DEM from OpenTopography...")
    r = requests.get(OT_API_URL, params=params, timeout=180, stream=True)
    if r.status_code == 401:
        raise ValueError("Invalid API key. Register at https://portal.opentopography.org")
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"[RAW] DEM saved â†’ {out_path}")
    return out_path

# â”€â”€ STEP 2: EXTRACT ELEVATION AND SLOPE AT SITES â”€â”€
def extract_terrain_at_sites(dem_path: str,
                               sites_csv: str,
                               out_csv: str):
    """
    Sample elevation and compute slope at each candidate site.
    Uses rasterio (install: pip install rasterio).
    """
    sites = pd.read_csv(sites_csv)

    with rasterio.open(dem_path) as src:
        # Print the raster metadata so you can verify it loaded correctly
        print(f"[INSPECT] DEM CRS: {src.crs}, shape: {src.shape}, nodata: {src.nodata}")

        transform = src.transform
        dem_arr = src.read(1).astype(float)

        # Replace nodata with NaN â€” value varies by dataset, check src.nodata
        nodata_val = src.nodata
        if nodata_val is not None:
            dem_arr[dem_arr == nodata_val] = np.nan

        # Slope: approximate cell size in metres from transform
        cell_deg = abs(transform.a)
        cell_m   = cell_deg * 111320   # approximate for mid-latitudes
        dy, dx   = np.gradient(dem_arr, cell_m)
        slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))

        elevs, slopes = [], []
        for _, row in sites.iterrows():
            r, c = rowcol(transform, row["longitude"], row["latitude"])
            r = int(np.clip(r, 0, dem_arr.shape[0]-1))
            c = int(np.clip(c, 0, dem_arr.shape[1]-1))
            elevs.append(float(dem_arr[r, c]))
            slopes.append(float(slope_deg[r, c]))

    result = sites[["site_id"]].copy()
    result["elevation_m"] = elevs
    result["slope_deg"]   = slopes
    result.to_csv(out_csv, index=False)
    print(f"[FINAL] Terrain saved â†’ {out_csv}")
    return result

def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    paths, terr = config["paths"], config["terrain"]
    api_key = os.environ.get(terr["api_key_env"]) or terr["api_key"]
    if config.get("force_refetch") or not os.path.exists(paths["raw_dem"]):
        download_dem(paths["raw_dem"], config["study_area"]["bbox"],
                     terr["dem_type"], api_key)
    else:
        print(f"[SKIP] Using cached {paths['raw_dem']}")
    return extract_terrain_at_sites(paths["raw_dem"], paths["out_sites"],
                                    paths["out_topography"])


if __name__ == "__main__":
    dem = download_dem()
    extract_terrain_at_sites(dem, "data_processed/sites/candidate_sites.csv",
                             "data_processed/sites/topography_per_site.csv")
