"""Run the deterministic location model on the included synthetic fixture."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples"
SOLVER = ROOT / "pipelines" / "deterministic_current" / "step2_solve_model.py"


def main() -> int:
    env = dict(os.environ)
    env["PIPELINE_ROOT"] = str(EXAMPLE_ROOT)
    env["MODEL_MODE"] = "risk_aware"
    return subprocess.call([sys.executable, str(SOLVER)], cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
