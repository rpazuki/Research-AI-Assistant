"""Database-backed ingestion worker.

Run with:
    python -m app.ingestion.worker
"""

from __future__ import annotations

import asyncio
import logging
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.models import IngestionJob
from app.db.session import AsyncSessionLocal
from app.ingestion.admin_service import JOB_WORK_ROOT, _REPO_ROOT, write_worker_heartbeat

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.indexing.build_index import build_index  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class IngestionCancelled(Exception):
    """Raised when a running job observes a cancellation request."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def append_log(existing: str | None, message: str, limit: int = 12000) -> str:
    line = f"{utcnow().isoformat()} {message}"
    combined = f"{existing}\n{line}" if existing else line
    return combined[-limit:]


def format_toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(format_toml_value(item) for item in value) + "]"
    if value is None:
        return '""'
    raise TypeError(f"Unsupported TOML value type: {type(value).__name__}")


def dump_toml_sections(config: dict[str, Any]) -> str:
    lines: list[str] = []
    for section_name, section in config.items():
        if not isinstance(section, dict):
            continue
        if lines:
            lines.append("")
        lines.append(f"[{section_name}]")
        for key, value in section.items():
            if isinstance(value, dict):
                continue
            lines.append(f"{key} = {format_toml_value(value)}")
    lines.append("")
    return "\n".join(lines)


async def claim_next_job() -> uuid.UUID | None:
    write_worker_heartbeat(state="polling")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(IngestionJob)
                .where(IngestionJob.status == "queued")
                .order_by(IngestionJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None
            job.status = "running"
            job.started_at = utcnow()
            job.progress_message = "Worker started"
            job.log_tail = append_log(job.log_tail, "Worker started")
            write_worker_heartbeat(state="running", job_id=job.id)
            return job.id


async def update_job_progress(
    job_id: uuid.UUID,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    write_worker_heartbeat(state="running", job_id=job_id)
    cancelled = False
    async with AsyncSessionLocal() as session:
        async with session.begin():
            job = await session.get(IngestionJob, job_id)
            if job is None:
                return
            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.finished_at = utcnow()
                job.progress_message = "Cancelled"
                job.log_tail = append_log(job.log_tail, "Cancellation observed")
                cancelled = True
            else:
                job.progress_message = message
                job.log_tail = append_log(job.log_tail, f"{message} {payload or {}}")
                if payload:
                    if "manifest_id" in payload and payload["manifest_id"]:
                        job.manifest_id = uuid.UUID(str(payload["manifest_id"]))
                    if "document_count" in payload:
                        job.document_count = int(payload["document_count"])
                    if "chunk_count" in payload:
                        job.chunk_count = int(payload["chunk_count"])
                    if "cache_path" in payload and payload["cache_path"]:
                        job.cache_path = str(payload["cache_path"])
    if cancelled:
        raise IngestionCancelled()


def write_job_config(job: IngestionJob) -> Path:
    job_dir = JOB_WORK_ROOT / str(job.id)
    job_dir.mkdir(parents=True, exist_ok=True)
    config_path = job_dir / "corpus.toml"
    config_path.write_text(dump_toml_sections(job.config_snapshot or {}))
    return config_path


async def maintain_running_heartbeat(job_id: uuid.UUID, interval_s: float = 30.0) -> None:
    """Refresh the worker heartbeat while long indexing phases are in progress."""
    try:
        while True:
            write_worker_heartbeat(state="running", job_id=job_id)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        write_worker_heartbeat(state="running", job_id=job_id)
        raise


async def run_job(job_id: uuid.UUID) -> None:
    write_worker_heartbeat(state="running", job_id=job_id)
    async with AsyncSessionLocal() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            return
        config_path = write_job_config(job)
        mode = job.mode
        from_date = job.from_date if mode == "incremental" else None
        year = job.year if mode == "test_year" else None
        local_only = mode in {"local_only", "queue_only"}
        options = job.options or {}
        cache_path = job.cache_path

    heartbeat_task = asyncio.create_task(maintain_running_heartbeat(job_id))
    try:
        result = await build_index(
            str(config_path),
            from_date=from_date,
            year=year,
            cache_path=cache_path,
            use_cache=True,
            local_only=local_only,
            write_queue=bool(options.get("write_acquisition_queue")),
            include_cached_fulltext=bool(options.get("include_cached_fulltext")),
            progress_callback=lambda message, payload: update_job_progress(job_id, message, payload),
        )
    except IngestionCancelled:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        write_worker_heartbeat(state="idle")
        logger.info("Ingestion job %s cancelled", job_id)
        return
    except Exception as exc:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        logger.exception("Ingestion job %s failed", job_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                job = await session.get(IngestionJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.finished_at = utcnow()
                    job.error = str(exc)
                    job.progress_message = "Failed"
                    job.log_tail = append_log(job.log_tail, f"Failed: {exc}")
        write_worker_heartbeat(state="idle")
        return

    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    async with AsyncSessionLocal() as session:
        async with session.begin():
            job = await session.get(IngestionJob, job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.finished_at = utcnow()
            job.progress_message = "Succeeded"
            job.manifest_id = uuid.UUID(str(result["manifest_id"]))
            job.document_count = int(result["document_count"])
            job.chunk_count = int(result["chunk_count"])
            if result.get("cache_path"):
                job.cache_path = str(result["cache_path"])
            job.log_tail = append_log(job.log_tail, "Succeeded")
    write_worker_heartbeat(state="idle")


async def worker_loop(poll_interval_s: float = 5.0) -> None:
    logger.info("Ingestion worker started")
    write_worker_heartbeat(state="started")
    while True:
        job_id = await claim_next_job()
        if job_id is None:
            await asyncio.sleep(poll_interval_s)
            continue
        await run_job(job_id)


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
