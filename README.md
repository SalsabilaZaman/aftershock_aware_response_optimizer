# Aftershock Aware Response Optimizer

A research pipeline and static browser dashboard for studying post-earthquake hazard and medical-facility planning after the 6 February 2023 Kahramanmaraş earthquake sequence.

**Dashboard:** `https://salsabilazaman.github.io/aftershock_aware_response_optimizer` after GitHub Pages is enabled and the deployment workflow succeeds.

## What this repository runs

The repository contains the research pipeline source, a small synthetic solver example, and a curated reference-data snapshot. The published dashboard is a static, read-only viewer: it does not run Python models, accept uploads, or connect to a live API. The full real-data pipeline requires external source data that is not included here.

The reference dashboard currently includes:

- Hazard, site, hospital, demand-point, and site-status data for the Kahramanmaraş case.
- Risk-blind and risk-aware deterministic MILP results.
- Paper LP results for all prepared candidates and the TOPSIS top-120 shortlist.
- All-candidates SAA results and one detailed policy export.
- An optional SQLite catalog generated from the CSV snapshot.

The TOPSIS-screened SAA profile is incomplete and therefore remains unavailable in the dashboard. See [current pipeline and result status](docs/CURRENT_PIPELINE.md) for methods, data coverage, and reproduction steps.

The landing **Compare plans** view puts risk-blind MILP, risk-aware MILP, and the available 25-site SAA policy side by side. It distinguishes the 38/803 all-site PGA exceedances from the 34 eligible TMC candidates removed by the 0.2 g screen, and documents why model totals and selected-site counts differ. See the dashboard interpretation notes in [current pipeline](docs/CURRENT_PIPELINE.md) before comparing model outcomes.

## Run the dashboard locally

Node.js 20 is used by the Pages workflow. The committed static JSON bundle is sufficient to start the dashboard:

```bash
cd frontend
npm ci
npm run dev
```

For a production build:

```bash
npm run build
```

The map uses OpenStreetMap tiles and needs an internet connection. The frontend does not require a map API key.

If you replace or add files under `examples/reference_results/`, rebuild the browser JSON bundle from the repository root:

```bash
python -m pip install "pandas>=2.0,<3.0"
python scripts/build_pages_data.py
```

The primary research repo exports CSVs separately under `dashboard_data/`; this showcase does not consume that folder automatically. When bringing in a new research run, reconcile the selected outputs into `examples/reference_results/`, check profile availability and the documented metric definitions, then rebuild the JSON bundle above.

The GitHub Actions workflow performs this export and runs the frontend build before publishing `frontend/dist/` to Pages. The workflow deploys when frontend files, reference data, the exporter, or the workflow itself change.

## Run the synthetic solver example

Python 3.10+ is recommended. This example is intentionally small and synthetic; it is not the real Kahramanmaraş study run.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-demo.txt
python examples/run_solver_demo.py
```

Generated example outputs are written under `examples/model_outputs/`.

## Run the full research pipeline

The extraction, PSAHA, deterministic, Paper LP, and SAA code is under `pipelines/`. Running the real case requires the external and curated data listed in [full pipeline inputs](docs/full-pipeline-inputs.md), credentials for providers that require them, and the dependencies in `requirements.txt`. The detailed stage order and model approaches are documented in [current pipeline](docs/CURRENT_PIPELINE.md).

The main stages are:

1. Extract and validate earthquake, site, terrain, road, soil, damage, hospital, sub-district, and casualty data.
2. Fit aftershock occurrence and magnitude models, estimate ground motion, and calculate site hazard.
3. Prepare and solve the risk-blind and risk-aware deterministic facility-location models.
4. Optionally calculate the separate AHP/TOPSIS advisory ranking.
5. Run the scenario-wise Paper LP and/or two-stage SAA models.
6. Export the completed results to `dashboard_data/`, then rebuild the frontend JSON if publishing a new reference run.

Do not commit API credentials. The extraction config reads the OpenTopography credential from `OPENTOPO_API_KEY` in the environment.

## Optional local SQLite catalog

This catalog is a queryable projection of the curated CSV snapshot. CSV remains the source of truth; the database is local, disposable, and ignored by Git. It is not used by the browser dashboard or by the full research solvers.

```bash
python scripts/init_db.py --dry-run
python scripts/init_db.py
```

The database is written to `data_etl/earthquake_response.db`. Rows are stored as JSON in `data_rows`, with source paths and SHA-256 digests in `datasets`.

See [data access](docs/data-access.md) for details.

## Scope and reuse

This is a research visualization and reproducibility aid, not an operational dispatch system or emergency-services recommendation. Results depend on source coverage, capacity data, modeled hazard, casualty scenarios, and explicit model assumptions. Review [data provenance](docs/data-provenance.md) and the [component design](docs/01-component-level-design.md) before interpreting or reusing the outputs.

The repository currently has no software license. Public visibility permits inspection but does not grant reuse rights.
