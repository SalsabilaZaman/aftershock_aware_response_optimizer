"""SQLite projection of the curated reference-result CSV bundle."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data_etl" / "earthquake_response.db"
SOURCE_ROOT = ROOT / "examples" / "reference_results"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS data_rows (
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    row_json TEXT NOT NULL,
    PRIMARY KEY (dataset_id, row_number)
);
CREATE TABLE IF NOT EXISTS data_migration (
    migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    file_count INTEGER NOT NULL,
    row_count INTEGER NOT NULL
);
"""


def initialize(db_path: Path = DB_PATH, dry_run: bool = False) -> tuple[int, int]:
    files = sorted(SOURCE_ROOT.rglob("*.csv"))
    total_rows = 0
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            count = sum(1 for _ in csv.DictReader(stream))
        total_rows += count
        print(f"{path.relative_to(ROOT).as_posix()}: {count} rows")
    if dry_run:
        print("Dry run: no database written.")
        return len(files), total_rows

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            dataset_id = path.relative_to(SOURCE_ROOT).with_suffix("").as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with path.open(newline="", encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
            conn.execute(
                "INSERT INTO datasets(dataset_id, source_path, row_count, sha256) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(dataset_id) DO UPDATE SET "
                "source_path=excluded.source_path, row_count=excluded.row_count, "
                "sha256=excluded.sha256, loaded_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')",
                (dataset_id, rel, len(rows), digest),
            )
            conn.execute("DELETE FROM data_rows WHERE dataset_id = ?", (dataset_id,))
            conn.executemany(
                "INSERT INTO data_rows(dataset_id, row_number, row_json) VALUES (?, ?, ?)",
                ((dataset_id, i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(rows)),
            )
        conn.execute("INSERT INTO data_migration(file_count, row_count) VALUES (?, ?)",
                     (len(files), total_rows))
    print(f"Loaded {len(files)} CSV files / {total_rows} rows into {db_path.relative_to(ROOT)}")
    return len(files), total_rows


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    initialize(dry_run=args.dry_run)
