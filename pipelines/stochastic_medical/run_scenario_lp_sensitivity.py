"""One-at-a-time parameter sensitivity runs for the paper-style scenario LP."""
import pandas as pd
import pulp
import argparse

try:
    from .scenario_lp_support import SENSITIVITY, load_scenario_data
    from .run_scenario_lp import run, OUT
except ImportError:  # direct script execution
    from scenario_lp_support import SENSITIVITY, load_scenario_data
    from run_scenario_lp import run, OUT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-pool", choices=("all", "topsis"), default="all")
    args = parser.parse_args()
    if not hasattr(pulp, "HiGHS") or not pulp.HiGHS(msg=False).available():
        raise RuntimeError("HiGHS is required; install highspy")
    rows = []
    for parameter, levels in SENSITIVITY.items():
        for level in levels:
            overrides = {parameter: level}
            distance_limit = level if parameter == "distance_limit_km" else 12.0
            data = load_scenario_data(candidate_pool=args.candidate_pool,
                                      **({} if parameter == "distance_limit_km" else overrides))
            label = f"{parameter}_{level:g}".replace(".", "p")
            pool_dir = "all_candidates" if args.candidate_pool == "all" else "topsis_120"
            out = OUT / pool_dir / "sensitivity" / label
            results, weighted, worst = run(output_dir=out, data=data,
                                           solver=pulp.HiGHS(msg=False),
                                           distance_limit_km=distance_limit)
            for metric, value in weighted.items():
                rows.append({"parameter": parameter, "value": level, "metric": metric,
                             "probability_weighted_value": value, "worst_scenario_by_Z1": worst,
                             "scenario_count": len(results)})
            print(f"Completed {parameter}={level:g}")
    pool_dir = "all_candidates" if args.candidate_pool == "all" else "topsis_120"
    target = OUT / pool_dir
    target.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(target / "sensitivity_summary.csv", index=False)
    print(f"Sensitivity results: {target / 'sensitivity_summary.csv'}")


if __name__ == "__main__":
    main()
