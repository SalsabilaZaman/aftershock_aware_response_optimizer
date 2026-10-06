"""
Step 06 — Damage Indicators per Candidate Site
Copernicus EMSR648 AOI04 (Kahramanmaras city centre)

Inputs:
  data_raw/copernicus_builtUpA/EMSR648_AOI04_GRA_PRODUCT_builtUpA_r1_v1.shp
  data_processed/sites/candidate_sites.csv  (columns: site_id, latitude, longitude,facility_type)

Outputs:
  data_processed/sites/damage_indicators_per_site.csv
  data_processed/sites/candidate_sites_aoi04.csv

Damage grades are only valid INSIDE AOI04 — sites outside get NaN, never
fabricated values.
"""

import os

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point, box

# ── DEFAULTS (overridden by pipelines/extraction/config.yaml via run()) ───────
SHP_PATH    = "data_raw\\copernicus_builtUpA\\EMSR648_AOI04_GRA_PRODUCT_builtUpA_r1_v1.shp"
SITES_CSV   = "data_processed\\sites\\candidate_sites.csv"
OUT_ALL     = "data_processed\\sites\\damage_indicators_per_site.csv"
OUT_AOI     = "data_processed\\sites\\candidate_sites_aoi04.csv"
CRS_METRIC  = "EPSG:32637"
BUFFER_M    = 500
AOI_PAD_DEG = 0.09


