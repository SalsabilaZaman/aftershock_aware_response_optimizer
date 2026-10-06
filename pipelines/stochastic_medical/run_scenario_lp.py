"""Solve 20 independent paper-style scenario LPs (separate from the SAA pipeline)."""
import argparse
import json
from pathlib import Path
import time

import pandas as pd
import pulp

try:
    from .scenario_lp_support import load_scenario_data, solve_lexicographic, extract_solution
    from . import settings as base
    from .runtime_metrics import peak_memory_mb
except ImportError:  # direct script execution
    from scenario_lp_support import load_scenario_data, solve_lexicographic, extract_solution
    import settings as base
    from runtime_metrics import peak_memory_mb


OUT = base.OUTPUT_DIR / "paper_lp"
POOL_DIRS = {"all": "all_candidates", "topsis": "topsis_120"}


def weighted_summary(results):
    metrics = ("Z1", "Z2", "Z3", "served_fraction", "generated_casualties",
               "served_casualties", "unmet_casualties", "tmcs_with_assigned_casualties",
               "tmcs_with_assigned_staff", "tmcs_with_casualties_or_staff", "staff_added")
    return {metric: float((results.scenario_prob * results[metric]).sum()) for metric in metrics}


def run(output_dir=None, solver=None, data=None, distance_limit_km=12.0,
        candidate_pool="all", **overrides):
    if solver is None:
        if not hasattr(pulp, "HiGHS") or not pulp.HiGHS(msg=False).available():
            raise RuntimeError("HiGHS is required for the paper-style LP; install highspy")
        solver = pulp.HiGHS(msg=False)
    data = data or load_scenario_data(candidate_pool=candidate_pool, **overrides)
    if output_dir is None:
        output_dir = OUT / POOL_DIRS[data.candidate_pool]
    started = time.monotonic()
    rows, allocations_all, unmet_all, staff_all = [], [], [], []
    for scenario in sorted(data.probabilities):
        scenario_started = time.monotonic()
        _, variables, (z1, z2, z3) = solve_lexicographic(
            data, scenario, distance_limit_km=distance_limit_km, solver=solver)
        allocations, unmet, staffing, used, staffed = extract_solution(
            data, scenario, variables, distance_limit_km=distance_limit_km)
        generated = sum(data.casualties.get((i, t, p, scenario), 0.0)
                        for i in data.demand_ids for t in ("T1", "T2", "T3") for p in base.PERIODS)
        served = sum(r["assigned_casualties"] for r in allocations)
        rows.append({"scenario_id": scenario, "scenario_prob": data.probabilities[scenario],
                     "Z1": z1, "Z2": z2, "Z3": z3,
                     "served_fraction": served / generated if generated else 1.0,
                     "generated_casualties": generated, "served_casualties": served,
                     "unmet_casualties": sum(r["unmet_casualties"] for r in unmet),
                     "tmcs_with_assigned_casualties": len(used),
                     "tmcs_with_assigned_staff": len(staffed),
                     "tmcs_with_casualties_or_staff": len(used | staffed),
                     "staff_added": sum(r["extra_staff"] for r in staffing),
                     "solve_seconds": time.monotonic() - scenario_started,
                     "solver_status": "Optimal"})
        allocations_all.extend(allocations)
        unmet_all.extend(unmet)
        staff_all.extend(staffing)

    results = pd.DataFrame(rows).sort_values("scenario_id")
    weighted = weighted_summary(results)
    worst = results.sort_values(["Z1", "scenario_id"], ascending=[False, True]).iloc[0]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(output_dir / "scenario_results.csv", index=False)
    pd.DataFrame(allocations_all).to_csv(output_dir / "casualty_allocation.csv", index=False)
    pd.DataFrame(unmet_all).to_csv(output_dir / "unmet_by_triage.csv", index=False)
    pd.DataFrame(staff_all).to_csv(output_dir / "staffing_plan.csv", index=False)
    elapsed = time.monotonic() - started
    summary = ["Paper-style scenario-wise medical response LP", "Solver: HiGHS",
               f"Candidate pool: {data.candidate_pool}",
               f"TMC candidates used / available: {data.candidate_count}/{data.available_candidate_count}",
               f"Scenarios solved: {len(results)}", f"Wall time seconds: {elapsed:.3f}",
               "Optimality gap: not applicable (continuous LP)", "Probability-weighted totals/means:"]
    summary.extend(f"  {k}: {v:.6f}" for k, v in weighted.items())
    summary.append(f"Worst case by Z1: scenario {int(worst.scenario_id)} (Z1={worst.Z1:.6f}, served={worst.served_fraction:.2%})")
    (output_dir / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    (output_dir / "run_metadata.json").write_text(json.dumps({
        "model": "paper_lp", "candidate_pool": data.candidate_pool,
        "candidate_count": data.candidate_count,
        "available_candidate_count": data.available_candidate_count,
        "scenario_count": len(results), "solver": "HiGHS",
        "wall_time_seconds": round(elapsed, 3), "peak_memory_mb": peak_memory_mb(),
        "optimality_gap": None, "optimality_gap_note": "Not applicable to continuous LP",
        "distance_limit_t1_km": distance_limit_km,
    }, indent=2), encoding="utf-8")
    return results, weighted, int(worst.scenario_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--candidate-pool", choices=("all", "topsis"), default="all",
                        help="all prepared TMCs or the TOPSIS top-120 shortlist")
    args = parser.parse_args()
    output_dir = args.output_dir or (OUT / POOL_DIRS[args.candidate_pool])
    results, _, worst = run(output_dir=output_dir, candidate_pool=args.candidate_pool)
    print(f"Solved {len(results)} scenarios; worst case by Z1: {worst}")
    print(f"Results: {output_dir}")


if __name__ == "__main__":
    main()
