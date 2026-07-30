"""Crossref discovery — the coverage source, at the cost of precision.

Crossref indexes the chemical-engineering and food-science journals that PubMed
does not, which is where much of the 28% PubMed-missing slice of this corpus
lives. It has no field-restricted phrase search: `query.bibliographic` is fuzzy
and relevance-ranked, so a query for "Yarrowia lipolytica" returns a Russian
history-of-science article in its first page of hits. That noise is expected and
is removed locally by ``relevance.py`` — one query per term, filter afterwards.

`mailto` puts the requests in Crossref's polite pool.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator

import httpx

from pipelines.discovery.http import HttpSettings, get_json
from pipelines.discovery.query_builder import crossref_filter, crossref_queries
from pipelines.discovery.relevance import count_hits
from pipelines.discovery.sources.base import SourceQuery, SourceRecord, coerce_year

logger = logging.getLogger(__name__)

WORKS_URL = "https://api.crossref.org/works"
SOURCE = "crossref"
UPSTREAM = "Crossref"
PAGE_SIZE = 200
# Crossref's documented offset ceiling. A term with more results than this is
# reported as truncated rather than quietly cut short.
MAX_OFFSET = 10000
# Floor on the per-term budget, so a seed with many synonyms still walks each one
# deep enough to be useful.
MIN_PER_TERM = 1200
# Crossref sorts by relevance, so once whole pages stop mentioning the term at all
# the tail is noise. Stopping after this many consecutive barren pages keeps the
# precise term's recall without paying for the fuzzy tail.
MAX_BARREN_PAGES = 3

_JATS_TAG = re.compile(r"<[^>]+>")
# Crossref types that are not research papers. `posted-content` is a preprint.
_PREPRINT_TYPES = frozenset({"posted-content"})
_REVIEW_HINTS = frozenset({"review-article", "book-review"})


def _clean_abstract(value: object) -> str | None:
    """Crossref abstracts are JATS fragments."""
    if not value:
        return None
    text = _JATS_TAG.sub(" ", str(value))
    text = text.replace("Abstract", "", 1) if text.strip().startswith("Abstract") else text
    return " ".join(text.split()) or None


def _first(value: object) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None


def _mentions_term(record: SourceRecord, term: str) -> bool:
    """Does this record's own text mention the term Crossref matched it against?

    Crossref scores the words of a phrase separately, so a page of hits can contain
    nothing that names the term. Used only to decide when to stop paging — the real
    relevance verdict is `relevance.py`, after merging.
    """
    hits, _matched = count_hits(record.searchable_text, (term,))
    return hits > 0


def _issued_year(item: dict) -> int | None:
    for key in ("issued", "published", "published-print", "published-online", "created"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return coerce_year(parts[0][0])
    return None


def parse_item(item: dict) -> SourceRecord:
    item_type = str(item.get("type") or "")
    # `update-to` with a "retraction" type is Crossref's retraction linkage; a
    # retracted paper's own record is often not otherwise marked.
    retraction_note: str | None = None
    for update in item.get("update-to") or []:
        if "retract" in str(update.get("type") or "").lower():
            retraction_note = f"Crossref update-to {update.get('type')} {update.get('DOI') or ''}".strip()
            break

    return SourceRecord(
        source=SOURCE,
        doi=item.get("DOI"),
        title=_first(item.get("title")),
        abstract=_clean_abstract(item.get("abstract")),
        journal=_first(item.get("container-title")),
        publisher=item.get("publisher"),
        year=_issued_year(item),
        types=(item_type,) + ((item.get("subtype"),) if item.get("subtype") else ()),
        is_preprint=item_type in _PREPRINT_TYPES,
        version_of_record_doi=next(
            (
                relation.get("id")
                for relation in (item.get("relation") or {}).get("is-preprint-of") or []
                if relation.get("id")
            ),
            None,
        ),
        is_retracted=bool(retraction_note),
        retraction_note=retraction_note,
        url=item.get("URL"),
        extra={"score": item.get("score"), "is_review_type": item_type in _REVIEW_HINTS},
    )


def search(
    query: SourceQuery,
    *,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    mailto: str | None = None,
) -> Iterator[SourceRecord]:
    """Yield Crossref records, one deep-paged query per term."""
    filters = crossref_filter(query)
    budget = query.max_records_per_source
    terms = crossref_queries(query)
    # Per-term budget, so one noisy synonym cannot consume the whole source. The
    # concrete case: `Candida lipolytica` matches 27,471 Crossref records because
    # the bibliographic index scores the words separately, which would starve every
    # later term of budget.
    per_term_budget = max(MIN_PER_TERM, query.max_records_per_source // max(1, len(terms)))

    for term in terms:
        offset = 0
        for_term = 0
        barren_pages = 0
        total: int | None = None

        while budget > 0 and for_term < per_term_budget:
            payload = get_json(
                WORKS_URL,
                upstream=UPSTREAM,
                params={
                    "query.bibliographic": term,
                    "filter": filters,
                    "rows": PAGE_SIZE,
                    # Offset, not cursor: with `query.bibliographic` Crossref returns
                    # the *same* `next-cursor` on the second page, so a cursor walk
                    # silently stops after 400 records. Offset paging advances
                    # correctly and is documented up to offset 10000.
                    "offset": offset,
                    "mailto": mailto,
                },
                client=client,
                settings=settings,
            )
            message = (payload or {}).get("message") or {}
            items = message.get("items") or []
            if total is None:
                total = message.get("total-results")
            if not items:
                break

            page_hits = 0
            for item in items:
                record = parse_item(item)
                if _mentions_term(record, term):
                    page_hits += 1
                yield record
                for_term += 1
                budget -= 1
                if budget <= 0 or for_term >= per_term_budget:
                    break

            barren_pages = 0 if page_hits else barren_pages + 1
            if barren_pages >= MAX_BARREN_PAGES:
                logger.info(
                    "crossref: term %r produced %d consecutive pages with no textual match "
                    "(of %s reported results); stopping this term",
                    term,
                    barren_pages,
                    total,
                )
                break

            offset += PAGE_SIZE
            if offset >= MAX_OFFSET:
                # Never a silent truncation: what was dropped is stated.
                logger.warning(
                    "crossref: term %r has %s results but offset paging stops at %d — "
                    "%s records not retrieved",
                    term,
                    total,
                    MAX_OFFSET,
                    (total - MAX_OFFSET) if isinstance(total, int) else "an unknown number of",
                )
                break
            if isinstance(total, int) and offset >= total:
                break

        logger.info(
            "crossref: %d of %s records for term %r%s",
            for_term,
            total,
            term,
            " (per-term budget reached)" if for_term >= per_term_budget else "",
        )
        if budget <= 0:
            logger.info("crossref: stopped at the per-source cap")
            return
