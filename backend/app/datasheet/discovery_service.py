"""
app/datasheet/discovery_service.py
----------------------------------
Run lifecycle and phase-A persistence for datasheet runs.

The search itself is `pipelines.discovery` (pure, no DB). This module owns the DB
half: creating a run from a resolved seed, driving discovery, writing
`datasheet_candidates`, and rendering the manifest CSV from the persisted rows
rather than from memory — so what a curator downloads is what the run actually
recorded.

Runs created before round 2 carry `stop_after_phase='ingestion'` and still stop
after acquisition; new runs go through to export. A run that never
extracts finishes as `succeeded` instead of looking like a failure.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.datasheet.admin_service import build_template_snapshot, get_template
from app.datasheet.extractor import cancel_extraction_batch, extraction_provider
from app.db.models import DatasheetCandidate, DatasheetRow, DatasheetRun

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.acquisition.cache_layout import manifest_csv_path  # noqa: E402
from pipelines.discovery.canonicalize import Candidate  # noqa: E402
from pipelines.discovery.discover import (  # noqa: E402
    ALL_SOURCES,
    DiscoveryCredentials,
    discover,
    included_candidates,
)
from pipelines.discovery.manifest_csv import write_manifest_csv  # noqa: E402
from pipelines.discovery.relevance import UNKNOWN  # noqa: E402
from pipelines.discovery.sources.base import SourceQuery  # noqa: E402

logger = logging.getLogger(__name__)

LOG_TAIL_LINES = 60
CANDIDATE_PAGE_SIZE = 200

# Where a run may be asked to stop. 'ingestion' is not offered: it exists only on
# round-1 rows created before extraction, and offering it now would queue runs into
# a phase that no longer has a distinct meaning.
STOPPABLE_PHASES = {"discovery", "acquisition", "export"}

# A run in one of these has not finished, so its rows and batch state are still
# being written. Re-extracting one would race the worker.
ACTIVE_STATUSES = {"queued", "running", "awaiting_batch", "cancel_requested"}


class DatasheetRunError(Exception):
    """A run could not be created or driven. Surfaces as 400/404, not 500."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def append_log(existing: str | None, message: str) -> str:
    lines = (existing or "").splitlines()
    lines.append(f"{utcnow().isoformat(timespec='seconds')} {message}")
    return "\n".join(lines[-LOG_TAIL_LINES:])


# ── Run CRUD ──────────────────────────────────────────────────────────────────


