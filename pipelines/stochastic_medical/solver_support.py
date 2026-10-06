"""Two-stage facility-location model with shared first-stage TMC decisions."""
try:
    from .settings import (
        DISTANCE_LIMIT_T1_KM,
        DOCTOR_PATIENTS_PER_PERIOD,
        NURSE_PATIENTS_PER_PERIOD,
        PERIODS,
        SCENARIO_PROB,
        SCENARIOS_USED,
        TRIAGE,
        UNTREAT_TRANSITION,
        ROAD_DAMAGE_RATIO_MAX,
        UNMET_PENALTY_FACTOR,
        TRAVEL_COST_WEIGHT_PER_CASUALTY_KM,
        STAFFING_COST_WEIGHT_PER_STAFF_PERIOD,
    )
except ImportError:  # pragma: no cover - allows direct script execution
    from settings import (
        DISTANCE_LIMIT_T1_KM,
        DOCTOR_PATIENTS_PER_PERIOD,
        NURSE_PATIENTS_PER_PERIOD,
        PERIODS,
        SCENARIO_PROB,
        SCENARIOS_USED,
        TRIAGE,
        UNTREAT_TRANSITION,
        ROAD_DAMAGE_RATIO_MAX,
        UNMET_PENALTY_FACTOR,
        TRAVEL_COST_WEIGHT_PER_CASUALTY_KM,
        STAFFING_COST_WEIGHT_PER_STAFF_PERIOD,
    )


def facility_triage_pairs(i_ids, jh, jt, distance):
    """Which (j, t) combinations a facility can serve.

    T1 (immediate/critical) is hospital-only (PDF eq. 36 is JH-specific;
    JT has no T1 term anywhere in eq. 37-38) and additionally limited to
    hospitals within DISTANCE_LIMIT_T1_KM (PDF eq. 46). T2/T3 can go to
    either JH or JT.
    """
    pairs = set()
    for i in i_ids:
        for j in jh:
            if distance[(i, j)] <= DISTANCE_LIMIT_T1_KM:
                pairs.add((i, j, "T1"))
            pairs.add((i, j, "T2"))
            pairs.add((i, j, "T3"))
        for j in jt:
            pairs.add((i, j, "T2"))
            pairs.add((i, j, "T3"))
    return pairs


def build_model_data(i_ids, jh_df, jt_df, distance):
    jh = jh_df["site_id"].tolist()
    jt = jt_df["site_id"].tolist()
    doctors_init = {r["site_id"]: (r["n_doctors_pre"] if r["n_doctors_pre"] == r["n_doctors_pre"] else 0.0) for _, r in jh_df.iterrows()}
    nurses_init = {r["site_id"]: (r["n_nurses_pre"] if r["n_nurses_pre"] == r["n_nurses_pre"] else 0.0) for _, r in jh_df.iterrows()}
    return jh, jt, doctors_init, nurses_init


