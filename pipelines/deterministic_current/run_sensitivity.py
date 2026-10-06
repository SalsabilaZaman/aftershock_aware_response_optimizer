"""
Sensitivity sweep over OPENING_PENALTY_CASUALTY_KM, the one judgement-chosen
parameter left in the objective after the 2026-07-30 units fix (see
docs/CURRENT_PIPELINE.md and settings.py). The objective is denominated in
casualty-km; this constant sets the exchange rate between opening an extra
TMC and reducing aggregate travel burden.

Solves both modes at each penalty value in a subprocess (RUN_TAG isolates
each run's model_inputs/model_outputs subfolder so the committed reference
run at 1000.0 is never touched) and summarizes the effect on the paper's
three claims:
  1. risk-blind opens sites that risk-aware (hazard-filtered) rejects
  2. risk-aware costs little extra over risk-blind
  3. the same rural sub-districts are underserved in both modes

Writes docs/SENSITIVITY.md (narrative) and sensitivity_results.csv (data).
"""

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
MODES = ["risk_blind", "risk_aware"]
PENALTIES = [100, 300, 1000, 3000, 10000]
RURAL_THRESHOLD_KM = 45.0
LONG_TRIP_THRESHOLD_KM = 30.0


def run_tag_for(penalty):
    return f"__pen{int(penalty)}"


def solve_at_penalty(penalty):
    tag = run_tag_for(penalty)
    for mode in MODES:
        env = dict(os.environ, MODEL_MODE=mode, RUN_TAG=tag,
                   OPENING_PENALTY_CASUALTY_KM=str(penalty))
        for step in ("step1_prepare_data.py", "step2_solve_model.py"):
            print(f"\n--- penalty={penalty} mode={mode} :: {step} ---")
            result = subprocess.run([sys.executable, str(HERE / step)], env=env, cwd=str(HERE))
            if result.returncode != 0:
                raise SystemExit(f"{step} failed at penalty={penalty} mode={mode} "
                                 f"(exit {result.returncode})")


def read_outputs(penalty, mode):
    tag = run_tag_for(penalty)
    out_dir = PROJECT_ROOT / "model_outputs" / (mode + tag)
    alloc = pd.read_csv(out_dir / "casualty_allocation.csv")
    tmc = pd.read_csv(out_dir / "tmc_selected.csv")
    demand = pd.read_csv(PROJECT_ROOT / "model_inputs" / (mode + tag) / "demand_points.csv")
    return alloc, tmc, demand


def summarize_run(penalty, mode, alloc, tmc, demand, pga_lookup, pga_max):
    total_casualties = alloc["assigned_casualties"].sum()
    wtd_dist = (alloc["distance_km"] * alloc["assigned_casualties"]).sum() / total_casualties
    pct_over_30 = (
        alloc.loc[alloc["distance_km"] > LONG_TRIP_THRESHOLD_KM, "assigned_casualties"].sum()
        / total_casualties * 100
    )
    travel_burden = alloc["travel_burden_casualty_km"].sum()
    opening_total = len(tmc) * penalty
    objective = travel_burden + opening_total

    tmc_with_pga = tmc.merge(pga_lookup, on="site_id", how="left")
    unsafe_picks = int((tmc_with_pga["pga"] > pga_max).sum()) if mode == "risk_blind" else 0

    sub_dist_avg = (
        alloc.merge(demand[["sub_district_id", "name"]], left_on="demand_point_id", right_on="sub_district_id")
        .groupby("name")
        .apply(lambda g: (g["distance_km"] * g["assigned_casualties"]).sum() / g["assigned_casualties"].sum())
    )
    rural_over_threshold = int((sub_dist_avg > RURAL_THRESHOLD_KM).sum())
    rural_names = sorted(sub_dist_avg[sub_dist_avg > RURAL_THRESHOLD_KM].index.tolist())

    return {
        "penalty": penalty,
        "mode": mode,
        "tmcs_opened": len(tmc),
        "unsafe_blind_picks": unsafe_picks,
        "casualty_wtd_avg_dist_km": round(wtd_dist, 2),
        "pct_casualties_over_30km": round(pct_over_30, 1),
        "sub_districts_over_45km": rural_over_threshold,
        "rural_sub_districts": ";".join(rural_names),
        "objective_casualty_km": round(objective, 2),
    }