async def create_run(
    db: AsyncSession,
    *,
    name: str,
    seed_kind: str,
    organism_name: str | None,
    organism_taxid: int | None,
    organism_synonyms: list[str],
    product_term: str | None,
    product_ids: dict | None,
    product_synonyms: list[str],
    product_classes: list[str] | None,
    year_from: int | None,
    year_to: int | None,
    template_name: str,
    config: dict[str, Any],
    requested_by_user_id: uuid.UUID | None,
    stop_after_phase: str = "export",
) -> DatasheetRun:
    """Create a queued run with the template frozen onto it.

    The snapshot is what makes a run reproducible: editing the template later must
    not silently change what an old run meant.
    """
    if seed_kind not in {"organism", "bioproduct", "organism_and_product"}:
        raise DatasheetRunError(f"Unknown seed kind '{seed_kind}'")
    if not organism_synonyms and not product_synonyms:
        raise DatasheetRunError("A run needs at least one organism or product search term")
    if stop_after_phase not in STOPPABLE_PHASES:
        raise DatasheetRunError(
            f"Cannot stop after '{stop_after_phase}'; choose one of {sorted(STOPPABLE_PHASES)}"
        )

    template = await get_template(db, template_name)
    if template is None:
        raise DatasheetRunError(f"Template '{template_name}' not found")

    run = DatasheetRun(
        name=name,
        requested_by_user_id=requested_by_user_id,
        status="queued",
        # Defaults to the whole way now that extraction exists. Whether the
        # extraction pass actually calls the model is a separate, explicit
        # decision (`DATASHEET_EXTRACTION_ENABLED`) — reaching phase D only means
        # the run reports what a real pass would cost. A caller can still ask for a
        # discovery-only or acquisition-only run, which is how a curator reviews the
        # manifest before spending anything on fetching.
        stop_after_phase=stop_after_phase,
        seed_kind=seed_kind,
        organism_name=organism_name,
        organism_taxid=organism_taxid,
        organism_synonyms=list(organism_synonyms),
        product_term=product_term,
        product_ids=product_ids or None,
        product_synonyms=list(product_synonyms),
        product_classes=list(product_classes) if product_classes else None,
        year_from=year_from,
        year_to=year_to,
        template_id=template.id,
        template_snapshot=build_template_snapshot(template),
        config_snapshot=config,
        progress_message="Queued",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def list_runs(db: AsyncSession, *, limit: int = 50) -> list[DatasheetRun]:
    result = await db.execute(
        select(DatasheetRun).order_by(DatasheetRun.created_at.desc()).limit(limit)
    )
    return list(result.scalars())


async def get_run(db: AsyncSession, run_id: uuid.UUID) -> DatasheetRun | None:
    return await db.get(DatasheetRun, run_id)


async def request_cancel(db: AsyncSession, run_id: uuid.UUID) -> DatasheetRun | None:
    """Ask a run to stop. Terminal runs are left alone.

    A run parked on an extraction batch is not `running`, so no worker will look at
    it again — which means cancelling it here has to cancel the batch too, or the
    batch runs to completion, is billed in full, and its results are never
    collected. Best-effort: failing to reach the provider still cancels the run, and
    the batch id stays on the row so the cost remains traceable.
    """
    run = await db.get(DatasheetRun, run_id)
    if run is None:
        return None
    if run.status in {"succeeded", "failed", "cancelled"}:
        return run

    batch_note = None
    if run.extraction_batch_id:
        cancelled_batch = await cancel_extraction_batch(extraction_provider(), run)
        batch_note = (
            f"Extraction batch {run.extraction_batch_id} cancel requested — requests already "
            "in flight still complete and are still billed"
            if cancelled_batch
            else f"Extraction batch {run.extraction_batch_id} could not be cancelled; it will "
            "run to completion and be billed"
        )

    run.status = "cancel_requested" if run.status == "running" else "cancelled"
    run.progress_message = "Cancellation requested"
    run.log_tail = append_log(run.log_tail, "Cancellation requested")
    if batch_note:
        run.log_tail = append_log(run.log_tail, batch_note)
    if run.status == "cancelled":
        run.finished_at = utcnow()
    await db.commit()
    await db.refresh(run)
    return run


async def request_reextraction(db: AsyncSession, run_id: uuid.UUID) -> DatasheetRun | None:
    """Re-queue a finished run at phase D, keeping its discovery and acquisition.

    The case this exists for is a fixed extraction hint or a corrected template:
    without it, improving one column means re-running discovery over thousands of
    upstream records and re-fetching every full text, none of which changed.

    `phase='extraction'` on a queued run is the worker's "start at D" signal — a
    normal queued run has `phase = NULL`, so the two stay distinct without another
    column. Rows are cleared rather than left: a re-extraction that produced fewer
    rows would otherwise leave the previous run's rows mixed into the datasheet.
    """
    run = await db.get(DatasheetRun, run_id)
    if run is None:
        return None
    if run.status in ACTIVE_STATUSES:
        raise DatasheetRunError(
            f"Run is {run.status}; cancel it before re-extracting so the worker is not raced"
        )

    await db.execute(delete(DatasheetRow).where(DatasheetRow.run_id == run_id))
    await db.execute(
        update(DatasheetCandidate)
        .where(DatasheetCandidate.run_id == run_id)
        .values(extraction_status=None, extraction_error=None)
    )

    run.status = "queued"
    run.phase = "extraction"
    run.stop_after_phase = "export"
    # Cleared so the worker does not mistake a finished run's batch for a live one.
    run.extraction_batch_id = None
    run.extraction_batch_submitted_at = None
    run.extraction_batch_polled_at = None
    run.extracted_count = None
    run.prompt_tokens = None
    run.completion_tokens = None
    run.cached_tokens = None
    run.error = None
    run.finished_at = None
    run.progress_message = "Queued for re-extraction"
    run.log_tail = append_log(
        run.log_tail, "Re-extraction requested: rows cleared, will restart at phase D"
    )
    await db.commit()
    await db.refresh(run)
    return run


async def count_candidates(db: AsyncSession, run_id: uuid.UUID) -> dict[str, int]:
    """Counts by relevance and by acquisition status, for the run detail page."""
    relevance_rows = await db.execute(
        select(DatasheetCandidate.relevance, func.count())
        .where(DatasheetCandidate.run_id == run_id)
        .group_by(DatasheetCandidate.relevance)
    )
    status_rows = await db.execute(
        select(DatasheetCandidate.acquisition_status, func.count())
        .where(DatasheetCandidate.run_id == run_id)
        .group_by(DatasheetCandidate.acquisition_status)
    )
    flags = await db.execute(
        select(
            func.count(),
            func.sum(func.cast(DatasheetCandidate.is_review, __import__("sqlalchemy").Integer)),
            func.sum(func.cast(DatasheetCandidate.is_retracted, __import__("sqlalchemy").Integer)),
            func.sum(func.cast(DatasheetCandidate.is_preprint, __import__("sqlalchemy").Integer)),
        ).where(DatasheetCandidate.run_id == run_id)
    )
    total, reviews, retracted, preprints = flags.one()

    counts = {f"relevance_{key or 'unknown'}": value for key, value in relevance_rows.all()}
    counts.update({f"acquisition_{key or 'pending'}": value for key, value in status_rows.all()})
    counts.update(
        {
            "total": int(total or 0),
            "reviews": int(reviews or 0),
            "retracted": int(retracted or 0),
            "preprints": int(preprints or 0),
        }
    )
    return counts


async def list_candidates(
    db: AsyncSession,
    run_id: uuid.UUID,
    *,
    relevance: str | None = None,
    acquisition_status: str | None = None,
    include_excluded: bool = True,
    limit: int = CANDIDATE_PAGE_SIZE,
    offset: int = 0,
) -> list[DatasheetCandidate]:
    query = select(DatasheetCandidate).where(DatasheetCandidate.run_id == run_id)
    if relevance:
        query = query.where(DatasheetCandidate.relevance == relevance)
    if acquisition_status:
        query = query.where(DatasheetCandidate.acquisition_status == acquisition_status)
    if not include_excluded:
        query = query.where(DatasheetCandidate.acquisition_status != "skipped")

    query = query.order_by(
        DatasheetCandidate.is_retracted.asc(),
        DatasheetCandidate.relevance.asc(),
        DatasheetCandidate.year.desc().nullslast(),
    ).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars())


