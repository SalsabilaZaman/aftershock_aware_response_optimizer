import os
import sys

import pandas as pd

IN_DIR = "model_inputs"
OUT_DIR = "model_outputs"
MAP_PATH = os.path.join(OUT_DIR, "allocation_map_simple.html")

# Visual scaling for assignment lines
MIN_LINE_WIDTH = 1.0
MAX_LINE_WIDTH = 6.0


def read_csv(path, required_cols):
    if not os.path.exists(path):
        sys.exit(f"[ERROR] Missing file: {path}")
    df = pd.read_csv(path)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        sys.exit(f"[ERROR] {path} missing columns: {missing}")
    return df


def scaled_width(value, min_val, max_val):
    if max_val <= min_val:
        return (MIN_LINE_WIDTH + MAX_LINE_WIDTH) / 2
    frac = (value - min_val) / (max_val - min_val)
    return MIN_LINE_WIDTH + frac * (MAX_LINE_WIDTH - MIN_LINE_WIDTH)


def build_demand_traces(alloc, loc_lookup, demand_lookup):
    """Build (line, hover) trace pairs PER DEMAND POINT, so each demand point's outgoing
    assignments can be shown/hidden independently via a dropdown. A demand point can send
    casualties to both a hospital and a TMC, so it may contribute up to two pairs (one per
    color/facility_set) -- but they're grouped together under a single demand_point_id for
    the purposes of the dropdown, so one entry per demand point.

    Returns:
      traces: flat list of Scattermapbox traces
      demand_order: list of demand_point_id, one per group of traces added (1 or 2 pairs)
      group_sizes: matching list of how many trace-pairs belong to that demand point (1 or 2)
    """
    import plotly.graph_objects as go

    traces = []
    demand_order = []
    group_sizes = []

    color_by_set = {"JH": "#1b6f8f", "JT": "#d35d2f"}

    for demand_id, sub in alloc.groupby("demand_point_id"):
        if demand_id not in demand_lookup:
            continue
        d_lat, d_lon = demand_lookup[demand_id]
        demand_name = sub["demand_point_name"].iloc[0]

        pairs_added = 0
        for facility_set, type_sub in sub.groupby("facility_set"):
            color = color_by_set.get(facility_set, "#888888")
            min_flow = type_sub["assigned_casualties"].min()
            max_flow = type_sub["assigned_casualties"].max()

            lats, lons = [], []
            hover_lats, hover_lons, hover_text = [], [], []
            widths_meta = []

            for _, r in type_sub.iterrows():
                facility_id = r["facility_id"]
                if facility_id not in loc_lookup:
                    continue
                f_lat, f_lon = loc_lookup[facility_id]

                lats += [d_lat, f_lat, None]
                lons += [d_lon, f_lon, None]

                hover_lats.append((d_lat + f_lat) / 2)
                hover_lons.append((d_lon + f_lon) / 2)
                hover_text.append(
                    f"{demand_name} -> {facility_id}<br>"
                    f"Assigned: {r['assigned_casualties']:,.0f}<br>"
                    f"Distance: {r['distance_km']:.1f} km"
                )
                widths_meta.append(scaled_width(r["assigned_casualties"], min_flow, max_flow))

            if not lats:
                continue

            avg_width = sum(widths_meta) / len(widths_meta)
            traces.append(
                go.Scattermapbox(
                    lat=lats,
                    lon=lons,
                    mode="lines",
                    line={"width": avg_width, "color": color},
                    opacity=0.55,
                    hoverinfo="skip",
                    showlegend=False,
                    visible=True,
                )
            )
            traces.append(
                go.Scattermapbox(
                    lat=hover_lats,
                    lon=hover_lons,
                    mode="markers",
                    marker={"size": 5, "color": color, "opacity": 0.01},
                    text=hover_text,
                    hoverinfo="text",
                    showlegend=False,
                    visible=True,
                )
            )
            pairs_added += 1

        if pairs_added:
            demand_order.append((demand_id, demand_name))
            group_sizes.append(pairs_added)

    return traces, demand_order, group_sizes


