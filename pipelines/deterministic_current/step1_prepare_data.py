try:
    from .prep_support import (
        add_demand_coordinates,
        build_demand_points,
        build_distance_matrix,
        build_hospitals_jh,
        build_tmc_candidates,
        load_optional_psaha,
        load_raw_inputs,
        validate_prepared_inputs,
        write_prepared_outputs,
    )
except ImportError:  # pragma: no cover - allows direct script execution
    from prep_support import (
        add_demand_coordinates,
        build_demand_points,
        build_distance_matrix,
        build_hospitals_jh,
        build_tmc_candidates,
        load_optional_psaha,
        load_raw_inputs,
        validate_prepared_inputs,
        write_prepared_outputs,
    )


print("=" * 65)
print("  STEP 1 - Data Preparation")
print("=" * 65)

raw = load_raw_inputs()
sub_districts = raw["sub_districts"]
casualties = raw["casualties"]
sites = raw["sites"]
hospitals = raw["hospitals"]
site_area = raw["site_area"]
psaha, pga_col = load_optional_psaha()

print(f"\n  sub_districts_raw.csv : {len(sub_districts)} rows")
print(f"  casualty_projections  : {len(casualties)} rows")
print(f"  candidate_sites.csv   : {len(sites)} rows")
print(f"  hospital_data.csv     : {len(hospitals)} rows")
print("  candidate facility types:")
for ft, cnt in sites["facility_type"].value_counts().items():
    print(f"    {ft:20s}: {cnt}")
print(f"  psaha_output          : {'enabled' if psaha is not None and pga_col else 'not available'}")

print("\n[1] Geocoding demand centroids")
sub_districts = add_demand_coordinates(sub_districts)

print("\n[2] Building demand vector")
demand = build_demand_points(sub_districts, casualties)
print(f"  demand points: {len(demand)}")
print(f"  total demand : {demand['pop_i'].sum():,} casualties")

print("\n[3] Building JH existing hospitals")
jh_df, matched_osm_site_ids, hospital_sources, hospital_audit = build_hospitals_jh(hospitals, sites)
print(f"  JH rows      : {len(jh_df)}")
print(f"  JH capacity  : {jh_df['cap_j'].sum():,}")
print(f"  matched OSM hospital sites excluded from JT: {len(matched_osm_site_ids)}")

print("\n[4] Building JT candidate TMC sites")
jt_df, tmc_audit, excluded_count, opening_cost_note = build_tmc_candidates(
    sites, matched_osm_site_ids, site_area, psaha, pga_col
)
print(f"  excluded sites: {excluded_count}")
print(f"  opening costs : {opening_cost_note}")
print("  JT capacity by type (area-derived, no longer uniform per type):")
for ft, sub in jt_df.groupby("facility_type"):
    print(f"    {ft:20s}: n={len(sub):4d} cap min/median/max={sub['cap_j'].min():4d}/"
          f"{int(sub['cap_j'].median()):4d}/{sub['cap_j'].max():5d} total={sub['cap_j'].sum():,}")

print("\n[5] Validating inputs and building distance matrix")
validate_prepared_inputs(jh_df, jt_df)
dist_df = build_distance_matrix(demand, jh_df, jt_df)
capacity_audit = hospital_audit + tmc_audit
write_prepared_outputs(demand, jh_df, jt_df, dist_df, hospital_sources, capacity_audit)

total_demand = int(demand["pop_i"].sum())
total_jh_cap = int(jh_df["cap_j"].sum())
total_jt_cap = int(jt_df["cap_j"].sum())
total_cap = total_jh_cap + total_jt_cap

print("\n" + "=" * 65)
print("  STEP 1 COMPLETE - Summary")
print("=" * 65)
print(f"  demand_points.csv             : {len(demand)} demand points")
print(f"  hospitals_jh.csv              : {len(jh_df)} hospitals cap={total_jh_cap:,}")
print(f"  candidates_jt.csv             : {len(jt_df)} TMC candidates cap={total_jt_cap:,}")
print(f"  distance_matrix.csv           : {len(dist_df):,} pairs")
print(f"  capacity_audit.csv            : {len(capacity_audit):,} audit rows")
print(f"  hospital_capacity_sources.csv : {len(hospital_sources)} source rows")
print(f"  total demand                  : {total_demand:,}")
print(f"  total usable capacity         : {total_cap:,}")
print(f"  feasibility                   : {'OK' if total_cap >= total_demand else 'INFEASIBLE'}")
if total_cap < total_demand:
    print(f"  shortfall                     : {total_demand - total_cap:,}")

print("\nNext: python deterministic_model\\step2_solve_model.py")
