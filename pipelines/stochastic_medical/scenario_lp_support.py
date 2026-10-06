"""Paper-style, single-scenario medical response LP (kept separate from SAA)."""
from __future__ import annotations

from dataclasses import dataclass

import pulp

try:
    from . import settings as base
    from .prep_support import load_fixed_network, build_distance_lookup, select_tmc_candidates
except ImportError:  # direct script execution
    import settings as base
    from prep_support import load_fixed_network, build_distance_lookup, select_tmc_candidates


TRIAGE = ("T1", "T2", "T3")
SENSITIVITY = {
    "distance_limit_km": (8.0, 12.0, 16.0),
    "hospital_damage_max": (0.25, 0.50, 0.75),
    "t1_share": (0.10, 0.20, 0.30),
    "operational_staff_fraction": (0.50, 0.75, 1.00),
}


@dataclass
class ScenarioData:
    demand_ids: list
    hospitals: list
    tmcs: list
    distance: dict
    casualties: dict
    probabilities: dict
    road_damage: dict
    damage: dict
    bed_capacity: dict
    outpatient_capacity: dict
    doctors: dict
    nurses: dict
    candidate_pool: str = "all"
    candidate_count: int = 0
    available_candidate_count: int = 0


def load_scenario_data(hospital_damage_max=0.50,
                       operational_staff_fraction=1.0, t1_share=None,
                       candidate_pool="all"):
    """Read source scenarios and either the full or TOPSIS-screened TMC pool."""
    import pandas as pd

    hospitals_df, tmcs_df, demand_df = load_fixed_network()
    available_candidate_count = len(tmcs_df)
    tmcs_df = select_tmc_candidates(tmcs_df, candidate_pool)
    hospitals = hospitals_df.site_id.tolist()
    tmcs = tmcs_df.site_id.tolist()
    demand_ids = demand_df.sub_district_id.tolist()
    distance = build_distance_lookup(demand_df, hospitals_df, tmcs_df)
    raw = pd.read_csv(base.CASUALTY_PROJECTIONS_PATH)
    scenarios = sorted(int(s) for s in raw.scenario_id.unique())
    if len(scenarios) != 20:
        raise ValueError(f"Expected 20 source scenarios, found {len(scenarios)}")
    probabilities = raw.groupby("scenario_id").scenario_prob.first().to_dict()
    if abs(sum(float(probabilities[s]) for s in scenarios) - 1.0) > 1e-8:
        raise ValueError("scenario_prob values must sum to 1")
    casualties = {}
    for row in raw.itertuples():
        sid, period = int(row.scenario_id), int(row.period)
        for triage in TRIAGE:
            casualties[(row.sub_district_id, triage, period, sid)] = float(getattr(row, triage + "_count"))
    if t1_share is not None:
        if not 0 <= t1_share <= 1:
            raise ValueError("t1_share must be between 0 and 1")
        for i in demand_ids:
            for sid in scenarios:
                for period in base.PERIODS:
                    k1, k2, k3 = ((i, t, period, sid) for t in TRIAGE)
                    total = sum(casualties[k] for k in (k1, k2, k3))
                    remainder = casualties[k2] + casualties[k3]
                    t2_ratio = casualties[k2] / remainder if remainder else 0.5
                    casualties[k1] = total * t1_share
                    casualties[k2] = total * (1 - t1_share) * t2_ratio
                    casualties[k3] = total * (1 - t1_share) * (1 - t2_ratio)

    severity_rows = raw.groupby("scenario_id").dead_count.sum().to_dict()
    severity_max = max(severity_rows.values())
    severity = {int(s): float(v / severity_max if severity_max else 0) for s, v in severity_rows.items()}
    road_damage = {int(s): base.ROAD_DAMAGE_RATIO_MAX * severity[int(s)] for s in scenarios}
    damage_table = pd.read_csv(base.DAMAGE_INDICATORS_PATH, usecols=["site_id", "damage_score"])
    matched = hospitals_df[["site_id", "matched_site_id"]].merge(
        damage_table, left_on="matched_site_id", right_on="site_id", how="left", suffixes=("", "_damage"))
    matched.damage_score = matched.damage_score.fillna(1.0)
    local_loss = dict(zip(matched.site_id, 1.0 - matched.damage_score))
    damage = {(j, int(s)): local_loss[j] * hospital_damage_max * severity[int(s)]
              for j in hospitals for s in scenarios}
    bed_capacity, outpatient_capacity = {}, {}
    for _, row in hospitals_df.iterrows():
        for s in scenarios:
            factor = 1 - damage[(row.site_id, int(s))]
            bed_capacity[(row.site_id, int(s))] = float(row.cap_j) * factor
            out = row.outpatient_capacity if pd.notna(row.outpatient_capacity) else row.cap_j * base.TMC_OUTPATIENT_CAPACITY_MULTIPLIER
            outpatient_capacity[(row.site_id, int(s))] = float(out) * factor
    for _, row in tmcs_df.iterrows():
        for s in scenarios:
            bed_capacity[(row.site_id, int(s))] = float(row.cap_j)
            outpatient_capacity[(row.site_id, int(s))] = float(row.cap_j) * base.TMC_OUTPATIENT_CAPACITY_MULTIPLIER
    doctors = {r.site_id: (float(r.n_doctors_pre) if pd.notna(r.n_doctors_pre) else 0.0) * operational_staff_fraction
               for r in hospitals_df.itertuples()}
    nurses = {r.site_id: (float(r.n_nurses_pre) if pd.notna(r.n_nurses_pre) else 0.0) * operational_staff_fraction
              for r in hospitals_df.itertuples()}
    return ScenarioData(demand_ids, hospitals, tmcs, distance, casualties,
                        {int(s): float(p) for s, p in probabilities.items()}, road_damage,
                        damage, bed_capacity, outpatient_capacity, doctors, nurses,
                        candidate_pool, len(tmcs), available_candidate_count)


