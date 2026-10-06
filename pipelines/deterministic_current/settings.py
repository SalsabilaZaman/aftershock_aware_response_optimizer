import os
from pathlib import Path


# PIPELINE_ROOT lets a job-scoped demo run (pipelines/run_demo_job.py) point the
# whole solver at an isolated data bundle instead of this repo checkout.
PROJECT_ROOT = Path(os.environ.get("PIPELINE_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = str(PROJECT_ROOT / "data_processed")

# risk_aware  — candidate TMCs above PGA_MAX are excluded (the PSAHA filter)
# risk_blind  — no hazard filter; used as the comparison baseline showing what
#               a hazard-unaware plan would have opened
# Selected via the MODEL_MODE environment variable (see run_both_modes.py);
# each mode gets its own model_inputs/<mode>/ and model_outputs/<mode>/ tree.
MODEL_MODE = os.environ.get("MODEL_MODE", "risk_aware")
if MODEL_MODE not in ("risk_aware", "risk_blind"):
    raise ValueError(f"MODEL_MODE must be risk_aware or risk_blind, got {MODEL_MODE!r}")
APPLY_PGA_FILTER = MODEL_MODE == "risk_aware"

# RUN_TAG isolates one-off parameter-sweep runs (see run_sensitivity.py) into
# their own model_inputs/model_outputs subfolder instead of overwriting the
# committed reference run. Empty by default, so ordinary risk_aware/risk_blind
# runs are unaffected.
RUN_TAG = os.environ.get("RUN_TAG", "")
INPUT_DIR = str(PROJECT_ROOT / "model_inputs" / (MODEL_MODE + RUN_TAG))
OUTPUT_DIR = str(PROJECT_ROOT / "model_outputs" / (MODEL_MODE + RUN_TAG))
PSAHA_OUTPUT_DIR = str(PROJECT_ROOT / "outputs_psaha")
CACHE_FILE = str(PROJECT_ROOT / "model_inputs" / "geocode_cache.json")  # shared across modes
# Each list is checked in order; the current post-reorg location comes first,
# with the pre-reorg `data/` layout kept as a legacy fallback.
DATA_FILE_CANDIDATES = {
    "sub_districts_raw.csv": [
        PROJECT_ROOT / "data_processed" / "casualties" / "sub_districts_raw.csv",
        PROJECT_ROOT / "data" / "sub_districts_raw.csv",
    ],
    "casualty_projections.csv": [
        PROJECT_ROOT / "data_processed" / "casualties" / "casualty_projections.csv",
        PROJECT_ROOT / "data" / "casualty_projections.csv",
    ],
    "candidate_sites.csv": [
        PROJECT_ROOT / "data_processed" / "sites" / "candidate_sites.csv",
        PROJECT_ROOT / "data" / "candidate_sites.csv",
    ],
    "hospital_data.csv": [
        PROJECT_ROOT / "data_processed" / "hospitals" / "hospital_data.csv",
        PROJECT_ROOT / "data" / "hospital_data.csv",
    ],
    "site_area_per_site.csv": [
        PROJECT_ROOT / "data_processed" / "sites" / "site_area_per_site.csv",
    ],
}

SCENARIO_ID = 1
PERIODS = None
HOSPITAL_MATCH_RADIUS_KM = 25.0
# Risk-aware candidate filter: exclude sites whose representative aftershock
# PGA (max median PGA over M>=5 aftershock scenarios, outputs_psaha,
# pipelines/psaha/step3_gmpe.py) exceeds this. PGA is now computed with
# BSSA14 (Boore, Stewart, Seyhan & Atkinson 2014), a published NGA-West2
# GMPE, rather than the earlier unpublished toy attenuation formula — so
# this is a real, physically interpretable PGA value in g, not a
# model-relative tuning knob.
# 0.2 g is the same EMS-98-based threshold used as g* in
# pipelines/psaha/step4_hazard_probability.py for P_unsafe: the level above
# which unreinforced/already-damaged masonry sustains further structural
# damage, i.e. "unsafe for a field TMC." Reusing it here (rather than a
# separately invented cutoff) keeps the candidate-filter criterion and the
# probabilistic hazard criterion consistent with each other.
# Excludes 38/803 candidate sites (~4.7%) at time of writing.
PGA_MAX = 0.2

# Opening penalty for candidate TMCs, expressed in the objective's own units
# (casualty-km — see the C_TRANS comment below). This is NOT a facility setup
# cost: unlike TMC capacity (Sphere/UNHCR shelter-area standard, see below),
# there is no defensible standard for what it costs to establish a tented TMC,
# and an earlier version of this constant (TMC_DEFAULT_COST) was applied
# uniformly to every candidate with no cited rationale for its value or units.
# It is instead an explicit, judgement-chosen exchange rate between facility
# parsimony and patient travel burden: opening one additional TMC is only
# worth it if doing so reduces total casualty-km by at least this amount.
# A TMC serving N casualties clears that bar if it shortens their average
# trip by OPENING_PENALTY_CASUALTY_KM / N km (e.g. 0.5 km at N=2000) — i.e.
# this parameter is fairly permissive at the capacities this model produces.
# Robustness of the paper's findings to this choice is checked across
# {100, 300, 1000, 3000, 10000} in run_sensitivity.py / docs/SENSITIVITY.md.
# Overridable via env var (same pattern as MODEL_MODE) so run_sensitivity.py
# can sweep it across subprocess runs without editing this file.
OPENING_PENALTY_CASUALTY_KM = float(os.environ.get("OPENING_PENALTY_CASUALTY_KM", 1000.0))

# TMC capacity is derived from real per-site OSM polygon area (see
# pipelines/data_prep/extract_02_osm_sites.py -> site_area_per_site.csv),
# not a fixed per-type guess. For the ~92% of candidates that are OSM "way"
# features this polygon is almost always the site/campus boundary (schoolyard,
# university grounds, stadium grounds) rather than a building outline — OSM
# rarely tags building=* separately for these in this catalog — so it is used
# deliberately as OUTDOOR usable site area for a tented/field TMC, not indoor
# floor area. That's also the more defensible reading operationally: the PGA
# filter already exists because post-earthquake buildings may be structurally
# unsafe, so a TMC modeled as tents on open ground (as was actually done in
# the 2023 response — school yards, stadiums) is more realistic than assuming
# people shelter inside a structure whose safety the model itself questions.
#
# cap_j = site_area_m2 / SHELTER_AREA_PER_PERSON_M2, clipped to
# [TMC_MIN_CAPACITY, TMC_MAX_CAPACITY].
#
# SHELTER_AREA_PER_PERSON_M2 = 30 m^2/person: Sphere Handbook / UNHCR figure
# for a temporary/transitional settlement site — basic internal circulation
# and communal space but not the full road/infrastructure buildout a
# long-term planned camp (45 m^2/person) needs. A TMC here represents a
# 30-day emergency-window facility, not a long-duration IDP camp, so the
# transitional-site figure is the better-fitting standard of the two.
# TMC_MAX_CAPACITY = 2000: a handful of OSM campuses (e.g. KSU Avşar campus,
# ~2.7 km^2) would otherwise imply a single site absorbing tens of thousands
# of casualties, which is an area artifact, not an operational plan — disaster
# response doctrine favors multiple distributed, independently staffed sites
# over one mega-camp, so a single TMC's capacity is capped.
# TMC_MIN_CAPACITY = 30: below this a site isn't practically viable as a
# standalone TMC (staffing/setup overhead dominates).
SHELTER_AREA_PER_PERSON_M2 = 30.0
TMC_MIN_CAPACITY = 30
TMC_MAX_CAPACITY = 2000

# Fallback only — used if a candidate is missing a site_area_m2 value (should
# not happen after extract_02's type-median imputation, but kept defensive).
TMC_CAPACITY_BY_TYPE = {
    "school": 200,
    "university": 300,
    "sports_centre": 250,
    "stadium": 500,
    "social_facility": 100,
}

# The solver's objective is denominated in casualty-kilometres: the transport
# term is distance_km * casualties, taken directly. C_TRANS is kept as a named
# identity constant (several call sites reference it) but is definitionally
# 1.0 by construction of what the objective's units are — it is not a
# currency-conversion or calibration factor, and must not be changed to
# "tune" the model. An earlier draft priced this term in real diesel-cost USD;
# that was rejected because it swaps units without changing the model (only
# the ratio between this term and OPENING_PENALTY_CASUALTY_KM affects the
# solve) while adding several unverifiable assumptions (fuel price, FX rate,
# vehicle consumption, occupancy) and still leaving the opening term invented.
C_TRANS = 1.0
TIME_LIMIT_SEC = 600
MIP_GAP = 0.01
