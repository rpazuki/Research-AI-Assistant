"""
app/datasheet/worker.py
-----------------------
Claims queued datasheet runs and drives them.

Runs share the ingestion worker process rather than getting their own
(plan §6.5): the per-host rate limits are only enforceable if one process owns
them. Two worker processes with independent buckets double real egress to NCBI,
Crossref and every publisher — which is how a polite client becomes a blocked IP.

Phases, in order: discovery (A), acquisition (B), extraction (D), export (E).
Extraction is dry-run by default — it reports what a real pass would cost and
stops. See `app/datasheet/extractor.py` for why that is the default rather than an
option.

**A batch is waited on by parking, not by sleeping.** Because one process serves
both queues, a job that sat inside the poll loop for the 1–24 hours an extraction
batch can take would block every ingestion job an admin is watching. So a run with
a submitted batch is set to `awaiting_batch` and the worker returns; it re-claims
the run when the poll interval has elapsed and collects then. The batch id lives on
the run, so a restart resumes instead of orphaning a paid batch.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, select

from app.core.config import settings
from app.datasheet.acquisition_service import run_acquisition_phase
from app.datasheet.discovery_service import (
    append_log,
    resolve_run_cache_root,
    run_discovery_phase,
    utcnow,
)
from app.datasheet.export_service import run_export_phase
from app.datasheet.extractor import (
    ExtractionSummary,
    cancel_extraction_batch,
    collect_extraction_batch,
    extraction_provider,
    run_extraction_phase,
)
from app.db.models import DatasheetRun
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# A run records where it meant to stop. Round-1 runs were created with
# `stop_after_phase='ingestion'` — before extraction existed — so those rows must
# still finish after acquisition rather than being swept into a phase they were
# never queued for. New runs default to 'export' and go the whole way.
STOP_BEFORE_EXTRACTION = {"discovery", "acquisition", "ingestion"}


def _phase_reporter(session, run: DatasheetRun):
    """A progress sink that writes each line to the run the admin is watching.

    Extraction can spend an hour inside one batch. Without this the run page shows
    a single unchanging message for that whole time, which looks exactly like a
    hung worker — and the first thing anyone does about a hung worker is restart
    it, in the middle of a paid batch.
    """

    async def report(message: str, _payload: dict | None = None) -> None:
        run.progress_message = message
        run.log_tail = append_log(run.log_tail, message)
        await session.commit()

    return report


async def claim_next_run() -> uuid.UUID | None:
    """Atomically claim the oldest run that has work to do.

    Two kinds qualify: a `queued` run, and an `awaiting_batch` run whose batch is
    due another poll. The `extraction_batch_polled_at` predicate is what stops the
    worker re-claiming the same parked run on every loop and hammering the batch
    endpoint.

    `FOR UPDATE SKIP LOCKED` so a second worker — or a restarted one racing the
    old process — cannot pick up the same run and run discovery twice.
    """
    cutoff = utcnow() - timedelta(seconds=max(1, settings.datasheet_batch_poll_interval_s))
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(DatasheetRun)
                .where(
                    or_(
                        DatasheetRun.status == "queued",
                        and_(
                            DatasheetRun.status == "awaiting_batch",
                            or_(
                                DatasheetRun.extraction_batch_polled_at.is_(None),
                                DatasheetRun.extraction_batch_polled_at < cutoff,
                            ),
                        ),
                    )
                )
                .order_by(DatasheetRun.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            run = result.scalars().first()
            if run is None:
                return None
            if run.status == "awaiting_batch":
                # Deliberately left parked rather than flipped to 'running': a crash
                # during collection must leave the run re-claimable, and 'running'
                # would strand it with a live batch nobody comes back for. Stamping
                # the poll time here is what enforces the throttle.
                run.extraction_batch_polled_at = utcnow()
                return run.id
            run.status = "running"
            run.started_at = run.started_at or utcnow()
            run.progress_message = "Claimed by worker"
            run.log_tail = append_log(run.log_tail, "Claimed by worker")
            return run.id


async def is_cancel_requested(run_id: uuid.UUID) -> bool:
    async with AsyncSessionLocal() as session:
        run = await session.get(DatasheetRun, run_id)
        return bool(run and run.status == "cancel_requested")


async def run_datasheet_job(run_id: uuid.UUID) -> bool:
    """Drive one run as far as it can go now.

    Returns whether anything actually progressed. A parked run whose batch is still
    processing returns False so the caller sleeps instead of spinning on it.
    """
    async with AsyncSessionLocal() as session:
        run = await session.get(DatasheetRun, run_id)
        if run is None:
            return False

        # A parked run: the batch is with the provider, so the only work here is to
        # collect it — never to re-run discovery or acquisition.
        if run.extraction_batch_id:
            return await _collect_batch(session, run, run_id)

        # A re-extraction: queued at phase D on purpose, so A and B are not
        # repeated. A normal queued run has phase = NULL, which keeps the two cases
        # distinct without a second column.
        if run.phase == "extraction":
            run.log_tail = append_log(run.log_tail, "Re-extracting: starting at phase D")
            await session.commit()
            return await _extract_and_finish(session, run, run_id, resolve_run_cache_root(run))

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
            return True

        if await is_cancel_requested(run_id):
            run.status = "cancelled"
            run.finished_at = utcnow()
            run.progress_message = "Cancelled after discovery"
            run.log_tail = append_log(run.log_tail, "Cancelled after discovery")
            await session.commit()
            return True

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
            return True

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
            return True

        if run.stop_after_phase in STOP_BEFORE_EXTRACTION:
            run.status = "succeeded"
            run.finished_at = utcnow()
            run.progress_message = (
                f"Complete: {summary['fetched']} full texts, "
                f"{summary['assisted_pending']} awaiting assisted acquisition"
            )
            run.log_tail = append_log(run.log_tail, "Run complete (stopped after acquisition)")
            await session.commit()
            return True

        return await _extract_and_finish(session, run, run_id, cache_root)


async def _extract_and_finish(
    session, run: DatasheetRun, run_id: uuid.UUID, cache_root
) -> bool:
    """Phase D, then either park on the batch, stop at the projection, or export.

    Always runs, but defaults to a dry run: it resolves candidates, counts tokens
    and reports projected cost without sending anything. A live pass additionally
    requires settings.datasheet_extraction_enabled — the standing owner decision
    about sending paper text off-site.
    """
    try:
        run.phase = "extraction"
        run.progress_message = "Extracting datasheet rows"
        await session.commit()

        extraction = await run_extraction_phase(
            session,
            run,
            cache_root=cache_root,
            provider=extraction_provider(),
            dry_run=not settings.datasheet_extraction_enabled,
            is_cancelled=lambda: is_cancel_requested(run_id),
            progress=_phase_reporter(session, run),
        )
    except Exception as exc:  # noqa: BLE001 - a failed run must not kill the worker
        logger.exception("datasheet run %s failed during extraction", run_id)
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = utcnow()
        run.progress_message = "Extraction failed"
        run.log_tail = append_log(run.log_tail, f"Extraction failed: {exc}")
        await session.commit()
        return True

    _record_extraction(run, extraction)

    if extraction.awaiting_batch:
        # Parked, not finished. The run is picked up again when the batch is due a
        # poll; until then this process is free to serve the ingestion queue.
        run.status = "awaiting_batch"
        run.progress_message = (
            f"Waiting on extraction batch {extraction.batch_id} "
            f"({extraction.plan.get('to_extract', 0)} papers)"
        )
        run.log_tail = append_log(
            run.log_tail,
            f"Extraction batch {extraction.batch_id} submitted; run parked until it ends",
        )
        await session.commit()
        return True

    if extraction.dry_run:
        plan = extraction.plan
        run.status = "succeeded"
        run.phase = "extraction"
        run.finished_at = utcnow()
        run.progress_message = (
            f"Dry run: {plan['papers']} papers ready to extract, "
            f"~${plan['projected_cost_usd']:.2f} projected"
        )
        run.log_tail = append_log(
            run.log_tail,
            f"Extraction dry run: {plan['papers']} papers, ~{plan['input_tokens']} input "
            f"tokens ({plan['token_method']}), ~${plan['projected_cost_usd']:.2f} on "
            f"{plan['model']}. Extraction is disabled — set DATASHEET_EXTRACTION_ENABLED "
            "to run it for real.",
        )
        await session.commit()
        return True

    run.log_tail = append_log(run.log_tail, _extraction_log_line(extraction))
    await session.commit()
    return await _export_and_finish(session, run, extraction, run_id, cache_root)


async def _collect_batch(session, run: DatasheetRun, run_id: uuid.UUID) -> bool:
    """Poll a parked run's batch once: park again, cancel, or finish the run."""
    provider = extraction_provider()
    if provider is None:
        # Parking forever would hide a paid batch nobody will ever read. Failing
        # says which batch is outstanding.
        logger.error("run %s is waiting on a batch but no provider is configured", run_id)
        run.status = "failed"
        run.error = (
            "No LLM provider configured, so extraction batch "
            f"{run.extraction_batch_id} cannot be collected."
        )
        run.finished_at = utcnow()
        run.progress_message = "Cannot collect the extraction batch"
        run.log_tail = append_log(run.log_tail, run.error)
        await session.commit()
        return True

    if await is_cancel_requested(run_id):
        cancelled = await cancel_extraction_batch(provider, run)
        run.status = "cancelled"
        run.finished_at = utcnow()
        run.progress_message = "Cancelled while waiting on the extraction batch"
        run.log_tail = append_log(
            run.log_tail,
            f"Extraction batch {run.extraction_batch_id} cancel requested — requests already "
            "in flight still complete and are still billed"
            if cancelled
            else f"Extraction batch {run.extraction_batch_id} could not be cancelled; it will "
            "run to completion and be billed",
        )
        await session.commit()
        return True

    try:
        extraction = await collect_extraction_batch(
            session,
            run,
            cache_root=resolve_run_cache_root(run),
            provider=provider,
            progress=_phase_reporter(session, run),
        )
    except Exception as exc:  # noqa: BLE001 - a failed run must not kill the worker
        logger.exception("datasheet run %s failed collecting its extraction batch", run_id)
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = utcnow()
        run.progress_message = "Collecting the extraction batch failed"
        run.log_tail = append_log(run.log_tail, f"Batch collection failed: {exc}")
        await session.commit()
        return True

    if extraction.awaiting_batch:
        run.status = "awaiting_batch"
        await session.commit()
        # Nothing progressed. Reported as "no work" so the loop sleeps rather than
        # re-claiming this run immediately — the throttle in claim_next_run is the
        # other half of the same guard.
        return False

    run.status = "running"
    _record_extraction(run, extraction)
    run.log_tail = append_log(run.log_tail, _extraction_log_line(extraction))
    await session.commit()
    return await _export_and_finish(
        session, run, extraction, run_id, resolve_run_cache_root(run)
    )


