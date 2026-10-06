"""Compatibility entry point for the retired multi-objective workflow.

The stochastic pipeline now uses one cost objective and SAA validation.
Run: python pipelines/stochastic_medical/run_saa.py
"""
from run_saa import main

if __name__ == "__main__":
    main()