def build_model(pulp, i_ids, jh, jt, doctors_init, nurses_init, distance, new_casualties,
                 cap1, cap2, road_damage_ratio, scenario_ids=None, scenario_prob=None,
                 open_sites=None, required_sites=None, budget_limit=None, unmet_weight=None):
    """Build a two-stage MILP with a site-count budget and nonnegative objective."""
    model = pulp.LpProblem("Stochastic_Medical_Response", pulp.LpMinimize)
    scenario_ids = list(scenario_ids or SCENARIOS_USED)
    scenario_prob = scenario_prob or {s: 1.0 / len(scenario_ids) for s in scenario_ids}
    max_distance = max(distance.values()) if distance else 0.0
    max_transport_cost = max_distance * (1.0 + ROAD_DAMAGE_RATIO_MAX) * TRAVEL_COST_WEIGHT_PER_CASUALTY_KM
    max_staff_cost_per_casualty = STAFFING_COST_WEIGHT_PER_STAFF_PERIOD * (
        1.0 / DOCTOR_PATIENTS_PER_PERIOD + 1.0 / NURSE_PATIENTS_PER_PERIOD
    )
    unmet_weight = unmet_weight or UNMET_PENALTY_FACTOR * (max_transport_cost + max_staff_cost_per_casualty)
    generated = {
        s: sum(new_casualties.get((i, t, p, s), 0.0) for i in i_ids for t in TRIAGE for p in PERIODS)
        for s in scenario_ids
    }
    valid = facility_triage_pairs(i_ids, jh, jt, distance)

    T = {
        (i, j, t, p, s): pulp.LpVariable(f"T_{i}_{j}_{t}_{p}_{s}", lowBound=0, cat="Continuous")
        for (i, j, t) in valid
        for p in PERIODS
        for s in scenario_ids
    }
    Non = {
        (i, t, p, s): pulp.LpVariable(f"Non_{i}_{t}_{p}_{s}", lowBound=0, cat="Continuous")
        for i in i_ids for t in TRIAGE for p in PERIODS for s in scenario_ids
    }
    De = {(j, p, s): pulp.LpVariable(f"De_{j}_{p}_{s}", lowBound=0, cat="Continuous") for j in jh for p in PERIODS for s in scenario_ids}
    Ne = {(j, p, s): pulp.LpVariable(f"Ne_{j}_{p}_{s}", lowBound=0, cat="Continuous") for j in jh for p in PERIODS for s in scenario_ids}
    Dt = {(j, p, s): pulp.LpVariable(f"Dt_{j}_{p}_{s}", lowBound=0, cat="Continuous") for j in jt for p in PERIODS for s in scenario_ids}
    Nt = {(j, p, s): pulp.LpVariable(f"Nt_{j}_{p}_{s}", lowBound=0, cat="Continuous") for j in jt for p in PERIODS for s in scenario_ids}
    y = {j: pulp.LpVariable(
        f"open_{j}", cat="Binary" if open_sites is None else "Continuous",
        lowBound=(1 if j in (required_sites or set()) else 0) if open_sites is None else int(j in open_sites),
        upBound=1 if open_sites is None or j in open_sites else 0,
    ) for j in jt}
    UniqueUnmet = {s: pulp.LpVariable(f"UniqueUnmet_{s}", lowBound=0, upBound=generated[s], cat="Continuous") for s in scenario_ids}
    if budget_limit is not None:
        model += (pulp.lpSum(y.values()) <= budget_limit, "TMC_Budget")

    def routed(i, j, t, p, s):
        return T.get((i, j, t, p, s))

    def facilities_for(i, t):
        return [j for (ii, j, tt) in valid if ii == i and tt == t]

    # --- Demand balance (PDF eq. 42-45) ---------------------------------
    for s in scenario_ids:
        for i in i_ids:
            for p in PERIODS:
                for t in TRIAGE:
                    inflow = new_casualties.get((i, t, p, s), 0.0)
                    if p > 1:
                        prev = p - 1
                        if t == "T1":
                            inflow += (
                                Non[(i, "T1", prev, s)] * UNTREAT_TRANSITION["T1"]["T1"]
                                + Non[(i, "T2", prev, s)] * UNTREAT_TRANSITION["T2"]["T1"]
                            )
                        elif t == "T2":
                            inflow += (
                                Non[(i, "T2", prev, s)] * UNTREAT_TRANSITION["T2"]["T2"]
                                + Non[(i, "T3", prev, s)] * UNTREAT_TRANSITION["T3"]["T2"]
                            )
                        else:  # T3
                            inflow += Non[(i, "T3", prev, s)] * UNTREAT_TRANSITION["T3"]["T3"]
                    served = pulp.lpSum(routed(i, j, t, p, s) for j in facilities_for(i, t))
                    model += (served + Non[(i, t, p, s)] == inflow, f"Demand_{i}_{t}_{p}_{s}")

    # --- Capacity (PDF eq. 36-38, held static across periods per scenario
    #     -- see docs/STOCHASTIC_MODEL.md simplification S2) --------------
    for s in scenario_ids:
        for p in PERIODS:
            for j in jh:
                model += (
                    pulp.lpSum(routed(i, j, t, p, s) for i in i_ids for t in ("T1", "T2") if routed(i, j, t, p, s) is not None)
                    <= cap1[(j, s)],
                    f"CapJH1_{j}_{p}_{s}",
                )
                model += (
                    pulp.lpSum(routed(i, j, "T3", p, s) for i in i_ids if routed(i, j, "T3", p, s) is not None)
                    <= cap2[(j, s)],
                    f"CapJH2_{j}_{p}_{s}",
                )
            for j in jt:
                model += (
                    pulp.lpSum(routed(i, j, "T2", p, s) for i in i_ids if routed(i, j, "T2", p, s) is not None)
                    <= cap1[(j, s)],
                    f"CapJT1_{j}_{p}_{s}",
                )
                model += (
                    pulp.lpSum(routed(i, j, "T3", p, s) for i in i_ids if routed(i, j, "T3", p, s) is not None)
                    <= cap2[(j, s)],
                    f"CapJT2_{j}_{p}_{s}",
                )
                model += (pulp.lpSum(routed(i, j, t, p, s) for i in i_ids for t in ("T2", "T3") if routed(i, j, t, p, s) is not None)
                          <= (cap1[(j, s)] + cap2[(j, s)]) * y[j], f"OpenLink_{j}_{p}_{s}")

    # --- Staffing (PDF eq. 47-50) ---------------------------------------
    for s in scenario_ids:
        for p in PERIODS:
            for j in jh:
                model += (
                    pulp.lpSum(routed(i, j, t, p, s) for i in i_ids for t in ("T1", "T2") if routed(i, j, t, p, s) is not None)
                    / DOCTOR_PATIENTS_PER_PERIOD
                    <= doctors_init[j] + De[(j, p, s)],
                    f"StaffDoctorJH_{j}_{p}_{s}",
                )
                model += (
                    pulp.lpSum(routed(i, j, t, p, s) for i in i_ids for t in TRIAGE if routed(i, j, t, p, s) is not None)
                    / NURSE_PATIENTS_PER_PERIOD
                    <= nurses_init[j] + Ne[(j, p, s)],
                    f"StaffNurseJH_{j}_{p}_{s}",
                )
            for j in jt:
                model += (
                    pulp.lpSum(routed(i, j, "T2", p, s) for i in i_ids if routed(i, j, "T2", p, s) is not None)
                    / DOCTOR_PATIENTS_PER_PERIOD
                    <= Dt[(j, p, s)],
                    f"StaffDoctorJT_{j}_{p}_{s}",
                )
                model += (
                    pulp.lpSum(routed(i, j, t, p, s) for i in i_ids for t in ("T2", "T3") if routed(i, j, t, p, s) is not None)
                    / NURSE_PATIENTS_PER_PERIOD
                    <= Nt[(j, p, s)],
                    f"StaffNurseJT_{j}_{p}_{s}",
                )

    # --- Objectives (PDF eq. 33-35) --------------------------------------
    # Unique unmet = total unique casualties generated minus all treatment
    # events. Treated casualties leave the untreated transition pool, so each
    # casualty can contribute at most once to routed treatment.
    treated = {s: pulp.lpSum(T[(i,j,t,p,s)] for (i,j,t) in valid for p in PERIODS) for s in scenario_ids}
    for s in scenario_ids:
        model += (UniqueUnmet[s] + treated[s] >= generated[s], f"UniqueUnmetBalance_{s}")
    Z1 = pulp.lpSum(scenario_prob[s] * UniqueUnmet[s] for s in scenario_ids)
    Z2 = pulp.lpSum(
        scenario_prob[s] * distance[(i, j)] * (1 + road_damage_ratio[s]) * T[(i, j, t, p, s)]
        for (i, j, t) in valid for p in PERIODS for s in scenario_ids
    )
    Z3 = pulp.lpSum(
        scenario_prob[s] * (De[(j, p, s)] + Ne[(j, p, s)])
        for j in jh for p in PERIODS for s in scenario_ids
    ) + pulp.lpSum(
        scenario_prob[s] * (Dt[(j, p, s)] + Nt[(j, p, s)])
        for j in jt for p in PERIODS for s in scenario_ids
    )

    Zunmet = unmet_weight * Z1
    Ztravel = TRAVEL_COST_WEIGHT_PER_CASUALTY_KM * Z2
    Zstaff = STAFFING_COST_WEIGHT_PER_STAFF_PERIOD * Z3
    Zobj = Zunmet + Ztravel + Zstaff
    variables = {"T": T, "Non": Non, "De": De, "Ne": Ne, "Dt": Dt, "Nt": Nt,
                 "y": y, "UniqueUnmet": UniqueUnmet, "Zunmet": Zunmet,
                 "Ztravel": Ztravel, "Zstaff": Zstaff, "Zobj": Zobj,
                 "unmet_weight": unmet_weight}
    return model, variables, Z1, Z2, Z3