def extract_damage(shp_path=SHP_PATH, sites_csv=SITES_CSV, out_all=OUT_ALL,
                   out_aoi=OUT_AOI, crs_metric=CRS_METRIC, buffer_m=BUFFER_M,
                   aoi_pad_deg=AOI_PAD_DEG):
    # ── 1. LOAD DAMAGE LAYER ──────────────────────────────────────────────────
    print("Loading damage layer...")
    if not os.path.exists(shp_path):
        raise FileNotFoundError(
            f"{shp_path} missing. Download the EMSR648 AOI04 builtUpA product "
            "from https://emergency.copernicus.eu/ (mapping activation EMSR648) "
            "and place the unzipped shapefile there."
        )
    gdf = gpd.read_file(shp_path)
    print(f"  Total polygons: {len(gdf)}")
    print(f"  Damage grades: {gdf['damage_gra'].value_counts().to_dict()}")

    damaged    = gdf[gdf['damage_gra'].isin(['Destroyed', 'Damaged', 'Possibly damaged'])].copy()
    destroyed  = gdf[gdf['damage_gra'] == 'Destroyed'].copy()
    print(f"  Damaged (any): {len(damaged)}  |  Destroyed only: {len(destroyed)}")

    # ── 2. LOAD SITES ─────────────────────────────────────────────────────────
    print("\nLoading candidate sites...")
    sites = pd.read_csv(sites_csv)
    sites_gdf = gpd.GeoDataFrame(
        sites,
        geometry=[Point(lon, lat) for lon, lat in zip(sites['longitude'], sites['latitude'])],
        crs="EPSG:4326"
    )

    # ── 3. FILTER TO AOI04 REGION ─────────────────────────────────────────────
    aoi_bounds = gdf.total_bounds
    aoi_box = box(
        aoi_bounds[0] - aoi_pad_deg, aoi_bounds[1] - aoi_pad_deg,
        aoi_bounds[2] + aoi_pad_deg, aoi_bounds[3] + aoi_pad_deg
    )
    in_aoi_mask = sites_gdf.geometry.within(aoi_box)
    sites_aoi   = sites_gdf[in_aoi_mask].copy()
    print(f"  Sites within AOI04 (+10km buffer): {len(sites_aoi)}")
    sites_aoi[['site_id', 'latitude', 'longitude', 'name', 'facility_type']].to_csv(out_aoi, index=False)
    print(f"  Saved: {out_aoi}")

    # ── 4. PROJECT TO METRIC CRS ──────────────────────────────────────────────
    print("\nProjecting to UTM 37N...")
    sites_m     = sites_aoi.to_crs(crs_metric).reset_index(drop=True)
    damaged_m   = damaged.to_crs(crs_metric).reset_index(drop=True)
    destroyed_m = destroyed.to_crs(crs_metric).reset_index(drop=True)

    # Extract centroid coordinates as plain numpy arrays — avoids all Series ambiguity
    dam_xy = np.array([(g.centroid.x, g.centroid.y) for g in damaged_m.geometry])
    des_xy = np.array([(g.centroid.x, g.centroid.y) for g in destroyed_m.geometry])

    print(f"  Damage centroids: {len(dam_xy)}  |  Destroyed centroids: {len(des_xy)}")

    # ── 5. COMPUTE INDICATORS PER SITE ────────────────────────────────────────
    print(f"\nComputing indicators for {len(sites_m)} sites...")

    results = []
    for idx, row in sites_m.iterrows():
        if idx % 50 == 0:
            print(f"  Processing site {idx + 1}/{len(sites_m)}...")

        pt_arr = np.array([float(row.geometry.x), float(row.geometry.y)])

        if len(dam_xy) > 0:
            dists = np.sqrt(((dam_xy - pt_arr) ** 2).sum(axis=1))
            dist_damaged = float(dists.min())
        else:
            dist_damaged = np.nan

        if len(des_xy) > 0:
            dists_d = np.sqrt(((des_xy - pt_arr) ** 2).sum(axis=1))
            dist_destroyed = float(dists_d.min())
        else:
            dist_destroyed = np.nan

        count_dam  = int((dists  <= buffer_m).sum()) if len(dam_xy) > 0 else 0
        count_dest = int((dists_d <= buffer_m).sum()) if len(des_xy) > 0 else 0

        results.append({
            'site_id':               row['site_id'],
            'dist_to_damaged_m':     round(dist_damaged, 1),
            'dist_to_destroyed_m':   round(dist_destroyed, 1) if not np.isnan(dist_destroyed) else np.nan,
            'damage_count_500m':     count_dam,
            'destroyed_count_500m':  count_dest,
            'in_aoi':                True,
        })

    out = pd.DataFrame(results)

    # ── 6. DAMAGE SCORE ───────────────────────────────────────────────────────
    def safe_norm(series):
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.5, index=series.index)
        return (series - mn) / (mx - mn)

    out['norm_dist']    = safe_norm(out['dist_to_damaged_m'])
    out['norm_density'] = 1 - safe_norm(out['damage_count_500m'])
    out['damage_score'] = (out['norm_dist'] + out['norm_density']) / 2
    out = out.drop(columns=['norm_dist', 'norm_density'])

    # ── 7. APPEND OUT-OF-AOI SITES AS NaN ─────────────────────────────────────
    remaining = sites_gdf[~in_aoi_mask][['site_id']].copy()
    remaining['dist_to_damaged_m']    = np.nan
    remaining['dist_to_destroyed_m']  = np.nan
    remaining['damage_count_500m']    = np.nan
    remaining['destroyed_count_500m'] = np.nan
    remaining['damage_score']         = np.nan
    remaining['in_aoi']               = False

    final = pd.concat([out, remaining], ignore_index=True)
    final = final.merge(sites[['site_id', 'latitude', 'longitude', 'facility_type']], on='site_id', how='left')
    final = final[['site_id', 'latitude', 'longitude', 'facility_type', 'in_aoi',
                   'dist_to_damaged_m', 'dist_to_destroyed_m',
                   'damage_count_500m', 'destroyed_count_500m', 'damage_score']]
    final.to_csv(out_all, index=False)

    # ── 8. SUMMARY ────────────────────────────────────────────────────────────
    aoi_rows = final[final['in_aoi']]
    print("\n── RESULTS SUMMARY ──────────────────────────────────────────────────────")
    print(f"Sites in AOI04:          {len(aoi_rows)}")
    print(f"Sites outside AOI (NaN): {len(final) - len(aoi_rows)}")
    print(f"\nDist to nearest damaged building:")
    print(f"  Min:    {aoi_rows['dist_to_damaged_m'].min():.1f} m")
    print(f"  Median: {aoi_rows['dist_to_damaged_m'].median():.1f} m")
    print(f"  Max:    {aoi_rows['dist_to_damaged_m'].max():.1f} m")
    print(f"\nDamaged buildings within 500m:")
    print(f"  Min:    {int(aoi_rows['damage_count_500m'].min())}")
    print(f"  Median: {aoi_rows['damage_count_500m'].median():.0f}")
    print(f"  Max:    {int(aoi_rows['damage_count_500m'].max())}")
    print(f"\nSaved: {out_all}")
    return final


def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    paths, dmg = config["paths"], config["damage"]
    return extract_damage(
        shp_path=paths["raw_damage_shp"],
        sites_csv=paths["out_sites"],
        out_all=paths["out_damage"],
        out_aoi=paths["out_sites_aoi04"],
        crs_metric=f"EPSG:{config['study_area']['utm_epsg']}",
        buffer_m=dmg["buffer_m"],
        aoi_pad_deg=dmg["aoi_pad_deg"],
    )


if __name__ == "__main__":
    extract_damage()
