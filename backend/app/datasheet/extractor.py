"""
app/datasheet/extractor.py
--------------------------
Phase D: turn a run's fetched full text into datasheet rows.

One call per paper (plan §7). Input is title + abstract + Methods + Results (+ SI
tables when fetched), budgeted to `max_section_tokens`; output is one JSON object
keyed by template column, each value carrying `{value, confidence,
evidence_quote, evidence_section}`. The schema is generated from the run's frozen
template snapshot, so an admin adding a column adds a schema field with no code
change.

Three properties of this module are load-bearing:

**Dry-run first.** `plan_extraction` resolves every candidate, counts tokens with
the provider's own tokeniser and reports projected cost — without sending a
single paper. It is the default, and the live pass additionally requires
`settings.datasheet_extraction_enabled`. Extraction is the only phase that both
costs money and sends paper text off-site; it does not happen because a job was
queued, it happens because someone said so.

**Results are keyed by `custom_id`.** Batch results return in arbitrary order.
Nothing here may match on position.

**A paper that fails is one missing row, not a failed run.** Refusals, unparseable
output and expired batch entries are recorded against their candidate and the
rest of the run proceeds.

**A submitted batch is state on the run, not a loop in this process.** Submitting
parks the run (`awaiting_batch`) and returns; the worker re-claims it later and
calls `collect_extraction_batch`. That is what keeps a restart from orphaning a
paid batch, and what keeps a 24-hour batch from blocking the ingestion queue the
same process serves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.datasheet import extraction_cache
from app.db.models import DatasheetCandidate, DatasheetRow, DatasheetRun
from app.providers.base import BatchRequest, CompletionUsage, LLMProvider
from app.providers.registry import get_llm_provider

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.acquisition.cache_layout import cache_paths  # noqa: E402
from pipelines.extraction.sections import (  # noqa: E402
    DEFAULT_SECTIONS,
    SelectionResult,
    select_sections,
)
from pipelines.extraction.template import (  # noqa: E402
    NOT_REPORTED,
    ColumnSpec,
    build_extraction_schema,
    column_specs_from_rows,
    enabled_columns,
)

logger = logging.getLogger(__name__)

# Published rates, $/MTok, halved for the Batch API. Used only to project a cost
# in the dry run — the authoritative number is always the per-run token counters,
# which are recorded from actual usage.
BATCH_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (1.00, 5.00),      # intro rates through 2026-08-31
    "claude-opus-5": (2.50, 12.50),
    "claude-opus-4-8": (2.50, 12.50),
    "claude-sonnet-4-6": (1.50, 7.50),
}
# Output tokens per paper: 17 cells, each with a value, a confidence and an
# evidence quote. Only used for the projection.
ASSUMED_OUTPUT_TOKENS = 1_500


SYSTEM_PROMPT = """You extract structured data from a single scientific paper into a datasheet row.

You will be given selected sections of ONE paper: its title and abstract, and where \
available its Methods, Results and supplementary tables. Each block is labelled with \
the section it came from.