def eligible_t1_pairs(data: ScenarioData, scenario_id: int, distance_limit_km: float):
    return {(i, j) for i in data.demand_ids for j in data.hospitals
            if data.distance[(i, j)] * (1 + data.road_damage[scenario_id]) <= distance_limit_km}


def build_scenario_lp(data: ScenarioData, scenario_id: int, distance_limit_km=12.0):
    """Build one continuous LP. Returns model, variables, and objective expressions."""
    model = pulp.LpProblem(f"Medical_Response_s{scenario_id}", pulp.LpMinimize)
    I, JH, JT, P = data.demand_ids, data.hospitals, data.tmcs, base.PERIODS
    facilities, all_t = JH + JT, TRIAGE
    pairs_t1 = eligible_t1_pairs(data, scenario_id, distance_limit_km)
    # Integer indices keep generated LP names solver-safe despite source IDs.
    ii, jj = {v: k for k, v in enumerate(I)}, {v: k for k, v in enumerate(facilities)}
    T = {}
    for i in I:
        for j in facilities:
            for t in all_t:
                if t == "T1" and (j not in JH or (i, j) not in pairs_t1):
                    continue
                if t == "T1" and j in JT:
                    continue
                for p in P:
                    T[(i, j, t, p)] = pulp.LpVariable(f"T_{ii[i]}_{jj[j]}_{all_t.index(t)}_{p}", lowBound=0)
    Non = {(i, t, p): pulp.LpVariable(f"N_{ii[i]}_{all_t.index(t)}_{p}", lowBound=0)
           for i in I for t in all_t for p in P}
    ExtraD = {(j, p): pulp.LpVariable(f"ED_{jj[j]}_{p}", lowBound=0) for j in facilities for p in P}
    ExtraN = {(j, p): pulp.LpVariable(f"EN_{jj[j]}_{p}", lowBound=0) for j in facilities for p in P}
    Occ = {(j, t, p): pulp.LpVariable(f"Occ_{jj[j]}_{all_t.index(t)}_{p}", lowBound=0)
           for j in facilities for t in all_t for p in P}

    def flow_to(j, t, p):
        return pulp.lpSum(T[(i, j, t, p)] for i in I if (i, j, t, p) in T)

    # Untreated demand follows the paper's period-to-period Markov transitions.
    untreated_transition = base.UNTREAT_TRANSITION
    for i in I:
        for p in P:
            for t in all_t:
                inflow = data.casualties.get((i, t, p, scenario_id), 0.0)
                if p > 1:
                    prev = p - 1
                    inflow += pulp.lpSum(Non[(i, source, prev)] * untreated_transition[source].get(t, 0.0)
                                         for source in all_t)
                model += (pulp.lpSum(T[(i, j, t, p)] for j in facilities if (i, j, t, p) in T)
                          + Non[(i, t, p)] == inflow, f"Demand_{ii[i]}_{all_t.index(t)}_{p}")

    # Treated patients progress through health states; deaths/discharges leave occupancy.
    treat_transition = base.TREAT_TRANSITION
    for j in facilities:
        for p in P:
            for t in all_t:
                prior = 0
                if p > 1:
                    prior = pulp.lpSum(Occ[(j, source, p - 1)] * treat_transition[source].get(t, 0.0)
                                       for source in all_t)
                model += (Occ[(j, t, p)] == flow_to(j, t, p) + prior,
                          f"Occupancy_{jj[j]}_{all_t.index(t)}_{p}")
            model += (Occ[(j, "T1", p)] + Occ[(j, "T2", p)] <= data.bed_capacity[(j, scenario_id)],
                      f"BedCap_{jj[j]}_{p}")
            model += (Occ[(j, "T3", p)] <= data.outpatient_capacity[(j, scenario_id)],
                      f"OutCap_{jj[j]}_{p}")

    for j in facilities:
        for p in P:
            t1t2 = pulp.lpSum(flow_to(j, t, p) for t in ("T1", "T2"))
            all_flows = pulp.lpSum(flow_to(j, t, p) for t in all_t)
            docs = data.doctors.get(j, 0.0) if j in JH else 0.0
            nurs = data.nurses.get(j, 0.0) if j in JH else 0.0
            model += t1t2 / base.DOCTOR_PATIENTS_PER_PERIOD <= docs + ExtraD[(j, p)], f"DoctorCap_{jj[j]}_{p}"
            model += all_flows / base.NURSE_PATIENTS_PER_PERIOD <= nurs + ExtraN[(j, p)], f"NurseCap_{jj[j]}_{p}"

    Z1 = pulp.lpSum(Non.values())
    Z2 = pulp.lpSum(data.distance[(i, j)] * (1 + data.road_damage[scenario_id]) * var
                    for (i, j, t, p), var in T.items())
    Z3 = pulp.lpSum(ExtraD.values()) + pulp.lpSum(ExtraN.values())
    vars_ = {"T": T, "Non": Non, "ExtraD": ExtraD, "ExtraN": ExtraN, "Occ": Occ,
             "pairs_t1": pairs_t1}
    return model, vars_, (Z1, Z2, Z3)