# ── Persistence of phase-A output ─────────────────────────────────────────────


def _candidate_row(run_id: uuid.UUID, candidate: Candidate, *, included: bool) -> DatasheetCandidate:
    return DatasheetCandidate(
        run_id=run_id,
        doi=candidate.doi,
        pmid=candidate.pmid,
        pmc_id=candidate.pmc_id,
        title=candidate.title,
        journal=candidate.journal,
        publisher=candidate.publisher,
        year=candidate.year,
        found_in=list(candidate.found_in),
        oa_status=candidate.oa_status,
        license=candidate.license,
        is_preprint=candidate.is_preprint,
        preprint_doi=candidate.preprint_doi,
        version_of_record_doi=candidate.version_of_record_doi,
        doc_type=candidate.doc_type,
        is_review=candidate.is_review,
        is_retracted=candidate.is_retracted,
        retraction_checked_at=utcnow(),
        relevance=candidate.relevance or UNKNOWN,
        relevance_reason=candidate.relevance_reason,
        # 'skipped' is the honest status for an excluded candidate: it stays in the
        # manifest with its reason instead of disappearing.
        acquisition_status="pending" if included else "skipped",
        dedupe_group=candidate.dedupe_group,
        possible_duplicate_of=list(candidate.possible_duplicate_of) or None,
        duplicate_evidence=candidate.duplicate_evidence,
        notes=candidate.retraction_note,
    )


