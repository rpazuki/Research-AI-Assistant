"""
pipelines/ingestion/discovery_search.py
-----------------------------------------
Multi-source literature search as a corpus source.

PubMed indexes a large part of this lab's literature, but not all of it: a
measured Yarrowia run found 97% of the gold papers PubMed misses, mostly through
Crossref and OpenAlex (docs/DATASHEET_FEATURE_PLAN.md §8). This ingester reuses
the datasheet discovery engine — the same search, canonicalisation, preprint
collapse, doc-type and relevance judgements — and turns its candidates into
corpus documents.

It deliberately owns none of that logic. Everything below the query is
`pipelines.discovery`, so a fix to a source parser or a dedupe rule reaches the
corpus and the datasheet at once.

Usage:
    ingester = DiscoverySearchIngester.from_config("configs/discovery.multisource.rlalab.toml")
    for doc in ingester.fetch():
        process(doc)
"""

import json
import logging
import os
from collections.abc import Iterator
from dataclasses import asdict
from datetime import date

from pipelines.corpus_cache import PARSER_VERSIONS, CorpusCache
from pipelines.discovery.discover import (
    ALL_SOURCES,
    DiscoveryCredentials,
    DiscoveryResult,
    discover,
    included_candidates,
)
from pipelines.discovery.canonicalize import Candidate
from pipelines.discovery.http import HttpSettings
from pipelines.discovery.manifest_csv import write_manifest_csv
from pipelines.discovery.sources.base import SourceQuery
from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)

CANDIDATES_PATH = "raw/discovery/candidates.jsonl"
SUMMARY_PATH = "raw/discovery/summary.json"
MANIFEST_CSV_PATH = "reports/discovery_manifest.csv"


def candidate_to_document(candidate: Candidate) -> NormalizedDocument:
    """Map one merged candidate onto the corpus document schema.

    `document_id` prefers the PMID so a paper found by both this source and the
    PubMed ingester lands on one row (`documents.document_id` is UNIQUE) instead
    of being indexed twice under two identifiers.
    """
    if candidate.pmid:
        document_id = f"pmid:{candidate.pmid}"
    elif candidate.doi:
        document_id = f"doi:{candidate.doi}"
    elif candidate.pmc_id:
        document_id = f"pmc:{candidate.pmc_id}"
    else:
        # canonicalise() keeps identifier-less records as their own candidates,
        # so this is reachable. A title hash is a stable id for such a row and
        # never collides with a registrar-assigned one.
        from pipelines.corpus_cache import sha256_bytes

        document_id = f"discovery:{sha256_bytes((candidate.title or '').encode('utf-8'))[:32]}"

    url = candidate.url or (f"https://doi.org/{candidate.doi}" if candidate.doi else None)

    return NormalizedDocument(
        document_id=document_id,
        source="discovery",
        title=candidate.title,
        abstract=candidate.abstract,
        journal=candidate.journal,
        publication_date=_parse_published_date(candidate.published_date),
        year=candidate.year,
        doi=candidate.doi,
        pmid=candidate.pmid,
        pmc_id=candidate.pmc_id,
        mesh_terms=list(candidate.mesh_terms),
        keywords=list(candidate.keywords),
        url=url,
        license=candidate.license,
        publisher=candidate.publisher,
        oa_status=candidate.oa_status,
        doc_type=candidate.doc_type,
        is_review=bool(candidate.is_review),
        is_retracted=bool(candidate.is_retracted),
        preprint_of_doi=candidate.version_of_record_doi if candidate.is_preprint else None,
        full_text_source="abstract_only",
        metadata={
            "found_in": list(candidate.found_in),
            "relevance": candidate.relevance,
            "relevance_reason": candidate.relevance_reason,
            "dedupe_group": candidate.dedupe_group,
            "merged_identifiers": list(candidate.merged_identifiers),
            "is_preprint": bool(candidate.is_preprint),
            "retraction_note": candidate.retraction_note,
            "access_status": "metadata-only",
            "source_system": "discovery",
            "parser_version": PARSER_VERSIONS["discovery"],
        },
    )