def extract_allocation(pulp, variables, distance):
    """Non-zero routed casualties, one row per (i,j,t,p,s)."""
    T = variables["T"]
    rows = []
    for (i, j, t, p, s), var in T.items():
        val = pulp.value(var)
        if val is not None and val > 0.01:
            rows.append({
                "demand_point_id": i,
                "facility_id": j,
                "triage": t,
                "period": p,
                "scenario_id": s,
                "assigned_casualties": round(val, 2),
                "distance_km": round(distance[(i, j)], 3),
            })
    return rows


def extract_unmet(pulp, variables):
    Non = variables["Non"]
    rows = []
    for (i, t, p, s), var in Non.items():
        val = pulp.value(var)
        if val is not None and val > 0.01:
            rows.append({"demand_point_id": i, "triage": t, "period": p, "scenario_id": s, "unmet_casualties": round(val, 2)})
    return rows


def extract_staffing(pulp, variables):
    rows = []
    for kind, var_dict in (("De", variables["De"]), ("Ne", variables["Ne"]), ("Dt", variables["Dt"]), ("Nt", variables["Nt"])):
        for (j, p, s), var in var_dict.items():
            val = pulp.value(var)
            if val is not None and val > 0.01:
                rows.append({"facility_id": j, "staff_type": kind, "period": p, "scenario_id": s, "extra_staff": round(val, 2)})
    return rows
