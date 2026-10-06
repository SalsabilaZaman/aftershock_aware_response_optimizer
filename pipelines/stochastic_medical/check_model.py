"""Acceptance checks for prepared inputs and generated stochastic outputs.

Run: python pipelines/stochastic_medical/check_model.py
"""
import sys
from pathlib import Path
import pandas as pd

try:
    from . import settings as cfg
    from .prep_support import screen_tmc_candidates
except ImportError:
    import settings as cfg
    from prep_support import screen_tmc_candidates

root = cfg.PROJECT_ROOT
dist = pd.read_csv(cfg.DETERMINISTIC_INPUT_DIR / "distance_matrix.csv")
src = pd.read_csv(cfg.HOSPITAL_DATA_PATH)
tests = {
    "SD004-H001": ("SD004", "JH_H001", 10.70),
    "SD004-H002": ("SD004", "JH_H002", 9.31),
    "SD009-H001": ("SD009", "JH_H001", 10.94),
    "SD009-H002": ("SD009", "JH_H002", 8.68),
}
for label, (i, j, expected) in tests.items():
    found = dist[(dist.demand_point == i) & (dist.facility == j)]
    assert len(found) == 1, f"{label}: missing or duplicate distance row"
    assert abs(float(found.iloc[0].distance_km)-expected) < .011, f"{label}: distance mismatch"
assert int(src.effective_capacity_postquake.sum()) == 2568, "effective post-quake hospital capacity must equal 2,568"
assert int(src.bed_capacity_total.sum()) == 2693, "raw listed bed total changed; review capacity interpretation"
assert cfg.DISTANCE_LIMIT_T1_KM == 12.0
candidate_df = pd.read_csv(cfg.DETERMINISTIC_INPUT_DIR / "candidates_jt.csv")
screened = screen_tmc_candidates(candidate_df)
ranking = pd.read_csv(cfg.TOPSIS_RANKING_PATH)
expected_top = (candidate_df.merge(ranking[["site_id", "CC_i"]], on="site_id", how="inner")
                .sort_values(["CC_i", "site_id"], ascending=[False, True])
                .head(cfg.TMC_CANDIDATE_LIMIT).site_id.tolist())
assert screened.site_id.tolist() == expected_top
assert len(screened) <= 120

alloc_path = cfg.OUTPUT_DIR / "casualty_allocation.csv"
summary_path = cfg.OUTPUT_DIR / "model_summary.txt"
current_summary = summary_path.exists() and "model_version: two_stage_budget_saa_v2" in summary_path.read_text(encoding="utf-8")
if alloc_path.exists() and current_summary:
    allocation = pd.read_csv(alloc_path)
    hospitals = set(pd.read_csv(cfg.DETERMINISTIC_INPUT_DIR / "hospitals_jh.csv").site_id)
    t1 = allocation[allocation.triage == "T1"]
    assert set(t1.facility_id).issubset(hospitals), "T1 flow must be hospital-only"
    assert (t1.distance_km <= cfg.DISTANCE_LIMIT_T1_KM + 1e-6).all(), "T1 flow exceeds 12 km"
    selected_path = cfg.OUTPUT_DIR / "tmc_selected.csv"
    if selected_path.exists():
        selected = set(pd.read_csv(selected_path).site_id)
        tmc = set(pd.read_csv(cfg.DETERMINISTIC_INPUT_DIR / "candidates_jt.csv").site_id)
        used_tmc = set(allocation.facility_id) & tmc
        assert used_tmc.issubset(selected), "flow uses a closed TMC"
if current_summary:
    summary = summary_path.read_text(encoding="utf-8").lower()
    assert "fraction of casualties served" in summary
    assert "reliability" not in summary
    assert "objective components" in summary
    det_path = cfg.DETERMINISTIC_OUTPUT_DIR / "tmc_selected.csv"
    if det_path.exists():
        det = pd.read_csv(det_path)
        site_col = "site_id" if "site_id" in det.columns else "facility_id"
        det_sites = set(det[site_col].astype(str))
        candidate_sites = set(candidate_df.site_id.astype(str))
        assert det_sites.issubset(candidate_sites), "deterministic baseline contains unknown TMC sites"

saa = cfg.OUTPUT_DIR / "saa"
sweep_path = saa / "budget_sweep_summary.csv"
component_path = saa / "objective_components_by_budget.csv"
baseline_path = saa / "deterministic_baseline.csv"
saa_complete = sweep_path.exists() and component_path.exists() and baseline_path.exists()
if saa_complete:
    sweep = pd.read_csv(sweep_path).sort_values("budget")
    assert sweep.budget.tolist() == cfg.BUDGET_VALUES
    in_sample = pd.read_csv(saa / "budget_sweep_in_sample_by_replication.csv")
    assert (in_sample.selected_site_count <= in_sample.budget).all()
    assert in_sample[in_sample.budget == in_sample.budget.max()].training_signature.nunique() > 1
    components = pd.read_csv(component_path)
    baseline = pd.read_csv(baseline_path).iloc[0]
    served = sweep.in_sample_expected_served_fraction.tolist()
    assert all(b + 1e-6 >= a for a, b in zip(served, served[1:])), "in-sample served fraction decreased with budget"
    assert baseline.expected_served_fraction > sweep.iloc[0].out_of_sample_expected_served_fraction
    assert (components.objective >= -1e-6).all()
    assert ((components.Zunmet + components.Ztravel + components.Zstaff - components.objective).abs() < 1e-4).all()
if not current_summary:
    print("input checks passed; output checks await a fresh step2_solve_stochastic_model.py run")
elif not saa_complete:
    print("single-solve checks passed; budget-SAA output checks await a fresh run_saa.py run")
else:
    print("stochastic model and budget-SAA acceptance checks passed")
