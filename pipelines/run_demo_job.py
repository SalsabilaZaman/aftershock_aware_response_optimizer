"""
Job-scoped demo orchestrator: runs PSAHA hazard steps -> deterministic MILP
prep/solve (both modes) -> allocation map -> dashboard_data export, all against
a single --root data bundle (a directory containing data_processed/, matching
this repo's layout) instead of this repo checkout. data_raw/ is accepted if
present but not read by any of these stages.

Used by the dashboard's "upload a dataset -> watch it compute -> see results"
demo (backend/app.py POST /api/run/{job_id}), but also runnable standalone:

    python pipelines/run_demo_job.py --root /path/to/job_dir

Each stage is a subprocess so PIPELINE_ROOT/MODEL_MODE (read at import time by
settings.py and the PSAHA scripts) are picked up fresh per stage, mirroring
run_both_modes.py's existing pattern for MODEL_MODE.

Progress is appended to <root>/status.json as each stage starts/finishes, so a
caller (e.g. the FastAPI backend) can poll it instead of blocking on this
process. On failure, the stage's captured stderr tail is recorded and the
remaining stages are skipped.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent
DET_DIR = CODE_ROOT / "pipelines" / "deterministic_current"
PSAHA_DIR = CODE_ROOT / "pipelines" / "psaha"
EXTRACTION_DIR = CODE_ROOT / "pipelines" / "extraction"
MODES = ["risk_blind", "risk_aware"]

STAGES = (
    [("psaha", s, PSAHA_DIR, s) for s in (
        "step1_omori.py", "step2_gutenberg_richter.py",
        "step3_gmpe.py", "step4_hazard_probability.py")]
    + [(f"solve_{mode}", step, DET_DIR, step)
       for mode in MODES for step in ("step1_prepare_data.py", "step2_solve_model.py")]
    + [("allocation_map", "make_allocation_map_simple.py", DET_DIR, "make_allocation_map_simple.py")]
    + [("dashboard_export", "run_extraction.py", EXTRACTION_DIR, "run_extraction.py")]
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_status(status_path, status):
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")


def run(root: Path):
    root = root.resolve()
    status_path = root / "status.json"
    status = {"root": str(root), "started_utc": _now(), "stages": [], "state": "running"}
    _write_status(status_path, status)

    base_env = dict(os.environ, PIPELINE_ROOT=str(root))

    for stage_id, script_name, script_dir, script_file in STAGES:
        env = dict(base_env)
        if stage_id.startswith("solve_"):
            env["MODEL_MODE"] = stage_id.removeprefix("solve_")

        args = [sys.executable, str(script_dir / script_file)]
        if stage_id == "dashboard_export":
            args += ["--datasets", "dashboard_export"]

        entry = {"stage": stage_id, "script": script_name, "started_utc": _now(),
                  "status": "running"}
        status["stages"].append(entry)
        _write_status(status_path, status)

        result = subprocess.run(args, env=env, cwd=str(script_dir),
                                 capture_output=True, text=True)

        entry["finished_utc"] = _now()
        if result.returncode == 0:
            entry["status"] = "ok"
        else:
            entry["status"] = "error"
            entry["stderr_tail"] = "\n".join(result.stderr.splitlines()[-40:])
            status["state"] = "error"
            status["failed_stage"] = stage_id
            _write_status(status_path, status)
            return status

        _write_status(status_path, status)

    status["state"] = "done"
    status["finished_utc"] = _now()
    _write_status(status_path, status)
    return status


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True,
                     help="job directory containing data_processed/ (data_raw/ is accepted "
                          "but not read by any stage this orchestrator runs)")
    args = ap.parse_args()

    root = Path(args.root)
    if not (root / "data_processed").exists():
        raise SystemExit(f"--root {root} has no data_processed/ subdirectory")

    status = run(root)
    if status["state"] != "done":
        raise SystemExit(f"job failed at stage {status.get('failed_stage')}; "
                          f"see {root / 'status.json'}")
    print(f"Job complete. Results in {root / 'dashboard_data'}.")


if __name__ == "__main__":
    main()
