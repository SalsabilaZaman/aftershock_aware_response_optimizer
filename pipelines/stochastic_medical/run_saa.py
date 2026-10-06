"""Budget sweep with independent SAA training samples and paired validation.

Run a quick development sample: python pipelines/stochastic_medical/run_saa.py
Run publication-sized SAA: python pipelines/stochastic_medical/run_saa.py --profile final
All policies use the same generated out-of-sample draws. Distinct opened-site sets
are evaluated once and reused for duplicate policies.
"""
import sys
import argparse
import json
import time
import numpy as np
import pandas as pd

try:
    import pulp
except ImportError:
    sys.exit("PuLP is required: install it in the project environment.")

_DAMAGE_TABLE = None

try:
    from . import settings as cfg
    from .prep_support import build_distance_lookup, build_capacity, load_fixed_network, select_tmc_candidates
    from .solver_support import (build_model, build_model_data, extract_allocation,
                                 extract_unmet, extract_staffing)
    from .runtime_metrics import peak_memory_mb
except ImportError:
    import settings as cfg
    from prep_support import build_distance_lookup, build_capacity, load_fixed_network, select_tmc_candidates
    from solver_support import (build_model, build_model_data, extract_allocation,
                                extract_unmet, extract_staffing)
    from runtime_metrics import peak_memory_mb


def load_sources():
    raw = pd.read_csv(cfg.CASUALTY_PROJECTIONS_PATH)
    source_ids = sorted(raw.scenario_id.unique())
    samples = {}
    for sid in source_ids:
        samples[sid] = {
            (r.sub_district_id, t, int(r.period)): float(getattr(r, t + "_count"))
            for r in raw[raw.scenario_id == sid].itertuples()
            for t in cfg.TRIAGE if int(r.period) in cfg.PERIODS
        }
    if len(source_ids) != 20:
        raise ValueError(f"Expected 20 source casualty scenarios, found {len(source_ids)}")
    return samples, source_ids


def make_draw(source, source_ids, jh_df, jt_df, rng, draw_id):
    global _DAMAGE_TABLE
    base = int(rng.choice(source_ids))
    mult = float(rng.lognormal(-0.5 * cfg.CASUALTY_LOGNORMAL_SIGMA**2,
                               cfg.CASUALTY_LOGNORMAL_SIGMA))
    casualties = {(i, t, p, draw_id): count * mult
                  for (i, t, p), count in source[base].items()}
    road = {draw_id: float(rng.uniform(0.0, cfg.ROAD_DAMAGE_RATIO_MAX))}
    if _DAMAGE_TABLE is None:
        _DAMAGE_TABLE = pd.read_csv(cfg.DAMAGE_INDICATORS_PATH, usecols=["site_id", "damage_score"])
    damage = _DAMAGE_TABLE
    matched = jh_df[["site_id", "matched_site_id"]].merge(
        damage, left_on="matched_site_id", right_on="site_id", how="left", suffixes=("", "_damage"))
    matched["damage_score"] = matched["damage_score"].fillna(1.0)
    factors = {
        (r.site_id, draw_id): (1.0-r.damage_score)
        * float(rng.uniform(0.0, cfg.HOSPITAL_DAMAGE_MAX_FRACTION))
        for r in matched.itertuples()
    }
    cap1, cap2 = build_capacity(jh_df, jt_df, factors, [draw_id])
    for row in jt_df.itertuples():
        cap1[(row.site_id, draw_id)] = float(row.cap_j)
        cap2[(row.site_id, draw_id)] = float(row.cap_j) * cfg.TMC_OUTPATIENT_CAPACITY_MULTIPLIER
    meta = {"base_scenario": base, "casualty_multiplier": mult, "road_damage": road[draw_id]}
    return draw_id, casualties, cap1, cap2, road, meta


