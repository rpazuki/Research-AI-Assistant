"""Helpers for exposing ingestion safely through admin APIs."""

from __future__ import annotations

import re
import sys
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.12 has tomllib
    import tomli as tomllib  # type: ignore

from fastapi import HTTPException, UploadFile, status

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

APP_DATA_DIR = _REPO_ROOT / "data"
APPROVED_CONFIG_DIR = _REPO_ROOT / "pipelines" / "configs"
INGESTION_DEFAULTS_PATH = APPROVED_CONFIG_DIR / "admin_ingestion_defaults.toml"
UPLOAD_ROOT = APP_DATA_DIR / "admin_uploads" / "pdf"
JOB_WORK_ROOT = APP_DATA_DIR / "ingestion_jobs"
WORKER_HEARTBEAT_PATH = JOB_WORK_ROOT / "worker_heartbeat.json"
ALLOWED_CACHE_ROOT = APP_DATA_DIR / "corpora"

SAFE_PATH_PART = re.compile(r"[^A-Za-z0-9._ -]+")


def load_toml(path: Path) -> dict[str, Any]:
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def write_worker_heartbeat(*, state: str, job_id: uuid.UUID | None = None) -> None:
    WORKER_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKER_HEARTBEAT_PATH.write_text(
        json.dumps(
            {
                "state": state,
                "job_id": str(job_id) if job_id else None,
                "updated_at": utcnow().isoformat(),
            },
            sort_keys=True,
        )
        + "\n"
    )


def get_worker_status(stale_after_seconds: int = 120) -> dict[str, Any]:
    if not WORKER_HEARTBEAT_PATH.exists():
        return {
            "active": False,
            "state": "not_seen",
            "job_id": None,
            "updated_at": None,
            "seconds_since_heartbeat": None,
            "message": "No ingestion worker heartbeat has been seen.",
        }

    try:
        payload = json.loads(WORKER_HEARTBEAT_PATH.read_text())
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
    except Exception:
        return {
            "active": False,
            "state": "invalid",
            "job_id": None,
            "updated_at": None,
            "seconds_since_heartbeat": None,
            "message": "The ingestion worker heartbeat file is unreadable.",
        }

    age = (utcnow() - updated_at.astimezone(timezone.utc)).total_seconds()
    active = age <= stale_after_seconds
    return {
        "active": active,
        "state": payload.get("state") or "unknown",
        "job_id": payload.get("job_id"),
        "updated_at": updated_at.isoformat(),
        "seconds_since_heartbeat": int(age),
        "message": "Worker heartbeat is current." if active else "Ingestion worker heartbeat is stale.",
    }


def list_approved_configs() -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    if not APPROVED_CONFIG_DIR.is_dir():
        return configs

    for path in sorted(APPROVED_CONFIG_DIR.glob("*.toml")):
        if path.name == INGESTION_DEFAULTS_PATH.name:
            continue
        cfg = load_toml(path)
        corpus = cfg.get("corpus", {})
        pubmed = cfg.get("pubmed", {})
        pdf = cfg.get("pdf", {})
        source = str(corpus.get("source", ""))
        configs.append(
            {
                "name": path.name,
                "path": str(path),
                "corpus_name": corpus.get("name", path.stem),
                "source": source,
                "embedding_model": corpus.get("embedding_model", "pubmedbert"),
                "year_from": pubmed.get("year_from"),
                "year_to": pubmed.get("year_to"),
                "pdf_dir": pdf.get("dir"),
                "supports_pdf_upload": source == "pdf",
            }
        )
    return configs


def load_ingestion_defaults() -> dict[str, Any]:
    defaults = {
        "config_name": "",
        "mode": "full",
        "cache_path": "",
        "write_acquisition_queue": False,
        "include_cached_fulltext": False,
    }
    if INGESTION_DEFAULTS_PATH.is_file():
        raw = load_toml(INGESTION_DEFAULTS_PATH).get("defaults", {})
        defaults.update({key: value for key, value in raw.items() if key in defaults})

    config_name = str(defaults.get("config_name") or "")
    if config_name:
        try:
            get_approved_config(config_name)
        except HTTPException:
            defaults["config_name"] = ""

    mode = str(defaults.get("mode") or "full")
    if mode not in {"full", "incremental", "test_year", "local_only", "queue_only"}:
        defaults["mode"] = "full"

    cache_path = str(defaults.get("cache_path") or "")
    if cache_path:
        validate_cache_path(cache_path)

    return defaults


def get_approved_config(config_name: str) -> tuple[Path, dict[str, Any]]:
    requested = Path(config_name).name
    config_path = (APPROVED_CONFIG_DIR / requested).resolve()
    config_dir = APPROVED_CONFIG_DIR.resolve()
    if config_path.parent != config_dir or not config_path.is_file() or config_path.suffix != ".toml":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown ingestion config",
        )
    return config_path, load_toml(config_path)


def validate_cache_path(cache_path: str | None) -> str | None:
    if not cache_path:
        return None
    path = Path(cache_path).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    resolved = path.resolve()
    allowed_root = ALLOWED_CACHE_ROOT.resolve()
    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cache path must live under data/corpora",
        )
    return str(resolved)


def safe_pdf_relative_path(filename: str) -> Path:
    parts = [part for part in filename.replace("\\", "/").split("/") if part not in {"", ".", ".."}]
    if not parts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file has no name")
    safe_parts = [SAFE_PATH_PART.sub("_", part).strip() for part in parts]
    safe_parts = [part or "unnamed" for part in safe_parts]
    path = Path(*safe_parts)
    if path.suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files can be uploaded for folder ingestion",
        )
    return path


async def save_pdf_upload_folder(files: list[UploadFile], *, batch_id: uuid.UUID) -> tuple[Path, int, int]:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload at least one PDF file",
        )

    destination_root = UPLOAD_ROOT / str(batch_id)
    destination_root.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    file_count = 0
    used_paths: set[Path] = set()

    for upload in files:
        relative_path = safe_pdf_relative_path(upload.filename or "document.pdf")
        destination = destination_root / relative_path
        if relative_path in used_paths or destination.exists():
            destination = destination.with_name(f"{destination.stem}-{file_count + 1}{destination.suffix}")
        used_paths.add(destination.relative_to(destination_root))
        destination.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        with open(destination, "wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                handle.write(chunk)
        if written == 0:
            destination.unlink(missing_ok=True)
            continue
        total_bytes += written
        file_count += 1

    if file_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No non-empty PDF files were uploaded",
        )
    return destination_root, file_count, total_bytes
