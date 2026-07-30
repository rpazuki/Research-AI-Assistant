"""PubMed discovery via E-utilities.

esearch collects PMIDs with the history server, then efetch pulls records in
batches. efetch (not esummary) because the rule relevance pass needs abstracts,
and esummary does not carry them.

Parsed with ElementTree rather than Biopython: this module must stay importable
from the backend without pulling the ingestion stack, and the fields needed here
are a small, stable subset of the PubMed DTD.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterator

import httpx

from pipelines.discovery.http import DiscoveryLookupError, HttpSettings, get, get_json
from pipelines.discovery.sources.base import SourceRecord, SourceQuery, coerce_year
from pipelines.discovery.query_builder import pubmed_query

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SOURCE = "pubmed"
UPSTREAM = "PubMed"
BATCH_SIZE = 200

# PubMed marks a retracted paper with this publication type on the paper itself.
RETRACTED_TYPE = "Retracted Publication"
# ...and the notice is a separate record with this type. Notices are not corpus
# candidates, so they are dropped rather than scored.
NOTICE_TYPES = frozenset({"Retraction of Publication", "Published Erratum"})


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    # itertext keeps the content of inline markup (<i>, <sup>) that PubMed uses
    # inside titles and abstracts; element.text alone would truncate at the tag.
    joined = " ".join(part.strip() for part in element.itertext() if part.strip())
    return joined or None


def _abstract_text(article_node: ET.Element) -> str | None:
    """Join labelled abstract sections, keeping the labels.

    A structured abstract's labels ("RESULTS:", "CONCLUSIONS:") are signal for the
    relevance pass, which cares where a term appears.
    """
    parts: list[str] = []
    for node in article_node.findall("Abstract/AbstractText"):
        label = node.get("Label")
        body = _text(node)
        if not body:
            continue
        parts.append(f"{label}: {body}" if label else body)
    return "\n".join(parts) or None


def parse_efetch_xml(xml_text: str) -> list[SourceRecord]:
    """Parse one efetch batch. Retraction notices are dropped, retracted papers kept."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DiscoveryLookupError(UPSTREAM, f"efetch returned unparseable XML: {exc}") from exc

    records: list[SourceRecord] = []
    for article in root.findall(".//PubmedArticle"):
        citation_node = article.find("MedlineCitation")
        if citation_node is None:
            continue
        types = tuple(
            value
            for value in (
                _text(node)
                for node in citation_node.findall("Article/PublicationTypeList/PublicationType")
            )
            if value
        )
        if any(value in NOTICE_TYPES for value in types):
            continue

        # Scoped to PubmedData, never `.//`: efetch embeds the paper's whole
        # reference list, each reference carrying its own ArticleIdList. A
        # descendant search picks those up and the last one wins, so the record
        # ends up labelled with a *cited* paper's DOI. That silently mislabels
        # most PMC-deposited records.
        own_ids = article.find("PubmedData/ArticleIdList")
        ids = {
            (node.get("IdType") or "").lower(): (node.text or "").strip()
            for node in (own_ids.findall("ArticleId") if own_ids is not None else [])
        }
        article_node = citation_node.find("Article")
        if article_node is None:
            continue

        # Some records carry the DOI only as an ELocationID.
        doi = ids.get("doi") or article_node.findtext("ELocationID[@EIdType='doi']")
        journal = _text(article_node.find("Journal/Title"))
        pub_date = article_node.find("Journal/JournalIssue/PubDate")
        year = coerce_year(_text(pub_date) if pub_date is not None else None)

        records.append(
            SourceRecord(
                source=SOURCE,
                doi=doi,
                pmid=ids.get("pubmed") or _text(citation_node.find("PMID")),
                pmc_id=ids.get("pmc"),
                title=_text(article_node.find("ArticleTitle")),
                abstract=_abstract_text(article_node),
                journal=journal,
                year=year,
                published_date=_text(article_node.find("ArticleDate")),
                types=types,
                mesh_terms=tuple(
                    value
                    for value in (
                        _text(node)
                        for node in citation_node.findall(
                            "MeshHeadingList/MeshHeading/DescriptorName"
                        )
                    )
                    if value
                ),
                keywords=tuple(
                    value
                    for value in (
                        _text(node) for node in citation_node.findall("KeywordList/Keyword")
                    )
                    if value
                ),
                is_retracted=RETRACTED_TYPE in types,
                retraction_note=(
                    "PubMed publication type 'Retracted Publication'"
                    if RETRACTED_TYPE in types
                    else None
                ),
            )
        )
    return records


def search(
    query: SourceQuery,
    *,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    email: str | None = None,
    api_key: str | None = None,
) -> Iterator[SourceRecord]:
    """Yield PubMed records for the query, newest batch first."""
    term = pubmed_query(query)
    credentials = {"email": email, "api_key": api_key}

    payload = get_json(
        f"{EUTILS_BASE}/esearch.fcgi",
        upstream=UPSTREAM,
        params={
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "retmax": query.max_records_per_source,
            **credentials,
        },
        client=client,
        settings=settings,
    )
    result = (payload or {}).get("esearchresult") or {}
    pmids = [str(value) for value in result.get("idlist", [])]
    logger.info("pubmed: %s hits, fetching %d", result.get("count"), len(pmids))

    for start in range(0, len(pmids), BATCH_SIZE):
        batch = pmids[start : start + BATCH_SIZE]
        response = get(
            f"{EUTILS_BASE}/efetch.fcgi",
            upstream=UPSTREAM,
            params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml", **credentials},
            client=client,
            settings=settings,
        )
        if response is None:
            continue
        yield from parse_efetch_xml(response.text)