def _parse_published_date(value: str | None) -> date | None:
    """Sources format dates several ways; only a full ISO date is usable here."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class DiscoverySearchIngester(BaseIngester):
    source_name = "discovery"

    def __init__(
        self,
        organism_terms: list[str],
        product_terms: list[str] | None = None,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        sources: tuple[str, ...] = ALL_SOURCES,
        max_records_per_source: int = 5000,
        include_mentions: bool = False,
        include_reviews: bool = False,
        collapse_preprint_versions: bool = True,
        check_retraction_notices: bool = False,
        credentials: DiscoveryCredentials | None = None,
        http_settings: HttpSettings | None = None,
        cache: CorpusCache | None = None,
    ) -> None:
        self.organism_terms = list(organism_terms or [])
        self.product_terms = list(product_terms or [])
        self.year_from = year_from
        self.year_to = year_to
        self.sources = tuple(sources)
        self.max_records_per_source = max_records_per_source
        self.include_mentions = include_mentions
        self.include_reviews = include_reviews
        self.collapse_preprint_versions = collapse_preprint_versions
        self.check_retraction_notices = check_retraction_notices
        self.credentials = credentials or DiscoveryCredentials()
        self.http_settings = http_settings
        self.cache = cache

    @classmethod
    def from_config(
        cls,
        config_path: str,
        cache: CorpusCache | None = None,
    ) -> "DiscoverySearchIngester":
        """Instantiate from a TOML config file."""
        from dotenv import load_dotenv

        from pipelines.config import load_pipeline_config

        load_dotenv()
        cfg = load_pipeline_config(config_path)
        discovery_cfg = cfg.get("discovery", {})

        contact = discovery_cfg.get("ncbi_email") or os.environ.get("NCBI_EMAIL")
        credentials = DiscoveryCredentials(
            ncbi_email=contact,
            ncbi_api_key=discovery_cfg.get("ncbi_api_key") or os.environ.get("NCBI_API_KEY"),
            # Crossref and OpenAlex ask for a contact address to grant polite-pool
            # rates. Neither is a secret, and the NCBI address is the one that is
            # always configured — same fallback the datasheet service uses.
            crossref_mailto=discovery_cfg.get("crossref_mailto") or contact,
            openalex_mailto=discovery_cfg.get("openalex_mailto") or contact,
        )

        http_cfg = discovery_cfg.get("http", {})
        http_settings = (
            HttpSettings(
                timeout_s=float(http_cfg.get("timeout_s", 30.0)),
                max_attempts=int(http_cfg.get("attempts", 3)),
            )
            if http_cfg
            else None
        )

        return cls(
            organism_terms=list(discovery_cfg.get("organism_terms", [])),
            product_terms=list(discovery_cfg.get("product_terms", [])),
            year_from=discovery_cfg.get("year_from"),
            year_to=discovery_cfg.get("year_to"),
            sources=tuple(discovery_cfg.get("sources", ALL_SOURCES)),
            max_records_per_source=int(discovery_cfg.get("max_records_per_source", 5000)),
            include_mentions=bool(discovery_cfg.get("include_mentions", False)),
            include_reviews=bool(discovery_cfg.get("include_reviews", False)),
            collapse_preprint_versions=bool(discovery_cfg.get("collapse_preprint_versions", True)),
            check_retraction_notices=bool(discovery_cfg.get("check_retraction_notices", False)),
            credentials=credentials,
            http_settings=http_settings,
            cache=cache,
        )

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "organism_terms": self.organism_terms,
            "product_terms": self.product_terms,
            "sources": list(self.sources),
            "year_from": self.year_from,
            "year_to": self.year_to,
            "max_records_per_source": self.max_records_per_source,
        }

    def build_query(self) -> SourceQuery:
        return SourceQuery(
            organism_terms=tuple(self.organism_terms),
            product_terms=tuple(self.product_terms),
            year_from=self.year_from,
            year_to=self.year_to,
            max_records_per_source=self.max_records_per_source,
        )

    def fetch(self) -> Iterator[NormalizedDocument]:
        query = self.build_query()
        query.require_terms()

        result = discover(
            query,
            sources=self.sources,
            credentials=self.credentials,
            include_mentions=self.include_mentions,
            collapse_preprint_versions=self.collapse_preprint_versions,
            check_retraction_notices=self.check_retraction_notices,
            settings=self.http_settings,
        )
        logger.info(
            "discovery: %d source records -> %d candidates (%s)",
            result.total_source_records,
            len(result.candidates),
            ", ".join(f"{name}={count}" for name, count in result.source_record_counts.items()),
        )
        for name, error in result.source_errors.items():
            # A source that failed is partial coverage, not an empty result. Say so
            # loudly: a silent zero makes a recall number mean something it does not.
            logger.warning("discovery: source %s returned no records: %s", name, error)

        self._write_audit_artifacts(result)

        keep = included_candidates(
            result,
            include_mentions=self.include_mentions,
            include_reviews=self.include_reviews,
        )
        logger.info("discovery: %d of %d candidates included", len(keep), len(result.candidates))

        normalized_count = 0
        without_abstract = 0
        for candidate in keep:
            doc = candidate_to_document(candidate)
            if not doc.abstract:
                without_abstract += 1
            normalized_count += 1
            if self.cache is not None:
                self.cache.write_document(
                    doc,
                    raw_asset_path=CANDIDATES_PATH,
                    access_status="metadata-only",
                    parser_version=PARSER_VERSIONS["discovery"],
                )
            yield doc

        if without_abstract:
            # Crossref-only rows routinely have no abstract. They are still worth
            # indexing (title + identifiers make them findable and citable), but
            # the count belongs in the log rather than in a silent truncation.
            logger.warning(
                "discovery: %d of %d included candidates had no abstract; "
                "those documents are indexed from their title alone",
                without_abstract,
                normalized_count,
            )

        if self.cache is not None:
            self.cache.update_counts(
                raw_records=result.total_source_records,
                normalized_documents=normalized_count,
            )
            self.cache.refresh_counts_from_artifacts()

    def _write_audit_artifacts(self, result: DiscoveryResult) -> None:
        """Persist what was found and why, before any of it is filtered."""
        if self.cache is None:
            return

        included_dois = {
            candidate.doi
            for candidate in included_candidates(
                result,
                include_mentions=self.include_mentions,
                include_reviews=self.include_reviews,
            )
            if candidate.doi
        }

        self.cache.append_jsonl(
            CANDIDATES_PATH,
            [_candidate_to_cache_record(candidate) for candidate in result.candidates],
        )
        self.cache.write_json(SUMMARY_PATH, result.summary())
        self.cache.write_bytes(
            MANIFEST_CSV_PATH,
            write_manifest_csv(result.candidates, included_dois=included_dois).encode("utf-8"),
        )
        self.cache.record_asset(
            document_id=None,
            asset_type="discovery_candidates",
            relative_path=CANDIDATES_PATH,
            source_url=None,
            access_status="metadata-only",
            license="metadata-only",
            terms_note="Bibliographic metadata from PubMed, Europe PMC, Crossref and OpenAlex",
            parser_version=PARSER_VERSIONS["discovery"],
            source_system="discovery",
        )


def _candidate_to_cache_record(candidate: Candidate) -> dict:
    """A candidate as plain JSON, so a local-only rebuild can replay it."""
    record = asdict(candidate)
    for key, value in list(record.items()):
        if isinstance(value, tuple):
            record[key] = list(value)
    # `extra` carries whatever a source attached; keep only what survives JSON.
    try:
        json.dumps(record["extra"])
    except (TypeError, ValueError):
        record["extra"] = {}
    return record


def candidate_from_cache_record(record: dict) -> Candidate:
    """Inverse of `_candidate_to_cache_record`, for `--local-only` rebuilds."""
    fields = {key: value for key, value in record.items() if key in Candidate.__dataclass_fields__}
    for key in ("types", "mesh_terms", "keywords", "found_in", "merged_identifiers", "possible_duplicate_of"):
        if key in fields and fields[key] is not None:
            fields[key] = tuple(fields[key])
    return Candidate(**fields)
