"""
Run the deterministic facility-location model in both hazard modes:

  risk_blind  — no PGA filter on candidate TMCs (what a hazard-unaware plan opens)
  risk_aware  — candidates with PGA > settings.PGA_MAX excluded (the PSAHA filter)

Outputs land in model_inputs/<mode>/ and model_outputs/<mode>/. The dashboard's
comparison view is built from the difference between the two runs.

Each mode runs in a subprocess so settings.py (which reads MODEL_MODE at import
time) is evaluated fresh per mode.
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODES = ["risk_blind", "risk_aware"]


def main():
    for mode in MODES:
        env = dict(os.environ, MODEL_MODE=mode)
        for step in ("step1_prepare_data.py", "step2_solve_model.py"):
            print(f"\n{'=' * 70}\n{mode.upper()} :: {step}\n{'=' * 70}")
            result = subprocess.run([sys.executable, str(HERE / step)],
                                    env=env, cwd=str(HERE))
            if result.returncode != 0:
                raise SystemExit(f"{step} failed in mode {mode} "
                                 f"(exit {result.returncode})")
    print("\nBoth modes solved. Compare model_outputs/risk_blind/ vs "
          "model_outputs/risk_aware/.")


if __name__ == "__main__":
    main()
