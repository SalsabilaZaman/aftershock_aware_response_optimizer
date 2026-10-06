import osmnx as ox
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
import pickle

# Print version — important for API compatibility
print(f"OSMnx version: {ox.__version__}")

# Bounding box for city-level analysis
# Use a smaller box than the seismic region — just your candidate site area
NORTH, SOUTH = 37.70, 37.45
EAST,  WEST  = 37.05, 36.80

def download_road_graph(out_pkl: str = "data_raw/osm/road_graph.pkl", bbox: dict = None):
    """
    Download OSM drivable road network as a graph object.
    Save as pickle to avoid re-downloading.
    """
    print("Downloading road network from OSM (this may take 30-120 seconds)...")

    # NOTE: function signature varies by OSMnx version
    # v1.x: ox.graph_from_bbox(north, south, east, west, network_type='drive')
    # v2.x: ox.graph_from_bbox((north, south, east, west), network_type='drive')
    # Inspect the docs for YOUR installed version
    north = bbox["north"] if bbox else NORTH
    south = bbox["south"] if bbox else SOUTH
    east = bbox["east"] if bbox else EAST
    west = bbox["west"] if bbox else WEST
    try:
        # Try v1.x signature first
        G = ox.graph_from_bbox(north, south, east, west,
                               network_type='drive')
    except TypeError:
        # Fall back to v2.x tuple signature
        G = ox.graph_from_bbox((north, south, east, west),
                               network_type='drive')

    with open(out_pkl, "wb") as f:
        pickle.dump(G, f)
    print(f"[RAW] Graph saved: {len(G.nodes)} nodes, {len(G.edges)} edges")
    return G
# ── STEP 2: COMPUTE DISTANCES ──
def compute_road_distances(graph_pkl: str,
                             sites_csv: str,
                             out_csv: str,
                             utm_epsg: int = 32637):
    """
    Compute distance (m) from each site to the nearest road edge.
    utm_epsg: UTM zone for your area. Zone 37N (32637) for Turkey.
    Find your UTM zone at: https://epsg.io/?q=UTM+Turkey
    """
    with open(graph_pkl, "rb") as f:
        G = pickle.load(f)

    sites = pd.read_csv(sites_csv)

    # Convert graph edges to GeoDataFrame
    edges_gdf = ox.graph_to_gdfs(G, nodes=False, edges=True)
    print(f"[INSPECT] Edge columns: {list(edges_gdf.columns)}")
    # ↑ Inspect this — columns include 'highway', 'length', 'geometry', etc.

    # Project to UTM for accurate metre distances
    edges_proj = edges_gdf.to_crs(epsg=utm_epsg)
    road_union  = edges_proj.geometry.union_all()  # single geometry object

    # Build GeoDataFrame of sites, project to same CRS
    sites_gdf = gpd.GeoDataFrame(
        sites,
        geometry=[Point(r.longitude, r.latitude) for _, r in sites.iterrows()],
        crs="EPSG:4326"
    ).to_crs(epsg=utm_epsg)

    dist_list = []
    for _, s in sites_gdf.iterrows():
        dist_list.append(float(s.geometry.distance(road_union)))

    result = sites[["site_id"]].copy()
    result["dist_to_road_m"] = dist_list
    result.to_csv(out_csv, index=False)
    print(f"[FINAL] Road distances → {out_csv}")
    return result

def run(config: dict):
    """Config-driven entrypoint (see pipelines/extraction/config.yaml)."""
    import os
    paths = config["paths"]
    if config.get("force_refetch") or not os.path.exists(paths["raw_road_graph"]):
        download_road_graph(paths["raw_road_graph"], config["study_area"]["road_bbox"])
    else:
        print(f"[SKIP] Using cached {paths['raw_road_graph']}")
    return compute_road_distances(paths["raw_road_graph"], paths["out_sites"],
                                  paths["out_accessibility"],
                                  utm_epsg=config["study_area"]["utm_epsg"])


if __name__ == "__main__":
    G = download_road_graph()
    compute_road_distances("data_raw/osm/road_graph.pkl",
                           "data_processed/sites/candidate_sites.csv",
                           "data_processed/sites/accessibility_per_site.csv")