async def _export_and_finish(
    session, run: DatasheetRun, extraction: ExtractionSummary, run_id: uuid.UUID, cache_root
) -> bool:
    """Phase E. A run's deliverable is the datasheet, so the run is not complete
    until that file exists on disk beside the assets it came from. Writing it here
    rather than only on download also means `csv_path` points at something."""
    try:
        run.phase = "export"
        run.progress_message = "Writing the datasheet"
        await session.commit()

        export = await run_export_phase(
            session, run, cache_root=cache_root, progress=_phase_reporter(session, run)
        )
    except Exception as exc:  # noqa: BLE001 - a failed run must not kill the worker
        # The rows are already committed, so this loses a file and not work.
        logger.exception("datasheet run %s failed during export", run_id)
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = utcnow()
        run.progress_message = "Export failed"
        run.log_tail = append_log(
            run.log_tail,
            f"Export failed: {exc}. The rows are extracted and still downloadable from the "
            "run page.",
        )
        await session.commit()
        return True

    run.config_snapshot = {**(run.config_snapshot or {}), "export_result": export}
    run.status = "succeeded"
    run.finished_at = utcnow()
    run.progress_message = (
        f"Complete: {extraction.extracted} datasheet rows"
        + (f", written to {export['csv_path']}" if export.get("csv_path") else "")
    )
    run.log_tail = append_log(
        run.log_tail,
        f"Export complete: {export['rows']} rows"
        + (f" -> {export['csv_path']}" if export.get("csv_path") else " (nothing to write)"),
    )
    await session.commit()
    return True


