"""Phase A: run every source, reconcile, judge, and report.

Pure orchestration — no database, no LLM. Takes a seed and returns candidates plus
a manifest of what happened, which is what the backend persists and what the
manifest CSV is built from.

Ordering is deliberate:

    search all sources → canonicalise → collapse preprints → doc type
      → relevance → retraction

Relevance runs *after* merging because a Crossref record with no abstract may be
judgeable once PubMed's abstract for the same DOI has been merged in. Judging
per source instead would send that paper to the LLM adjudicator for no reason.
Retraction runs last so only surviving candidates cost a request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import httpx

from pipelines.discovery import doctype, relevance as relevance_rules, retraction
from pipelines.discovery.canonicalize import (
    Candidate,
    canonicalise,
    collapse_preprints,
    flag_possible_duplicates,
)
from pipelines.discovery.http import DiscoveryLookupError, HttpSettings, build_client
from pipelines.discovery.query_builder import build_all
from pipelines.discovery.sources import biorxiv, crossref, europepmc, openalex, pubmed
from pipelines.discovery.sources.base import SourceQuery, SourceRecord

logger = logging.getLogger(__name__)

ALL_SOURCES: tuple[str, ...] = ("pubmed", "europepmc", "crossref", "openalex")


@dataclass
class DiscoveryCredentials:
    """Identification for the polite pools. No secrets: these are contact addresses."""

    ncbi_email: str | None = None
    ncbi_api_key: str | None = None
    crossref_mailto: str | None = None
    openalex_mailto: str | None = None


@dataclass
class DiscoveryResult:
    candidates: list[Candidate] = field(default_factory=list)
    queries: dict = field(default_factory=dict)
    source_record_counts: dict[str, int] = field(default_factory=dict)
    source_errors: dict[str, str] = field(default_factory=dict)
    relevance_counts: dict[str, int] = field(default_factory=dict)
    doc_type_counts: dict[str, int] = field(default_factory=dict)
    total_source_records: int = 0
    duplicates_collapsed: int = 0
    preprints_collapsed: int = 0
    retracted_count: int = 0
    needs_adjudication: int = 0
    possible_duplicates_flagged: int = 0

    def summary(self) -> dict:
        return {
            "total_source_records": self.total_source_records,
            "candidates": len(self.candidates),
            "duplicates_collapsed": self.duplicates_collapsed,
            "preprints_collapsed": self.preprints_collapsed,
            "source_record_counts": dict(self.source_record_counts),
            "source_errors": dict(self.source_errors),
            "relevance_counts": dict(self.relevance_counts),
            "doc_type_counts": dict(self.doc_type_counts),
            "retracted_count": self.retracted_count,
            "needs_adjudication": self.needs_adjudication,
            "possible_duplicates_flagged": self.possible_duplicates_flagged,
            "queries": self.queries,
        }


def _collect(
    query: SourceQuery,
    *,
    sources: tuple[str, ...],
    credentials: DiscoveryCredentials,
    client: httpx.Client,
    settings: HttpSettings | None,
    result: DiscoveryResult,
    progress: Callable[[str, dict], None] | None,
) -> list[SourceRecord]:
    """Query every source. One source failing must not lose the others' results."""
    records: list[SourceRecord] = []

    runners: dict[str, Callable[[], list[SourceRecord]]] = {
        "pubmed": lambda: list(
            pubmed.search(
                query,
                client=client,
                settings=settings,
                email=credentials.ncbi_email,
                api_key=credentials.ncbi_api_key,
            )
        ),
        "europepmc": lambda: list(europepmc.search(query, client=client, settings=settings)),
        "crossref": lambda: list(
            crossref.search(query, client=client, settings=settings, mailto=credentials.crossref_mailto)
        ),
        "openalex": lambda: list(
            openalex.search(query, client=client, settings=settings, mailto=credentials.openalex_mailto)
        ),
    }

    for name in sources:
        runner = runners.get(name)
        if runner is None:
            result.source_errors[name] = "unknown source"
            continue
        if progress:
            progress(f"Searching {name}", {"source": name})
        try:
            found = runner()
        except DiscoveryLookupError as exc:
            # Partial coverage is reported, never silently treated as "no results":
            # a missing source changes what a recall number means.
            logger.warning("discovery: %s failed: %s", name, exc)
            result.source_errors[name] = str(exc)
            result.source_record_counts[name] = 0
            continue

        result.source_record_counts[name] = len(found)
        records.extend(found)
        logger.info("discovery: %s returned %d records", name, len(found))

    result.total_source_records = len(records)
    return records


