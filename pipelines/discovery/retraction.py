"""Retraction detection.

A retracted paper in a datasheet is worse than a missing one: its numbers get
cited onward as if curated. Three independent signals are used, because each misses
cases the others catch:

* **PubMed** publication type `Retracted Publication` — reliable, but only for
  PubMed-indexed papers, and often added months after the notice.
* **Crossref** `update-to` with a retraction type — reaches the non-PubMed journals
  where 28% of this corpus lives.
* **Europe PMC** `commentCorrectionList` — links the paper to its notice.

Those are collected by the source clients. This module adds the fourth signal that
needs a request of its own: a **PubMed notice search**, which finds the retraction
notice pointing *at* a DOI even when the paper's own record is not yet flagged.

Retraction Watch is deliberately not queried directly: its data is distributed
through Crossref (which the Crossref client already reads), and scraping the site
is neither necessary nor polite.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from pipelines.discovery.http import HttpSettings, get_json
from pipelines.discovery.sources.base import normalise_doi

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UPSTREAM = "PubMed"

# Signals a candidate's own metadata can carry, checked without any request.
_TYPE_SIGNALS = ("retracted publication", "retraction")


@dataclass(frozen=True)
class RetractionVerdict:
    is_retracted: bool
    note: str | None = None
    checked: bool = True


def from_metadata(
    *, types: tuple[str, ...] | list[str] = (), existing_note: str | None = None
) -> RetractionVerdict:
    """Verdict from what the sources already said. No network."""
    for value in types:
        lowered = str(value).casefold()
        if any(signal in lowered for signal in _TYPE_SIGNALS):
            return RetractionVerdict(True, existing_note or f"publication type '{value}'")
    if existing_note:
        return RetractionVerdict(True, existing_note)
    return RetractionVerdict(False, None)


def search_notices(
    dois: list[str],
    *,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    email: str | None = None,
    api_key: str | None = None,
    batch_size: int = 40,
) -> dict[str, str]:
    """Find retraction notices that reference the given DOIs.

    One esearch per batch rather than per DOI: the corpus is hundreds of papers and
    NCBI's quota is the binding constraint. Returns ``{doi: note}`` for the DOIs a
    notice mentions.

    A notice references its retracted paper's DOI in the notice record, so a DOI
    appearing in a `Retraction of Publication` search is evidence about *that* DOI.
    """
    cleaned = [doi for doi in (normalise_doi(value) for value in dois) if doi]
    if not cleaned:
        return {}

    found: dict[str, str] = {}
    for start in range(0, len(cleaned), batch_size):
        batch = cleaned[start : start + batch_size]
        clause = " OR ".join(f'"{doi}"[AID]' for doi in batch)
        term = f'("Retraction of Publication"[Publication Type]) AND ({clause})'

        payload = get_json(
            f"{EUTILS_BASE}/esearch.fcgi",
            upstream=UPSTREAM,
            params={
                "db": "pubmed",
                "term": term,
                "retmode": "json",
                "retmax": len(batch),
                "email": email,
                "api_key": api_key,
            },
            client=client,
            settings=settings,
        )
        result = (payload or {}).get("esearchresult") or {}
        notice_pmids = [str(value) for value in result.get("idlist", [])]
        if not notice_pmids:
            continue

        # The search cannot say which DOI in the batch each notice belongs to, so
        # the batch is re-checked one DOI at a time. Only batches with a hit pay
        # this cost, which on a clean corpus is none of them.
        for doi in batch:
            single = get_json(
                f"{EUTILS_BASE}/esearch.fcgi",
                upstream=UPSTREAM,
                params={
                    "db": "pubmed",
                    "term": f'("Retraction of Publication"[Publication Type]) AND ("{doi}"[AID])',
                    "retmode": "json",
                    "email": email,
                    "api_key": api_key,
                },
                client=client,
                settings=settings,
            )
            hits = ((single or {}).get("esearchresult") or {}).get("idlist") or []
            if hits:
                found[doi] = f"PubMed retraction notice PMID {hits[0]}"
                logger.warning("retraction notice found for %s: PMID %s", doi, hits[0])

    return found
