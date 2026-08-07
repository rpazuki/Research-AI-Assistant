"""
app/datasheet/acquisition_service.py
------------------------------------
Phase B: walk the acquisition ladder for a run's candidates, cache what comes
back, and record what happened to every one of them.

The measured shape of this corpus decides the design: 46% is paywalled and a
further ~126 papers sit behind bot protection that answers the *first* request
with 403. So most candidates will exhaust every automated rung, and the honest
outcome for them is `assisted_pending` with a resolver URL — work for a human,
not a failure to debug.

Three properties matter more than throughput:

* **One limiter per run.** Buckets, circuit breakers and tallies are shared across
  the whole phase, so a publisher that blocks the first three papers stops being
  asked about the other forty-five.
* **Fetch once, ever.** Assets land in the run's corpus cache under `assets/`,
  keyed by DOI; a re-run or a refresh never re-requests them.
* **Every attempt is recorded.** `acquisition_route`, status and the reason go on
  the candidate row, and per-host tallies go on the run — silence is what this
  whole feature exists to remove.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import DatasheetCandidate, DatasheetRun

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.acquisition import extract_text  # noqa: E402
from pipelines.acquisition.cache_layout import (  # noqa: E402
    ASSET_DIR_NAME,
    TEXT_DIR_NAME,
    cache_paths,
    safe_stem,
)
from pipelines.acquisition.ladder import (  # noqa: E402
    DEFAULT_LADDER,
    STATUS_ASSISTED,
    STATUS_FETCHED,
    AcquisitionTarget,
    LadderConfig,
    acquire,
    resolver_url,
)
from pipelines.acquisition.ratelimit import RateLimiter  # noqa: E402

logger = logging.getLogger(__name__)

# The layout itself lives in pipelines/acquisition/cache_layout.py: ingestion
# reads these files back to index a finished run and must derive the same stems.
_safe_stem = safe_stem


@dataclass
class AcquisitionSummary:
    attempted: int = 0
    fetched: int = 0
    assisted: int = 0
    failed: int = 0
    from_cache: int = 0
    by_route: dict[str, int] = None  # type: ignore[assignment]
    by_format: dict[str, int] = None  # type: ignore[assignment]
    host_tallies: list[dict] = None  # type: ignore[assignment]
    fidelity_warnings: int = 0

    def __post_init__(self) -> None:
        self.by_route = self.by_route or {}
        self.by_format = self.by_format or {}
        self.host_tallies = self.host_tallies or []

    def as_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "fetched": self.fetched,
            "assisted_pending": self.assisted,
            "failed": self.failed,
            "from_cache": self.from_cache,
            "by_route": dict(self.by_route),
            "by_format": dict(self.by_format),
            "fidelity_warnings": self.fidelity_warnings,
            "host_tallies": list(self.host_tallies),
        }


def ladder_config_from(run_config: dict) -> LadderConfig:
    """Ladder settings for a run: per-run config first, then process settings."""
    acquisition = (run_config or {}).get("acquisition") or {}
    return LadderConfig(
        routes=tuple(acquisition.get("ladder") or DEFAULT_LADDER),
        unpaywall_email=settings.unpaywall_email or settings.ncbi_email or None,
        ncbi_api_key=settings.ncbi_api_key or None,
        publisher_tdm_key=settings.elsevier_tdm_key or None,
        resolver_url_template=settings.libkey_resolver_template or None,
        prefer_xml=bool(acquisition.get("prefer_xml", True)),
    )


def build_limiter(run_config: dict) -> RateLimiter:
    acquisition = (run_config or {}).get("acquisition") or {}
    return RateLimiter(
        contact_email=settings.ncbi_email or None,
        max_requests_per_host=int(acquisition.get("max_requests_per_host_per_run", 400)),
        respect_robots=bool(acquisition.get("respect_robots", True)),
    )


def load_cached_asset(cache_root: Path, target: AcquisitionTarget) -> tuple[bytes, str, str] | None:
    """Return an already-downloaded asset, so it is never re-requested."""
    identifier = target.doi or target.pmid or target.pmc_id
    if not identifier:
        return None

    asset_base, _text_path = cache_paths(cache_root, identifier)
    for suffix, content_format in ((".xml", "xml"), (".pdf", "pdf")):
        path = asset_base.with_suffix(suffix)
        if path.is_file() and path.stat().st_size > 0:
            return (path.read_bytes(), content_format, "cache")
    return None


def store_asset(cache_root: Path, identifier: str, content: bytes, content_format: str) -> Path:
    asset_base, _ = cache_paths(cache_root, identifier)
    path = asset_base.with_suffix(".xml" if content_format == "xml" else ".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def store_text(cache_root: Path, identifier: str, document: extract_text.ExtractedDocument) -> Path:
    """Section-labelled text, written next to the asset.

    Stored as JSON with the labels intact because ingestion chunks per section and
    extraction (round 2) restricts itself to Methods and Results.
    """
    _asset_base, text_path = cache_paths(cache_root, identifier)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        json.dumps(
            {
                "source_format": document.source_format,
                "title": document.title,
                "abstract": document.abstract,
                "warnings": document.warnings,
                "sections": [
                    {"label": section.label, "heading": section.heading, "text": section.text}
                    for section in document.sections
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return text_path


def _acquire_one(
    candidate: DatasheetCandidate,
    *,
    cache_root: Path,
    config: LadderConfig,
    limiter: RateLimiter,
    client: httpx.Client,
) -> dict:
    """Blocking work for one candidate: ladder, cache, extract. Runs in a thread."""
    target = AcquisitionTarget(
        doi=candidate.doi,
        pmid=candidate.pmid,
        pmc_id=candidate.pmc_id,
        preprint_doi=candidate.preprint_doi,
        title=candidate.title,
        publisher=candidate.publisher,
    )

    outcome = acquire(
        target,
        config=config,
        limiter=limiter,
        client=client,
        cached_asset=lambda item: load_cached_asset(cache_root, item),
    )

    record: dict = {
        "status": outcome.status,
        "route": outcome.route,
        "resolver_url": outcome.resolver_url,
        "detail": outcome.detail,
        "asset_path": None,
        "content_format": outcome.content_format,
        "from_cache": outcome.route == "cache",
        "fidelity": None,
        "section_labels": [],
    }

    if not outcome.acquired:
        return record

    identifier = candidate.doi or candidate.pmid or candidate.pmc_id or str(candidate.id)
    asset_path = store_asset(cache_root, identifier, outcome.content, outcome.content_format or "pdf")
    record["asset_path"] = str(asset_path)

    document = extract_text.extract(outcome.content, outcome.content_format or "pdf")
    fidelity = extract_text.character_fidelity(document.all_text or "")
    store_text(cache_root, identifier, document)

    record["fidelity"] = fidelity.as_dict()
    record["section_labels"] = document.labels()
    if fidelity.looks_corrupted:
        # Not a failure — the asset is kept and the text is usable — but a Δ that
        # became a `D` renames a strain, so it must be visible.
        logger.warning(
            "character corruption in %s via %s: %s",
            identifier,
            outcome.route,
            fidelity.suspicious_strain_names or "replacement characters",
        )
    return record


async def run_acquisition_phase(
    db: AsyncSession,
    run: DatasheetRun,
    *,
    cache_root: Path,
    limit: int | None = None,
    is_cancelled=None,
) -> dict:
    """Acquire full text for the run's included candidates.

    Sequential on purpose: per-host concurrency is 1 and the limiter is process
    scoped, so parallelism here would only queue behind the same buckets while
    making the egress harder to reason about.
    """
    config = ladder_config_from(run.config_snapshot or {})
    limiter = build_limiter(run.config_snapshot or {})
    summary = AcquisitionSummary()

    result = await db.execute(
        select(DatasheetCandidate)
        .where(
            DatasheetCandidate.run_id == run.id,
            DatasheetCandidate.acquisition_status == "pending",
        )
        .order_by(DatasheetCandidate.year.desc().nullslast())
        .limit(limit or 100000)
    )
    candidates = list(result.scalars())
    logger.info("acquisition: %d candidates for run %s", len(candidates), run.id)

    cache_root.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=limiter.timeout_s, follow_redirects=True) as client:
        for index, candidate in enumerate(candidates, start=1):
            if is_cancelled is not None and await is_cancelled():
                logger.info("acquisition cancelled after %d candidates", index - 1)
                break

            record = await asyncio.to_thread(
                _acquire_one,
                candidate,
                cache_root=cache_root,
                config=config,
                limiter=limiter,
                client=client,
            )

            candidate.acquisition_status = record["status"]
            candidate.acquisition_route = record["route"]
            candidate.asset_path = record["asset_path"]
            candidate.resolver_url = record["resolver_url"] or resolver_url(
                candidate.doi, config.resolver_url_template
            )
            if record["detail"]:
                candidate.notes = record["detail"]

            summary.attempted += 1
            if record["status"] == STATUS_FETCHED:
                summary.fetched += 1
                summary.by_route[record["route"] or "unknown"] = (
                    summary.by_route.get(record["route"] or "unknown", 0) + 1
                )
                fmt = record["content_format"] or "unknown"
                summary.by_format[fmt] = summary.by_format.get(fmt, 0) + 1
                if record["from_cache"]:
                    summary.from_cache += 1
                if (record["fidelity"] or {}).get("looks_corrupted"):
                    summary.fidelity_warnings += 1
            elif record["status"] == STATUS_ASSISTED:
                summary.assisted += 1
            else:
                summary.failed += 1

            if index % 25 == 0:
                await db.commit()
                logger.info(
                    "acquisition progress: %d/%d (%d fetched, %d assisted)",
                    index,
                    len(candidates),
                    summary.fetched,
                    summary.assisted,
                )

    summary.host_tallies = limiter.tallies()
    await db.commit()
    return summary.as_dict()


async def assisted_links_csv(db: AsyncSession, run_id: uuid.UUID) -> str:
    """The work list for a human: one row per paper to fetch by hand.

    Deliberately a plain CSV of links rather than an automated proxy session — a
    scripted SSO login is what gets an institution's IP range blocked, and it is
    credential handling that should not be automated.
    """
    import csv
    import io

    result = await db.execute(
        select(DatasheetCandidate)
        .where(
            DatasheetCandidate.run_id == run_id,
            DatasheetCandidate.acquisition_status == STATUS_ASSISTED,
        )
        .order_by(DatasheetCandidate.publisher.asc().nullslast(), DatasheetCandidate.year.desc().nullslast())
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["doi", "title", "journal", "publisher", "year", "resolver_url", "reason", "relevance"]
    )
    for row in result.scalars():
        writer.writerow(
            [
                row.doi or "",
                row.title or "",
                row.journal or "",
                row.publisher or "",
                row.year or "",
                row.resolver_url or (f"https://doi.org/{row.doi}" if row.doi else ""),
                row.notes or "",
                row.relevance,
            ]
        )
    return buffer.getvalue()
