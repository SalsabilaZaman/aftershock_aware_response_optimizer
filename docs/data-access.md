# SQLite data catalog

This repository publishes a curated reference snapshot, rather than the complete pipeline input/output tree available in the research workspace. The local SQLite catalog therefore stores each CSV row as JSON to preserve the snapshot's varied columns without changing its contents.

- Source of truth: `examples/reference_results/**/*.csv`
- Generated database: `data_etl/earthquake_response.db` (git-ignored)
- Catalog: `datasets` tracks source path, row count, and SHA-256; `data_rows` stores the original CSV fields as JSON.
- Rebuild: `python scripts/init_db.py`; preview: `python scripts/init_db.py --dry-run`.
- Python dependencies: standard library only (`sqlite3`, `csv`, `hashlib`, `json`).

Dataset IDs are paths relative to `examples/reference_results`, without the `.csv` suffix (for example `risk_aware/tmc_selected`). A rebuild is idempotent: each CSV's previous row set is replaced in one transaction, then a migration summary is recorded. This catalog supports queries over the published snapshot; it does not replace the full data preparation pipeline or create a live service.
