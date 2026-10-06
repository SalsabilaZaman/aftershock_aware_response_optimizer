"""
Step 5 -- AHP + TOPSIS shelter/TMC ranking (docs/methodology/combined_methodology.pdf, S6).

This is a STANDALONE advisory ranking, not a solver input. The deterministic
MILP (pipelines/deterministic_current) already decides which candidate TMCs
open, using a PGA hard-filter (risk_aware mode) instead of a soft multi-
criteria score -- see docs/CURRENT_PIPELINE.md's "AHP/TOPSIS is dropped by
decision" note and prep_support.assign_opening_penalty's docstring, which
explains the earlier TOPSIS-scaled opening-penalty code path was removed as
dead code. That decision is not reopened here. This script produces a
parallel, informational deliverable -- exactly how the source PDF's own
workflow table treats it (Phase 2 "Shelter site ranking" is listed alongside,
not upstream of, Phase 3 "TMC location & routing").

Ranks every risk-aware candidate TMC site by four criteria (PDF S6.1):
  - Aftershock hazard level (PGA, g)      -- cost (minimise)
  - Terrain slope (degrees)                -- cost (minimise)
  - Elevation (m)                          -- benefit (maximise)
  - Distance to nearest road (m)           -- cost (minimise)

AHP fixed pairwise comparison matrix and TOPSIS steps follow the PDF's
worked example exactly (S6.2-6.3); the AHP weights are verified against the
PDF's own reference numbers in tests/test_topsis_ranking.py.

Run: python pipelines/psaha/step5_ahp_topsis.py
"""
import numpy as np
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
PSAHA_DIR = BASE_DIR / "outputs_psaha"
SITES_DIR = BASE_DIR / "data_processed" / "sites"
CANDIDATES_PATH = BASE_DIR / "model_inputs" / "risk_aware" / "candidates_jt.csv"
OUTPUT_PATH = PSAHA_DIR / "topsis_ranking.csv"

# Saaty-scale pairwise comparison matrix, criterion order
# [PGA, slope, elevation, dist_to_road] -- PDF eq. 23, S6.2.
PAIRWISE_MATRIX = np.array([
    [1.0,   3.0,   5.0,   3.0],
    [1 / 3, 1.0,   3.0,   2.0],
    [1 / 5, 1 / 3, 1.0,   1 / 2],
    [1 / 3, 1 / 2, 2.0,   1.0],
])
CRITERIA = ["pga_g", "slope_deg", "elevation_m", "dist_to_road_m"]
# cost criteria are minimised (lower is better); benefit criteria maximised
CRITERION_TYPE = {"pga_g": "cost", "slope_deg": "cost", "elevation_m": "benefit", "dist_to_road_m": "cost"}
RANDOM_INDEX_N4 = 0.90  # Saaty's RI for n=4 (PDF S6.2)
CR_ACCEPT_THRESHOLD = 0.10


def compute_ahp_weights(pairwise_matrix):
    """Column-normalise then row-average (PDF eq. 23 weight derivation) plus CR (eq. 24)."""
    n = pairwise_matrix.shape[0]
    col_sums = pairwise_matrix.sum(axis=0)
    normalised = pairwise_matrix / col_sums
    weights = normalised.mean(axis=1)

    weighted_sum = pairwise_matrix @ weights
    lambda_max = float(np.mean(weighted_sum / weights))
    ci = (lambda_max - n) / (n - 1)
    cr = ci / RANDOM_INDEX_N4
    return weights, cr


def build_decision_matrix():
    candidates = pd.read_csv(CANDIDATES_PATH, usecols=["site_id"])
    psaha = pd.read_csv(PSAHA_DIR / "psaha_output_per_site.csv", usecols=["site_id", "PGA_representative_g"])
    topo = pd.read_csv(SITES_DIR / "topography_per_site.csv", usecols=["site_id", "elevation_m", "slope_deg"])
    access = pd.read_csv(SITES_DIR / "accessibility_per_site.csv", usecols=["site_id", "dist_to_road_m"])

    matrix = (
        candidates
        .merge(psaha.rename(columns={"PGA_representative_g": "pga_g"}), on="site_id", how="left")
        .merge(topo, on="site_id", how="left")
        .merge(access, on="site_id", how="left")
    )
    missing = matrix[CRITERIA].isna().any(axis=1)
    if missing.any():
        dropped = matrix.loc[missing, "site_id"].tolist()
        print(f"  Dropping {len(dropped)} candidate(s) missing a criterion value: {dropped}")
        matrix = matrix.loc[~missing].reset_index(drop=True)
    return matrix


def topsis(matrix, weights):
    """PDF S6.3, eq. 25-30."""
    x = matrix[CRITERIA].to_numpy(dtype=float)
    norm = np.sqrt((x ** 2).sum(axis=0))
    r = x / norm
    v = r * weights

    ideal_best = np.empty(len(CRITERIA))
    ideal_worst = np.empty(len(CRITERIA))
    for k, crit in enumerate(CRITERIA):
        if CRITERION_TYPE[crit] == "cost":
            ideal_best[k], ideal_worst[k] = v[:, k].min(), v[:, k].max()
        else:
            ideal_best[k], ideal_worst[k] = v[:, k].max(), v[:, k].min()

    d_plus = np.sqrt(((v - ideal_best) ** 2).sum(axis=1))
    d_minus = np.sqrt(((v - ideal_worst) ** 2).sum(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        cc = np.where((d_plus + d_minus) > 0, d_minus / (d_plus + d_minus), 0.0)

    out = matrix.copy()
    out["D_plus"] = d_plus
    out["D_minus"] = d_minus
    out["CC_i"] = cc
    out["rank"] = out["CC_i"].rank(ascending=False, method="min").astype(int)
    return out.sort_values("rank")


def main():
    weights, cr = compute_ahp_weights(PAIRWISE_MATRIX)
    print("AHP weights (PGA, slope, elevation, dist_to_road):", np.round(weights, 3))
    print(f"Consistency ratio CR = {cr:.4f} ({'OK' if cr < CR_ACCEPT_THRESHOLD else 'WARNING: exceeds 0.10'})")

    matrix = build_decision_matrix()
    print(f"Ranking {len(matrix)} risk-aware candidate TMC sites")

    ranked = topsis(matrix, weights)
    out_cols = ["site_id", "CC_i", "rank", "D_plus", "D_minus"] + CRITERIA
    ranked = ranked[out_cols]

    PSAHA_DIR.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {OUTPUT_PATH} ({len(ranked)} rows)")
    print("Top 5 sites by CC_i:")
    print(ranked.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