Rules:
- Report only what THIS paper reports about its own work. Papers describe other \
groups' results when reviewing prior work; a number that belongs to a cited study \
must not be recorded here. If you cannot tell whose result a value is, treat it as \
not reported.
- Quote your evidence verbatim from the supplied text. Do not paraphrase the quote \
and do not quote text that was not supplied.
- Set `evidence_section` to the label of the block the quote came from.
- Where the supplied text does not state a value, return "{not_reported}" with an \
empty quote and a low confidence. A missing value is a fact about the paper; a \
plausible guess is not.
- `confidence` is your probability that the value is correct AND belongs to this \
paper's own work.
- Preserve notation exactly as written, including Greek characters and strain \
suffixes: `Po1g-Δku70` is a different strain from `Po1g-Dku70`.
"""


@dataclass
class PaperInput:
    """One candidate, resolved and ready to extract (or to be counted)."""

    candidate_id: uuid.UUID
    custom_id: str
    identifier: str
    title: str | None
    selection: SelectionResult
    prompt_tokens: int | None = None
    # sha256 of the text that would be sent — the cache key, not the document id.
    content_sha256: str = ""
    # A previous run's result for this exact prompt, or None. Set means this paper
    # costs nothing: its row is written from the entry without calling the model.
    cached: dict[str, Any] | None = None

    @property
    def source_tier(self) -> str:
        return self.selection.source_tier


@dataclass
class ExtractionPlan:
    """What a run would cost, and what it cannot do."""

    papers: list[PaperInput] = field(default_factory=list)
    skipped_no_text: list[str] = field(default_factory=list)
    skipped_over_cap: int = 0
    truncated: list[str] = field(default_factory=list)
    token_method: str = "estimated_from_chars"
    model: str = ""
    # Candidate ids behind the two skip reasons, so the outcome can be recorded on
    # the papers themselves rather than only counted in a summary.
    no_text_ids: list[uuid.UUID] = field(default_factory=list)
    over_cap_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def paper_count(self) -> int:
        return len(self.papers)

    @property
    def pending(self) -> list[PaperInput]:
        """Papers that actually have to be sent. Cache hits are not among them."""
        return [paper for paper in self.papers if paper.cached is None]

    @property
    def cached_papers(self) -> list[PaperInput]:
        return [paper for paper in self.papers if paper.cached is not None]

    @property
    def input_tokens(self) -> int:
        """Tokens this pass would send — cache hits excluded, since they are not sent."""
        return sum(paper.prompt_tokens or paper.selection.tokens for paper in self.pending)

    def projected_cost_usd(self) -> float:
        """What running this now would cost. A cached paper contributes nothing:
        the projection answers "what will this cost me", not "what would it have
        cost from scratch"."""
        input_price, output_price = BATCH_PRICES_PER_MTOK.get(self.model, (0.0, 0.0))
        output_tokens = len(self.pending) * ASSUMED_OUTPUT_TOKENS
        return (self.input_tokens / 1_000_000) * input_price + (
            output_tokens / 1_000_000
        ) * output_price

    def as_dict(self) -> dict[str, Any]:
        pending = self.pending
        return {
            "papers": self.paper_count,
            "cached": len(self.cached_papers),
            "to_extract": len(pending),
            "input_tokens": self.input_tokens,
            "assumed_output_tokens": len(pending) * ASSUMED_OUTPUT_TOKENS,
            "token_method": self.token_method,
            "model": self.model,
            "projected_cost_usd": round(self.projected_cost_usd(), 2),
            "skipped_no_text": len(self.skipped_no_text),
            "skipped_over_cap": self.skipped_over_cap,
            "truncated": len(self.truncated),
            "median_tokens_per_paper": _median(
                [paper.prompt_tokens or paper.selection.tokens for paper in pending]
            ),
        }


ProgressCallback = Any  # Callable[[str, dict], Awaitable[None] | None]


async def _report(progress: ProgressCallback, message: str, payload: dict | None = None) -> None:
    """Push a progress line, tolerating a sync or async callback, or none at all."""
    if progress is None:
        return
    outcome = progress(message, payload or {})
    if asyncio.iscoroutine(outcome):
        await outcome


@dataclass
class ExtractionSummary:
    extracted: int = 0
    refused: int = 0
    failed: int = 0
    escalated: int = 0
    # Papers that wanted escalation but did not fit the cell budget. Reported so a
    # capped run is distinguishable from one that needed no escalation at all.
    escalation_skipped: int = 0
    # Rows written from the result cache. Counted in `extracted` too — they are
    # rows in the datasheet — but reported separately, because a run that reused
    # everything and a run that paid for everything look identical otherwise.
    reused: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    model: str = ""
    escalation_model: str = ""
    dry_run: bool = False
    # True when a batch is with the provider and this run is parked. The worker
    # reads it to decide whether to finish the run or set it to `awaiting_batch`.
    awaiting_batch: bool = False
    batch_id: str | None = None
    plan: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "extracted": self.extracted,
            "refused": self.refused,
            "failed": self.failed,
            "escalated": self.escalated,
            "escalation_skipped": self.escalation_skipped,
            "reused": self.reused,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "model": self.model,
            "escalation_model": self.escalation_model,
            "dry_run": self.dry_run,
            "awaiting_batch": self.awaiting_batch,
            "batch_id": self.batch_id,
            "plan": self.plan,
        }


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def template_specs(run: DatasheetRun) -> list[ColumnSpec]:
    """Columns as frozen on the run, not as the live template stands today."""
    snapshot = run.template_snapshot or {}
    return column_specs_from_rows(snapshot.get("columns") or [])


