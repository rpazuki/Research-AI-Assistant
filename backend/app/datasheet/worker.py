"""
app/datasheet/worker.py
-----------------------
Claims queued datasheet runs and drives them.

Runs share the ingestion worker process rather than getting their own
(plan §6.5): the per-host rate limits are only enforceable if one process owns
them. Two worker processes with independent buckets double real egress to NCBI,
Crossref and every publisher — which is how a polite client becomes a blocked IP.

Round 1 drives phase A only. Acquisition (S3) and extraction (round 2) hook in
here as further phases on the same claimed run.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.datasheet.acquisition_service import run_acquisition_phase
from app.datasheet.discovery_service import (
    append_log,
    resolve_run_cache_root,
    run_discovery_phase,
    utcnow,
)
from app.db.models import DatasheetRun
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def claim_next_run() -> uuid.UUID | None:
    """Atomically claim the oldest queued run.

    `FOR UPDATE SKIP LOCKED` so a second worker — or a restarted one racing the
    old process — cannot pick up the same run and run discovery twice.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(DatasheetRun)
                .where(DatasheetRun.status == "queued")
                .order_by(DatasheetRun.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            run = result.scalars().first()
            if run is None:
                return None
            run.status = "running"
            run.started_at = run.started_at or utcnow()
            run.progress_message = "Claimed by worker"
            run.log_tail = append_log(run.log_tail, "Claimed by worker")
            return run.id


async def is_cancel_requested(run_id: uuid.UUID) -> bool:
    async with AsyncSessionLocal() as session:
        run = await session.get(DatasheetRun, run_id)
        return bool(run and run.status == "cancel_requested")


async def run_datasheet_job(run_id: uuid.UUID) -> None:
    """Drive one run through the phases enabled for this round."""
    async with AsyncSessionLocal() as session:
        run = await session.get(DatasheetRun, run_id)
        if run is None:
            return

        try:
            await run_discovery_phase(
                session,
                run,
                is_cancelled=lambda: False,  # checked between phases, not mid-search
            )
        except Exception as exc:  # noqa: BLE001 - a failed run must not kill the worker
            logger.exception("datasheet run %s failed during discovery", run_id)
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = utcnow()
            run.progress_message = "Discovery failed"
            run.log_tail = append_log(run.log_tail, f"Discovery failed: {exc}")
            await session.commit()
            return

        if await is_cancel_requested(run_id):
            run.status = "cancelled"
            run.finished_at = utcnow()
            run.progress_message = "Cancelled after discovery"
            run.log_tail = append_log(run.log_tail, "Cancelled after discovery")
            await session.commit()
            return

        # ── Phase B: acquisition ─────────────────────────────────────────────
        try:
            run.phase = "acquisition"
            run.progress_message = "Acquiring full text"
            run.log_tail = append_log(run.log_tail, "Acquisition started")
            await session.commit()

            cache_root = resolve_run_cache_root(run)
            summary = await run_acquisition_phase(
                session,
                run,
                cache_root=cache_root,
                is_cancelled=lambda: is_cancel_requested(run_id),
            )
        except Exception as exc:  # noqa: BLE001 - a failed run must not kill the worker
            logger.exception("datasheet run %s failed during acquisition", run_id)
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = utcnow()
            run.progress_message = "Acquisition failed"
            run.log_tail = append_log(run.log_tail, f"Acquisition failed: {exc}")
            await session.commit()
            return

        run.acquired_count = summary["fetched"]
        run.config_snapshot = {**(run.config_snapshot or {}), "acquisition_result": summary}
        run.log_tail = append_log(
            run.log_tail,
            f"Acquisition complete: {summary['fetched']} fetched "
            f"({summary['from_cache']} from cache), {summary['assisted_pending']} need assisted "
            f"acquisition, {summary['failed']} failed",
        )
        blocked_hosts = [
            tally["host"] for tally in summary["host_tallies"] if tally.get("circuit_open")
        ]
        if blocked_hosts:
            run.log_tail = append_log(
                run.log_tail,
                "Circuit opened for: " + ", ".join(blocked_hosts) + " — their papers went to assisted",
            )

        if await is_cancel_requested(run_id):
            run.status = "cancelled"
            run.finished_at = utcnow()
            run.progress_message = "Cancelled during acquisition"
            await session.commit()
            return

        # Round 1 ends here: extraction is round 2. Reported as succeeded, not left
        # 'running', so the run list is honest about a round without extraction.
        run.status = "succeeded"
        run.finished_at = utcnow()
        run.progress_message = (
            f"Complete: {summary['fetched']} full texts, "
            f"{summary['assisted_pending']} awaiting assisted acquisition"
        )
        run.log_tail = append_log(
            run.log_tail, "Run complete (extraction is round 2 and is not enabled)"
        )
        await session.commit()


async def poll_once() -> bool:
    """Claim and drive one run. Returns whether anything was found to do."""
    run_id = await claim_next_run()
    if run_id is None:
        return False
    logger.info("datasheet run %s claimed", run_id)
    await run_datasheet_job(run_id)
    return True


async def worker_loop(poll_interval_s: float = 5.0) -> None:
    """Standalone loop, for running datasheet runs without the ingestion worker."""
    logger.info("Datasheet worker started")
    while True:
        if not await poll_once():
            await asyncio.sleep(poll_interval_s)
