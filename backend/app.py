"""Run-scoped API for AARO's static React dashboard and research pipeline."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = Path(os.environ.get("AARO_RUNS_DIR", ROOT / "backend_data" / "runs")).resolve()
PIPELINE_PYTHON = os.environ.get("PIPELINE_PYTHON", sys.executable)
MAX_UPLOAD_BYTES = int(os.environ.get("AARO_MAX_UPLOAD_BYTES", 250 * 1024 * 1024))
MAX_UNPACKED_BYTES = int(os.environ.get("AARO_MAX_UNPACKED_BYTES", 2 * 1024 * 1024 * 1024))
MAX_ARCHIVE_FILES = int(os.environ.get("AARO_MAX_ARCHIVE_FILES", 20000))
MAX_ACTIVE_RUNS = int(os.environ.get("AARO_MAX_ACTIVE_RUNS", 1))
RUNS_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_COLUMNS = {
    "data_processed/seismic/aftershock_catalog.csv": {"time_utc", "latitude", "longitude", "magnitude"},
    "data_processed/sites/candidate_sites.csv": {"site_id", "latitude", "longitude", "facility_type"},
    "data_processed/sites/site_condition_per_site.csv": {"site_id", "vs30_ms"},
    "data_processed/sites/site_area_per_site.csv": {"site_id", "site_area_m2"},
    "data_processed/casualties/sub_districts_raw.csv": {"sub_district_id", "name", "population"},
    "data_processed/casualties/casualty_projections.csv": {
        "sub_district_id", "scenario_id", "period", "T1_count", "T2_count", "T3_count"},
    "data_processed/hospitals/hospital_data.csv": {
        "hospital_id", "hospital_name", "latitude", "longitude", "bed_capacity_total"},
}

app = FastAPI(title="AARO Research Pipeline API", version="1.0.0")
origins = [value.strip() for value in os.environ.get("AARO_ALLOWED_ORIGINS", "*").split(",") if value.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                   allow_headers=["*"])
_threads: dict[str, threading.Thread] = {}
_start_lock = threading.Lock()


def _job_dir(run_id: str) -> Path:
    if not run_id or any(ch not in "0123456789abcdef" for ch in run_id.lower()):
        raise HTTPException(400, detail="Invalid run id")
    directory = (RUNS_DIR / run_id).resolve()
    if RUNS_DIR not in directory.parents:
        raise HTTPException(400, detail="Invalid run id")
    if not directory.is_dir():
        raise HTTPException(404, detail="Run not found")
    return directory


def _status(job_dir: Path) -> dict:
    path = job_dir / "status.json"
    if not path.is_file():
        return {"state": "queued", "stages": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "error", "stages": [], "error": "Could not read run status"}


def _validate_bundle(job_dir: Path) -> list[str]:
    problems = []
    for relative, required in REQUIRED_COLUMNS.items():
        path = job_dir / Path(relative)
        if not path.is_file():
            problems.append(f"Missing {relative}")
            continue
        try:
            columns = set(pd.read_csv(path, nrows=0).columns)
        except Exception as exc:
            problems.append(f"Could not read {relative}: {exc}")
            continue
        missing = sorted(required - columns)
        if missing:
            problems.append(f"{relative} is missing columns: {', '.join(missing)}")
    return problems


def _extract_zip(upload: UploadFile, job_dir: Path) -> str:
    total = 0
    count = 0
    try:
        with zipfile.ZipFile(upload.file) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise HTTPException(413, detail=f"Archive has more than {MAX_ARCHIVE_FILES} entries")
            for info in infos:
                raw_name = info.filename.replace("\\", "/")
                member = PurePosixPath(raw_name)
                mode = (info.external_attr >> 16) & 0o170000
                windows_member = PureWindowsPath(info.filename)
                if (member.is_absolute() or windows_member.is_absolute() or windows_member.drive
                        or ":" in raw_name or ".." in member.parts or mode == 0o120000
                        or mode not in (0, 0o100000, 0o040000)):
                    raise HTTPException(400, detail=f"Unsafe ZIP entry: {info.filename}")
                total += info.file_size
                if total > MAX_UNPACKED_BYTES:
                    raise HTTPException(413, detail="Uncompressed dataset exceeds the configured size limit")
                count += 1
            archive.extractall(job_dir)
    except zipfile.BadZipFile:
        raise HTTPException(400, detail="The uploaded file is not a valid ZIP archive")

    # Accept either data_processed/... or one enclosing directory containing it.
    if not (job_dir / "data_processed").is_dir():
        entries = list(job_dir.iterdir())
        wrappers = [entry for entry in entries if entry.is_dir() and (entry / "data_processed").is_dir()]
        if len(entries) == 1 and len(wrappers) == 1:
            wrapper = wrappers[0]
            for child in wrapper.iterdir():
                shutil.move(str(child), str(job_dir / child.name))
            wrapper.rmdir()
    if not (job_dir / "data_processed").is_dir():
        raise HTTPException(400, detail="ZIP must contain a data_processed/ directory")
    return str(count)


def _run_pipeline(run_id: str) -> None:
    job_dir = _job_dir(run_id)
    command = [PIPELINE_PYTHON, str(ROOT / "pipelines" / "run_demo_job.py"), "--root", str(job_dir)]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        status = _status(job_dir)
        if result.returncode and status.get("state") != "error":
            status.update({"state": "error", "failed_stage": "pipeline", "error_tail": result.stderr[-6000:]})
            (job_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception as exc:
        status = _status(job_dir)
        status.update({"state": "error", "failed_stage": status.get("failed_stage", "pipeline"),
                       "error_tail": str(exc)})
        (job_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/runs")
def list_runs():
    runs = []
    for directory in RUNS_DIR.iterdir():
        if not directory.is_dir():
            continue
        metadata_path = directory / "run.json"
        metadata = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        status = _status(directory)
        runs.append({"run_id": directory.name, "name": metadata.get("name", directory.name),
                     "created_utc": metadata.get("created_utc"), "state": status.get("state", "queued")})
    runs.sort(key=lambda item: item.get("created_utc") or "", reverse=True)
    return {"runs": runs}


@app.post("/api/runs/upload", status_code=202)
async def upload_run(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, detail="Choose a .zip bundle")
    job_id = uuid.uuid4().hex
    job_dir = RUNS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    try:
        written = 0
        zip_path = job_dir / "upload.zip"
        with zip_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, detail="Upload exceeds the configured file-size limit")
                target.write(chunk)
        with zip_path.open("rb") as source:
            _extract_zip(UploadFile(filename="upload.zip", file=source), job_dir)
        zip_path.unlink(missing_ok=True)
        problems = _validate_bundle(job_dir)
        if problems:
            raise HTTPException(422, detail={"message": "Dataset bundle did not pass validation", "issues": problems})
        metadata = {"run_id": job_id, "name": Path(file.filename).name, "created_utc": pd.Timestamp.now(tz="UTC").isoformat()}
        (job_dir / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        with _start_lock:
            active = sum(thread.is_alive() for thread in _threads.values())
            if active >= MAX_ACTIVE_RUNS:
                raise HTTPException(429, detail="The pipeline is busy. Try again after the active run finishes.")
            thread = threading.Thread(target=_run_pipeline, args=(job_id,), daemon=True)
            _threads[job_id] = thread
            thread.start()
        return {"run_id": job_id, "name": metadata["name"], "state": "running"}
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        await file.close()


@app.get("/api/runs/{run_id}/status")
def run_status(run_id: str):
    status = _status(_job_dir(run_id))
    status.pop("root", None)
    return status


@app.get("/api/{relative_path:path}")
def run_data(relative_path: str, run_id: str | None = None):
    if not run_id:
        raise HTTPException(400, detail="run_id is required for uploaded-run data")
    job_dir = _job_dir(run_id)
    if _status(job_dir).get("state") != "done":
        raise HTTPException(409, detail="Run results are not ready")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(400, detail="Invalid result path")
    api_dir = (job_dir / "api_data").resolve()
    target = (api_dir / Path(*relative.parts)).resolve()
    if api_dir not in target.parents or not target.is_file():
        raise HTTPException(404, detail="Result is unavailable for this run")
    if target.name == "scenarios.json":
        value = json.loads(target.read_text(encoding="utf-8"))
        value["data_source"] = {"kind": "job", "job_id": run_id}
        return JSONResponse(value)
    return FileResponse(target, media_type="application/json")
