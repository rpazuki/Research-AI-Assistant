"""
pipelines/ingestion/pmc_fulltext.py
-------------------------------------
PubMed Central full-text ingester (Open Access subset only).

Uses the PMC OA API to fetch full-text XML for open-access articles.
IMPORTANT: Only open-access articles are retrievable. Always check
the license field before ingesting.

This ingester is designed to complement pubmed_abstract.py:
  - Start with abstract ingestion to build the initial index.
  - Run PMC full-text ingestion selectively for articles where full text
    is available and relevant (e.g. methods/results sections for the lab's
    core organisms: Y. lipolytica, E. coli, S. cerevisiae).

PMC OA API docs:
    https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/

IMPLEMENTER NOTE:
    This is a skeleton. The full XML parsing of PMC JATS format is non-trivial.
    Consider using the `pymed` or `pubmed-parser` libraries, or write a custom
    JATS parser targeting the sections you need (Abstract, Intro, Methods, Results).
"""

import logging
import time
from collections.abc import Iterator
from xml.etree import ElementTree as ET

import httpx

from pipelines.corpus_cache import CorpusCache, PARSER_VERSIONS
from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import AuthorRecord
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)

PMC_OA_BASE = "https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi"


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


def _iter_elements(root: ET.Element, name: str):
    for element in root.iter():
        if _local_name(element.tag) == name:
            yield element


def _find_first(root: ET.Element, name: str) -> ET.Element | None:
    return next(_iter_elements(root, name), None)


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return _normalize_space(" ".join(text for text in element.itertext()))


def _extract_metadata(xml_text: str) -> dict[str, object]:
    root = ET.fromstring(xml_text)

    article = _find_first(root, "article")
    if article is None:
        raise ValueError("PMC response did not contain an article element")

    title = _element_text(_find_first(article, "article-title")) or None
    abstract = _element_text(_find_first(article, "abstract")) or None

    pmid = None
    doi = None
    for article_id in _iter_elements(article, "article-id"):
        id_type = article_id.attrib.get("pub-id-type", "")
        value = _element_text(article_id) or None
        if id_type == "pmid":
            pmid = value
        elif id_type == "doi":
            doi = value

    keywords = [
        keyword
        for keyword in (_element_text(kwd) for kwd in _iter_elements(article, "kwd"))
        if keyword
    ]

    license_text = _element_text(_find_first(article, "license-p")) or None
    journal = _element_text(_find_first(article, "journal-title")) or None

    year = None
    pub_year = _element_text(_find_first(article, "year"))
    if pub_year.isdigit():
        year = int(pub_year)

    authors: list[AuthorRecord] = []
    for contrib in _iter_elements(article, "contrib"):
        if contrib.attrib.get("contrib-type") != "author":
            continue
        name = _find_first(contrib, "name")
        surname = _element_text(_find_first(name, "surname")) if name is not None else ""
        given_names = _element_text(_find_first(name, "given-names")) if name is not None else ""
        if surname or given_names:
            initials = "".join(part[0] for part in given_names.split() if part)
            authors.append(
                AuthorRecord(
                    last_name=surname,
                    fore_name=given_names,
                    initials=initials,
                )
            )

    return {
        "title": title,
        "abstract": abstract,
        "pmid": pmid,
        "doi": doi,
        "keywords": keywords,
        "license": license_text,
        "journal": journal,
        "year": year,
        "authors": authors,
    }


