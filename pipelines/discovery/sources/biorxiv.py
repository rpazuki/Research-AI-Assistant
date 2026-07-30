"""bioRxiv / medRxiv — a lookup client, not a search client.

**bioRxiv has no term-search API.** Its endpoints are `details/{server}/{doi}` and
a date-interval listing that pages the entire server; neither can answer "papers
mentioning Yarrowia lipolytica". Term discovery of preprints therefore happens
through Europe PMC (`SRC:PPR`) and OpenAlex, both of which index bioRxiv DOIs —
the same route the original analysis used to find its 13 preprint records.

What bioRxiv uniquely provides is the **preprint → version-of-record link**
(`pubs/{server}/{doi}` → `published_doi`). Without it a preprint and its journal
article are two candidates, which double-counts the corpus and would send the same
paper through acquisition twice.
"""

from __future__ import annotations

import logging

import httpx

from pipelines.discovery.http import HttpSettings, get_json
from pipelines.discovery.sources.base import SourceRecord, coerce_year, normalise_doi

logger = logging.getLogger(__name__)

API_BASE = "https://api.biorxiv.org"
SOURCE = "biorxiv"
UPSTREAM = "bioRxiv"
SERVERS = ("biorxiv", "medrxiv")


def _collection(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    collection = payload.get("collection")
    return [entry for entry in collection if isinstance(entry, dict)] if collection else []


def fetch_details(
    doi: str,
    *,
    servers: tuple[str, ...] = SERVERS,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
) -> SourceRecord | None:
    """Preprint metadata for a bioRxiv/medRxiv DOI, or ``None`` if it is neither.

    The server is not derivable from the DOI (both use the 10.1101 prefix), so each
    is tried in turn; the API answers an unknown DOI with an empty collection.
    """
    cleaned = normalise_doi(doi)
    if not cleaned:
        return None

    for server in servers:
        payload = get_json(
            f"{API_BASE}/details/{server}/{cleaned}",
            upstream=UPSTREAM,
            client=client,
            settings=settings,
            allow_404=True,
        )
        entries = _collection(payload)
        if not entries:
            continue

        # The last entry is the newest version.
        entry = entries[-1]
        return SourceRecord(
            source=SOURCE,
            doi=entry.get("doi") or cleaned,
            title=entry.get("title"),
            abstract=entry.get("abstract"),
            journal=f"{server} (preprint)",
            publisher=server,
            year=coerce_year(entry.get("date")),
            published_date=entry.get("date"),
            types=(str(entry.get("type") or "preprint"),),
            is_preprint=True,
            preprint_doi=entry.get("doi") or cleaned,
            license=entry.get("license"),
            oa_status="open",
            url=f"https://www.{server}.org/content/{cleaned}",
            extra={
                "server": server,
                "version": entry.get("version"),
                "category": entry.get("category"),
                "jatsxml": entry.get("jatsxml"),
            },
        )
    return None


def fetch_version_of_record(
    preprint_doi: str,
    *,
    servers: tuple[str, ...] = SERVERS,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
) -> dict | None:
    """The journal publication of a preprint, if bioRxiv has recorded one.

    Returns ``{'published_doi', 'published_journal', 'published_date'}`` — the
    input ``canonicalize.collapse_preprints`` needs to merge the two records.
    """
    cleaned = normalise_doi(preprint_doi)
    if not cleaned:
        return None

    for server in servers:
        payload = get_json(
            f"{API_BASE}/pubs/{server}/{cleaned}",
            upstream=UPSTREAM,
            client=client,
            settings=settings,
            allow_404=True,
        )
        for entry in _collection(payload):
            published = normalise_doi(entry.get("published_doi"))
            if published:
                return {
                    "published_doi": published,
                    "published_journal": entry.get("published_journal"),
                    "published_date": entry.get("published_date"),
                    "preprint_doi": cleaned,
                    "server": server,
                }
    return None


def is_preprint_doi(doi: str | None) -> bool:
    """bioRxiv and medRxiv both register under the 10.1101 prefix.

    A cheap pre-filter so the lookup is only spent on DOIs that could be preprints
    — bioRxiv's quota is the tightest of any source here (1 req/s).
    """
    cleaned = normalise_doi(doi)
    return bool(cleaned and cleaned.startswith("10.1101/"))