async def replace_candidates(
    db: AsyncSession,
    run_id: uuid.UUID,
    candidates: list[Candidate],
    *,
    included_dois: set[str],
) -> int:
    """Write the run's candidates, replacing any from an earlier attempt.

    Replace rather than upsert: re-running discovery for a run means the previous
    answer is superseded, and a partial merge would leave rows no source vouches
    for any more.
    """
    await db.execute(delete(DatasheetCandidate).where(DatasheetCandidate.run_id == run_id))

    seen_dois: set[str] = set()
    rows: list[DatasheetCandidate] = []
    for candidate in candidates:
        # The unique index is (run_id, doi); canonicalisation should already
        # guarantee this, so a survivor here means a bug upstream, not bad data.
        if candidate.doi:
            if candidate.doi in seen_dois:
                logger.warning("duplicate DOI %s survived canonicalisation", candidate.doi)
                continue
            seen_dois.add(candidate.doi)
        rows.append(
            _candidate_row(
                run_id, candidate, included=(candidate.doi or "") in included_dois or not candidate.doi
            )
        )

    db.add_all(rows)
    await db.commit()
    return len(rows)


async def manifest_csv_for_run(db: AsyncSession, run_id: uuid.UUID) -> str:
    """Render the manifest from the persisted rows, not from memory."""
    result = await db.execute(
        select(DatasheetCandidate)
        .where(DatasheetCandidate.run_id == run_id)
        .order_by(DatasheetCandidate.acquisition_status.asc(), DatasheetCandidate.year.desc().nullslast())
    )
    rows = list(result.scalars())

    candidates: list[Candidate] = []
    included: set[str] = set()
    for row in rows:
        candidates.append(
            Candidate(
                doi=row.doi,
                pmid=row.pmid,
                pmc_id=row.pmc_id,
                title=row.title,
                journal=row.journal,
                publisher=row.publisher,
                year=row.year,
                found_in=tuple(row.found_in or ()),
                oa_status=row.oa_status,
                license=row.license,
                is_preprint=bool(row.is_preprint),
                preprint_doi=row.preprint_doi,
                version_of_record_doi=row.version_of_record_doi,
                is_retracted=bool(row.is_retracted),
                retraction_note=row.notes,
                doc_type=row.doc_type,
                is_review=bool(row.is_review),
                relevance=row.relevance,
                relevance_reason=row.relevance_reason,
                dedupe_group=row.dedupe_group,
                possible_duplicate_of=tuple(row.possible_duplicate_of or ()),
                duplicate_evidence=row.duplicate_evidence,
            )
        )
        if row.acquisition_status != "skipped" and row.doi:
            included.add(row.doi)

    return write_manifest_csv(candidates, included_dois=included)


def write_manifest_to_cache(
    run: DatasheetRun,
    candidates: list[Candidate],
    *,
    included_dois: set[str],
) -> Path | None:
    """Drop the manifest into the run's cache directory.

    Without it the directory is unreadable from outside this process: `safe_stem`
    is one-way, so `assets/<stem>.pdf` and `fulltext/<stem>.json` cannot be traced
    back to a DOI. Writing the CSV here is what lets the ingestion pipeline index
    a finished run with no database access and no manual download.

    Failure is logged, never raised: a run that found 4,000 papers must not be
    marked failed because a directory was read-only.
    """
    try:
        path = manifest_csv_path(resolve_run_cache_root(run))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            write_manifest_csv(candidates, included_dois=included_dois), encoding="utf-8"
        )
        return path
    except OSError as exc:
        logger.warning("could not write discovery manifest for run %s: %s", run.id, exc)
        return None


