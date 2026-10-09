import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, UploadFile

from backend import app as api


class DatasetBundleTests(unittest.TestCase):
    def test_required_prepared_files_and_headers_are_accepted(self):
        with tempfile.TemporaryDirectory(dir=api.RUNS_DIR) as temp:
            root = Path(temp)
            for relative, columns in api.REQUIRED_COLUMNS.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                pd.DataFrame(columns=sorted(columns)).to_csv(path, index=False)
            self.assertEqual(api._validate_bundle(root), [])

    def test_missing_file_and_required_column_are_reported(self):
        with tempfile.TemporaryDirectory(dir=api.RUNS_DIR) as temp:
            root = Path(temp)
            relative = "data_processed/seismic/aftershock_catalog.csv"
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text("time_utc,latitude\n", encoding="utf-8")
            issues = api._validate_bundle(root)
            self.assertTrue(any("longitude" in issue and "magnitude" in issue for issue in issues))
            self.assertTrue(any("candidate_sites.csv" in issue for issue in issues))

    def test_zip_path_traversal_is_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("../outside.csv", "bad")
        data.seek(0)
        with tempfile.TemporaryDirectory(dir=api.RUNS_DIR) as temp:
            upload = UploadFile(file=data, filename="dataset.zip")
            with self.assertRaises(HTTPException) as raised:
                api._extract_zip(upload, Path(temp))
            self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
