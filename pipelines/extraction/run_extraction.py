"""
Config-driven extraction pipeline CLI.

    python pipelines/extraction/run_extraction.py --all --validate --fix --report validation_report.html
    python pipelines/extraction/run_extraction.py --datasets earthquake_catalog,hospitals --validate
    python pipelines/extraction/run_extraction.py --all --set event.min_magnitude=2.5 --set force_refetch=true

Adding a new dataset = write one extractor function taking the config dict,
add one REGISTRY line (and optionally a validator in validators.py).
"""

import argparse
import importlib
import os
import sys
import traceback
from pathlib import Path

import yaml

EXTRACTION_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXTRACTION_DIR.parents[1]
DATA_PREP_DIR = REPO_ROOT / "pipelines" / "data_prep"
CONFIG_PATH = EXTRACTION_DIR / "config.yaml"

# extractors live in pipelines/data_prep (no package __init__) — import by path
sys.path.insert(0, str(DATA_PREP_DIR))
sys.path.insert(0, str(EXTRACTION_DIR))

from validators import VALIDATORS  # noqa: E402


def _extractor(module_name):
    """Lazy import so one missing dependency (osmnx, rasterio, geopandas)
    doesn't break unrelated datasets."""
    def call(config):
        return importlib.import_module(module_name).run(config)
    return call


# dataset name -> extractor callable(config). Order matters: sites feed the
# per-site extractors; sub_districts feed casualties.
REGISTRY = {
    "earthquake_catalog": _extractor("extract_01_usgs_aftershock_catalog"),
    "candidate_sites": _extractor("extract_02_osm_sites"),
    "slope_by_site": _extractor("extract_03_terrain"),
    "road_network": _extractor("extract_04_road_access"),
    "vs30_by_site": _extractor("extract_05_vs30"),
    "building_damage": _extractor("extract_06_damage"),   # also writes sites_aoi04
    "hospitals": _extractor("extract_07_hospitals"),
    "sub_districts": _extractor("extract_08_sub_districts"),
    "casualties": _extractor("extract_09_casualties"),
    # not an extraction: bundles validated outputs + solver results for the
    # dashboard repo (needs run_both_modes.py to have been run for the delta)
    "dashboard_export": _extractor("export_dashboard"),
}

# validate-only datasets (produced as side outputs of an extractor above)
VALIDATE_ONLY = ["sites_aoi04"]


def load_config(overrides):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    for spec in overrides:
        if "=" not in spec:
            raise SystemExit(f"--set expects path.to.key=value, got: {spec}")
        keypath, raw = spec.split("=", 1)
        node = config
        keys = keypath.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = yaml.safe_load(raw)  # parses numbers/bools/strings
    return config


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="run every extractor")
    ap.add_argument("--datasets", default="", help="comma-separated dataset names")
    ap.add_argument("--set", dest="overrides", action="append", default=[],
                    metavar="KEY=VALUE", help="override a config value (repeatable)")
    ap.add_argument("--validate", action="store_true", help="run validators afterwards")
    ap.add_argument("--fix", action="store_true",
                    help="auto-apply safe mechanical fixes (implies --validate)")
    ap.add_argument("--report", default=None, metavar="PATH.html",
                    help="write the HTML validation dashboard")
    ap.add_argument("--list", action="store_true", help="list available datasets")
    args = ap.parse_args()

    if args.list:
        print("Datasets:", ", ".join(REGISTRY))
        return 0

    config = load_config(args.overrides)
    validate = args.validate or args.fix or bool(args.report)

    if args.all:
        selected = list(REGISTRY)
    elif args.datasets:
        selected = [d.strip() for d in args.datasets.split(",") if d.strip()]
        unknown = [d for d in selected if d not in REGISTRY]
        if unknown:
            raise SystemExit(f"Unknown datasets: {unknown}. Available: {list(REGISTRY)}")
    else:
        selected = []
        if not validate:
            ap.print_help()
            return 1

    # extractors write repo-root-relative paths
    os.chdir(REPO_ROOT)

    extraction_errors = {}
    for name in selected:
        print(f"\n{'=' * 70}\nEXTRACT: {name}\n{'=' * 70}")
        try:
            REGISTRY[name](config)
        except Exception as e:  # keep going — the validator reports the gap
            traceback.print_exc()
            extraction_errors[name] = str(e)

    results = []
    if validate:
        to_validate = (selected or list(REGISTRY)) + VALIDATE_ONLY
        print(f"\n{'=' * 70}\nVALIDATE (fix={'on' if args.fix else 'off'})\n{'=' * 70}")
        for name in dict.fromkeys(to_validate):  # dedupe, keep order
            if name not in VALIDATORS:
                continue
            validator, out_key = VALIDATORS[name]
            try:
                result, cleaned = validator(config, fix=args.fix)
            except Exception as e:
                traceback.print_exc()
                result, cleaned = {
                    "dataset": name, "status": "fail", "row_count": 0,
                    "issues": [{"severity": "review_needed",
                                "message": f"validator crashed: {e}", "fixed": False}],
                }, None
            if name in extraction_errors:
                result["issues"].insert(0, {
                    "severity": "review_needed",
                    "message": f"extraction failed: {extraction_errors[name]}",
                    "fixed": False,
                })
                result["status"] = "fail"
            if args.fix and cleaned is not None and any(i["fixed"] for i in result["issues"]):
                cleaned.to_csv(config["paths"][out_key], index=False, encoding="utf-8")
                print(f"[FIXED] rewrote {config['paths'][out_key]}")
            results.append(result)
            n_open = sum(1 for i in result["issues"] if not i["fixed"])
            print(f"  {result['status'].upper():4s}  {name:20s} rows={result['row_count']:>6} "
                  f"issues_open={n_open}")

    if args.report:
        from report import write_report
        write_report(results, config, args.report)
        print(f"\nReport written: {args.report}")

    if any(r["status"] == "fail" for r in results):
        print("\nRESULT: at least one dataset FAILED — fix before using downstream.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
