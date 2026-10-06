import os
import sys

import pandas as pd

try:
    from .settings import C_TRANS, INPUT_DIR, OUTPUT_DIR
except ImportError:  # pragma: no cover - allows direct script execution
    from settings import C_TRANS, INPUT_DIR, OUTPUT_DIR


def load_input_csv(filename, required_cols=None):
    path = os.path.join(INPUT_DIR, filename)
    if not os.path.exists(path):
        sys.exit(f"\n[ERROR] {path} not found. Run step1_prepare_data.py first.")
    df = pd.read_csv(path)
    missing = [c for c in (required_cols or []) if c not in df.columns]
    if missing:
        sys.exit(f"\n[ERROR] {filename} missing columns: {missing}")
    return df


def fail_on_duplicates(df, column, label):
    duplicates = df[df[column].duplicated(keep=False)]
    if not duplicates.empty:
        sys.exit(f"\n[ERROR] Duplicate {column} values in {label}:\n{duplicates.sort_values(column)}")


def load_solver_inputs():
    demand = load_input_csv("demand_points.csv", ["sub_district_id", "name", "latitude", "longitude", "pop_i"])
    jh_df = load_input_csv("hospitals_jh.csv", ["site_id", "cap_j"])
    jt_df = load_input_csv("candidates_jt.csv", ["site_id", "cap_j", "F_j"])
    dist_df = load_input_csv("distance_matrix.csv", ["demand_point", "facility", "distance_km"])
    return demand, jh_df, jt_df, dist_df


def validate_solver_inputs(demand, jh_df, jt_df, dist_df):
    fail_on_duplicates(demand, "sub_district_id", "demand_points.csv")
    fail_on_duplicates(jh_df, "site_id", "hospitals_jh.csv")
    fail_on_duplicates(jt_df, "site_id", "candidates_jt.csv")
    if set(jh_df["site_id"]) & set(jt_df["site_id"]):
        sys.exit("\n[ERROR] JH/JT facility ID overlap detected.")
    if (jh_df["cap_j"] <= 0).any() or (jt_df["cap_j"] <= 0).any():
        sys.exit("\n[ERROR] Nonpositive facility capacity detected.")

    expected_pairs = len(demand) * (len(jh_df) + len(jt_df))
    if len(dist_df) != expected_pairs:
        sys.exit(f"\n[ERROR] distance_matrix.csv has {len(dist_df):,} rows; expected {expected_pairs:,}.")


def build_model_data(demand, jh_df, jt_df, dist_df):
    i_ids = demand["sub_district_id"].tolist()
    jh = set(jh_df["site_id"].tolist())
    jt = set(jt_df["site_id"].tolist())
    j_all = jh | jt
    pop = {r["sub_district_id"]: int(r["pop_i"]) for _, r in demand.iterrows()}
    cap = {}
    for _, r in pd.concat([jh_df[["site_id", "cap_j"]], jt_df[["site_id", "cap_j"]]]).iterrows():
        cap[r["site_id"]] = float(r["cap_j"])
    opening_cost = {r["site_id"]: float(r["F_j"]) for _, r in jt_df.iterrows()}
    distance = {(r["demand_point"], r["facility"]): float(r["distance_km"]) for _, r in dist_df.iterrows()}

    missing = [(i, j) for i in i_ids for j in j_all if (i, j) not in distance]
    if missing:
        sys.exit(f"\n[ERROR] Missing distances for {len(missing)} demand/facility pairs.")

    return i_ids, jh, jt, j_all, pop, cap, opening_cost, distance


def extract_solution(i_ids, jh, jt, pop, cap, opening_cost, distance, demand, jh_df, jt_df, x, y, pulp):
    selected_tmcs = {j for j in jt if pulp.value(y[j]) is not None and pulp.value(y[j]) > 0.5}
    tmc_out = jt_df[jt_df["site_id"].isin(selected_tmcs)].copy()
    tmc_out["y_j"] = 1
    tmc_out["assigned_casualties"] = tmc_out["site_id"].apply(
        lambda j: sum(pulp.value(x[(i, j)]) for i in i_ids if pulp.value(x[(i, j)]) is not None)
    )
    tmc_out["utilisation_pct"] = (tmc_out["assigned_casualties"] / tmc_out["cap_j"] * 100).round(1)

    demand_names = dict(zip(demand["sub_district_id"], demand["name"]))
    alloc_rows = []
    for i in i_ids:
        for j in jh | jt:
            val = pulp.value(x[(i, j)])
            if val is not None and val > 0.01:
                alloc_rows.append(
                    {
                        "demand_point_id": i,
                        "demand_point_name": demand_names[i],
                        "facility_id": j,
                        "facility_set": "JH" if j in jh else "JT",
                        "assigned_casualties": round(val, 2),
                        "distance_km": round(distance[(i, j)], 3),
                        # Objective is denominated in casualty-km; C_TRANS is
                        # definitionally 1.0 (see settings.py) so this column
                        # IS distance_km * assigned_casualties.
                        "travel_burden_casualty_km": round(C_TRANS * distance[(i, j)] * val, 2),
                    }
                )
    alloc_df = pd.DataFrame(alloc_rows)

    hosp_util_rows = []
    for j in sorted(jh):
        assigned = sum(pulp.value(x[(i, j)]) for i in i_ids if pulp.value(x[(i, j)]) is not None)
        hosp_info = jh_df[jh_df["site_id"] == j].iloc[0]
        hosp_util_rows.append(
            {
                "site_id": j,
                "hospital_id": hosp_info.get("hospital_id", ""),
                "hospital_name": hosp_info.get("hospital_name", j),
                "cap_j": cap[j],
                "assigned_casualties": round(assigned, 0),
                "utilisation_pct": round(assigned / cap[j] * 100, 1) if cap[j] > 0 else 0.0,
            }
        )
    hosp_util_df = pd.DataFrame(hosp_util_rows).sort_values("utilisation_pct", ascending=False)
    return selected_tmcs, tmc_out, alloc_df, hosp_util_df