def resolve_run_cache_root(run: DatasheetRun) -> Path:
    """The run's corpus cache directory, created on first use.

    Same `data/corpora/<name>` layout the ingestion pipeline uses, and stored
    repo-relative on the run for the reason recorded in migration 0007: an
    absolute path means "wherever the writing process's filesystem was".
    """
    from app.ingestion.admin_service import ALLOWED_CACHE_ROOT, resolve_cache_path, store_cache_path

    if run.cache_path:
        resolved = resolve_cache_path(run.cache_path)
        if resolved is not None:
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved

    safe_name = "".join(
        char if char.isalnum() or char in "-._" else "-" for char in (run.name or "run")
    ).strip("-") or "run"
    root = ALLOWED_CACHE_ROOT / "datasheets" / f"{safe_name}-{str(run.id)[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    run.cache_path = store_cache_path(str(root))
    return root


# ── Phase A driver ────────────────────────────────────────────────────────────


def build_query(run: DatasheetRun) -> SourceQuery:
    config = run.config_snapshot or {}
    discovery_config = config.get("discovery") or {}
    return SourceQuery(
        organism_terms=tuple(run.organism_synonyms or ()),
        product_terms=tuple(run.product_synonyms or ()),
        year_from=run.year_from,
        year_to=run.year_to,
        max_records_per_source=int(discovery_config.get("max_records_per_source", 6000)),
    )


def credentials_from_settings() -> DiscoveryCredentials:
    """Contact addresses for the polite pools. Falls back to the NCBI address, which
    is the one guaranteed to be configured."""
    contact = settings.ncbi_email or None
    return DiscoveryCredentials(
        ncbi_email=contact,
        ncbi_api_key=settings.ncbi_api_key or None,
        crossref_mailto=contact,
        openalex_mailto=contact,
    )


async def run_discovery_phase(
    db: AsyncSession,
    run: DatasheetRun,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Drive phase A for one run and persist the result.

    The blocking HTTP clients run in a worker thread; the event loop stays free so
    the API keeps serving while a run is in flight.
    """
    config = run.config_snapshot or {}
    discovery_config = config.get("discovery") or {}
    sources = tuple(discovery_config.get("sources") or ALL_SOURCES)
    include_mentions = bool(discovery_config.get("include_mentions", False))
    include_reviews = bool(discovery_config.get("include_reviews", False))
    check_notices = bool(discovery_config.get("check_retraction_notices", False))

    run.status = "running"
    run.phase = "discovery"
    run.started_at = run.started_at or utcnow()
    run.progress_message = "Discovery started"
    run.log_tail = append_log(run.log_tail, f"Discovery started over {', '.join(sources)}")
    await db.commit()

    query = build_query(run)
    result = await asyncio.to_thread(
        discover,
        query,
        sources=sources,
        credentials=credentials_from_settings(),
        include_mentions=include_mentions,
        check_retraction_notices=check_notices,
    )

    included = included_candidates(
        result, include_mentions=include_mentions, include_reviews=include_reviews
    )
    included_dois = {candidate.doi for candidate in included if candidate.doi}

    if is_cancelled and is_cancelled():
        run.status = "cancelled"
        run.finished_at = utcnow()
        run.progress_message = "Cancelled during discovery"
        run.log_tail = append_log(run.log_tail, "Cancelled after discovery, results discarded")
        await db.commit()
        return result.summary()

    written = await replace_candidates(
        db, run.id, result.candidates, included_dois=included_dois
    )
    write_manifest_to_cache(run, result.candidates, included_dois=included_dois)

    summary = result.summary()
    run.candidate_count = written
    run.config_snapshot = {**config, "discovery_result": summary}
    run.progress_message = (
        f"Discovery complete: {written} candidates, {len(included)} to acquire"
    )
    run.log_tail = append_log(
        run.log_tail,
        f"Discovery complete: {summary['total_source_records']} source records -> "
        f"{written} candidates ({len(included)} included, "
        f"{summary['retracted_count']} retracted, {summary['needs_adjudication']} need adjudication)",
    )
    if summary["source_errors"]:
        run.log_tail = append_log(
            run.log_tail, f"Sources that failed: {', '.join(summary['source_errors'])}"
        )

    # Round 1 ends here: acquisition is S3.
    if run.stop_after_phase == "discovery":
        run.status = "succeeded"
        run.finished_at = utcnow()
    await db.commit()
    return summary
