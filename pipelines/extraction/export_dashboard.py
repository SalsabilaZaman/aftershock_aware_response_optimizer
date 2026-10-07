"""
Assemble dashboard_data/ — the single validated bundle the dashboard repo
consumes. Nothing in the UI reads data_processed/ or model_outputs/ directly;
if a file is missing here the manifest says so and the UI shows that state
instead of rendering fabricated data.

Contents:
  sites.csv              per-site master table (hazard + terrain + access + tier)
  hospitals.csv          curated hospitals with capacity provenance
  aftershocks.csv        cleaned catalog for the scenario window
  demand_points.csv      demand-point centroids (lat/lon/population) — mode-independent
  site_status.csv        per-site outcome in both solver modes (the View-3 delta)
  <mode>/tmc_selected.csv, casualty_allocation.csv, hospital_utilisation.csv
  paper_lp/...           scenario-wise paper LP results (optional)
  saa/...                two-stage SAA extension results (optional)
  scenario_manifest.json scenario params + summary stats + file inventory
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

EXTRACTION_DIR = Path(__file__).resolve().parent
CODE_ROOT = EXTRACTION_DIR.parents[1]  # this repo checkout — code/config always live here
MODEL_LABELS_PATH = CODE_ROOT / "pipelines" / "model_labels.json"
# PIPELINE_ROOT lets a job-scoped demo run (pipelines/run_demo_job.py) point
# data reads/writes at an isolated bundle while config.yaml/code stay fixed
# in this repo checkout (CODE_ROOT).
REPO_ROOT = Path(os.environ.get("PIPELINE_ROOT", CODE_ROOT))
OUT_DIR = REPO_ROOT / "dashboard_data"
MODES = ["risk_blind", "risk_aware"]
SAA_FILES = (
    "budget_sweep_summary.csv",
    "budget_sweep_in_sample_by_replication.csv",
    "budget_sweep_out_of_sample_by_draw.csv",
)
SAA_DETAIL_FILES = (
    "detailed_policy_sites.csv", "detailed_casualty_allocation.csv",
    "detailed_unmet.csv", "detailed_staffing.csv", "objective_components_by_budget.csv",
)
PAPER_LP_FILES = (
    "scenario_results.csv",
    "casualty_allocation.csv",
    "unmet_by_triage.csv",
    "staffing_plan.csv",
)

sys.path.insert(0, str(EXTRACTION_DIR))


def build_sites_table(config):
    paths = config["paths"]
    sites = pd.read_csv(REPO_ROOT / paths["out_sites"])

    def join(fname, cols):
        nonlocal sites
        p = REPO_ROOT / fname
        if p.exists():
            df = pd.read_csv(p)
            keep = ["site_id"] + [c for c in cols if c in df.columns]
            sites = sites.merge(df[keep], on="site_id", how="left")

    join(paths["out_topography"], ["elevation_m", "slope_deg"])
    join(paths["out_accessibility"], ["dist_to_road_m"])
    join(paths["out_vs30"], ["vs30_ms", "soil_class"])
    join(str(Path("outputs_psaha") / "psaha_output_per_site.csv"),
         ["qi", "Lambda_i", "P_unsafe", "PGA_representative_g"])
    join(str(Path("outputs_psaha") / "topsis_ranking.csv"), ["CC_i", "rank"])
    join(paths["out_damage"], ["in_aoi", "dist_to_damaged_m", "damage_count_500m",
                               "damage_score"])

    # resolution tier: Copernicus damage grades only exist inside AOI04
    aoi_path = REPO_ROOT / paths["out_sites_aoi04"]
    aoi_ids = set(pd.read_csv(aoi_path)["site_id"]) if aoi_path.exists() else set()
    sites["resolution_tier"] = sites["site_id"].map(
        lambda s: "AOI04_highres" if s in aoi_ids else "province_baseline")
    return sites


def build_site_status(sites):
    """Per-site outcome in each mode — the risk-blind vs risk-aware delta."""
    frames = {}
    for mode in MODES:
        cand = REPO_ROOT / "model_inputs" / mode / "candidates_jt.csv"
        sel = REPO_ROOT / "model_outputs" / mode / "tmc_selected.csv"
        if not (cand.exists() and sel.exists()):
            return None
        frames[mode] = (set(pd.read_csv(cand)["site_id"]),
                        set(pd.read_csv(sel)["site_id"]))

    (cand_b, sel_b), (cand_a, sel_a) = frames["risk_blind"], frames["risk_aware"]
    rows = []
    for sid in sorted(cand_b | cand_a):
        excluded = sid in cand_b and sid not in cand_a  # dropped by the PGA filter
        rows.append({
            "site_id": sid,
            "candidate_risk_blind": sid in cand_b,
            "candidate_risk_aware": sid in cand_a,
            "excluded_by_pga_filter": excluded,
            "selected_risk_blind": sid in sel_b,
            "selected_risk_aware": sid in sel_a,
            # the headline case: a hazard-unaware plan opens it, hazard says no
            "blind_pick_unsafe": (sid in sel_b) and excluded,
        })
    return pd.DataFrame(rows)


def summary_stats(sites, config):
    catalog_path = REPO_ROOT / config["paths"]["out_catalog"]
    n_aftershocks = len(pd.read_csv(catalog_path)) if catalog_path.exists() else None
    pga = sites.get("PGA_representative_g")
    p_unsafe = sites.get("P_unsafe")
    return {
        "aftershocks_in_window": n_aftershocks,
        "candidate_sites": int(len(sites)),
        "sites_aoi04_highres": int((sites["resolution_tier"] == "AOI04_highres").sum()),
        "pga_g": None if pga is None else {
            "min": round(float(pga.min()), 4), "max": round(float(pga.max()), 4),
            "mean": round(float(pga.mean()), 4)},
        "p_unsafe": None if p_unsafe is None else {
            "min": round(float(p_unsafe.min()), 4), "max": round(float(p_unsafe.max()), 4),
            "mean": round(float(p_unsafe.mean()), 4)},
    }


def export_saa_results(repo_root, out_dir):
    """Copy both TOPSIS-screened and all-candidate SAA bundles."""
    inventory = {}
    stochastic_root = Path(repo_root) / "outputs_stochastic"
    run_tag = os.environ.get("RUN_TAG", "")
    if run_tag:
        stochastic_root = stochastic_root / f"run{run_tag}"
    profiles = {
        "topsis_120": stochastic_root / "saa",
        "all_candidates": stochastic_root / "saa_unscreened",
    }
    required_summary = {
        "budget", "in_sample_expected_served_fraction",
        "in_sample_expected_unmet_casualties", "out_of_sample_expected_served_fraction",
        "out_of_sample_served_fraction_sd_across_replications",
        "out_of_sample_expected_unmet_casualties", "out_of_sample_unmet_sd_across_replications",
        "replications", "validation_draws_per_policy", "deterministic_expected_served_fraction",
    }
    for profile, source_dir in profiles.items():
        target_dir = Path(out_dir) / "saa" / profile
        prefix = f"saa/{profile}"
        missing = [name for name in SAA_FILES if not (source_dir / name).is_file()]
        if missing:
            inventory.update({f"{prefix}/{name}": {
                "status": "missing", "note": "SAA export incomplete; missing " + ", ".join(missing),
            } for name in SAA_FILES})
            continue

        summary = pd.read_csv(source_dir / SAA_FILES[0])
        replications = pd.read_csv(source_dir / SAA_FILES[1])
        draws = pd.read_csv(source_dir / SAA_FILES[2])
        if summary.empty or not required_summary.issubset(summary.columns):
            inventory.update({f"{prefix}/{name}": {
                "status": "missing", "note": "SAA summary is empty or has an unsupported schema",
            } for name in SAA_FILES})
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in zip(SAA_FILES, (summary, replications, draws)):
            frame.to_csv(target_dir / name, index=False, encoding="utf-8")
            inventory[f"{prefix}/{name}"] = {"status": "ok", "rows": len(frame)}
        for name in SAA_DETAIL_FILES:
            source = source_dir / name
            if source.is_file():
                frame = pd.read_csv(source)
                frame.to_csv(target_dir / name, index=False, encoding="utf-8")
                inventory[f"{prefix}/{name}"] = {"status": "ok", "rows": len(frame)}
            else:
                inventory[f"{prefix}/{name}"] = {"status": "missing", "note": "Detailed recourse export missing"}

        signatures = replications.get("training_signature", pd.Series(dtype=str)).dropna()
        training_scenarios = len(str(signatures.iloc[0]).split(";")) if not signatures.empty else None
        source_metadata = source_dir / "run_metadata.json"
        metadata = json.loads(source_metadata.read_text(encoding="utf-8")) if source_metadata.is_file() else {}
        metadata.update({
            "candidate_pool": "topsis_top_120" if profile == "topsis_120" else "all_prepared_candidates",
            "replications": int(summary["replications"].max()),
            "training_scenarios_per_replication": training_scenarios,
            "validation_draws_per_policy": int(summary["validation_draws_per_policy"].max()),
            "budgets": [int(value) for value in summary["budget"].tolist()],
        })
        (target_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        inventory[f"{prefix}/run_metadata.json"] = {"status": "ok", "rows": 1}
    return inventory


def export_paper_lp_results(repo_root, out_dir):
    """Copy both all-candidate and TOPSIS-screened Paper LP result bundles."""
    inventory = {}
    profiles = {"all_candidates": "all_candidates", "topsis_120": "topsis_120"}
    stochastic_root = Path(repo_root) / "outputs_stochastic"
    run_tag = os.environ.get("RUN_TAG", "")
    if run_tag:
        stochastic_root = stochastic_root / f"run{run_tag}"
    for profile, subdir in profiles.items():
        source_dir = stochastic_root / "paper_lp" / subdir
        target_dir = Path(out_dir) / "paper_lp" / profile
        prefix = f"paper_lp/{profile}"
        missing = [name for name in PAPER_LP_FILES if not (source_dir / name).is_file()]
        if missing:
            inventory.update({f"{prefix}/{name}": {
                "status": "missing", "note": "Paper LP export incomplete; missing " + ", ".join(missing),
            } for name in PAPER_LP_FILES})
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in PAPER_LP_FILES:
            target = target_dir / name
            shutil.copyfile(source_dir / name, target)
            inventory[f"{prefix}/{name}"] = {
                "status": "ok", "rows": sum(1 for _ in open(target, encoding="utf-8")) - 1}
        for optional in ("sensitivity_summary.csv", "summary.txt", "run_metadata.json"):
            source = source_dir / optional
            if source.is_file():
                shutil.copyfile(source, target_dir / optional)
                inventory[f"{prefix}/{optional}"] = {
                    "status": "ok", "rows": 1 if optional != "sensitivity_summary.csv" else
                    sum(1 for _ in open(target_dir / optional, encoding="utf-8")) - 1}
            elif optional == "sensitivity_summary.csv":
                inventory[f"{prefix}/{optional}"] = {"status": "missing", "note": "Sensitivity suite not run"}
    return inventory


def run(config: dict):
    os.chdir(REPO_ROOT)  # validators resolve config paths relative to repo root
    OUT_DIR.mkdir(exist_ok=True)

    # 1. per-site master table
    sites = build_sites_table(config)
    sites.to_csv(OUT_DIR / "sites.csv", index=False, encoding="utf-8")

    # 2. straight copies
    copies = {
        "hospitals.csv": REPO_ROOT / config["paths"]["out_hospitals"],
        "aftershocks.csv": REPO_ROOT / config["paths"]["out_catalog"],
        "topsis_ranking.csv": REPO_ROOT / "outputs_psaha" / "topsis_ranking.csv",
        # demand points don't depend on MODEL_MODE (only the JT candidate
        # pool does) — either mode's copy is identical, so export once
        "demand_points.csv": REPO_ROOT / "model_inputs" / "risk_aware" / "demand_points.csv",
    }
    for mode in MODES:
        for f in ("tmc_selected.csv", "casualty_allocation.csv",
                  "hospital_utilisation.csv"):
            copies[f"{mode}/{f}"] = REPO_ROOT / "model_outputs" / mode / f

    inventory = {"sites.csv": {"status": "ok", "rows": len(sites)}}
    for rel, src in copies.items():
        dst = OUT_DIR / rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            inventory[rel] = {"status": "ok", "rows": sum(1 for _ in open(src, encoding="utf-8")) - 1}
        else:
            inventory[rel] = {"status": "missing",
                              "note": f"source not found: {src.relative_to(REPO_ROOT)}"}

    # SAA results are an optional, all-or-nothing bundle for the dashboard.
    inventory.update(export_saa_results(REPO_ROOT, OUT_DIR))
    # Paper-style scenario LP is separately optional; neither workflow replaces the other.
    inventory.update(export_paper_lp_results(REPO_ROOT, OUT_DIR))

    # 3. the delta table
    status = build_site_status(sites)
    if status is not None:
        status.to_csv(OUT_DIR / "site_status.csv", index=False, encoding="utf-8")
        inventory["site_status.csv"] = {
            "status": "ok", "rows": len(status),
            "excluded_by_pga_filter": int(status["excluded_by_pga_filter"].sum()),
            "blind_picks_unsafe": int(status["blind_pick_unsafe"].sum()),
        }
    else:
        inventory["site_status.csv"] = {
            "status": "missing",
            "note": "run pipelines/deterministic_current/run_both_modes.py first"}

    # 4. validation status per dataset (same validators as the HTML report)
    from validators import VALIDATORS
    validation = {}
    for name, (validator, _) in VALIDATORS.items():
        try:
            result, _df = validator(config, fix=False)
            validation[name] = {"status": result["status"],
                                "open_issues": sum(1 for i in result["issues"]
                                                   if not i["fixed"])}
        except Exception as e:
            validation[name] = {"status": "fail", "open_issues": None, "error": str(e)}

    # 5. manifest — the only file the dashboard needs to know a priori
    ev = config["event"]
    try:
        # PGA threshold lives in the solver settings, not the extraction config
        # (imported from CODE_ROOT — settings.py itself reads PIPELINE_ROOT for data)
        sys.path.insert(0, str(CODE_ROOT / "pipelines" / "deterministic_current"))
        from settings import PGA_MAX  # noqa
    except Exception:
        PGA_MAX = None
    model_labels = json.loads(MODEL_LABELS_PATH.read_text(encoding="utf-8"))
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios": [{
            "id": "kahramanmaras_2023_30d",
            "name": "2023 Kahramanmaraş Mw 7.8, 30-day aftershock window",
            "mainshock_utc": ev["mainshock_utc"],
            "usgs_event_id": ev["usgs_event_id"],
            "window": [ev["window_start"], ev["window_end"]],
            "min_magnitude": ev["min_magnitude"],
            "bbox": config["study_area"]["bbox"],
            "pga_filter_threshold_g": PGA_MAX,
            "modes": MODES,
            "stats": summary_stats(sites, config),
        }],
        "files": inventory,
        "validation": validation,
        "model_labels": model_labels,
    }
    with open(OUT_DIR / "scenario_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"dashboard_data/ written: {len(inventory)} files, "
          f"{sum(1 for v in inventory.values() if v['status'] == 'ok')} ok")
    return manifest


if __name__ == "__main__":
    with open(EXTRACTION_DIR / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    run(cfg)
