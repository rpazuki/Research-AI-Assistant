"""Europe PMC discovery.

Two things make this source worth its own client rather than treating it as a
PubMed mirror:

* it indexes **preprints** as `SRC:PPR`, which is how a bioRxiv/medRxiv paper is
  found by search term at all (bioRxiv itself has no term search);
* it carries `commentCorrectionList`, which links a paper to its retraction
  notice — a retraction signal PubMed's publication types alone can miss.

Paging uses `cursorMark`, not an offset: Europe PMC caps offset paging well below
the result counts this corpus produces.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator

import httpx

from pipelines.discovery.http import HttpSettings, get_json
from pipelines.discovery.query_builder import europepmc_query
from pipelines.discovery.sources.base import SourceQuery, SourceRecord, coerce_year

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
SOURCE = "europepmc"
UPSTREAM = "Europe PMC"
PAGE_SIZE = 500

_TAG = re.compile(r"<[^>]+>")
_ENTITY = re.compile(r"&(lt|gt|amp|quot|apos|#\d+);")
_PREPRINT_SOURCES = frozenset({"ppr"})


def _clean(value: object) -> str | None:
    """Europe PMC embeds escaped HTML markup in titles and abstracts."""
    if value is None:
        return None
    text = str(value)
    text = (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )
    text = _TAG.sub("", text)
    return " ".join(text.split()) or None


def _retraction_note(record: dict) -> str | None:
    for entry in (record.get("commentCorrectionList") or {}).get("commentCorrection") or []:
        kind = str(entry.get("type") or "").lower()
        if "retraction" in kind:
            reference = entry.get("id") or entry.get("source") or ""
            return f"Europe PMC {entry.get('type')} {reference}".strip()
    return None


def parse_result(record: dict) -> SourceRecord:
    source_code = str(record.get("source") or "").lower()
    types = tuple(
        str(value)
        for value in ((record.get("pubTypeList") or {}).get("pubType") or [])
        if str(value).strip()
    )
    retraction_note = _retraction_note(record)

    return SourceRecord(
        source=SOURCE,
        doi=record.get("doi"),
        pmid=record.get("pmid"),
        pmc_id=record.get("pmcid"),
        title=_clean(record.get("title")),
        abstract=_clean(record.get("abstractText")),
        journal=_clean((record.get("journalInfo") or {}).get("journal", {}).get("title"))
        or _clean(record.get("journalTitle")),
        year=coerce_year(record.get("pubYear") or record.get("firstPublicationDate")),
        published_date=record.get("firstPublicationDate"),
        types=types,
        is_preprint=source_code in _PREPRINT_SOURCES,
        oa_status="open" if str(record.get("isOpenAccess") or "").upper() == "Y" else None,
        license=record.get("license"),
        is_retracted=bool(retraction_note)
        or any("retracted" in value.lower() for value in types),
        retraction_note=retraction_note,
        url=f"https://europepmc.org/article/{record.get('source')}/{record.get('id')}"
        if record.get("id")
        else None,
        extra={"epmc_source": record.get("source"), "in_pmc": record.get("inPMC")},
    )


def search(
    query: SourceQuery,
    *,
    include_preprints: bool = True,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
) -> Iterator[SourceRecord]:
    term = europepmc_query(query, include_preprints=include_preprints)
    cursor = "*"
    seen = 0

    while True:
        payload = get_json(
            SEARCH_URL,
            upstream=UPSTREAM,
            params={
                "query": term,
                "format": "json",
                "resultType": "core",
                "pageSize": PAGE_SIZE,
                "cursorMark": cursor,
            },
            client=client,
            settings=settings,
        )
        results = ((payload or {}).get("resultList") or {}).get("result") or []
        if not results:
            return

        for record in results:
            yield parse_result(record)
            seen += 1
            if seen >= query.max_records_per_source:
                logger.info("europepmc: stopped at the %d-record cap", seen)
                return

        next_cursor = (payload or {}).get("nextCursorMark")
        # A repeated cursor is Europe PMC's way of saying "no more pages"; without
        # this check the loop re-requests the last page forever.
        if not next_cursor or next_cursor == cursor:
            return
        cursor = next_cursor