def write_solution_outputs(tmc_out, alloc_df, hosp_util_df):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tmc_out.to_csv(os.path.join(OUTPUT_DIR, "tmc_selected.csv"), index=False)
    alloc_df.to_csv(os.path.join(OUTPUT_DIR, "casualty_allocation.csv"), index=False)
    hosp_util_df.to_csv(os.path.join(OUTPUT_DIR, "hospital_utilisation.csv"), index=False)


def build_summary(
    status_text,
    obj_val,
    i_ids,
    jh,
    jt,
    selected_tmcs,
    total_demand,
    jh_df,
    jt_df,
    pop,
    opening_cost,
    demand,
    tmc_out,
    alloc_df,
    hosp_util_df,
):
    travel_burden = alloc_df["travel_burden_casualty_km"].sum()
    opening_penalty_total = sum(opening_cost[j] for j in selected_tmcs)
    demand_names = dict(zip(demand["sub_district_id"], demand["name"]))
    lines = [
        "=" * 65,
        "  DETERMINISTIC FACILITY LOCATION MODEL - RESULTS",
        "  Kahramanmaras 2023 Post-Earthquake Emergency Response",
        "=" * 65,
        "",
        "  Objective is denominated in casualty-kilometres (not currency).",
        f"  Solver Status              : {status_text}",
        f"  Objective (casualty-km)    : {obj_val:,.2f}",
        f"    Travel burden (casualty-km)          : {travel_burden:,.2f}",
        f"    Opening penalty (casualty-km equiv.) : {opening_penalty_total:,.2f}",
        "",
        f"  |I|  Demand points   : {len(i_ids)}",
        f"  |JH| Hospitals       : {len(jh)}",
        f"  |JT| TMC candidates  : {len(jt)}",
        f"       TMCs opened      : {len(selected_tmcs)}",
        f"  Total demand         : {total_demand:,} casualties",
        f"  Total JH capacity    : {jh_df['cap_j'].sum():,}",
        f"  Total JT capacity    : {jt_df['cap_j'].sum():,}",
        "",
        "-" * 65,
        "  EXISTING HOSPITAL UTILISATION (JH)",
        "-" * 65,
        f"  {'Site ID':12s}  {'Hospital Name':38s}  {'Cap':>6s}  {'Assigned':>8s}  {'Util%':>6s}",
    ]
    for _, r in hosp_util_df.iterrows():
        lines.append(
            f"  {r['site_id']:12s}  {str(r['hospital_name'])[:38]:38s}  "
            f"{int(r['cap_j']):>6d}  {int(r['assigned_casualties']):>8d}  {r['utilisation_pct']:>5.1f}%"
        )

    lines += [
        "",
        "-" * 65,
        "  SELECTED TMC SITES (y_j = 1)",
        "-" * 65,
        f"  {'Site ID':12s}  {'Type':20s}  {'Cap':>6s}  {'Assigned':>8s}  {'Util%':>6s}",
    ]
    for _, r in tmc_out.iterrows():
        lines.append(
            f"  {r['site_id']:12s}  {str(r.get('facility_type', 'TMC'))[:20]:20s}  "
            f"{int(r['cap_j']):>6d}  {int(r['assigned_casualties']):>8d}  {r['utilisation_pct']:>5.1f}%"
        )

    lines += [
        "",
        "-" * 65,
        "  CASUALTY ASSIGNMENTS BY DEMAND POINT",
        "-" * 65,
        f"  {'ID':8s}  {'Name':22s}  {'Demand':>7s}  {'to JH':>8s}  {'to JT':>8s}  {'Avg dist':>8s}",
    ]
    for i in i_ids:
        sub = alloc_df[alloc_df["demand_point_id"] == i]
        to_jh = sub[sub["facility_set"] == "JH"]["assigned_casualties"].sum()
        to_jt = sub[sub["facility_set"] == "JT"]["assigned_casualties"].sum()
        avg_d = (
            (sub["distance_km"] * sub["assigned_casualties"]).sum() / sub["assigned_casualties"].sum()
            if len(sub)
            else 0
        )
        lines.append(
            f"  {i:8s}  {demand_names[i][:22]:22s}  {pop[i]:>7d}  "
            f"{int(to_jh):>8d}  {int(to_jt):>8d}  {avg_d:>7.1f}km"
        )
    lines += ["", "=" * 65]
    return "\n".join(lines)


def write_summary(report):
    with open(os.path.join(OUTPUT_DIR, "model_summary.txt"), "w", encoding="utf-8") as f:
        f.write(report)