def solve(draws, jh, jt, doctors, nurses, distance, budget=None, fixed_sites=None, required_sites=None,
          time_limit=None, gap=None, solver_name="cbc", include_detail=False):
    build_started = time.monotonic()
    ids = [d[0] for d in draws]
    probabilities = {sid: 1.0/len(ids) for sid in ids}
    casualties, cap1, cap2, road = {}, {}, {}, {}
    for sid, c, a, b, r, *_ in draws:
        casualties.update(c); cap1.update(a); cap2.update(b); road.update(r)
    model_jt = list(jt) if fixed_sites is None else sorted(fixed_sites)
    model, variables, Z1, _, _ = build_model(
        pulp, list(dict.fromkeys(i for i, _ in distance)), jh, model_jt,
        doctors, nurses, distance, casualties, cap1, cap2, road,
        scenario_ids=ids, scenario_prob=probabilities,
        open_sites=fixed_sites, required_sites=required_sites, budget_limit=budget)
    model += variables["Zobj"]
    build_seconds = time.monotonic() - build_started
    limit = cfg.TIME_LIMIT_SEC if time_limit is None else time_limit
    rel_gap = cfg.MIP_GAP if gap is None else gap
    solve_started = time.monotonic()
    if solver_name == "highs":
        status = model.solve(pulp.HiGHS(msg=False, timeLimit=limit, gapRel=rel_gap))
    else:
        status = model.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=limit, gapRel=rel_gap))
    solve_seconds = time.monotonic() - solve_started
    status_text = pulp.LpStatus[status]
    sol_status = getattr(model, "sol_status", None)
    has_incumbent = all(v.varValue is not None for v in model.variables())
    feasible_incumbent = has_incumbent and model.valid(1e-5)
    accepted_statuses = {getattr(pulp, "LpSolutionOptimal", 1),
                         getattr(pulp, "LpSolutionIntegerFeasible", 2)}
    if not feasible_incumbent or (status_text != "Optimal" and sol_status not in accepted_statuses):
        raise RuntimeError(
            f"Solve produced no accepted feasible solution (budget={budget}, "
            f"fixed={fixed_sites is not None}, status={status_text}, "
            f"solution_status={sol_status}, build={build_seconds:.1f}s, "
            f"solver={solve_seconds:.1f}s). Increase --time-limit, install highspy "
            "and use --solver highs, or reduce --train-scenarios."
        )
    objective = float(pulp.value(model.objective))
    if objective < -1e-6:
        raise AssertionError(f"Objective must be nonnegative, got {objective}")
    component_values = {k: float(pulp.value(variables[k]) or 0.0)
                        for k in ("Zunmet", "Ztravel", "Zstaff")}
    selected = {j for j, v in variables["y"].items() if (pulp.value(v) or 0.0) > 0.5}
    unmet = float(pulp.value(Z1))
    if abs(objective-sum(component_values.values())) > max(1e-4, objective*1e-8):
        raise AssertionError("Objective does not equal the sum of its nonnegative components")
    total = sum(probabilities[s] * sum(casualties.get((i,t,p,s), 0.0)
                for i in list(dict.fromkeys(i for i, _ in distance))
                for t in cfg.TRIAGE for p in cfg.PERIODS) for s in ids)
    scenario_fraction = 0.0
    demand_ids = list(dict.fromkeys(i for i, _ in distance))
    for sid in ids:
        generated_s = sum(casualties.get((i,t,p,sid), 0.0) for i in demand_ids
                          for t in cfg.TRIAGE for p in cfg.PERIODS)
        unmet_s = float(pulp.value(variables["UniqueUnmet"][sid]) or 0.0)
        scenario_fraction += probabilities[sid] * (1.0-(unmet_s/generated_s) if generated_s else 1.0)
    result = {"selected": selected, "unmet": unmet, "total": total,
            "fraction": scenario_fraction,
            "objective": objective, "components": component_values,
            "unmet_weight": variables["unmet_weight"],
            "solver_status": status_text, "solution_status": sol_status,
            "build_seconds": build_seconds, "solve_seconds": solve_seconds}
    if include_detail:
        result["allocation_rows"] = extract_allocation(pulp, variables, distance)
        result["unmet_rows"] = extract_unmet(pulp, variables)
        result["staffing_rows"] = extract_staffing(pulp, variables)
    return result


