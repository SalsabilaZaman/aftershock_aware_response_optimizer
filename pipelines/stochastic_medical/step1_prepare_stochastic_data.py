"""Step 6, part 1 -- load and validate the fixed network, scenario
casualties, capacities, and damage/road-ratio inputs the stochastic model
needs. Prints a summary; the actual lookups are cheap (no geocoding/OSM
calls) so run_augmecon2.py and step2 simply call prep_support again rather
than caching this to disk."""
try:
    from .prep_support import (
        build_capacity,
        build_distance_lookup,
        build_hospital_damage_factors,
        build_road_damage_ratios,
        load_fixed_network,
        load_scenario_casualties,
    )
    from .settings import PERIODS, SCENARIOS_USED, TRIAGE
except ImportError:  # pragma: no cover - allows direct script execution
    from prep_support import (
        build_capacity,
        build_distance_lookup,
        build_hospital_damage_factors,
        build_road_damage_ratios,
        load_fixed_network,
        load_scenario_casualties,
    )
    from settings import PERIODS, SCENARIOS_USED, TRIAGE

print("=" * 65)
print("  STEP 6 / PART 1 - Prepare stochastic model data")
print("=" * 65)

print("\n[1] Loading fixed facility network (risk-aware deterministic solve)")
jh_df, jt_df, demand_df = load_fixed_network()
print(f"  JH hospitals : {len(jh_df)}")
print(f"  JT TMCs      : {len(jt_df)} (already opened by the deterministic solve)")
print(f"  Demand points: {len(demand_df)}")

print("\n[2] Loading scenario casualties")
new_casualties = load_scenario_casualties()
total_by_scenario = {}
for (i, t, p, s), v in new_casualties.items():
    total_by_scenario[s] = total_by_scenario.get(s, 0.0) + v
print(f"  Scenarios used: {SCENARIOS_USED}")
for s in SCENARIOS_USED:
    print(f"    scenario {s}: {total_by_scenario.get(s, 0):,.0f} total casualties across periods {PERIODS}")

print("\n[3] Building distance lookup")
distance = build_distance_lookup(demand_df, jh_df, jt_df)
print(f"  {len(distance):,} (demand, facility) pairs")

print("\n[4] Building road-damage ratios (f^s) and hospital damage factors (g^s_j)")
road_damage_ratio = build_road_damage_ratios()
for s in SCENARIOS_USED:
    print(f"    scenario {s}: f^s = {road_damage_ratio[s]:.3f}")
damage_factors = build_hospital_damage_factors(jh_df)

print("\n[5] Building post-disaster capacity (Cap1/Cap2 per facility per scenario)")
cap1, cap2 = build_capacity(jh_df, jt_df, damage_factors)
total_cap1 = sum(v for (j, s), v in cap1.items() if s == SCENARIOS_USED[0])
total_cap2 = sum(v for (j, s), v in cap2.items() if s == SCENARIOS_USED[0])
print(f"  Total T1+T2 capacity (scenario {SCENARIOS_USED[0]}): {total_cap1:,.0f}")
print(f"  Total T3 capacity    (scenario {SCENARIOS_USED[0]}): {total_cap2:,.0f}")

print("\n[DONE] Data prepared and validated. Run step2_solve_stochastic_model.py")
print("       for a single representative solve, or run_augmecon2.py for the")
print("       full Pareto sweep.")
