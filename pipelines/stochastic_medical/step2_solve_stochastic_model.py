"""Solve the configured two-stage stochastic facility-location model."""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from .prep_support import (
        build_capacity,
        build_distance_lookup,
        build_hospital_damage_factors,
        build_road_damage_ratios,
        load_fixed_network,
        load_scenario_casualties,
        screen_tmc_candidates,
    )
    from .settings import OUTPUT_DIR, MIP_GAP, TIME_LIMIT_SEC, SCENARIO_PROB, SCENARIOS_USED, TRIAGE, PERIODS, SINGLE_RUN_TMC_BUDGET, ROAD_DAMAGE_RATIO_MAX
    from .solver_support import (
        build_model,
        build_model_data,
        extract_allocation,
        extract_staffing,
        extract_unmet,
    )
except ImportError:  # pragma: no cover - allows direct script execution
    from prep_support import (
        build_capacity,
        build_distance_lookup,
        build_hospital_damage_factors,
        build_road_damage_ratios,
        load_fixed_network,
        load_scenario_casualties,
        screen_tmc_candidates,
    )
    from settings import OUTPUT_DIR, MIP_GAP, TIME_LIMIT_SEC, SCENARIO_PROB, SCENARIOS_USED, TRIAGE, PERIODS, SINGLE_RUN_TMC_BUDGET, ROAD_DAMAGE_RATIO_MAX
    from solver_support import (
        build_model,
        build_model_data,
        extract_allocation,
        extract_staffing,
        extract_unmet,
    )

import pandas as pd

try:
    import pulp
except ImportError:
    sys.exit("\n[ERROR] PuLP not installed. Run: pip install pulp")

print("=" * 65)
print("  STEP 6 - Two-stage stochastic medical response model")
print("=" * 65)

jh_df, all_jt_df, demand_df = load_fixed_network()
jt_df = screen_tmc_candidates(all_jt_df)
i_ids = demand_df["sub_district_id"].tolist()
new_casualties = load_scenario_casualties()
distance = build_distance_lookup(demand_df, jh_df, all_jt_df)
road_damage_ratio = build_road_damage_ratios()
damage_factors = build_hospital_damage_factors(jh_df)
cap1, cap2 = build_capacity(jh_df, jt_df, damage_factors)
jh, jt, doctors_init, nurses_init = build_model_data(i_ids, jh_df, all_jt_df, distance)
jt = jt_df["site_id"].tolist()

print(f"\n  |I| demand points : {len(i_ids)}")
print(f"  |JH| hospitals    : {len(jh)}")
print(f"  |JT| candidates before screen: {len(all_jt_df)}")
print(f"  |JT| candidates optimized: {len(jt_df)} (top TOPSIS CC_i)")

print("\n[1] Building two-stage MILP")
model, variables, Z1, Z2, Z3 = build_model(
    pulp, i_ids, jh, jt, doctors_init, nurses_init, distance, new_casualties, cap1, cap2, road_damage_ratio,
    budget_limit=SINGLE_RUN_TMC_BUDGET
)
model += variables["Zobj"]
print(f"  Variables   : {len(model.variables()):,}")
print(f"  Constraints : {len(model.constraints):,}")

print(f"\n[2] Solving (time limit {TIME_LIMIT_SEC}s)")
solver = pulp.PULP_CBC_CMD(msg=1, timeLimit=TIME_LIMIT_SEC, gapRel=MIP_GAP)
model.solve(solver)
status_text = pulp.LpStatus[model.status]
print(f"  Solver status: {status_text}")
if model.status != 1:
    sys.exit(f"\n[ERROR] Solver did not find a feasible solution. Status: {status_text}")

z1_val, z2_val, z3_val = pulp.value(Z1), pulp.value(Z2), pulp.value(Z3)
component_values = {key: float(pulp.value(variables[key]) or 0.0)
                    for key in ("Zunmet", "Ztravel", "Zstaff")}
objective_value = float(pulp.value(model.objective))
if objective_value < -1e-6:
    sys.exit(f"[ERROR] Objective must be nonnegative; got {objective_value}")
