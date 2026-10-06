import os
import sys

import pandas as pd

try:
    from settings import INPUT_DIR, OUTPUT_DIR
except ImportError:  # run as a script, not a package
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from settings import INPUT_DIR, OUTPUT_DIR

IN_DIR = INPUT_DIR
OUT_DIR = OUTPUT_DIR
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


def build_facility_traces(alloc, loc_lookup, demand_lookup):
    """Build one (line, hover) trace pair PER FACILITY, so each facility's incoming
    assignments can be shown/hidden independently via a dropdown. Returns:
      traces: flat list of Scattermapbox traces, in (line, hover) pairs per facility
      facility_order: list of (facility_id, facility_set) matching each pair's position
    """
    import plotly.graph_objects as go

    traces = []
    facility_order = []

    color_by_set = {"JH": "#1b6f8f", "JT": "#d35d2f"}

    for facility_id, sub in alloc.groupby("facility_id"):
        facility_set = sub["facility_set"].iloc[0]
        color = color_by_set.get(facility_set, "#888888")
        if facility_id not in loc_lookup:
            continue

        min_flow = sub["assigned_casualties"].min()
        max_flow = sub["assigned_casualties"].max()

        lats, lons = [], []
        hover_lats, hover_lons, hover_text = [], [], []
        widths_meta = []

        for _, r in sub.iterrows():
            i = r["demand_point_id"]
            if i not in demand_lookup:
                continue
            d_lat, d_lon = demand_lookup[i]
            f_lat, f_lon = loc_lookup[facility_id]

            lats += [d_lat, f_lat, None]
            lons += [d_lon, f_lon, None]

            hover_lats.append((d_lat + f_lat) / 2)
            hover_lons.append((d_lon + f_lon) / 2)
            hover_text.append(
                f"{r['demand_point_name']} -> {facility_id}<br>"
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
        facility_order.append((facility_id, facility_set))

    return traces, facility_order


def build_legend_swatches(center_lat, center_lon):
    """Invisible-on-map, visible-in-legend dummy traces so JH/JT colors are explained
    without cluttering the legend with one entry per facility."""
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


def build_dropdown_menu(n_line_traces, facility_order):
    """Dropdown to isolate lines for: All / Hospitals only / TMCs only / one facility.
    Only the facility line/hover traces are ever toggled; markers stay untouched.
    """
    def visibility_for(predicate):
        vis = []
        for facility_id, facility_set in facility_order:
            show = predicate(facility_id, facility_set)
            vis.append(show)  # line trace
            vis.append(show)  # paired hover trace
        return vis

    line_trace_indices = list(range(2, 2 + n_line_traces))  # skip the 2 legend swatches

    buttons = [
        dict(
            label="All facilities",
            method="restyle",
            args=[{"visible": visibility_for(lambda fid, fset: True)}, line_trace_indices],
        ),
        dict(
            label="Hospitals only",
            method="restyle",
            args=[{"visible": visibility_for(lambda fid, fset: fset == "JH")}, line_trace_indices],
        ),
        dict(
            label="TMCs only",
            method="restyle",
            args=[{"visible": visibility_for(lambda fid, fset: fset == "JT")}, line_trace_indices],
        ),
        dict(
            label="Hide all lines (markers only)",
            method="restyle",
            args=[{"visible": visibility_for(lambda fid, fset: False)}, line_trace_indices],
        ),
    ]
    for facility_id, facility_set in facility_order:
        buttons.append(
            dict(
                label=f"Only: {facility_id}",
                method="restyle",
                args=[
                    {"visible": visibility_for(lambda fid, fset, target=facility_id: fid == target)},
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

    # --- Assignment lines, one pair of traces per facility (toggleable via dropdown) ---
    facility_traces, facility_order = build_facility_traces(alloc, facility_lookup, demand_lookup)
    for t in facility_traces:
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

    dropdown = build_dropdown_menu(len(facility_traces), facility_order)

    fig.update_layout(
        title="Emergency Response Allocation Map",
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

# import os
# import sys

# import pandas as pd

# IN_DIR = "model_inputs"
# OUT_DIR = "model_outputs"
# MAP_PATH = os.path.join(OUT_DIR, "allocation_map_simple.html")

# # Visual scaling for assignment lines
# MIN_LINE_WIDTH = 1.0
# MAX_LINE_WIDTH = 6.0


# def read_csv(path, required_cols):
#     if not os.path.exists(path):
#         sys.exit(f"[ERROR] Missing file: {path}")
#     df = pd.read_csv(path)
#     missing = [c for c in required_cols if c not in df.columns]
#     if missing:
#         sys.exit(f"[ERROR] {path} missing columns: {missing}")
#     return df


# def scaled_width(value, min_val, max_val):
#     if max_val <= min_val:
#         return (MIN_LINE_WIDTH + MAX_LINE_WIDTH) / 2
#     frac = (value - min_val) / (max_val - min_val)
#     return MIN_LINE_WIDTH + frac * (MAX_LINE_WIDTH - MIN_LINE_WIDTH)


# def build_line_traces(alloc, facility_set, color, name, loc_lookup, demand_lookup):
#     """Build one line trace per allocation edge for a given facility_set (JH or JT),
#     using None-separated segments so they render as a single Scattermapbox trace."""
#     import plotly.graph_objects as go

#     sub = alloc[alloc["facility_set"] == facility_set]
#     if sub.empty:
#         return None

#     min_flow = sub["assigned_casualties"].min()
#     max_flow = sub["assigned_casualties"].max()

#     lats, lons, widths_meta = [], [], []
#     hover_lats, hover_lons, hover_text = [], [], []

#     for _, r in sub.iterrows():
#         i = r["demand_point_id"]
#         j = r["facility_id"]
#         if i not in demand_lookup or j not in loc_lookup:
#             continue
#         d_lat, d_lon = demand_lookup[i]
#         f_lat, f_lon = loc_lookup[j]

#         # one segment per edge, separated by None to break the line between edges
#         lats += [d_lat, f_lat, None]
#         lons += [d_lon, f_lon, None]

#         mid_lat = (d_lat + f_lat) / 2
#         mid_lon = (d_lon + f_lon) / 2
#         hover_lats.append(mid_lat)
#         hover_lons.append(mid_lon)
#         hover_text.append(
#             f"{r['demand_point_name']} -> {j}<br>"
#             f"Assigned: {r['assigned_casualties']:,.0f}<br>"
#             f"Distance: {r['distance_km']:.1f} km"
#         )
#         widths_meta.append(scaled_width(r["assigned_casualties"], min_flow, max_flow))

#     # Scattermapbox doesn't support per-segment line width in one trace, so use an
#     # average width for the whole set (kept simple/readable); hover markers carry the detail.
#     avg_width = sum(widths_meta) / len(widths_meta) if widths_meta else MIN_LINE_WIDTH

#     line_trace = go.Scattermapbox(
#         lat=lats,
#         lon=lons,
#         mode="lines",
#         line={"width": avg_width, "color": color},
#         opacity=0.45,
#         name=name,
#         hoverinfo="skip",
#         showlegend=True,
#     )
#     hover_trace = go.Scattermapbox(
#         lat=hover_lats,
#         lon=hover_lons,
#         mode="markers",
#         marker={"size": 4, "color": color, "opacity": 0.01},
#         text=hover_text,
#         hoverinfo="text",
#         name=f"{name} (detail)",
#         showlegend=False,
#     )
#     return [line_trace, hover_trace]


# def main():
#     try:
#         import plotly.graph_objects as go
#     except ImportError:
#         sys.exit("[ERROR] Plotly is required for the simplified allocation map.")

#     demand = read_csv(
#         os.path.join(IN_DIR, "demand_points.csv"),
#         ["sub_district_id", "name", "latitude", "longitude", "pop_i"],
#     )
#     hospitals = read_csv(
#         os.path.join(IN_DIR, "hospitals_jh.csv"),
#         ["site_id", "cap_j", "latitude", "longitude"],
#     )
#     tmcs = read_csv(
#         os.path.join(OUT_DIR, "tmc_selected.csv"),
#         ["site_id", "latitude", "longitude", "cap_j", "assigned_casualties", "utilisation_pct"],
#     )
#     alloc = read_csv(
#         os.path.join(OUT_DIR, "casualty_allocation.csv"),
#         ["demand_point_id", "demand_point_name", "facility_id", "facility_set", "assigned_casualties", "distance_km"],
#     )

#     demand_lookup = {
#         r["sub_district_id"]: (r["latitude"], r["longitude"]) for _, r in demand.iterrows()
#     }
#     facility_lookup = {}
#     facility_lookup.update({r["site_id"]: (r["latitude"], r["longitude"]) for _, r in hospitals.iterrows()})
#     facility_lookup.update({r["site_id"]: (r["latitude"], r["longitude"]) for _, r in tmcs.iterrows()})

#     fig = go.Figure()

#     # --- Assignment lines (drawn first so markers sit on top) ---
#     jh_traces = build_line_traces(alloc, "JH", "#1b6f8f", "Assigned to hospital", facility_lookup, demand_lookup)
#     if jh_traces:
#         for t in jh_traces:
#             fig.add_trace(t)

#     jt_traces = build_line_traces(alloc, "JT", "#d35d2f", "Assigned to TMC", facility_lookup, demand_lookup)
#     if jt_traces:
#         for t in jt_traces:
#             fig.add_trace(t)

#     # --- Demand points ---
#     max_demand = demand["pop_i"].max() if len(demand) else 1
#     demand_sizes = 8 + 26 * demand["pop_i"] / max_demand
#     fig.add_trace(
#         go.Scattermapbox(
#             lat=demand["latitude"],
#             lon=demand["longitude"],
#             mode="markers",
#             marker={"size": demand_sizes, "color": "#6f3fa5", "opacity": 0.75},
#             name="Demand points",
#             text=[
#                 f"{r['name']}<br>Demand: {r['pop_i']:,.0f}" for _, r in demand.iterrows()
#             ],
#             hoverinfo="text",
#         )
#     )

#     # --- Existing hospitals ---
#     fig.add_trace(
#         go.Scattermapbox(
#             lat=hospitals["latitude"],
#             lon=hospitals["longitude"],
#             mode="markers",
#             marker={"size": 12, "color": "#1b6f8f", "symbol": "hospital"},
#             name="Existing hospitals",
#             text=[
#                 f"{r['site_id']}<br>Cap: {r['cap_j']:,.0f}" for _, r in hospitals.iterrows()
#             ],
#             hoverinfo="text",
#         )
#     )

#     # --- Selected TMCs: single category, no facility_type breakdown ---
#     fig.add_trace(
#         go.Scattermapbox(
#             lat=tmcs["latitude"],
#             lon=tmcs["longitude"],
#             mode="markers",
#             marker={"size": 11, "color": "#d35d2f", "opacity": 0.9},
#             name="Selected TMC (temporary)",
#             text=[
#                 f"{r['site_id']}<br>Cap: {r['cap_j']:,.0f}<br>Assigned: {r['assigned_casualties']:,.0f}<br>Util: {r['utilisation_pct']:.1f}%"
#                 for _, r in tmcs.iterrows()
#             ],
#             hoverinfo="text",
#         )
#     )

#     center_lat = demand["latitude"].mean() if len(demand) else 0
#     center_lon = demand["longitude"].mean() if len(demand) else 0
#     fig.update_layout(
#         title="Simplified Emergency Response Allocation Map",
#         mapbox={
#             "style": "open-street-map",
#             "center": {"lat": center_lat, "lon": center_lon},
#             "zoom": 7.6,
#         },
#         margin={"l": 0, "r": 0, "t": 40, "b": 0},
#         legend={"orientation": "v", "y": 0.98, "x": 0.01},
#         height=780,
#     )

#     os.makedirs(OUT_DIR, exist_ok=True)
#     fig.write_html(MAP_PATH, include_plotlyjs="cdn", full_html=True)
#     print(f"[DONE] Wrote {MAP_PATH}")


# if __name__ == "__main__":
#     main()

# import os
# import sys

# import pandas as pd

# IN_DIR = "model_inputs"
# OUT_DIR = "model_outputs"
# MAP_PATH = os.path.join(OUT_DIR, "allocation_map_simple.html")


# def read_csv(path, required_cols):
#     if not os.path.exists(path):
#         sys.exit(f"[ERROR] Missing file: {path}")
#     df = pd.read_csv(path)
#     missing = [c for c in required_cols if c not in df.columns]
#     if missing:
#         sys.exit(f"[ERROR] {path} missing columns: {missing}")
#     return df


# def main():
#     try:
#         import plotly.graph_objects as go
#     except ImportError:
#         sys.exit("[ERROR] Plotly is required for the simplified allocation map.")

#     demand = read_csv(
#         os.path.join(IN_DIR, "demand_points.csv"),
#         ["sub_district_id", "name", "latitude", "longitude", "pop_i"],
#     )
#     hospitals = read_csv(
#         os.path.join(IN_DIR, "hospitals_jh.csv"),
#         ["site_id", "cap_j", "latitude", "longitude"],
#     )
#     tmcs = read_csv(
#         os.path.join(OUT_DIR, "tmc_selected.csv"),
#         ["site_id", "latitude", "longitude", "facility_type", "cap_j", "assigned_casualties", "utilisation_pct"],
#     )

#     fig = go.Figure()

#     max_demand = demand["pop_i"].max() if len(demand) else 1
#     demand_sizes = 8 + 26 * demand["pop_i"] / max_demand
#     fig.add_trace(
#         go.Scattermapbox(
#             lat=demand["latitude"],
#             lon=demand["longitude"],
#             mode="markers",
#             marker={"size": demand_sizes, "color": "#6f3fa5", "opacity": 0.75},
#             name="Demand points",
#             text=[
#                 f"{r['name']}<br>Demand: {r['pop_i']:,.0f}" for _, r in demand.iterrows()
#             ],
#             hoverinfo="text",
#         )
#     )

#     fig.add_trace(
#         go.Scattermapbox(
#             lat=hospitals["latitude"],
#             lon=hospitals["longitude"],
#             mode="markers",
#             marker={"size": 12, "color": "#1b6f8f", "symbol": "hospital"},
#             name="Existing hospitals",
#             text=[
#                 f"{r['site_id']}<br>Cap: {r['cap_j']:,.0f}" for _, r in hospitals.iterrows()
#             ],
#             hoverinfo="text",
#         )
#     )

#     type_colors = {
#         "school": "#d35d2f",
#         "university": "#2d8f65",
#         "sports_centre": "#bc8b1f",
#         "stadium": "#9b3f3f",
#         "social_facility": "#607d8b",
#     }
#     for facility_type, sub in tmcs.groupby("facility_type"):
#         fig.add_trace(
#             go.Scattermapbox(
#                 lat=sub["latitude"],
#                 lon=sub["longitude"],
#                 mode="markers",
#                 marker={"size": 10, "color": type_colors.get(facility_type, "#555555"), "opacity": 0.85},
#                 name=f"Selected TMC: {facility_type}",
#                 text=[
#                     f"{r['site_id']}<br>{r['facility_type']}<br>Cap: {r['cap_j']:,.0f}<br>Assigned: {r['assigned_casualties']:,.0f}<br>Util: {r['utilisation_pct']:.1f}%"
#                     for _, r in sub.iterrows()
#                 ],
#                 hoverinfo="text",
#             )
#         )

#     center_lat = demand["latitude"].mean() if len(demand) else 0
#     center_lon = demand["longitude"].mean() if len(demand) else 0
#     fig.update_layout(
#         title="Simplified Emergency Response Allocation Map",
#         mapbox={
#             "style": "open-street-map",
#             "center": {"lat": center_lat, "lon": center_lon},
#             "zoom": 7.6,
#         },
#         margin={"l": 0, "r": 0, "t": 40, "b": 0},
#         legend={"orientation": "v", "y": 0.98, "x": 0.01},
#         height=780,
#     )

#     os.makedirs(OUT_DIR, exist_ok=True)
#     fig.write_html(MAP_PATH, include_plotlyjs="cdn", full_html=True)
#     print(f"[DONE] Wrote {MAP_PATH}")


# if __name__ == "__main__":
#     main()
