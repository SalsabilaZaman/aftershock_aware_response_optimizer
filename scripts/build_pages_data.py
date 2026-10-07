"""Build static JSON endpoints for the GitHub Pages dashboard from CSV exports."""

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "reference_results"
DEST = ROOT / "frontend" / "public" / "data" / "api"
LABELS_PATH = ROOT / "pipelines" / "model_labels.json"


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
        "casualty_allocation": records(path("detailed_casualty_allocation.csv")),
        "staffing": records(path("detailed_staffing.csv")),
        "unmet": records(path("detailed_unmet.csv")),
        "policy_sites": records(path("detailed_policy_sites.csv")),
    }


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / "scenario_manifest.json").read_text(encoding="utf-8"))
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    write_json("scenarios.json", {
        "scenarios": manifest.get("scenarios", []),
        "generated_utc": manifest.get("generated_utc"),
        "validation": manifest.get("validation", {}),
        "files": manifest.get("files", {}),
        "model_labels": labels,
        "data_source": {"kind": "reference", "job_id": None},
    })

    site_rows = records("sites.csv")
    demand_rows = records("demand_points.csv")
    # Stable, readable labels for every view. Unnamed OSM features are anchored
    # to the nearest named demand centre while retaining the source ID.
    type_labels = {
        "social_facility": "Social facility", "community_centre": "Community centre",
        "school": "School", "hospital": "Hospital", "sports_centre": "Sports centre",
        "place_of_worship": "Place of worship", "stadium": "Stadium", "college": "College",
        "university": "University", "clinic": "Clinic", "shelter": "Shelter",
    }
    def readable_type(value):
        text = str(value or "facility")
        return type_labels.get(text, text.replace("_", " ").title())
    def site_label(site):
        name = str(site.get("name") or "")
        if name and not name.startswith("Site_"):
            return name
        nearest = min(demand_rows, key=lambda d: (float(d["latitude"]) - float(site["latitude"])) ** 2 +
                      (float(d["longitude"]) - float(site["longitude"])) ** 2, default=None)
        if nearest:
            return f"{readable_type(site.get('facility_type'))} near {nearest['name']} ({site['site_id']})"
        return f"{readable_type(site.get('facility_type'))} ({site['site_id']})"
    for site in site_rows:
        site["display_name"] = site_label(site)
        site["display_type"] = readable_type(site.get("facility_type"))
    write_json("sites.json", site_rows)
    write_json("site_status.json", records("site_status.csv"))
    hospitals = records("hospitals.csv")
    for hospital in hospitals:
        hospital["display_name"] = hospital.get("hospital_name") or f"Hospital ({hospital.get('hospital_id', 'unknown')})"
        hospital["display_type"] = "Hospital"
    write_json("hospitals.json", hospitals)
    write_json("demand_points.json", demand_rows)
    site_by_id = {str(row["site_id"]): row for row in site_rows}
    demand_by_id = {str(row["sub_district_id"]): row for row in demand_rows}
    hospital_by_id = {str(row["hospital_id"]): row for row in hospitals}

    def enrich_allocation(row):
        demand_id = str(row.get("demand_point_id", ""))
        facility_id = str(row.get("facility_id", row.get("site_id", "")))
        site = site_by_id.get(facility_id.removeprefix("JT_"))
        hospital_id = facility_id.removeprefix("JH_")
        hospital = hospital_by_id.get(hospital_id)
        row["demand_point_label"] = demand_by_id.get(demand_id, {}).get("name") or demand_id
        row["facility_label"] = site["display_name"] if site else (hospital["display_name"] if hospital else facility_id)
        row["facility_type_label"] = site["display_type"] if site else ("Hospital" if hospital else "Facility")
        return row

    choices = []
    for mode in ("risk_blind", "risk_aware"):
        label = labels["models"][mode]
        names = ("tmc_selected.csv", "casualty_allocation.csv", "hospital_utilisation.csv")
        ok = all((SOURCE / f"{mode}/{name}").is_file() for name in names)
        choices.append({"id": mode, "label": label, "available": ok})
        if ok:
            selected = records(f"{mode}/tmc_selected.csv")
            for row in selected:
                site = site_by_id.get(str(row.get("site_id", "")), {})
                row["display_name"] = site.get("display_name", row.get("site_id"))
                row["display_type"] = site.get("display_type", readable_type(row.get("facility_type")))
            allocation = [enrich_allocation(row) for row in records(f"{mode}/casualty_allocation.csv")]
            write_json(f"solutions/{mode}.json", {
                "mode": mode,
                "tmc_selected": selected,
                "hospital_utilisation": records(f"{mode}/hospital_utilisation.csv"),
                "casualty_allocation": allocation,
            })

    profile_ids = tuple(labels["candidate_sets"])
    for kind in ("paper_lp", "saa"):
        for profile in profile_ids:
            required = (("scenario_results.csv", "casualty_allocation.csv", "unmet_by_triage.csv", "staffing_plan.csv")
                        if kind == "paper_lp" else
                        ("budget_sweep_summary.csv", "budget_sweep_in_sample_by_replication.csv",
                         "budget_sweep_out_of_sample_by_draw.csv", "run_metadata.json"))
            ok = all((SOURCE / profile_source(kind, profile, name)).is_file() for name in required)
            model_choice = next((item for item in choices if item["id"] == kind), None)
            if model_choice is None:
                model_choice = {"id": kind, "label": labels["models"][kind], "available": False,
                                "profiles": {}}
                choices.append(model_choice)
            model_choice["profiles"][profile] = {"label": labels["candidate_sets"][profile], "available": ok}
            model_choice["available"] = model_choice["available"] or ok
            if ok:
                profile_data = export_profile(kind, profile)
                profile_data["casualty_allocation"] = [enrich_allocation(row) for row in profile_data.get("casualty_allocation", [])]
                profile_data["staffing_plan"] = [enrich_allocation(row) for row in profile_data.get("staffing_plan", [])]
                profile_data["staffing"] = [enrich_allocation(row) for row in profile_data.get("staffing", [])]
                if kind == "saa":
                    detail_files = (
                        "detailed_casualty_allocation.csv", "detailed_policy_sites.csv",
                        "detailed_staffing.csv", "detailed_unmet.csv",
                    )
                    profile_data["detail_available"] = all(
                        (SOURCE / profile_source(kind, profile, name)).is_file() for name in detail_files
                    )
                    profile_data["policy_sites"] = [
                        {**row, "display_name": site_by_id.get(str(row.get("site_id")), {}).get("display_name", row.get("site_id"))}
                        for row in profile_data.get("policy_sites", [])
                    ]
                write_json(f"{kind}/{profile}.json", profile_data)

    write_json("model-options.json", {
        "choices": choices,
        "candidate_set_label": labels["candidate_set_label"],
        "candidate_sets": labels["candidate_sets"],
    })
    print(f"Wrote static dashboard data to {DEST}")


if __name__ == "__main__":
    main()
