import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from .settings import C_TRANS, MIP_GAP, TIME_LIMIT_SEC
    from .solver_support import (
        build_model_data,
        build_summary,
        extract_solution,
        load_solver_inputs,
        validate_solver_inputs,
        write_solution_outputs,
        write_summary,
    )
except ImportError:  # pragma: no cover - allows direct script execution
    from settings import C_TRANS, MIP_GAP, TIME_LIMIT_SEC
    from solver_support import (
        build_model_data,
        build_summary,
        extract_solution,
        load_solver_inputs,
        validate_solver_inputs,
        write_solution_outputs,
        write_summary,
    )


print("=" * 65)
print("  STEP 2 - Solve Facility Location MIP")
print("=" * 65)

demand, jh_df, jt_df, dist_df = load_solver_inputs()
validate_solver_inputs(demand, jh_df, jt_df, dist_df)

print(f"\n  Demand points  |I| : {len(demand)}")
print(f"  Hospitals      |JH|: {len(jh_df)}")
print(f"  TMC candidates |JT|: {len(jt_df)}")
print(f"  Distance pairs     : {len(dist_df):,}")
print(f"  Total demand       : {demand['pop_i'].sum():,} casualties")
print(f"  Total JH capacity  : {jh_df['cap_j'].sum():,}")
print(f"  Total JT capacity  : {jt_df['cap_j'].sum():,}")

print("\n[1] Building model data structures")
i_ids, jh, jt, j_all, pop, cap, opening_cost, distance = build_model_data(demand, jh_df, jt_df, dist_df)
total_demand = sum(pop.values())
total_capacity = sum(cap.values())
print(f"  Capacity check: {total_capacity:,.0f} >= {total_demand:,}: {'OK' if total_capacity >= total_demand else 'INFEASIBLE'}")

print("\n[2] Building PuLP MIP model")
try:
    import pulp
except ImportError:
    sys.exit("\n[ERROR] PuLP not installed. Run: pip install pulp")

model = pulp.LpProblem("Deterministic_Facility_Location", pulp.LpMinimize)
x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0, cat="Continuous") for i in i_ids for j in j_all}
y = {j: pulp.LpVariable(f"y_{j}", cat="Binary") for j in jt}

model += (
    pulp.lpSum(C_TRANS * distance[(i, j)] * x[(i, j)] for i in i_ids for j in j_all)
    + pulp.lpSum(opening_cost[j] * y[j] for j in jt),
    "Total_Cost",
)
for i in i_ids:
    model += (pulp.lpSum(x[(i, j)] for j in j_all) == pop[i], f"FullAllocation_{i}")
for j in jh:
    model += (pulp.lpSum(x[(i, j)] for i in i_ids) <= cap[j], f"CapHospital_{j}")
for j in jt:
    model += (pulp.lpSum(x[(i, j)] for i in i_ids) <= cap[j] * y[j], f"CapTMC_{j}")

print(f"  Variables   : {len(x) + len(y):,}")
print(f"  Constraints : {len(model.constraints):,}")

print(f"\n[3] Solving (time limit: {TIME_LIMIT_SEC}s, MIP gap: {MIP_GAP * 100:.0f}%)")
solver = pulp.PULP_CBC_CMD(msg=1, timeLimit=TIME_LIMIT_SEC, gapRel=MIP_GAP)
model.solve(solver)
status_text = pulp.LpStatus[model.status]
print(f"  Solver status: {status_text}")
if model.status != 1:
    sys.exit(f"\n[ERROR] Solver did not find a feasible solution. Status: {status_text}")
obj_val = pulp.value(model.objective)
print(f"  Objective (casualty-km): {obj_val:,.2f}")

print("\n[4] Extracting results")
selected_tmcs, tmc_out, alloc_df, hosp_util_df = extract_solution(
    i_ids, jh, jt, pop, cap, opening_cost, distance, demand, jh_df, jt_df, x, y, pulp
)
write_solution_outputs(tmc_out, alloc_df, hosp_util_df)

report = build_summary(
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
)
print("\n" + report)
write_summary(report)

print(f"\n  TMCs opened: {len(selected_tmcs)} / {len(jt)}")
print(f"  Allocation rows: {len(alloc_df)}")
print(f"  Hospital utilisation rows: {len(hosp_util_df)}")
print("\n[DONE] Step 2 complete.")