def main():
    try:
        from settings import PGA_MAX
    except ImportError:
        sys.path.insert(0, str(HERE))
        from settings import PGA_MAX

    psaha_path = PROJECT_ROOT / "outputs_psaha" / "psaha_output_per_site.csv"
    pga_lookup = pd.read_csv(psaha_path)[["site_id", "PGA_representative_g"]].rename(
        columns={"PGA_representative_g": "pga"}
    )

    rows = []
    for penalty in PENALTIES:
        solve_at_penalty(penalty)
        for mode in MODES:
            alloc, tmc, demand = read_outputs(penalty, mode)
            rows.append(summarize_run(penalty, mode, alloc, tmc, demand, pga_lookup, PGA_MAX))

    results = pd.DataFrame(rows)
    results_path = HERE / "sensitivity_results.csv"
    results.to_csv(results_path, index=False)
    print(f"\nWrote {results_path}")

    write_markdown_report(results)


def write_markdown_report(results):
    lines = [
        "# Opening-penalty sensitivity sweep",
        "",
        "Sweep of `OPENING_PENALTY_CASUALTY_KM` (settings.py) — the one",
        "judgement-chosen parameter in the objective after the 2026-07-30",
        "units fix (see docs/CURRENT_PIPELINE.md). The objective is",
        "casualty-km; this parameter is the exchange rate between opening an",
        "extra TMC and reducing aggregate travel burden. Lower = more",
        "permissive (more TMCs open); higher = more restrictive (fewer TMCs,",
        "each must justify itself by a larger travel-burden saving).",
        "",
        "Generated by `run_sensitivity.py`; raw data in `sensitivity_results.csv`.",
        "",
        "## Results",
        "",
        "| penalty | mode | TMCs opened | unsafe blind picks | casualty-wtd avg dist (km) | % casualties >30km | sub-districts >45km |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in results.iterrows():
        lines.append(
            f"| {int(r['penalty'])} | {r['mode']} | {int(r['tmcs_opened'])} | "
            f"{int(r['unsafe_blind_picks'])} | {r['casualty_wtd_avg_dist_km']} | "
            f"{r['pct_casualties_over_30km']} | {int(r['sub_districts_over_45km'])} |"
        )

    lines += ["", "## Claim-by-claim check", ""]

    aware = results[results["mode"] == "risk_aware"].set_index("penalty")
    blind = results[results["mode"] == "risk_blind"].set_index("penalty")

    claim1_holds = all(blind.loc[p, "unsafe_blind_picks"] > 0 for p in PENALTIES if p in blind.index)
    lines.append(
        f"1. **Risk-blind opens hazard-unsafe sites hazard-aware rejects**: "
        f"{'holds' if claim1_holds else 'DOES NOT hold'} across all penalties "
        f"({', '.join(str(int(blind.loc[p, 'unsafe_blind_picks'])) for p in PENALTIES if p in blind.index)} "
        f"unsafe picks at penalty {', '.join(str(p) for p in PENALTIES)} respectively)."
    )

    obj_deltas = [
        (p, aware.loc[p, "objective_casualty_km"] - blind.loc[p, "objective_casualty_km"])
        for p in PENALTIES if p in aware.index and p in blind.index
    ]
    max_delta_pct = max(
        abs(d) / blind.loc[p, "objective_casualty_km"] * 100 for p, d in obj_deltas
    )
    lines.append(
        f"2. **Hazard-aware siting costs little extra**: objective delta stays "
        f"under {max_delta_pct:.1f}% of the risk-blind objective across all "
        f"penalties tested."
    )

    rural_sets = {p: set(blind.loc[p, "rural_sub_districts"].split(";")) & set(aware.loc[p, "rural_sub_districts"].split(";"))
                  for p in PENALTIES if p in aware.index and p in blind.index}
    invariant_districts = set.intersection(*rural_sets.values()) if rural_sets else set()
    counts_by_penalty = ", ".join(
        f"{p}:{int(aware.loc[p, 'sub_districts_over_45km'])}" for p in PENALTIES if p in aware.index
    )
    invariant_text = ", ".join(sorted(invariant_districts)) if invariant_districts else "(none — see raw counts per penalty above)"
    lines.append(
        f"3. **Same rural sub-districts underserved in both modes, across "
        f"penalty values**: districts appearing over the 45km threshold in "
        f"*both* modes at *every* penalty tested: {invariant_text}. "
        f"Sub-district count over threshold by penalty (risk_aware): {counts_by_penalty}."
    )

    report_path = PROJECT_ROOT / "docs" / "SENSITIVITY.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