def fraction_served(result):
    return result["fraction"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Budget SAA with paired out-of-sample validation")
    parser.add_argument("--profile", choices=("dev", "final"), default="dev")
    parser.add_argument("--reps", type=int)
    parser.add_argument("--train-scenarios", type=int)
    parser.add_argument("--draws", type=int)
    parser.add_argument("--time-limit", type=float)
    parser.add_argument("--gap", type=float)
    parser.add_argument("--solver", choices=("auto", "cbc", "highs"), default="auto",
                        help="auto prefers PuLP HiGHS when highspy is installed, otherwise CBC")
    parser.add_argument("--candidate-pool", choices=("all", "topsis"), default="topsis",
                        help="all prepared TMCs or the TOPSIS top-120 shortlist")
    parser.add_argument("--detail-budget", type=int, default=25,
                        help="also export recourse detail for this budget (default: 25)")
    parser.add_argument("--detail-replication", type=int, default=1,
                        help="training replication whose policy gets detailed recourse")
    parser.add_argument("--detail-draw-index", type=int, default=1,
                        help="1-based shared out-of-sample draw for detailed recourse")
    parser.add_argument("--resume", action="store_true",
                        help="reuse saved training policies and evaluation rows for this seed/configuration")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    final = args.profile == "final"
    reps = args.reps if args.reps is not None else (cfg.SAA_REPLICATIONS if final else cfg.DEV_REPLICATIONS)
    train_n = args.train_scenarios if args.train_scenarios is not None else (cfg.SAA_SCENARIOS_PER_REPLICATION if final else cfg.DEV_SCENARIOS_PER_REPLICATION)
    draws_n = args.draws if args.draws is not None else (cfg.SAA_OUT_OF_SAMPLE_SIZE if final else cfg.DEV_OUT_OF_SAMPLE_SIZE)
    time_limit = args.time_limit if args.time_limit is not None else (cfg.TIME_LIMIT_SEC if final else cfg.DEV_TIME_LIMIT_SEC)
    gap = args.gap if args.gap is not None else (cfg.MIP_GAP if final else cfg.DEV_MIP_GAP)
    if min(reps, train_n, draws_n) < 1 or time_limit <= 0 or not 0 <= gap < 1:
        raise ValueError("Sample sizes/time limit must be positive; gap must be in [0,1)")
    if args.detail_budget not in cfg.BUDGET_VALUES:
        raise ValueError(f"--detail-budget must be one of {cfg.BUDGET_VALUES}")
    if not 1 <= args.detail_replication <= reps or not 1 <= args.detail_draw_index <= draws_n:
        raise ValueError("Detailed replication/draw index is outside the configured run")
    run_started = time.monotonic()
    if args.solver == "highs":
        if not hasattr(pulp, "HiGHS") or not pulp.HiGHS(msg=False).available():
            raise RuntimeError("HiGHS backend unavailable; install highspy in the project environment")
        solver_name = "highs"
    elif args.solver == "auto" and hasattr(pulp, "HiGHS") and pulp.HiGHS(msg=False).available():
        solver_name = "highs"
    else:
        solver_name = "cbc"
    print(f"SAA profile={args.profile}; solver={solver_name}; M={reps}, N={train_n}, OOS={draws_n}; "
          f"budgets={cfg.BUDGET_VALUES}; time limit={time_limit}s; gap={gap}", flush=True)
    rng = np.random.default_rng(cfg.SAA_SEED)
    source, source_ids = load_sources()
    jh_df, all_jt_df, demand_df = load_fixed_network()
    jt_df = select_tmc_candidates(all_jt_df, args.candidate_pool)
    demand_ids = demand_df.sub_district_id.tolist()
    distance = build_distance_lookup(demand_df, jh_df, all_jt_df)
    jh, all_jt, doctors, nurses = build_model_data(demand_ids, jh_df, all_jt_df, distance)
    screened_jt = jt_df.site_id.tolist()

    # Pre-generate the common validation sample before fitting any budget policy.
    out = cfg.OUTPUT_DIR / ("saa" if args.candidate_pool == "topsis" else "saa_unscreened")
    out.mkdir(parents=True, exist_ok=True)
    print(f"Generating shared OOS sample ({draws_n} draws) and {reps} independent "
          f"training samples ({train_n} scenarios each)...", flush=True)
    validation = [make_draw(source, source_ids, jh_df, all_jt_df, rng, 100000+k)
                  for k in range(draws_n)]
    training = {}
    for rep in range(reps):
        training[rep] = [make_draw(source, source_ids, jh_df, all_jt_df, rng,
                                   rep*train_n+k+1)
                         for k in range(train_n)]
    print("Scenario samples generated; starting budget training.", flush=True)

    det_path = cfg.DETERMINISTIC_OUTPUT_DIR / "tmc_selected.csv"
    if not det_path.exists():
        raise FileNotFoundError(f"Deterministic opened-site policy not found: {det_path}")
    det_df = pd.read_csv(det_path)
    det_col = "site_id" if "site_id" in det_df.columns else "facility_id"
    if "y_j" in det_df.columns:
        det_df = det_df[det_df.y_j.astype(float) > 0.5]
    deterministic_sites = set(det_df[det_col].astype(str))
    candidate_ids = set(all_jt_df.site_id.astype(str))
    missing = deterministic_sites - candidate_ids
    if missing:
        raise ValueError(f"Deterministic policy contains unknown TMC IDs: {sorted(missing)[:10]}")

    unmet_weight = cfg.UNMET_PENALTY_FACTOR * (
        max(distance.values()) * (1.0+cfg.ROAD_DAMAGE_RATIO_MAX) * cfg.TRAVEL_COST_WEIGHT_PER_CASUALTY_KM
        + cfg.STAFFING_COST_WEIGHT_PER_STAFF_PERIOD *
        (1.0/cfg.DOCTOR_PATIENTS_PER_PERIOD + 1.0/cfg.NURSE_PATIENTS_PER_PERIOD)
    )
    max_transport = max(distance.values()) * (1.0+cfg.ROAD_DAMAGE_RATIO_MAX) * cfg.TRAVEL_COST_WEIGHT_PER_CASUALTY_KM
    if unmet_weight + 1e-9 < cfg.UNMET_PENALTY_FACTOR*max_transport:
        raise AssertionError("Unmet penalty does not meet the required 10x maximum transport cost")

    in_rows, eval_rows, budget_policies = [], [], {}
    objective_rows = []
    checkpoint_in = out/"checkpoint_in_sample.csv"
    checkpoint_obj = out/"checkpoint_objective_components.csv"
    checkpoint_policies = out/"checkpoint_policies.csv"
    if args.resume and checkpoint_in.exists() and checkpoint_policies.exists():
        in_rows = pd.read_csv(checkpoint_in).to_dict("records")
        if checkpoint_obj.exists():
            objective_rows = pd.read_csv(checkpoint_obj).to_dict("records")
        saved = pd.read_csv(checkpoint_policies)
        for row in saved.itertuples():
            budget_policies.setdefault(int(row.budget), {})[int(row.replication)-1] = set(
                str(row.selected_sites).split(";") if pd.notna(row.selected_sites) and row.selected_sites else [])
        print(f"Resuming from {len(in_rows)} completed training policies.", flush=True)
    required_by_rep = {rep: set() for rep in training}
    for budget in cfg.BUDGET_VALUES:
        budget_policies.setdefault(budget, {})
        budget_started = time.monotonic()
        for rep, sample in training.items():
            if rep in budget_policies[budget]:
                required_by_rep[rep] = budget_policies[budget][rep]
                continue
            result = solve(sample, jh, screened_jt, doctors, nurses, distance,
                           budget=budget, required_sites=required_by_rep[rep],
                           time_limit=time_limit, gap=gap, solver_name=solver_name)
            budget_policies[budget][rep] = result["selected"]
            required_by_rep[rep] = result["selected"]
            meta = [d[5] for d in sample]
            signature = ";".join(f"{m['base_scenario']}:{m['casualty_multiplier']:.8f}" for m in meta)
            in_rows.append({"budget": budget, "replication": rep+1,
                            "selected_site_count": len(result["selected"]),
                            "selected_sites": ";".join(sorted(result["selected"])),
                            "training_signature": signature,
                            "in_sample_expected_unmet": result["unmet"],
                            "in_sample_expected_served_fraction": fraction_served(result),
                            "objective": result["objective"],
                            "unmet_component": result["components"]["Zunmet"],
                            "travel_component": result["components"]["Ztravel"],
                            "staffing_component": result["components"]["Zstaff"]})
            objective_rows.append({"budget": budget, "replication": rep+1,
                                   "objective": result["objective"],
                                   **result["components"], "unmet_weight": result["unmet_weight"],
                                   "solver_status": result["solver_status"],
                                   "build_seconds": result["build_seconds"],
                                   "solve_seconds": result["solve_seconds"]})
            print(f"B={budget} rep={rep+1}/{reps}: selected {len(result['selected'])} sites; "
                  f"status={result['solver_status']}; build={result['build_seconds']:.1f}s; "
                  f"solver={result['solve_seconds']:.1f}s; budget elapsed {time.monotonic()-budget_started:.1f}s", flush=True)
            pd.DataFrame(in_rows).to_csv(checkpoint_in, index=False)
            pd.DataFrame(objective_rows).to_csv(checkpoint_obj, index=False)
            pd.DataFrame([{"budget": b, "replication": r+1, "selected_sites": ";".join(sorted(sites))}
                          for b, rm in budget_policies.items() for r, sites in rm.items()]
                         ).to_csv(checkpoint_policies, index=False)
        # Always refresh checkpoints at each completed budget, including B=0.
        pd.DataFrame(in_rows).to_csv(checkpoint_in, index=False)
        pd.DataFrame(objective_rows).to_csv(checkpoint_obj, index=False)
        pd.DataFrame([{"budget": b, "replication": r+1, "selected_sites": ";".join(sorted(sites))}
                      for b, rm in budget_policies.items() for r, sites in rm.items()]
                     ).to_csv(checkpoint_policies, index=False)
        print(f"B={budget}: solved {reps} training samples; checkpoint saved", flush=True)

    # Paired out-of-sample evaluation: every deterministic and SAA policy uses
    # precisely these same 1,000 generated draws.
    policies = [("deterministic", None, deterministic_sites)]
    policies.extend((f"B{b}_rep{rep+1}", b, sites)
                    for b, rep_map in budget_policies.items()
                    for rep, sites in rep_map.items())
    evaluation_cache = {}
    evaluation_started = time.monotonic()
    total_unique_estimate = len({frozenset(sites) for _, _, sites in policies})
    completed_eval_labels = set()
    checkpoint_eval = out/"checkpoint_out_of_sample.csv"
    if args.resume and checkpoint_eval.exists():
        old_eval = pd.read_csv(checkpoint_eval)
        for label, _, sites in policies:
            rows = old_eval[old_eval.policy == label]
            if len(rows) == len(validation) and rows.draw_id.tolist() == [d[0] for d in validation]:
                evaluation_cache[frozenset(sites)] = rows[
                    ["draw_id", "expected_unmet_casualties", "fraction_of_casualties_served"]
                ].to_dict("records")
                completed_eval_labels.add(label)
        eval_rows = old_eval.to_dict("records")
        print(f"Resuming with {len(evaluation_cache)} cached policy evaluations.", flush=True)
    for label, budget, sites in policies:
        key = frozenset(sites)
        if label in completed_eval_labels:
            continue
        if key not in evaluation_cache:
            records = []
            for idx, draw in enumerate(validation, 1):
                result = solve([draw], jh, all_jt, doctors, nurses, distance,
                               fixed_sites=sites, time_limit=time_limit, gap=gap,
                               solver_name=solver_name)
                records.append({"draw_id": draw[0], "expected_unmet_casualties": result["unmet"],
                                "fraction_of_casualties_served": fraction_served(result)})
                if idx % 5 == 0 or idx == len(validation):
                    elapsed = time.monotonic()-evaluation_started
                    done = len(evaluation_cache)*len(validation)+idx
                    total = total_unique_estimate*len(validation)
                    eta = elapsed/max(done, 1)*(total-done)
                    print(f"OOS policy {label}: {idx}/{len(validation)} draws; "
                          f"elapsed {elapsed:.1f}s, ETA {eta:.1f}s", flush=True)
            evaluation_cache[key] = records
        records = evaluation_cache[key]
        for record in records:
            eval_rows.append({"policy": label, "budget": budget, **record})
        print(f"Evaluated {label} on {len(records)} shared draws (cached policies: {len(evaluation_cache)})")
        pd.DataFrame(eval_rows).to_csv(out/"checkpoint_out_of_sample.csv", index=False)

    detail_label = f"B{args.detail_budget}_rep{args.detail_replication}"
    detail_policy = next(((label, budget, sites) for label, budget, sites in policies
                          if label == detail_label), None)
    if detail_policy is None:
        raise RuntimeError(f"Detailed policy {detail_label} was not generated")
    detail_draw = validation[args.detail_draw_index - 1]
    detail_result = solve([detail_draw], jh, all_jt, doctors, nurses, distance,
                          fixed_sites=detail_policy[2], time_limit=time_limit,
                          gap=gap, solver_name=solver_name, include_detail=True)
    detail_key = {"policy": detail_label, "budget": args.detail_budget,
                  "replication": args.detail_replication, "draw_id": detail_draw[0]}
    pd.DataFrame([{**detail_key, "site_id": site}
                  for site in sorted(detail_policy[2])]).to_csv(out/"detailed_policy_sites.csv", index=False)
    detail_schemas = (
        ("detailed_casualty_allocation.csv", "allocation_rows",
         ["policy", "budget", "replication", "draw_id", "demand_point_id", "facility_id",
          "triage", "period", "scenario_id", "assigned_casualties", "distance_km"]),
        ("detailed_unmet.csv", "unmet_rows",
         ["policy", "budget", "replication", "draw_id", "demand_point_id", "triage",
          "period", "scenario_id", "unmet_casualties"]),
        ("detailed_staffing.csv", "staffing_rows",
         ["policy", "budget", "replication", "draw_id", "facility_id", "staff_type",
          "period", "scenario_id", "extra_staff"]),
    )
    for filename, result_key, columns in detail_schemas:
        detail_rows = [{**detail_key, **row} for row in detail_result[result_key]]
        pd.DataFrame(detail_rows, columns=columns).to_csv(out/filename, index=False)

    eval_df_pre = pd.DataFrame(eval_rows)
    for rep in range(reps):
        rates = [eval_df_pre.loc[eval_df_pre.policy == f"B{b}_rep{rep+1}",
                                 "fraction_of_casualties_served"].mean()
                 for b in cfg.BUDGET_VALUES]
        if any(later + 1e-6 < earlier for earlier, later in zip(rates, rates[1:])):
            raise AssertionError(f"Out-of-sample served fraction decreased with budget in replication {rep+1}: {rates}")

    in_df, eval_df = pd.DataFrame(in_rows), pd.DataFrame(eval_rows)
    in_df.to_csv(out/"budget_sweep_in_sample_by_replication.csv", index=False)
    eval_df.to_csv(out/"budget_sweep_out_of_sample_by_draw.csv", index=False)
    component_rep_df = pd.DataFrame(objective_rows)
    component_df = component_rep_df.groupby("budget", as_index=False).mean(numeric_only=True)
    component_df = component_df.drop(columns=["replication"], errors="ignore")
    component_df.to_csv(out/"objective_components_by_budget.csv", index=False)

    summary_rows = []
    for budget in cfg.BUDGET_VALUES:
        ins = in_df[in_df.budget == budget]
        policy = eval_df[eval_df.budget == budget]
        rep_eval = policy.groupby("policy").agg(
            expected_served_fraction=("fraction_of_casualties_served", "mean"),
            expected_unmet_casualties=("expected_unmet_casualties", "mean")).reset_index()
        summary_rows.append({
            "budget": budget,
            "in_sample_expected_served_fraction": ins.in_sample_expected_served_fraction.mean(),
            "in_sample_expected_unmet_casualties": ins.in_sample_expected_unmet.mean(),
            "out_of_sample_expected_served_fraction": rep_eval.expected_served_fraction.mean(),
            "out_of_sample_served_fraction_sd_across_replications": rep_eval.expected_served_fraction.std(ddof=1),
            "out_of_sample_expected_unmet_casualties": rep_eval.expected_unmet_casualties.mean(),
            "out_of_sample_unmet_sd_across_replications": rep_eval.expected_unmet_casualties.std(ddof=1),
            "replications": reps,
            "validation_draws_per_policy": draws_n,
        })
    summary_df = pd.DataFrame(summary_rows)
    baseline_rows = eval_df[eval_df.policy == "deterministic"]
    baseline = {"policy": "deterministic_existing_opened_set",
                "site_count": len(deterministic_sites),
                "expected_served_fraction": baseline_rows.fraction_of_casualties_served.mean(),
                "expected_unmet_casualties": baseline_rows.expected_unmet_casualties.mean(),
                "validation_draws": len(baseline_rows)}
    summary_df["deterministic_expected_served_fraction"] = baseline["expected_served_fraction"]
    if (summary_df.in_sample_expected_served_fraction.diff().dropna() < -1e-6).any():
        raise AssertionError("In-sample expected served fraction decreased as the site budget increased")
    if (summary_df.out_of_sample_expected_served_fraction.diff().dropna() < -1e-6).any():
        raise AssertionError("Out-of-sample expected served fraction decreased as the site budget increased")
    if baseline["expected_served_fraction"] <= summary_df.iloc[0].out_of_sample_expected_served_fraction + 1e-6:
        raise AssertionError("Existing deterministic policy did not outperform the B=0 policy")
    summary_df.to_csv(out/"budget_sweep_summary.csv", index=False)
    pd.DataFrame([baseline]).to_csv(out/"deterministic_baseline.csv", index=False)

    training_signatures = in_df[in_df.budget > 0].groupby("replication").training_signature.first()
    if training_signatures.nunique() < 2:
        raise AssertionError("Independent training replications produced identical sample signatures")
    policy_diversity = (in_df[in_df.budget.isin([25, 50])]
                        .groupby("budget").selected_sites.nunique().to_dict())
    summary = (
        "model_version: two_stage_budget_saa_v3\n"
        f"Candidate pool mode: {args.candidate_pool}.\n"
        f"Candidate screen: top {cfg.TMC_CANDIDATE_LIMIT} by descending TOPSIS CC_i; stable site_id tie-break when screened.\n"
        f"Candidate pool before/after screen: {len(all_jt)}/{len(screened_jt)}\n"
        f"Budgets: {cfg.BUDGET_VALUES}; SAA M={reps}, N={train_n}; OOS={draws_n}; time limit={time_limit}s; gap={gap}.\n"
        "Budget policies are nested within each replication so a larger budget retains the smaller-budget open set.\n"
        f"Distinct selected sets across replications at B=25/50: {policy_diversity}.\n"
        f"Unmet penalty={unmet_weight:.3f}; maximum transport per casualty={max_transport:.3f}; penalty/transport={unmet_weight/max_transport:.2f}x.\n"
        f"Deterministic baseline is the existing opened set from {det_path}; sites={len(deterministic_sites)}.\n"
        "Casualty: mean-one LogNormal multiplier around a uniform draw from the 20 source scenarios (assumption).\n"
        f"Road damage: Uniform(0,{cfg.ROAD_DAMAGE_RATIO_MAX}); hospital capacity loss: local damage x Uniform(0,{cfg.HOSPITAL_DAMAGE_MAX_FRACTION}) (assumptions).\n\n"
        "Objective components are nonnegative: unmet + transport + extra staffing; no opening-cost term.\n"
        + summary_df.to_string(index=False) + "\n\nObjective components by budget:\n"
        + component_df.to_string(index=False) + "\n\nDeterministic baseline:\n"
        + str(baseline) + "\n")
    (out/"budget_sweep_summary.txt").write_text(summary, encoding="utf-8")
    (out/"run_metadata.json").write_text(json.dumps({
        "candidate_pool": "topsis_top_120" if args.candidate_pool == "topsis" else "all_prepared_candidates",
        "candidate_count": len(screened_jt), "available_candidate_count": len(all_jt),
        "profile": args.profile, "solver": solver_name, "seed": cfg.SAA_SEED,
        "replications": reps, "training_scenarios_per_replication": train_n,
        "validation_draws_per_policy": draws_n, "time_limit_seconds": time_limit,
        "relative_gap_target": gap, "budgets": cfg.BUDGET_VALUES,
        "wall_time_seconds": round(time.monotonic() - run_started, 3),
        "peak_memory_mb": peak_memory_mb(),
        "detail_budget": args.detail_budget,
        "detail_replication": args.detail_replication,
        "detail_policy": detail_label, "detail_draw_id": int(detail_draw[0]),
        "detail_draw_index": args.detail_draw_index,
    }, indent=2), encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
