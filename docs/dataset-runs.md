# AARO uploaded dataset runs

The AARO React frontend can show the committed reference results without a backend. Uploading a dataset requires the FastAPI service in `backend/`; GitHub Pages serves the UI but does not execute Python or solve models. Set the GitHub Actions repository variable `AARO_API_BASE_URL` to the public HTTPS URL of that service. For local frontend development, copy `.env.example` to `frontend/.env.local`.

## Run flow

1. The user selects a ZIP containing the prepared `data_processed/` files below.
2. The API validates the ZIP contents and CSV headers, then saves the run in `AARO_RUNS_DIR` (default `backend_data/runs/`).
3. `pipelines/run_demo_job.py` runs PSAHA, risk-blind and risk-aware deterministic preparation/solves, allocation map creation, dashboard export, and JSON dashboard export in an isolated run directory.
4. The frontend polls the run status and reads the resulting JSON using the run ID. Runs remain available after an API restart when `AARO_RUNS_DIR` points to durable storage.

The API accepts CORS origins through `AARO_ALLOWED_ORIGINS` as a comma-separated list. Configure this to the Pages origin for deployment. Upload and extraction limits can be adjusted using `AARO_MAX_UPLOAD_BYTES`, `AARO_MAX_UNPACKED_BYTES`, and `AARO_MAX_ARCHIVE_FILES`. The API runs one pipeline job at a time by default; set `AARO_MAX_ACTIVE_RUNS` to change that limit.

## Where dashboard data comes from

The published dashboard does not fetch research data from a live external source. Its static JSON is generated from the checked-in CSV snapshot in `examples/reference_results/` by `scripts/build_pages_data.py`. That snapshot is refreshed deliberately from the primary `earthquake_response` repository and is independent of its `dashboard_data/` folder. The local SQLite database under `data_etl/` is only a query aid and is not read by the browser dashboard or FastAPI result endpoints.

For an uploaded run, the browser sends a ZIP of prepared `data_processed/` CSVs to the FastAPI backend. The backend stores the upload under `AARO_RUNS_DIR`, runs the pipeline against that isolated copy, and serves generated JSON for that run from its `api_data/` directory. The upload pipeline does not download raw datasets or query USGS, OSM, or other providers.

The dashboard's **Export selected run** button downloads one ZIP containing CSV tables for the selected model/profile and a human-readable `summary.txt`. The CSVs preserve row-level results; the text file records the selected model, profile, run/source identifiers, and summary metrics.

## Required prepared files

Put these CSV files at the exact paths below inside `data_processed/`. Required columns must be present. Numeric columns should contain valid numeric values and coordinates use decimal degrees.

| Path | Required columns | Notes |
| --- | --- | --- |
| `seismic/aftershock_catalog.csv` | `time_utc`, `latitude`, `longitude`, `magnitude` | Aftershock observations used by PSAHA. Times should be parseable UTC timestamps. |
| `sites/candidate_sites.csv` | `site_id`, `latitude`, `longitude`, `facility_type` | Candidate sites, including any hospital features used for matching. |
| `sites/site_condition_per_site.csv` | `site_id`, `vs30_ms` | Vs30 in metres per second for PSAHA ground-motion calculations. |
| `sites/site_area_per_site.csv` | `site_id`, `site_area_m2` | Site area in square metres for TMC capacity. |
| `casualties/sub_districts_raw.csv` | `sub_district_id`, `name`, `population` | Demand-point rows. Supplying `latitude` and `longitude` is recommended; if absent or missing, the pipeline geocodes names. |
| `casualties/casualty_projections.csv` | `sub_district_id`, `scenario_id`, `period`, `T1_count`, `T2_count`, `T3_count` | Casualty scenarios and triage totals. |
| `hospitals/hospital_data.csv` | `hospital_id`, `hospital_name`, `latitude`, `longitude`, `bed_capacity_total` | Existing hospital locations and bed capacities. `effective_capacity_postquake` can represent post-quake closures/capacity. |

`data_raw/` is optional and is not read by this run flow. This upload path starts from prepared data and does not launch the extraction pipeline, download source datasets, or run the stochastic Paper LP/SAA models.

## Run the backend

Install the repository's `requirements.txt` and `backend/requirements.txt`, then from the repository root:

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

For deployment, `backend/Dockerfile` installs the pipeline and API dependencies. Mount durable storage at `/var/lib/aaro` (or set `AARO_RUNS_DIR` to another persistent volume) and configure `AARO_ALLOWED_ORIGINS`. The frontend build reads `VITE_API_BASE_URL`; reference results still work if that variable is unset, but dataset runs are disabled.