def discover(
    query: SourceQuery,
    *,
    sources: tuple[str, ...] = ALL_SOURCES,
    credentials: DiscoveryCredentials | None = None,
    include_mentions: bool = False,
    collapse_preprint_versions: bool = True,
    check_retraction_notices: bool = False,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    progress: Callable[[str, dict], None] | None = None,
) -> DiscoveryResult:
    """Run phase A end to end and return candidates plus a manifest."""
    query.require_terms()
    creds = credentials or DiscoveryCredentials()
    result = DiscoveryResult(queries=build_all(query))

    owns_client = client is None
    active = client or build_client(settings)
    try:
        records = _collect(
            query,
            sources=sources,
            credentials=creds,
            client=active,
            settings=settings,
            result=result,
            progress=progress,
        )

        if progress:
            progress("Reconciling records", {"records": len(records)})
        candidates = canonicalise(records)
        result.duplicates_collapsed = max(0, len(records) - len(candidates))

        if collapse_preprint_versions:
            before = len(candidates)
            candidates = collapse_preprints(
                candidates,
                resolve_version_of_record=lambda doi: (
                    biorxiv.fetch_version_of_record(doi, client=active, settings=settings)
                    if biorxiv.is_preprint_doi(doi)
                    else None
                ),
            )
            result.preprints_collapsed = before - len(candidates)

        if progress:
            progress("Classifying candidates", {"candidates": len(candidates)})
        for candidate in candidates:
            verdict = doctype.classify(
                types=candidate.types, title=candidate.title, abstract=candidate.abstract
            )
            candidate.doc_type = verdict.doc_type
            candidate.is_review = verdict.is_review
            result.doc_type_counts[verdict.doc_type] = (
                result.doc_type_counts.get(verdict.doc_type, 0) + 1
            )

            judged = relevance_rules.judge(
                title=candidate.title,
                abstract=candidate.abstract,
                organism_terms=query.organism_terms,
                product_terms=query.product_terms,
                mesh_terms=candidate.mesh_terms,
                keywords=candidate.keywords,
            )
            candidate.relevance = judged.relevance
            candidate.relevance_reason = judged.reason
            result.relevance_counts[judged.relevance] = (
                result.relevance_counts.get(judged.relevance, 0) + 1
            )
            if judged.needs_adjudication:
                result.needs_adjudication += 1

            metadata_verdict = retraction.from_metadata(
                types=candidate.types, existing_note=candidate.retraction_note
            )
            if metadata_verdict.is_retracted:
                candidate.is_retracted = True
                candidate.retraction_note = metadata_verdict.note

        if check_retraction_notices:
            included = [
                candidate.doi
                for candidate in candidates
                if candidate.doi
                and not candidate.is_retracted
                and relevance_rules.is_included(
                    candidate.relevance, include_mentions=include_mentions
                )
            ]
            if progress:
                progress("Checking retraction notices", {"dois": len(included)})
            notices = retraction.search_notices(
                included,
                client=active,
                settings=settings,
                email=creds.ncbi_email,
                api_key=creds.ncbi_api_key,
            )
            for candidate in candidates:
                note = notices.get(candidate.doi or "")
                if note:
                    candidate.is_retracted = True
                    candidate.retraction_note = note

        # Last, because it needs doc_type: rows already judged `other` collide by the
        # dozen and flagging them would be noise. Records suspicion only — the owner
        # decision is that two rows for one work beat one row for two works.
        result.possible_duplicates_flagged = flag_possible_duplicates(candidates)

        result.retracted_count = sum(1 for candidate in candidates if candidate.is_retracted)
        result.candidates = candidates
        return result
    finally:
        if owns_client:
            active.close()


def included_candidates(
    result: DiscoveryResult, *, include_mentions: bool = False, include_reviews: bool = False
) -> list[Candidate]:
    """The candidates that should proceed to acquisition.

    Retracted papers are always excluded; reviews and peripheral mentions are
    excluded by default but stay in the manifest so the exclusion is visible.
    """
    return [
        candidate
        for candidate in result.candidates
        if not candidate.is_retracted
        and (include_reviews or not candidate.is_review)
        and candidate.doc_type != doctype.OTHER
        and relevance_rules.is_included(candidate.relevance, include_mentions=include_mentions)
    ]
