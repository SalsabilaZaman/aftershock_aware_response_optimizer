"""Build the local SQLite projection of examples/reference_results/*.csv."""
from pipelines.data_access.db_access import initialize
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
initialize(dry_run=args.dry_run)