if abs(objective_value - sum(component_values.values())) > max(1e-4, objective_value*1e-8):
    sys.exit("[ERROR] Objective total does not equal its printed components")
max_transport = max(distance.values()) * (1.0 + ROAD_DAMAGE_RATIO_MAX)
scenario_fractions = []
for s in SCENARIOS_USED:
    generated_s = sum(new_casualties.get((i,t,p,s), 0.0) for i in i_ids for t in TRIAGE for p in PERIODS)
    served_s = sum((pulp.value(v) or 0.0) for key, v in variables["T"].items() if key[-1] == s)
    scenario_fractions.append(SCENARIO_PROB[s] * (1.0 - (generated_s-served_s)/generated_s if generated_s else 1.0))
fraction_served = sum(scenario_fractions)
print(f"  Z1 (unmet casualties, weighted) : {z1_val:,.2f}")
print(f"  Z2 (travel burden casualty-km)  : {z2_val:,.2f}")
print(f"  Z3 (staffing, extra staff-periods): {z3_val:,.2f}")
print(f"  Objective components (unmet/travel/staffing): {component_values['Zunmet']:,.2f} / {component_values['Ztravel']:,.2f} / {component_values['Zstaff']:,.2f}")
print(f"  Objective total                    : {objective_value:,.2f}")
print(f"  Unmet penalty weight               : {variables['unmet_weight']:,.2f}")
print(f"  10x maximum transport threshold     : {10.0*max_transport:,.2f}")
print(f"  Expected fraction of casualties served: {fraction_served:.2%}")

print("\n[3] Extracting and writing outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
pd.DataFrame(extract_allocation(pulp, variables, distance)).to_csv(OUTPUT_DIR / "casualty_allocation.csv", index=False)
pd.DataFrame(extract_unmet(pulp, variables)).to_csv(OUTPUT_DIR / "unmet_demand.csv", index=False)
pd.DataFrame(extract_staffing(pulp, variables)).to_csv(OUTPUT_DIR / "staffing_plan.csv", index=False)
selected = sorted(j for j, v in variables["y"].items() if (pulp.value(v) or 0) > 0.5)
pd.DataFrame({"site_id": selected}).to_csv(OUTPUT_DIR / "tmc_selected.csv", index=False)

summary = (
    "=" * 65 + "\n"
    "  TWO-STAGE STOCHASTIC MEDICAL RESPONSE MODEL RESULT\n"
    "  model_version: two_stage_budget_saa_v2\n"
    "  Kahramanmaras 2023 Post-Earthquake Emergency Response\n"
    + "=" * 65 + "\n\n"
    f"  Solver status : {status_text}\n"
    "  Distance diagnosis (straight-line distance matrix): SD004 to H001/H002 = 10.70/9.31 km; SD009 = 10.94/8.68 km.\n"
    "  Effective post-quake hospital capacity: 2,568 beds (raw listed bed_capacity_total sums to 2,693).\n"
    f"  Z1 (unmet casualties, prob-weighted)  : {z1_val:,.2f}\n"
    f"  Z2 (travel burden, casualty-km, prob-weighted) : {z2_val:,.2f}\n"
    f"  Z3 (staffing, extra staff-periods, prob-weighted) : {z3_val:,.2f}\n"
    f"  Fraction of casualties served (scenario weighted) : {fraction_served:.2%}\n"
    f"  Open TMCs : {', '.join(selected)}\n"
    f"  TMC site budget: {SINGLE_RUN_TMC_BUDGET}; objective total: {objective_value:,.2f}.\n"
    f"  Objective components (nonnegative): unmet={component_values['Zunmet']:,.2f}, travel={component_values['Ztravel']:,.2f}, staffing={component_values['Zstaff']:,.2f}.\n"
    f"  Unmet penalty weight: {variables['unmet_weight']:,.2f}; 10x max transport: {10.0*max_transport:,.2f}.\n"
    "  T1 catchment uses straight-line distance with a 12 km limit; T1 routing is hospital-only.\n"
)
(OUTPUT_DIR / "model_summary.txt").write_text(summary, encoding="utf-8")
print(summary)
print("[DONE] Step 6 / Part 2 complete.")
