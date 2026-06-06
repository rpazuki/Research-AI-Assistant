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
import os
import time
from collections.abc import Iterator
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from pipelines.corpus_cache import CorpusCache, PARSER_VERSIONS
from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import AuthorRecord
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)

PMC_OA_BASE = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
PMC_IDCONV_BASE = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
PMC_ARTICLE_BASE = "https://pmc.ncbi.nlm.nih.gov/articles"


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
        http_attempts: int = 4,
        http_timeout_s: int = 30,
        retry_backoff_base_s: float = 2.0,
        retry_backoff_max_s: float = 30.0,
        cache: CorpusCache | None = None,
    ) -> None:
        self.pmc_ids = pmc_ids
        self.sleep_s = sleep_s
        self.http_attempts = http_attempts
        self.http_timeout_s = http_timeout_s
        self.retry_backoff_base_s = retry_backoff_base_s
        self.retry_backoff_max_s = retry_backoff_max_s
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
            except Exception as exc:
                logger.error(f"Failed to fetch PMC {pmc_id}: {exc}")
                if self.cache is not None:
                    self.cache.write_document_error(
                        {
                            "source": self.source_name,
                            "identifier": pmc_id,
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                            "access_status": "failed",
                        }
                    )
            finally:
                time.sleep(self.sleep_s)

    def _fetch_one(self, pmc_id: str) -> NormalizedDocument | None:
        """Fetch and parse one PMC article."""
        resolved = self._resolve_to_pmcid(pmc_id)
        if resolved is None:
            logger.warning(f"No PMC record found for identifier {pmc_id}; skipping")
            if self.cache is not None:
                self.cache.write_document_error(
                    {
                        "source": self.source_name,
                        "identifier": pmc_id,
                        "error_type": "no_pmc_record",
                        "message": (
                            "Identifier was not found in PubMed Central. A PubMed record may exist, "
                            "but PMC full-text ingestion requires an article to have a PMCID."
                        ),
                        "access_status": "unavailable",
                    }
                )
            return None

        safe_pmc_id = resolved["pmcid"]
        url = self._oai_url(safe_pmc_id)
        relative_path = f"raw/pmc/xml/{safe_pmc_id}.xml"

        if self.cache is not None and (self.cache.root / relative_path).exists():
            xml_text = (self.cache.root / relative_path).read_text()
            logger.info(f"Using cached PMC XML: {relative_path}")
            source_url = url
            cache_hit = True
        else:
            cache_hit = False
            try:
                xml_text, source_url = self._fetch_xml(url)
            except httpx.HTTPStatusError as exc:
                fallback = self._handle_oai_status_error(exc, pmc_id, safe_pmc_id)
                if fallback is None:
                    return None
                xml_text, source_url = fallback
            if self.cache is not None:
                self.cache.write_bytes(relative_path, xml_text.encode("utf-8"))
                self.cache.record_asset(
                    document_id=f"pmc:{pmc_id}",
                    asset_type="pmc_xml",
                    relative_path=relative_path,
                    source_url=source_url,
                    access_status="open-access",
                    license="open-access",
                    terms_note="PMC Open Access XML",
                    parser_version=PARSER_VERSIONS["pmc_jats"],
                    extra={
                        "requested_identifier": pmc_id,
                        "requested_url": url,
                        "resolved_pmid": resolved.get("pmid"),
                        "id_conversion": resolved,
                    },
                )

        doc = self.parse_xml(xml_text, safe_pmc_id)
        if cache_hit:
            logger.info(f"Parsed cached PMC XML {safe_pmc_id}: {len(xml_text)} chars")
        else:
            logger.info(f"Downloaded PMC XML {safe_pmc_id}: {len(xml_text)} chars")
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
            url=f"{PMC_ARTICLE_BASE}/{pmc_id}/",
            metadata={"access_status": "open-access", "parser_version": PARSER_VERSIONS["pmc_jats"]},
        )

    @staticmethod
    def _safe_pmc_id(pmc_id: str) -> str:
        clean = pmc_id.strip()
        if clean.upper().startswith("PMC"):
            return f"PMC{clean[3:]}"
        return f"PMC{clean}"

    @staticmethod
    def _oai_url(pmc_id: str) -> str:
        numeric_pmc_id = pmc_id.replace("PMC", "", 1)
        return (
            f"{PMC_OA_BASE}?verb=GetRecord"
            f"&identifier=oai:pubmedcentral.nih.gov:{numeric_pmc_id}"
            "&metadataPrefix=pmc"
        )

    def _fetch_xml(self, url: str) -> tuple[str, str]:
        response = self._get_with_backoff(
            url,
            attempts=self.http_attempts,
            timeout_s=self.http_timeout_s,
            retry_backoff_base_s=self.retry_backoff_base_s,
            retry_backoff_max_s=self.retry_backoff_max_s,
        )
        return response.text, str(response.url)

    @classmethod
    def _resolve_to_pmcid(cls, identifier: str) -> dict[str, Any] | None:
        """Resolve PMCID, PMID, DOI, or a mis-prefixed PMID to a PMCID."""
        clean_identifier = identifier.strip()
        if clean_identifier.upper().startswith("PMC") and clean_identifier[3:].isdigit():
            return {"pmcid": cls._safe_pmc_id(clean_identifier)}

        resolved = cls._convert_identifier(clean_identifier)
        if resolved and resolved.get("pmcid"):
            return resolved

        return None

    @staticmethod
    def _convert_identifier(identifier: str, idtype: str | None = None) -> dict[str, Any] | None:
        params: dict[str, str] = {
            "ids": identifier,
            "format": "json",
            "tool": "RLALab_AI_Assistant",
        }
        email = os.environ.get("NCBI_EMAIL")
        if email:
            params["email"] = email
        if idtype:
            params["idtype"] = idtype

        response = PMCFullTextIngester._get_with_backoff(PMC_IDCONV_BASE, params=params)

        payload = response.json()
        records = payload.get("records") or []
        if not records:
            return None
        record = records[0]
        if not record.get("pmcid"):
            return None
        return record

    @staticmethod
    def _get_with_backoff(
        url: str,
        *,
        params: dict[str, str] | None = None,
        attempts: int = 4,
        timeout_s: int = 30,
        retry_backoff_base_s: float = 2.0,
        retry_backoff_max_s: float = 30.0,
    ) -> httpx.Response:
        last_error: httpx.HTTPStatusError | None = None
        with httpx.Client(timeout=timeout_s, follow_redirects=True, headers={"Accept-Encoding": "gzip, deflate"}) as client:
            for attempt in range(attempts):
                response = client.get(url, params=params)
                if response.status_code != 429:
                    response.raise_for_status()
                    return response

                last_error = httpx.HTTPStatusError(
                    "429 Too Many Requests",
                    request=response.request,
                    response=response,
                )
                retry_after = response.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    sleep_s = float(retry_after)
                else:
                    sleep_s = min(retry_backoff_max_s, retry_backoff_base_s * (2 ** attempt))
                logger.warning("PMC request rate-limited; sleeping %.1fs before retry", sleep_s)
                time.sleep(sleep_s)

        if last_error is not None:
            raise last_error
        raise RuntimeError("PMC request failed before a response was returned")

    def _handle_oai_status_error(
        self,
        exc: httpx.HTTPStatusError,
        requested_identifier: str,
        pmc_id: str,
    ) -> tuple[str, str] | None:
        status_code = exc.response.status_code
        response_text = exc.response.text[:1000]

        if status_code == 400:
            message = (
                "PMC OAI did not return reusable full-text XML for this PMCID. "
                "The article may be in PMC but outside the OAI full-text reuse subset."
            )
            logger.warning("%s %s: %s", message, pmc_id, response_text)
            if self.cache is not None:
                self.cache.write_document_error(
                    {
                        "source": self.source_name,
                        "identifier": requested_identifier,
                        "pmc_id": pmc_id,
                        "error_type": "pmc_oai_fulltext_unavailable",
                        "status_code": status_code,
                        "message": message,
                        "response_text": response_text,
                        "access_status": "unavailable",
                    }
                )
            return None

        raise exc
