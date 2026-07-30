"""OpenAlex discovery — phrase-aware search with the widest coverage.

On the Yarrowia seed OpenAlex returns roughly twice what PubMed does, and unlike
Crossref its `title_and_abstract.search` filter is phrase-aware, so precision is
usable without local filtering. It also carries two fields no other source gives
in the same request: `is_retracted` and a resolved `oa_status`.

Abstracts arrive as an inverted index (word → positions) rather than text, so they
are reconstructed here; ``relevance.py`` needs running text.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import httpx

from pipelines.discovery.http import HttpSettings, get_json
from pipelines.discovery.query_builder import openalex_filter
from pipelines.discovery.sources.base import SourceQuery, SourceRecord, coerce_year

logger = logging.getLogger(__name__)

WORKS_URL = "https://api.openalex.org/works"
SOURCE = "openalex"
UPSTREAM = "OpenAlex"
PAGE_SIZE = 200

# OpenAlex `type` values that are not research papers.
_PREPRINT_TYPES = frozenset({"preprint"})
_NON_ARTICLE_TYPES = frozenset(
    {"paratext", "editorial", "erratum", "letter", "peer-review", "grant", "retraction"}
)


def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Rebuild running text from OpenAlex's word→positions map.

    Positions are authoritative, and gaps are possible (OpenAlex omits some
    tokens), so the words are placed by index and joined in position order rather
    than assuming a contiguous range.
    """
    if not inverted_index:
        return None

    positions: list[tuple[int, str]] = []
    for word, indices in inverted_index.items():
        for index in indices or []:
            if isinstance(index, int):
                positions.append((index, str(word)))
    if not positions:
        return None

    positions.sort()
    return " ".join(word for _index, word in positions) or None


def parse_work(work: dict) -> SourceRecord:
    primary = work.get("primary_location") or {}
    source_info = primary.get("source") or {}
    ids = work.get("ids") or {}
    work_type = str(work.get("type") or "")

    return SourceRecord(
        source=SOURCE,
        doi=work.get("doi"),
        pmid=ids.get("pmid"),
        pmc_id=ids.get("pmcid"),
        title=work.get("title") or work.get("display_name"),
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        journal=source_info.get("display_name"),
        publisher=source_info.get("host_organization_name"),
        year=coerce_year(work.get("publication_year")),
        published_date=work.get("publication_date"),
        types=(work_type,) + ((work.get("type_crossref"),) if work.get("type_crossref") else ()),
        is_preprint=work_type in _PREPRINT_TYPES,
        oa_status=(work.get("open_access") or {}).get("oa_status"),
        license=primary.get("license"),
        keywords=tuple(
            str(entry.get("display_name"))
            for entry in (work.get("keywords") or [])
            if entry.get("display_name")
        ),
        is_retracted=bool(work.get("is_retracted")),
        retraction_note="OpenAlex is_retracted" if work.get("is_retracted") else None,
        url=primary.get("landing_page_url") or ids.get("openalex"),
        extra={
            "is_paratext": bool(work.get("is_paratext")),
            "non_article_type": work_type in _NON_ARTICLE_TYPES,
            "cited_by_count": work.get("cited_by_count"),
        },
    )


def search(
    query: SourceQuery,
    *,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    mailto: str | None = None,
) -> Iterator[SourceRecord]:
    filters = openalex_filter(query)
    cursor = "*"
    seen = 0

    while True:
        payload = get_json(
            WORKS_URL,
            upstream=UPSTREAM,
            params={
                "filter": filters,
                "per_page": PAGE_SIZE,
                "cursor": cursor,
                "mailto": mailto,
            },
            client=client,
            settings=settings,
        )
        results = (payload or {}).get("results") or []
        if not results:
            return

        for work in results:
            yield parse_work(work)
            seen += 1
            if seen >= query.max_records_per_source:
                logger.info("openalex: stopped at the %d-record cap", seen)
                return

        next_cursor = ((payload or {}).get("meta") or {}).get("next_cursor")
        if not next_cursor or next_cursor == cursor:
            return
        cursor = next_cursor