def _record_extraction(run: DatasheetRun, extraction: ExtractionSummary) -> None:
    """Counters come from observed usage, never from the projection."""
    run.config_snapshot = {
        **(run.config_snapshot or {}),
        "extraction_result": extraction.as_dict(),
    }
    run.extracted_count = extraction.extracted
    run.prompt_tokens = extraction.prompt_tokens
    run.completion_tokens = extraction.completion_tokens
    run.cached_tokens = extraction.cached_tokens


def _extraction_log_line(extraction: ExtractionSummary) -> str:
    return (
        f"Extraction complete: {extraction.extracted} rows, {extraction.escalated} escalated"
        + (
            f" ({extraction.escalation_skipped} over the escalation cap)"
            if extraction.escalation_skipped
            else ""
        )
        + (f", {extraction.reused} reused from cache" if extraction.reused else "")
        + f", {extraction.refused} refused, {extraction.failed} failed "
        f"({extraction.prompt_tokens} prompt / {extraction.completion_tokens} completion / "
        f"{extraction.cached_tokens} cached tokens)"
    )


async def poll_once() -> bool:
    """Claim and drive one run. Returns whether anything was found to do."""
    run_id = await claim_next_run()
    if run_id is None:
        return False
    logger.info("datasheet run %s claimed", run_id)
    return await run_datasheet_job(run_id)


async def worker_loop(poll_interval_s: float = 5.0) -> None:
    """Standalone loop, for running datasheet runs without the ingestion worker."""
    logger.info("Datasheet worker started")
    while True:
        if not await poll_once():
            await asyncio.sleep(poll_interval_s)