def solve_lexicographic(data, scenario_id, distance_limit_km=12.0, solver=None):
    solver = solver or pulp.HiGHS(msg=False)
    model, variables, objectives = build_scenario_lp(data, scenario_id, distance_limit_km)
    optimum = []
    for idx, objective in enumerate(objectives):
        model.sense = pulp.LpMinimize
        model.setObjective(objective)
        status = model.solve(solver)
        if pulp.LpStatus[status] != "Optimal":
            raise RuntimeError(f"Scenario {scenario_id} lexicographic stage {idx+1}: {pulp.LpStatus[status]}")
        value = float(pulp.value(objective) or 0.0)
        if value < -1e-7:
            raise AssertionError(f"Scenario {scenario_id}: negative objective {value}")
        optimum.append(value)
        if idx < 2:
            tol = max(1e-7, abs(value) * 1e-9)
            model += objective <= value + tol, f"LexBound_{idx+1}"
    return model, variables, tuple(optimum)


def extract_solution(data, scenario_id, variables, distance_limit_km=12.0):
    val = lambda x: float(pulp.value(x) or 0.0)
    allocations, unmet, staffing = [], [], []
    for (i, j, t, p), var in variables["T"].items():
        amount = val(var)
        if amount > 1e-7:
            allocations.append({"scenario_id": scenario_id, "demand_point_id": i, "facility_id": j,
                                "triage": t, "period": p, "assigned_casualties": amount,
                                "distance_km": data.distance[(i, j)]})
    for (i, t, p), var in variables["Non"].items():
        amount = val(var)
        if amount > 1e-7:
            unmet.append({"scenario_id": scenario_id, "demand_point_id": i,
                          "triage": t, "period": p, "unmet_casualties": amount})
    for key in ("ExtraD", "ExtraN"):
        for (j, p), var in variables[key].items():
            amount = val(var)
            if amount > 1e-7:
                staffing.append({"scenario_id": scenario_id, "facility_id": j,
                                 "staff_type": "doctor" if key == "ExtraD" else "nurse",
                                 "period": p, "extra_staff": amount})
    assigned_tmcs = {r["facility_id"] for r in allocations if r["facility_id"] in data.tmcs}
    staffed_tmcs = {r["facility_id"] for r in staffing if r["facility_id"] in data.tmcs}
    return allocations, unmet, staffing, assigned_tmcs, staffed_tmcs

