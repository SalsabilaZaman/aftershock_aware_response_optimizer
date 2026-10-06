"""Settings for the two-stage stochastic medical response model and SAA."""
import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("PIPELINE_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = PROJECT_ROOT / "data_processed"
DETERMINISTIC_INPUT_DIR = PROJECT_ROOT / "model_inputs" / "risk_aware"
DETERMINISTIC_OUTPUT_DIR = PROJECT_ROOT / "model_outputs" / "risk_aware"

RUN_TAG = os.environ.get("RUN_TAG", "")
OUTPUT_DIR = PROJECT_ROOT / "outputs_stochastic" / ("run" + RUN_TAG if RUN_TAG else "")

CASUALTY_PROJECTIONS_PATH = DATA_DIR / "casualties" / "casualty_projections.csv"
HOSPITAL_DATA_PATH = DATA_DIR / "hospitals" / "hospital_data.csv"
DAMAGE_INDICATORS_PATH = DATA_DIR / "sites" / "damage_indicators_per_site.csv"
TOPSIS_RANKING_PATH = PROJECT_ROOT / "outputs_psaha" / "topsis_ranking.csv"

PERIODS = [1, 2, 3, 4]
TRIAGE = ["T1", "T2", "T3"]

# The 20 source scenarios are sampled uniformly for the SAA training and
# evaluation distributions.
SCENARIOS_USED = list(range(1, 21))
SCENARIO_PROB = {s: 1.0 / len(SCENARIOS_USED) for s in SCENARIOS_USED}

# --- Health-state Markov chains (PDF eq. 32) ---------------------------
# States order: D (dead), T1, T2, T3, DC (discharged) for treated;
# D, T1, T2, T3 for untreated (no discharge state -- untreated casualties
# do not recover on their own within the 72h horizon modelled here).
TREAT_TRANSITION = {
    "T1": {"D": 0.15, "T1": 0.60, "T2": 0.25, "T3": 0.00, "DC": 0.00},
    "T2": {"D": 0.10, "T1": 0.00, "T2": 0.20, "T3": 0.70, "DC": 0.00},
    "T3": {"D": 0.05, "T1": 0.00, "T2": 0.00, "T3": 0.15, "DC": 0.80},
}
UNTREAT_TRANSITION = {
    "T1": {"D": 0.60, "T1": 0.40, "T2": 0.00, "T3": 0.00},
    "T2": {"D": 0.00, "T1": 0.55, "T2": 0.45, "T3": 0.00},
    "T3": {"D": 0.00, "T1": 0.00, "T2": 0.25, "T3": 0.75},
}

# --- Distance limit for immediate (T1) casualties (PDF eq. 46) ---------
DISTANCE_LIMIT_T1_KM = 12.0

# --- Sample Average Approximation --------------------------------------
SAA_REPLICATIONS = 10
SAA_SCENARIOS_PER_REPLICATION = 10
SAA_OUT_OF_SAMPLE_SIZE = 1000
SAA_SEED = 20261002
BUDGET_VALUES = [0, 10, 25, 50, 100, 120]
TMC_CANDIDATE_LIMIT = 120
SINGLE_RUN_TMC_BUDGET = 120
# Assumption: mean-one LogNormal casualty multipliers, sigma=0.20.
CASUALTY_LOGNORMAL_SIGMA = 0.20
# Assumption: road damage U(0, ROAD_DAMAGE_RATIO_MAX); hospital loss is
# local observed damage times U(0, 0.50).
# Objective cost units: one uniquely unserved casualty is penalized by at
# least 10x the largest possible casualty transport cost, plus a margin for
# maximum per-casualty staffing cost. The runtime value is derived from the
# prepared distance matrix and the travel/staff weights below.
UNMET_PENALTY_FACTOR = 10.0
TRAVEL_COST_WEIGHT_PER_CASUALTY_KM = 1.0
STAFFING_COST_WEIGHT_PER_STAFF_PERIOD = 1000.0

# --- Staffing productivity (theta, gamma in the PDF) --------------------
# [ASSUMPTION] No cited source for casualties-treatable-per-clinician-per-
# 12h-period in the reviewed literature; these are order-of-magnitude
# planning defaults consistent with mass-casualty triage throughput
# figures (a doctor directly managing ~4 T2 "delayed" cases per 12h period
# alongside supervising others; a nurse handling ~8 T2/T3 cases per period).
# Flagged per REPORT_CONTEXT.md's "never invent a number" convention --
# any report text referencing these must carry this same [ASSUMPTION] tag.
DOCTOR_PATIENTS_PER_PERIOD = 4.0
NURSE_PATIENTS_PER_PERIOD = 8.0

# --- Road damage ratio f^s_ij (PDF eq. 34, Z2) --------------------------
# [ASSUMPTION] No per-edge road damage survey exists for this event at
# the granularity this model would need. Derived instead from each
# scenario's severity (total dead_count relative to the most severe
# scenario in SCENARIOS_USED) as a single scalar per scenario applied
# uniformly to every (i,j) pair in that scenario -- more severe scenarios
# imply more road/bridge damage, raising effective travel distance.
# Range chosen conservatively (0 to 30% extra effective distance) --
# see docs/STOCHASTIC_MODEL.md for the derivation.
ROAD_DAMAGE_RATIO_MAX = 0.30

# --- Hospital structural damage factor g^s_j (PDF eq. 40) ---------------
# Combines two real, already-collected data sources instead of a single
# invented per-hospital number: (1) data_processed/sites/damage_indicators_per_site.csv's
# damage_score (0=heavily damaged/near destroyed buildings, 1=undamaged
# area) for the OSM site matched to each hospital (hospitals_jh.csv's
# matched_site_id, from the deterministic prep step's coordinate
# cross-check), scaled by (2) the same per-scenario severity factor used
# for ROAD_DAMAGE_RATIO_MAX. A hospital with damage_score=1.0 (undamaged
# area) loses 0% capacity even in the worst scenario; one with
# damage_score=0.0 loses up to HOSPITAL_DAMAGE_MAX_FRACTION.
HOSPITAL_DAMAGE_MAX_FRACTION = 0.50

# --- Outpatient (T3) capacity for TMCs ----------------------------------
# TMCs have no outpatient_capacity column (that only exists for curated
# hospitals). Per the PDF's own Key Parameters table ("Outpatient capacity
# multiplier: 3x bed capacity, per EMC"), TMC outpatient (T3) capacity is
# derived as this multiple of the TMC's already area-derived cap_j
# (pipelines/deterministic_current/settings.py's SHELTER_AREA_PER_PERSON_M2
# standard), rather than inventing a second, independent capacity figure.
TMC_OUTPATIENT_CAPACITY_MULTIPLIER = 3.0

TIME_LIMIT_SEC = 300
MIP_GAP = 0.01
# CLI profiles: dev is the quick default; final preserves publication-sized SAA.
DEV_REPLICATIONS = 3
DEV_SCENARIOS_PER_REPLICATION = 10
DEV_OUT_OF_SAMPLE_SIZE = 100
DEV_TIME_LIMIT_SEC = 60
DEV_MIP_GAP = 0.02
