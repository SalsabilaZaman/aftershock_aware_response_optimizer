"""Build static JSON endpoints for the GitHub Pages dashboard from CSV exports."""

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "reference_results"
DEST = ROOT / "frontend" / "public" / "data" / "api"


def records(relpath: str) -> list[dict]:
    path = SOURCE / relpath
    if not path.is_file():
        return []
    return json.loads(pd.read_csv(path).to_json(orient="records"))


def write_json(relpath: str, value) -> None:
    path = DEST / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def profile_source(kind: str, profile: str, name: str) -> str:
    nested = f"{kind}/{profile}/{name}"
    if (SOURCE / nested).is_file():
        return nested
    if profile == "all_candidates" and (SOURCE / kind / name).is_file():
        return f"{kind}/{name}"
    return nested


def optional_json(relpath: str) -> dict:
    path = SOURCE / relpath
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def export_profile(kind: str, profile: str) -> dict:
    path = lambda name: profile_source(kind, profile, name)
    if kind == "paper_lp":
        return {
            "profile": profile,
            "metadata": optional_json(path("run_metadata.json")),
            "scenario_rows": records(path("scenario_results.csv")),
            "casualty_allocation": records(path("casualty_allocation.csv")),
            "unmet_by_triage": records(path("unmet_by_triage.csv")),
            "staffing_plan": records(path("staffing_plan.csv")),
            "sensitivity_rows": records(path("sensitivity_summary.csv")),
        }
    return {
        "profile": profile,
        "metadata": optional_json(path("run_metadata.json")),
        "budget_rows": records(path("budget_sweep_summary.csv")),
        "replication_rows": records(path("budget_sweep_in_sample_by_replication.csv")),
        "performance_rows": records(path("objective_components_by_budget.csv")),
    }


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / "scenario_manifest.json").read_text(encoding="utf-8"))
    write_json("scenarios.json", {
        "scenarios": manifest.get("scenarios", []),
        "generated_utc": manifest.get("generated_utc"),
        "validation": manifest.get("validation", {}),
        "files": manifest.get("files", {}),
        "data_source": {"kind": "reference", "job_id": None},
    })

    site_rows = records("sites.csv")
    write_json("sites.json", site_rows)
    write_json("site_status.json", records("site_status.csv"))
    write_json("hospitals.json", records("hospitals.csv"))
    write_json("demand_points.json", records("demand_points.csv"))

    choices = []
    for mode, label in (("risk_blind", "Risk-blind MILP"), ("risk_aware", "Risk-aware MILP")):
        names = ("tmc_selected.csv", "casualty_allocation.csv", "hospital_utilisation.csv")
        ok = all((SOURCE / f"{mode}/{name}").is_file() for name in names)
        choices.append({"id": mode, "label": label, "available": ok})
        if ok:
            write_json(f"solutions/{mode}.json", {
                "mode": mode,
                "tmc_selected": records(f"{mode}/tmc_selected.csv"),
                "hospital_utilisation": records(f"{mode}/hospital_utilisation.csv"),
                "casualty_allocation": records(f"{mode}/casualty_allocation.csv"),
            })

    profile_labels = {"all_candidates": "All prepared TMC candidates", "topsis_120": "TOPSIS top-120 TMC candidates"}
    for kind in ("paper_lp", "saa"):
        for profile, label in profile_labels.items():
            required = (("scenario_results.csv", "casualty_allocation.csv", "unmet_by_triage.csv", "staffing_plan.csv")
                        if kind == "paper_lp" else
                        ("budget_sweep_summary.csv", "budget_sweep_in_sample_by_replication.csv",
                         "budget_sweep_out_of_sample_by_draw.csv", "run_metadata.json"))
            ok = all((SOURCE / profile_source(kind, profile, name)).is_file() for name in required)
            model_id = f"{kind}_{profile}"
            choices.append({"id": model_id, "label": f"{kind.replace('_', ' ').upper()} · {label}",
                            "model": kind, "profile": profile, "available": ok})
            if ok:
                write_json(f"{kind}/{profile}.json", export_profile(kind, profile))

    write_json("model-options.json", {"choices": choices})
    print(f"Wrote static dashboard data to {DEST}")


if __name__ == "__main__":
    main()
