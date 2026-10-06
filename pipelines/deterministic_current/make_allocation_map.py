import os
import sys

import pandas as pd


IN_DIR = "model_inputs"
OUT_DIR = "model_outputs"
MAP_PATH = os.path.join(OUT_DIR, "allocation_map.html")


def read_csv(path, required_cols):
    if not os.path.exists(path):
        sys.exit(f"[ERROR] Missing file: {path}")
    df = pd.read_csv(path)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        sys.exit(f"[ERROR] {path} missing columns: {missing}")
    return df


def line_width(value, max_value):
    if max_value <= 0:
        return 1
    return max(1, min(8, 1 + 7 * value / max_value))


def main():
    try:
        import plotly.graph_objects as go
    except ImportError:
        sys.exit("[ERROR] Plotly is required for the allocation map.")

    demand = read_csv(
        os.path.join(IN_DIR, "demand_points.csv"),
        ["sub_district_id", "name", "latitude", "longitude", "pop_i"],
    )
    hospitals = read_csv(
        os.path.join(IN_DIR, "hospitals_jh.csv"),
        ["site_id", "hospital_name", "latitude", "longitude", "cap_j"],
    )
    tmcs = read_csv(
        os.path.join(OUT_DIR, "tmc_selected.csv"),
        ["site_id", "latitude", "longitude", "facility_type", "cap_j", "assigned_casualties", "utilisation_pct"],
    )
    allocation = read_csv(
        os.path.join(OUT_DIR, "casualty_allocation.csv"),
        ["demand_point_id", "facility_id", "facility_set", "assigned_casualties", "distance_km"],
    )
    hospital_util = read_csv(
        os.path.join(OUT_DIR, "hospital_utilisation.csv"),
        ["site_id", "hospital_name", "cap_j", "assigned_casualties", "utilisation_pct"],
    )

    demand_lookup = demand.set_index("sub_district_id").to_dict("index")
    hospital_points = hospitals.merge(
        hospital_util[["site_id", "assigned_casualties", "utilisation_pct"]],
        on="site_id",
        how="left",
    )
    facility_points = pd.concat(
        [
            hospital_points.assign(facility_set="JH", facility_type="hospital"),
            tmcs.assign(facility_set="JT"),
        ],
        ignore_index=True,
        sort=False,
    )
    facility_lookup = facility_points.set_index("site_id").to_dict("index")

    fig = go.Figure()
    max_alloc = allocation["assigned_casualties"].max() if len(allocation) else 0
    for _, row in allocation.iterrows():
        if row["demand_point_id"] not in demand_lookup or row["facility_id"] not in facility_lookup:
            continue
        dpt = demand_lookup[row["demand_point_id"]]
        fac = facility_lookup[row["facility_id"]]
        color = "rgba(42, 92, 170, 0.35)" if row["facility_set"] == "JH" else "rgba(210, 93, 44, 0.30)"
        fig.add_trace(
            go.Scattermapbox(
                lat=[dpt["latitude"], fac["latitude"]],
                lon=[dpt["longitude"], fac["longitude"]],
                mode="lines",
                line={"width": line_width(row["assigned_casualties"], max_alloc), "color": color},
                hoverinfo="text",
                text=(
                    f"{dpt['name']} -> {row['facility_id']}<br>"
                    f"Assigned: {row['assigned_casualties']:,.0f}<br>"
                    f"Distance: {row['distance_km']:.1f} km"
                ),
                showlegend=False,
            )
        )

    max_demand = demand["pop_i"].max()
    demand_sizes = 10 + 28 * demand["pop_i"] / max_demand
    fig.add_trace(
        go.Scattermapbox(
            lat=demand["latitude"],
            lon=demand["longitude"],
            mode="markers",
            marker={"size": demand_sizes, "color": "#6f3fa5", "opacity": 0.82},
            name="Demand points",
            text=[
                f"{r['name']}<br>Demand: {r['pop_i']:,.0f}<br>Population: {r['population']:,.0f}"
                for _, r in demand.iterrows()
            ],
            hoverinfo="text",
        )
    )

    fig.add_trace(
        go.Scattermapbox(
            lat=hospital_points["latitude"],
            lon=hospital_points["longitude"],
            mode="markers",
            marker={"size": 13, "color": "#1b6f8f", "symbol": "hospital"},
            name="Existing hospitals",
            text=[
                f"{r['site_id']}<br>{r['hospital_name']}<br>"
                f"Capacity: {r['cap_j']:,.0f}<br>"
                f"Assigned: {r.get('assigned_casualties', 0):,.0f}<br>"
                f"Utilisation: {r.get('utilisation_pct', 0):.1f}%"
                for _, r in hospital_points.iterrows()
            ],
            hoverinfo="text",
        )
    )

    type_colors = {
        "school": "#d35d2f",
        "university": "#2d8f65",
        "sports_centre": "#bc8b1f",
        "stadium": "#9b3f3f",
        "social_facility": "#607d8b",
    }
    for facility_type, sub in tmcs.groupby("facility_type"):
        fig.add_trace(
            go.Scattermapbox(
                lat=sub["latitude"],
                lon=sub["longitude"],
                mode="markers",
                marker={"size": 9, "color": type_colors.get(facility_type, "#555555"), "opacity": 0.9},
                name=f"Selected TMC: {facility_type}",
                text=[
                    f"{r['site_id']}<br>{r['facility_type']}<br>"
                    f"Capacity: {r['cap_j']:,.0f}<br>"
                    f"Assigned: {r['assigned_casualties']:,.0f}<br>"
                    f"Utilisation: {r['utilisation_pct']:.1f}%"
                    for _, r in sub.iterrows()
                ],
                hoverinfo="text",
            )
        )

    center_lat = demand["latitude"].mean()
    center_lon = demand["longitude"].mean()
    fig.update_layout(
        title="Kahramanmaras Emergency Response Allocation",
        mapbox={
            "style": "open-street-map",
            "center": {"lat": center_lat, "lon": center_lon},
            "zoom": 7.6,
        },
        margin={"l": 0, "r": 0, "t": 42, "b": 0},
        legend={"orientation": "v", "y": 0.98, "x": 0.01},
        height=850,
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    fig.write_html(MAP_PATH, include_plotlyjs=True, full_html=True)
    print(f"[DONE] Wrote {MAP_PATH}")


if __name__ == "__main__":
    main()