def _extract_article_text(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    article = _find_first(root, "article")
    if article is None:
        raise ValueError("PMC response did not contain an article element")

    body = _find_first(article, "body")
    if body is None:
        return ""

    sections: list[str] = []
    for sec in _iter_elements(body, "sec"):
        title = _element_text(_find_first(sec, "title"))
        paragraphs = [
            paragraph
            for paragraph in (_element_text(p) for p in _iter_elements(sec, "p"))
            if paragraph
        ]
        if not title and not paragraphs:
            continue

        section_lines: list[str] = []
        if title:
            section_lines.append(title)
        section_lines.extend(paragraphs)
        sections.append("\n".join(section_lines))

    return "\n\n".join(section for section in sections if section).strip()


class PMCFullTextIngester(BaseIngester):
    """
    Fetch open-access full text from PubMed Central.

    Typical use: provide a list of PMC IDs to fetch, or integrate with
    the PubMed abstract pipeline to fetch full text for articles that
    were already ingested at abstract level.
    """
    source_name = "pmc"

    def __init__(
        self,
        pmc_ids: list[str],
        sleep_s: float = 0.5,
        cache: CorpusCache | None = None,
    ) -> None:
        self.pmc_ids = pmc_ids
        self.sleep_s = sleep_s
        self.cache = cache

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "pmc_id_count": len(self.pmc_ids),
        }

    def fetch(self) -> Iterator[NormalizedDocument]:
        """
        Yield NormalizedDocument objects with full_text populated.

        STUB: Full JATS XML parsing not yet implemented.
        Each yielded document has full_text set to the raw XML for now.
        The implementing agent should add proper section extraction.
        """
        for pmc_id in self.pmc_ids:
            try:
                doc = self._fetch_one(pmc_id)
                if doc is not None:
                    if self.cache is not None:
                        self.cache.write_document(
                            doc,
                            raw_asset_path=f"raw/pmc/xml/{self._safe_pmc_id(pmc_id)}.xml",
                            access_status="open-access",
                            parser_version=PARSER_VERSIONS["pmc_jats"],
                        )
                    yield doc
                time.sleep(self.sleep_s)
            except Exception as exc:
                logger.error(f"Failed to fetch PMC {pmc_id}: {exc}")

    def _fetch_one(self, pmc_id: str) -> NormalizedDocument | None:
        """Fetch and parse one PMC article."""
        url = f"{PMC_OA_BASE}?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:{pmc_id.replace('PMC', '')}&metadataPrefix=pmc"
        safe_pmc_id = self._safe_pmc_id(pmc_id)
        relative_path = f"raw/pmc/xml/{safe_pmc_id}.xml"

        if self.cache is not None and (self.cache.root / relative_path).exists():
            xml_text = (self.cache.root / relative_path).read_text()
            logger.info(f"Using cached PMC XML: {relative_path}")
        else:
            with httpx.Client(timeout=30) as client:
                response = client.get(url)
                response.raise_for_status()
            xml_text = response.text
            if self.cache is not None:
                self.cache.write_bytes(relative_path, xml_text.encode("utf-8"))
                self.cache.record_asset(
                    document_id=f"pmc:{pmc_id}",
                    asset_type="pmc_xml",
                    relative_path=relative_path,
                    source_url=url,
                    access_status="open-access",
                    license="open-access",
                    terms_note="PMC Open Access XML",
                    parser_version=PARSER_VERSIONS["pmc_jats"],
                )

        doc = self.parse_xml(xml_text, safe_pmc_id)
        logger.info(f"Fetched PMC {pmc_id}: {len(xml_text)} chars")
        return doc

    @staticmethod
    def parse_xml(xml_text: str, pmc_id: str) -> NormalizedDocument:
        """Parse cached or freshly fetched PMC JATS XML into a normalized document."""
        metadata = _extract_metadata(xml_text)
        full_text = _extract_article_text(xml_text)

        return NormalizedDocument(
            document_id=f"pmc:{pmc_id}",
            source="pmc",
            title=metadata["title"],
            abstract=metadata["abstract"],
            authors=metadata["authors"],
            journal=metadata["journal"],
            year=metadata["year"],
            doi=metadata["doi"],
            pmid=metadata["pmid"],
            pmc_id=pmc_id,
            full_text=full_text,
            keywords=metadata["keywords"],
            license=metadata["license"] or "open-access",
            url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/",
            metadata={"access_status": "open-access", "parser_version": PARSER_VERSIONS["pmc_jats"]},
        )

    @staticmethod
    def _safe_pmc_id(pmc_id: str) -> str:
        return pmc_id if pmc_id.startswith("PMC") else f"PMC{pmc_id}"