def build_legend_swatches(center_lat, center_lon):
    """Invisible-on-map, visible-in-legend dummy traces so JH/JT colors are explained
    without cluttering the legend with one entry per demand point."""
    import plotly.graph_objects as go

    swatches = [
        go.Scattermapbox(
            lat=[center_lat, center_lat],
            lon=[center_lon, center_lon],
            mode="lines",
            line={"width": 4, "color": "#1b6f8f"},
            opacity=0,
            name="Assigned to hospital",
            hoverinfo="skip",
            showlegend=True,
        ),
        go.Scattermapbox(
            lat=[center_lat, center_lat],
            lon=[center_lon, center_lon],
            mode="lines",
            line={"width": 4, "color": "#d35d2f"},
            opacity=0,
            name="Assigned to TMC",
            hoverinfo="skip",
            showlegend=True,
        ),
    ]
    return swatches


def build_dropdown_menu(n_line_traces, demand_order, group_sizes):
    """Dropdown to isolate lines for: All / Hide all / one demand point.
    Only the demand-point line/hover traces are ever toggled; markers stay untouched.
    """
    # Each group_sizes[k] pairs (line+hover) belong to demand_order[k]; expand to a flat
    # per-trace-pair-index -> demand_index map so we can build visibility arrays.
    pair_owner = []
    for demand_idx, n_pairs in enumerate(group_sizes):
        pair_owner += [demand_idx] * n_pairs

    def visibility_for(predicate):
        vis = []
        for pair_idx, demand_idx in enumerate(pair_owner):
            show = predicate(demand_idx)
            vis.append(show)  # line trace
            vis.append(show)  # paired hover trace
        return vis

    line_trace_indices = list(range(2, 2 + n_line_traces))  # skip the 2 legend swatches

    buttons = [
        dict(
            label="All demand points",
            method="restyle",
            args=[{"visible": visibility_for(lambda idx: True)}, line_trace_indices],
        ),
        dict(
            label="Hide all lines (markers only)",
            method="restyle",
            args=[{"visible": visibility_for(lambda idx: False)}, line_trace_indices],
        ),
    ]
    for demand_idx, (demand_id, demand_name) in enumerate(demand_order):
        buttons.append(
            dict(
                label=f"Only: {demand_name} ({demand_id})",
                method="restyle",
                args=[
                    {"visible": visibility_for(lambda idx, target=demand_idx: idx == target)},
                    line_trace_indices,
                ],
            )
        )

    return dict(
        buttons=buttons,
        direction="down",
        showactive=True,
        x=0.01,
        y=0.98,
        xanchor="left",
        yanchor="top",
        bgcolor="white",
        bordercolor="#cccccc",
    )