def system_prompt_for(specs: list[ColumnSpec]) -> str:
    """The shared prefix: instructions plus the column brief.

    Identical for every paper in a run, which is what makes it worth a
    `cache_control` breakpoint. Nothing per-paper — and nothing time-varying — may
    appear here, or the cache never reads.
    """
    lines = [SYSTEM_PROMPT.format(not_reported=NOT_REPORTED), "\nColumns to fill:"]
    for spec in enabled_columns(specs):
        hint = f" — {spec.extraction_hint}" if spec.extraction_hint else ""
        lines.append(f"- {spec.key} ({spec.label}){hint}")
        if spec.kind == "controlled" and spec.vocabulary:
            lines.append(f"    one of: {'; '.join(spec.vocabulary)}")
    return "\n".join(lines)


def load_fulltext_payload(cache_root: Path, identifier: str) -> dict | None:
    """Read the text the acquisition ladder already fetched for this paper."""
    _asset_base, text_path = cache_paths(cache_root, identifier)
    if not text_path.is_file():
        return None
    try:
        return json.loads(text_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("unreadable extracted text at %s: %s", text_path, exc)
        return None


async def plan_extraction(
    db: AsyncSession,
    run: DatasheetRun,
    *,
    cache_root: Path,
    provider: LLMProvider | None = None,
    max_papers: int | None = None,
    use_cache: bool = True,
) -> ExtractionPlan:
    """Resolve candidates, count tokens, project cost. Sends nothing to the model.

    Token counting uses the provider's own tokeniser when one is available —
    `count_tokens` is free and is the difference between a projection and a guess.

    Deterministic over the candidates and the cached full-text payloads, which is
    what makes it safe to call again when collecting a batch: the same papers come
    back with the same `custom_id`s, so results match by identifier rather than by
    anything this function has to remember.
    """
    specs = template_specs(run)
    system = system_prompt_for(specs)
    model = settings.datasheet_extraction_model
    cap = max_papers if max_papers is not None else settings.datasheet_max_papers_per_run
    template_version = int((run.template_snapshot or {}).get("version") or 1)

    result = await db.execute(
        select(DatasheetCandidate)
        .where(DatasheetCandidate.run_id == run.id)
        .where(DatasheetCandidate.acquisition_status != "skipped")
        .order_by(DatasheetCandidate.year.desc().nullslast())
    )
    candidates = list(result.scalars())

    plan = ExtractionPlan(model=model)
    for candidate in candidates:
        identifier = candidate.doi or candidate.pmid or candidate.pmc_id
        if not identifier:
            continue
        payload = load_fulltext_payload(cache_root, identifier)
        if payload is None:
            # No fetched text. The paper stays in the manifest with its
            # acquisition status; it simply has nothing to extract from.
            plan.skipped_no_text.append(identifier)
            plan.no_text_ids.append(candidate.id)
            continue

        selection = select_sections(
            payload,
            sections=DEFAULT_SECTIONS,
            max_tokens=settings.datasheet_max_section_tokens,
        )
        if not selection.text.strip():
            plan.skipped_no_text.append(identifier)
            plan.no_text_ids.append(candidate.id)
            continue
        if len(plan.papers) >= cap:
            plan.skipped_over_cap += 1
            plan.over_cap_ids.append(candidate.id)
            continue
        if selection.truncated:
            plan.truncated.append(identifier)

        plan.papers.append(
            PaperInput(
                candidate_id=candidate.id,
                custom_id=str(candidate.id),
                identifier=identifier,
                title=candidate.title,
                selection=selection,
                content_sha256=extraction_cache.content_hash(selection.text),
            )
        )

    if use_cache and plan.papers:
        # One query for the run. A hit means this exact prompt, template version and
        # model already produced a result, so the paper costs nothing to "extract".
        entries = await extraction_cache.lookup(
            db,
            hashes=[paper.content_sha256 for paper in plan.papers],
            template_version=template_version,
            model=model,
        )
        for paper in plan.papers:
            paper.cached = entries.get(paper.content_sha256)

    pending = plan.pending
    if provider is not None and pending:
        try:
            counts = await asyncio.gather(
                *[
                    provider.count_prompt_tokens(
                        system=system, content=paper.selection.text, model=model
                    )
                    for paper in pending
                ]
            )
            for paper, count in zip(pending, counts):
                paper.prompt_tokens = count
            plan.token_method = "provider"
        except NotImplementedError:
            logger.info("provider cannot count tokens; using the character estimate")
        except Exception as exc:  # noqa: BLE001 - a projection must not fail a run
            logger.warning("token counting failed, using the character estimate: %s", exc)

    return plan


def _cells_from(data: dict, specs: list[ColumnSpec], *, source_tier: str) -> dict[str, Any]:
    """Normalise one model response into the stored cell shape.

    Every enabled column gets a cell even when the model omitted it, so a row's
    shape never depends on what a particular call happened to return.
    """
    cells: dict[str, Any] = {}
    for spec in enabled_columns(specs):
        raw = data.get(spec.key) or {}
        if not isinstance(raw, dict):
            raw = {"value": raw}
        value = str(raw.get("value") or "").strip() or NOT_REPORTED
        try:
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        cells[spec.key] = {
            "value": value,
            "confidence": max(0.0, min(1.0, confidence)),
            "evidence_quote": str(raw.get("evidence_quote") or ""),
            "evidence_section": str(raw.get("evidence_section") or "not_found"),
            "source_tier": source_tier,
        }
    return cells


def cells_needing_escalation(cells: dict[str, Any], *, threshold: float) -> list[str]:
    """Column keys a second, stronger pass should revisit.

    Two signals, both meaning the same thing: the bulk model did not find a value
    it trusts. `Not reported` counts — for a paper whose full text was read, an
    empty cell is as likely to be a miss as a genuine absence.
    """
    keys = []
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        if cell.get("value") == NOT_REPORTED or float(cell.get("confidence") or 0.0) < threshold:
            keys.append(key)
    return keys


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _mark_candidates(
    db: AsyncSession,
    candidate_ids: list[uuid.UUID],
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Record what extraction did with these papers.

    A paper that refuses, fails or has no text produces no `datasheet_rows` row —
    writing one with empty cells would put a fabricated line in the datasheet — so
    this is the only place the reason survives. `3 failed` with no way to learn
    which three is not a usable report.
    """
    if not candidate_ids:
        return
    await db.execute(
        update(DatasheetCandidate)
        .where(DatasheetCandidate.id.in_(candidate_ids))
        .values(extraction_status=status, extraction_error=error)
    )


async def _persist_row(
    db: AsyncSession,
    run: DatasheetRun,
    paper: PaperInput,
    *,
    cells: dict[str, Any],
    usage: CompletionUsage | None,
    model: str,
) -> None:
    """Upsert one row. Re-running a run replaces its rows rather than doubling them."""
    await db.execute(
        delete(DatasheetRow)
        .where(DatasheetRow.run_id == run.id)
        .where(DatasheetRow.candidate_id == paper.candidate_id)
    )
    db.add(
        DatasheetRow(
            id=uuid.uuid4(),
            run_id=run.id,
            candidate_id=paper.candidate_id,
            cells=cells,
            source_tier=paper.source_tier,
            extraction_model=model,
            template_version=int((run.template_snapshot or {}).get("version") or 1),
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
    )


def build_batch_requests(
    papers: list[PaperInput], *, system: str, schema: dict, model: str
) -> list[BatchRequest]:
    return [
        BatchRequest(
            custom_id=paper.custom_id,
            system=system,
            content=paper.selection.text,
            schema=schema,
            model=model,
        )
        for paper in papers
    ]


async def run_extraction_phase(
    db: AsyncSession,
    run: DatasheetRun,
    *,
    cache_root: Path,
    provider: LLMProvider | None,
    dry_run: bool | None = None,
    is_cancelled=None,
    progress: ProgressCallback = None,
) -> ExtractionSummary:
    """Drive phase D for one run.

    Defaults to a dry run. A live pass needs both an explicit `dry_run=False` and
    `settings.datasheet_extraction_enabled` — the flag is the owner's standing
    decision about sending paper text off-site, and a caller cannot override it by
    passing an argument.
    """
    specs = template_specs(run)
    system = system_prompt_for(specs)
    model = settings.datasheet_extraction_model

    await _report(progress, "Counting tokens for the papers with fetched text")
    plan = await plan_extraction(db, run, cache_root=cache_root, provider=provider)
    summary = ExtractionSummary(
        model=model,
        escalation_model=settings.datasheet_escalation_model,
        plan=plan.as_dict(),
    )
    await _report(
        progress,
        f"{plan.paper_count} papers ready, ~${plan.projected_cost_usd():.2f} projected",
        plan.as_dict(),
    )

    requested_live = dry_run is False
    if not requested_live or not settings.datasheet_extraction_enabled or provider is None:
        summary.dry_run = True
        logger.info(
            "extraction dry run for %s: %d papers (%d cached), ~%d input tokens, ~$%.2f",
            run.id,
            plan.paper_count,
            len(plan.cached_papers),
            plan.input_tokens,
            plan.projected_cost_usd(),
        )
        return summary

    if not plan.papers:
        return summary

    # Recorded before anything is sent: these papers are already decided, and a run
    # that parks on a batch should not leave them looking unattempted.
    await _mark_candidates(db, plan.no_text_ids, status="no_text")
    await _mark_candidates(db, plan.over_cap_ids, status="over_cap")
    await _persist_cached_rows(db, run, plan, summary=summary, model=model, progress=progress)

    pending = plan.pending
    if not pending:
        await db.commit()
        await _report(
            progress,
            f"Nothing to send: all {summary.reused} papers were already extracted",
            summary.as_dict(),
        )
        return summary

    # Built here rather than up front: a dry run needs no schema, and a run whose
    # template snapshot has no columns should report its projection rather than
    # fail on a schema it was never going to use.
    schema = build_extraction_schema(specs)

    if settings.datasheet_use_batch_api:
        if is_cancelled is not None and await _cancelled(is_cancelled):
            await db.commit()
            await _report(progress, "Cancelled before the extraction batch was submitted")
            return summary
        try:
            batch_id = await provider.submit_batch(
                build_batch_requests(pending, system=system, schema=schema, model=model)
            )
        except NotImplementedError:
            logger.info("provider does not support batching; falling back to sequential calls")
        else:
            # The id is committed with the run before anything else happens. A
            # restart between submission and this commit is the one window where a
            # paid batch can still be orphaned, and it is a single statement wide.
            run.extraction_batch_id = batch_id
            run.extraction_batch_submitted_at = _utcnow()
            run.extraction_batch_polled_at = _utcnow()
            await db.commit()
            summary.awaiting_batch = True
            summary.batch_id = batch_id
            logger.info("extraction batch %s submitted with %d papers", batch_id, len(pending))
            await _report(
                progress,
                f"Batch {batch_id} submitted with {len(pending)} papers; "
                "parked until it ends",
                {"batch_id": batch_id, "papers": len(pending)},
            )
            return summary

    results = await _extract_sequentially(
        provider,
        pending,
        system=system,
        schema=schema,
        model=model,
        is_cancelled=is_cancelled,
        progress=progress,
    )
    await _finish_extraction(
        db,
        run,
        pending,
        results,
        specs=specs,
        system=system,
        model=model,
        summary=summary,
        provider=provider,
        progress=progress,
    )
    return summary


async def collect_extraction_batch(
    db: AsyncSession,
    run: DatasheetRun,
    *,
    cache_root: Path,
    provider: LLMProvider,
    progress: ProgressCallback = None,
) -> ExtractionSummary:
    """Poll the run's parked batch once and, if it has ended, finish phase D.

    Called by the worker when it re-claims an `awaiting_batch` run. Polls **once**
    rather than looping: the whole point of parking is that this process is free to
    do other work between polls. A batch still in progress re-stamps
    `extraction_batch_polled_at` and returns with `awaiting_batch` set.
    """
    specs = template_specs(run)
    system = system_prompt_for(specs)
    model = settings.datasheet_extraction_model
    batch_id = run.extraction_batch_id
    summary = ExtractionSummary(
        model=model,
        escalation_model=settings.datasheet_escalation_model,
        batch_id=batch_id,
    )
    if not batch_id:
        raise ValueError("this run has no extraction batch to collect")

    status = await provider.poll_batch(batch_id)
    if not status.ended:
        run.extraction_batch_polled_at = _utcnow()
        await db.commit()
        summary.awaiting_batch = True
        await _report(
            progress,
            f"Batch {batch_id}: {status.succeeded} done, {status.processing} processing"
            + (f", {status.errored} errored" if status.errored else ""),
            {
                "batch_id": batch_id,
                "succeeded": status.succeeded,
                "processing": status.processing,
                "errored": status.errored,
            },
        )
        return summary

    await _report(progress, f"Batch {batch_id} ended; collecting results")
    # Rebuilt rather than remembered. `plan_extraction` is deterministic over the
    # candidates and the cached payloads, and `custom_id` is the candidate id — so
    # a resumed collection matches results by identifier, never by position.
    # provider=None: the token counts were taken before submission and re-counting
    # would be a second round of API calls for a number already known.
    plan = await plan_extraction(db, run, cache_root=cache_root, provider=None)
    summary.plan = plan.as_dict()
    await _persist_cached_rows(db, run, plan, summary=summary, model=model, progress=progress)

    results = await _collect_batch_results(provider, batch_id)
    await _finish_extraction(
        db,
        run,
        plan.pending,
        results,
        specs=specs,
        system=system,
        model=model,
        summary=summary,
        provider=provider,
        progress=progress,
    )
    # Cleared so a re-claim cannot re-collect a finished batch. The id survives in
    # the run's extraction_result for cost traceability.
    run.extraction_batch_id = None
    await db.commit()
    return summary


async def cancel_extraction_batch(provider: LLMProvider | None, run: DatasheetRun) -> bool:
    """Tell the provider to stop the run's batch. Best-effort, and cheap to call.

    "Cancelled" is not "free": requests already in flight finish and are billed.
    What this buys is the requests that had not started yet — for a 700-paper batch
    cancelled early, most of it. A failure to reach the provider is logged and
    returns False rather than blocking the cancellation of the run, and the batch id
    stays on the row so the cost remains traceable instead of invisible.
    """
    batch_id = getattr(run, "extraction_batch_id", None)
    if provider is None or not batch_id:
        return False
    try:
        await provider.cancel_batch(batch_id)
    except NotImplementedError:
        logger.warning("provider cannot cancel batch %s; it will run to completion", batch_id)
        return False
    except Exception as exc:  # noqa: BLE001 - the run still cancels
        logger.warning("could not cancel extraction batch %s: %s", batch_id, exc)
        return False
    return True


def extraction_provider() -> LLMProvider | None:
    """The provider for phase D, or None when a dry run can proceed without one.

    A live pass needs a key and must fail loudly without one. A dry run does not:
    it only wants the tokeniser, and falls back to a character estimate — so a
    deployment with no key still gets a cost projection instead of a failed run.
    """
    if settings.datasheet_extraction_enabled:
        return get_llm_provider()
    try:
        return get_llm_provider()
    except Exception as exc:  # noqa: BLE001 - absence of a key is not a run failure
        logger.info("no LLM provider configured; dry run will estimate tokens: %s", exc)
        return None


async def _persist_cached_rows(
    db: AsyncSession,
    run: DatasheetRun,
    plan: ExtractionPlan,
    *,
    summary: ExtractionSummary,
    model: str,
    progress: ProgressCallback = None,
) -> None:
    """Write rows for the cache hits. No provider call, no tokens.

    Token columns are left NULL rather than copied from the entry: the row records
    what this pass spent, and summing a copied figure would report money that was
    never spent again.
    """
    cached = plan.cached_papers
    if not cached:
        return
    for paper in cached:
        await _persist_row(
            db, run, paper, cells=paper.cached["cells"], usage=None, model=model
        )
        await _mark_candidates(db, [paper.candidate_id], status="cached")
        summary.extracted += 1
        summary.reused += 1
    await _report(
        progress,
        f"Reused {len(cached)} previously extracted papers at no cost",
        {"reused": len(cached)},
    )


async def _finish_extraction(
    db: AsyncSession,
    run: DatasheetRun,
    papers: list[PaperInput],
    results: dict[str, dict[str, Any]],
    *,
    specs: list[ColumnSpec],
    system: str,
    model: str,
    summary: ExtractionSummary,
    provider: LLMProvider,
    progress: ProgressCallback = None,
) -> None:
    """Turn model output into rows: attribute failures, escalate, persist, cache."""
    template_version = int((run.template_snapshot or {}).get("version") or 1)
    extracted: list[tuple[PaperInput, dict[str, Any], CompletionUsage | None]] = []

    unmatched = set(results) - {paper.custom_id for paper in papers}
    if unmatched:
        # A candidate deleted between submission and collection. Logged rather than
        # guessed at: there is no paper to attach the result to.
        logger.warning(
            "%d batch results have no matching candidate and were skipped: %s",
            len(unmatched),
            sorted(unmatched)[:5],
        )

    for paper in papers:
        outcome = results.get(paper.custom_id)
        if outcome is None or outcome.get("error"):
            reason = (outcome or {}).get("error") or "no result returned for this paper"
            if outcome and outcome.get("refused"):
                summary.refused += 1
                state = "refused"
            else:
                summary.failed += 1
                state = "failed"
            await _mark_candidates(
                db, [paper.candidate_id], status=state, error=str(reason)[:2000]
            )
            continue

        usage: CompletionUsage | None = outcome.get("usage")
        cells = _cells_from(outcome["data"], specs, source_tier=paper.source_tier)
        if usage:
            summary.prompt_tokens += usage.prompt_tokens
            summary.completion_tokens += usage.completion_tokens
            summary.cached_tokens += usage.cached_tokens
        extracted.append((paper, cells, usage))

    if settings.datasheet_escalation_enabled and extracted:
        await _report(progress, f"Revisiting low-confidence cells on {summary.escalation_model}")
        await _escalate(
            provider, extracted, specs=specs, system=system, summary=summary, progress=progress
        )

    for paper, cells, usage in extracted:
        await _persist_row(db, run, paper, cells=cells, usage=usage, model=model)
        await _mark_candidates(db, [paper.candidate_id], status="extracted")
        # Written after escalation so a re-run inherits the escalated values rather
        # than re-paying the stronger model for the same cells.
        await extraction_cache.store(
            db,
            content_sha256=paper.content_sha256,
            template_version=template_version,
            model=model,
            cells=cells,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            escalated_cells=extraction_cache.escalated_cell_count(cells),
        )
        summary.extracted += 1

    await db.commit()
    await _report(
        progress,
        f"Extracted {summary.extracted} rows "
        + (f"({summary.reused} reused, " if summary.reused else "(")
        + f"{summary.escalated} escalated, {summary.refused} refused, {summary.failed} failed)",
        summary.as_dict(),
    )


async def _escalate(
    provider: LLMProvider,
    extracted: list[tuple[PaperInput, dict[str, Any], CompletionUsage | None]],
    *,
    specs: list[ColumnSpec],
    system: str,
    summary: ExtractionSummary,
    progress: ProgressCallback = None,
) -> None:
    """Second pass over the cells the bulk model was unsure about.

    Scoped twice over: only the flagged columns are re-asked (a full re-extraction
    would re-pay for cells that were already confident), and the number of papers
    escalated is capped so a batch that comes back uniformly low-confidence cannot
    quietly turn a $7 run into a $70 one. Papers are taken worst-first, so the cap
    spends the budget where the bulk pass struggled most.
    """
    threshold = settings.datasheet_escalation_confidence
    model = settings.datasheet_escalation_model
    by_key = {spec.key: spec for spec in enabled_columns(specs)}

    flagged = [
        (paper, cells, keys)
        for paper, cells, _usage in extracted
        if (keys := cells_needing_escalation(cells, threshold=threshold))
    ]
    if not flagged:
        return

    total_cells = max(1, len(extracted) * len(by_key))
    cell_budget = int(total_cells * settings.datasheet_escalation_max_fraction)
    flagged.sort(key=lambda item: len(item[2]), reverse=True)
    skipped_for_budget = 0

    spent = 0
    for paper, cells, keys in flagged:
        if spent + len(keys) > cell_budget:
            skipped_for_budget += 1
            continue
        subset = [by_key[key] for key in keys if key in by_key]
        if not subset:
            continue
        try:
            structured = await provider.extract_structured(
                system=system,
                content=paper.selection.text,
                schema=build_extraction_schema(subset),
                model=model,
            )
        except Exception as exc:  # noqa: BLE001 - escalation is best-effort
            logger.warning("escalation failed for %s: %s", paper.identifier, exc)
            continue

        revised = _cells_from(structured.data, subset, source_tier=paper.source_tier)
        for key, cell in revised.items():
            # Keep the stronger answer rather than blindly overwriting: the
            # escalation model can also come back unsure, and replacing a
            # confident value with a less confident one would be a regression.
            if cell["confidence"] >= cells[key]["confidence"]:
                cell["escalated"] = True
                cells[key] = cell
        spent += len(keys)
        summary.escalated += 1
        summary.prompt_tokens += structured.usage.prompt_tokens
        summary.completion_tokens += structured.usage.completion_tokens
        summary.cached_tokens += structured.usage.cached_tokens

    if skipped_for_budget:
        # A silent cap reads as "nothing needed escalating". Say what was left.
        message = (
            f"Escalation budget reached: {skipped_for_budget} of {len(flagged)} papers with "
            f"low-confidence cells were not revisited "
            f"(cap {settings.datasheet_escalation_max_fraction:.0%} of cells)"
        )
        logger.warning(message)
        summary.escalation_skipped = skipped_for_budget
        await _report(progress, message)


async def _extract_sequentially(
    provider: LLMProvider,
    papers: list[PaperInput],
    *,
    system: str,
    schema: dict,
    model: str,
    is_cancelled=None,
    progress: ProgressCallback = None,
) -> dict[str, dict[str, Any]]:
    """One call per paper, in this process.

    Returns `{custom_id: {...}}`. The batch API halves the price and extraction is
    not latency-sensitive, so batching is the default; this path exists for small
    runs and for providers without batching. Cancellation here needs nothing from
    the provider — stopping the loop is the whole of it.
    """
    results: dict[str, dict[str, Any]] = {}
    for index, paper in enumerate(papers, start=1):
        if is_cancelled is not None and await _cancelled(is_cancelled):
            break
        if index % 10 == 0 or index == len(papers):
            await _report(progress, f"Extracted {index} of {len(papers)} papers")
        try:
            structured = await provider.extract_structured(
                system=system, content=paper.selection.text, schema=schema, model=model
            )
            results[paper.custom_id] = {"data": structured.data, "usage": structured.usage}
        except Exception as exc:  # noqa: BLE001 - one paper, not the run
            logger.warning("extraction failed for %s: %s", paper.identifier, exc)
            results[paper.custom_id] = {"error": str(exc), "refused": "refus" in str(exc)}
    return results


async def _collect_batch_results(
    provider: LLMProvider, batch_id: str
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    async for entry in provider.fetch_batch_results(batch_id):
        # Keyed by custom_id: batch results arrive in arbitrary order.
        if entry.status == "succeeded":
            results[entry.custom_id] = {"data": entry.data, "usage": entry.usage}
        else:
            results[entry.custom_id] = {
                "error": entry.error or entry.status,
                "refused": entry.status == "refused",
                "usage": entry.usage,
            }
    return results


async def _cancelled(is_cancelled) -> bool:
    outcome = is_cancelled()
    if asyncio.iscoroutine(outcome):
        return bool(await outcome)
    return bool(outcome)