def main():
    try:
        import plotly.graph_objects as go
    except ImportError:
        sys.exit("[ERROR] Plotly is required for the simplified allocation map.")

    demand = read_csv(
        os.path.join(IN_DIR, "demand_points.csv"),
        ["sub_district_id", "name", "latitude", "longitude", "pop_i"],
    )
    hospitals = read_csv(
        os.path.join(IN_DIR, "hospitals_jh.csv"),
        ["site_id", "cap_j", "latitude", "longitude"],
    )
    tmcs = read_csv(
        os.path.join(OUT_DIR, "tmc_selected.csv"),
        ["site_id", "latitude", "longitude", "cap_j", "assigned_casualties", "utilisation_pct"],
    )
    alloc = read_csv(
        os.path.join(OUT_DIR, "casualty_allocation.csv"),
        ["demand_point_id", "demand_point_name", "facility_id", "facility_set", "assigned_casualties", "distance_km"],
    )

    demand_lookup = {
        r["sub_district_id"]: (r["latitude"], r["longitude"]) for _, r in demand.iterrows()
    }
    facility_lookup = {}
    facility_lookup.update({r["site_id"]: (r["latitude"], r["longitude"]) for _, r in hospitals.iterrows()})
    facility_lookup.update({r["site_id"]: (r["latitude"], r["longitude"]) for _, r in tmcs.iterrows()})

    center_lat = demand["latitude"].mean() if len(demand) else 0
    center_lon = demand["longitude"].mean() if len(demand) else 0

    fig = go.Figure()

    # --- Legend color key (dummy, invisible-on-map traces) ---
    for t in build_legend_swatches(center_lat, center_lon):
        fig.add_trace(t)

    # --- Assignment lines, one pair of traces per demand point (toggleable via dropdown) ---
    demand_traces, demand_order, group_sizes = build_demand_traces(alloc, facility_lookup, demand_lookup)
    for t in demand_traces:
        fig.add_trace(t)

    # --- Demand points: white halo underneath for contrast against line clutter ---
    max_demand = demand["pop_i"].max() if len(demand) else 1
    demand_sizes = 8 + 26 * demand["pop_i"] / max_demand
    fig.add_trace(
        go.Scattermapbox(
            lat=demand["latitude"],
            lon=demand["longitude"],
            mode="markers",
            marker={"size": demand_sizes + 4, "color": "white", "opacity": 0.9},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scattermapbox(
            lat=demand["latitude"],
            lon=demand["longitude"],
            mode="markers",
            marker={"size": demand_sizes, "color": "#6f3fa5", "opacity": 0.9},
            name="Demand points",
            text=[
                f"{r['name']}<br>Demand: {r['pop_i']:,.0f}" for _, r in demand.iterrows()
            ],
            hoverinfo="text",
        )
    )

    # --- Existing hospitals: white halo underneath ---
    fig.add_trace(
        go.Scattermapbox(
            lat=hospitals["latitude"],
            lon=hospitals["longitude"],
            mode="markers",
            marker={"size": 16, "color": "white"},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scattermapbox(
            lat=hospitals["latitude"],
            lon=hospitals["longitude"],
            mode="markers",
            marker={"size": 12, "color": "#1b6f8f", "symbol": "hospital"},
            name="Existing hospitals",
            text=[
                f"{r['site_id']}<br>Cap: {r['cap_j']:,.0f}" for _, r in hospitals.iterrows()
            ],
            hoverinfo="text",
        )
    )

    # --- Selected TMCs: single category, no facility_type breakdown, white halo underneath ---
    fig.add_trace(
        go.Scattermapbox(
            lat=tmcs["latitude"],
            lon=tmcs["longitude"],
            mode="markers",
            marker={"size": 15, "color": "white"},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scattermapbox(
            lat=tmcs["latitude"],
            lon=tmcs["longitude"],
            mode="markers",
            marker={"size": 11, "color": "#d35d2f", "opacity": 0.95},
            name="Selected TMC (temporary)",
            text=[
                f"{r['site_id']}<br>Cap: {r['cap_j']:,.0f}<br>Assigned: {r['assigned_casualties']:,.0f}<br>Util: {r['utilisation_pct']:.1f}%"
                for _, r in tmcs.iterrows()
            ],
            hoverinfo="text",
        )
    )

    dropdown = build_dropdown_menu(len(demand_traces), demand_order, group_sizes)

    fig.update_layout(
        title="Simplified Emergency Response Allocation Map",
        mapbox={
            "style": "open-street-map",
            "center": {"lat": center_lat, "lon": center_lon},
            "zoom": 7.6,
        },
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        legend={"orientation": "v", "y": 0.98, "x": 0.80},
        updatemenus=[dropdown],
        height=780,
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    fig.write_html(MAP_PATH, include_plotlyjs="cdn", full_html=True)
    print(f"[DONE] Wrote {MAP_PATH}")


if __name__ == "__main__":
    main()
