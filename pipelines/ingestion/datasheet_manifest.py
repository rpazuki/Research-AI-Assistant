"""
pipelines/ingestion/datasheet_manifest.py
-------------------------------------------
A finished datasheet run's manifest, used as an ingestion worklist.

A datasheet run has already answered the expensive question — which papers exist
and which of them are on topic — and recorded the answer, row by row with its
reason, in `discovery/manifest.csv`. This ingester reads that verdict and fetches
the content for the rows it kept, so the corpus inherits a curated selection
instead of re-searching for it.

It fetches nothing itself. PMCIDs go to the PMC full-text ingester and PMIDs to
the PubMed ingester's explicit-identifier mode; both already handle caching,
retries, rate limits and error records.

Usage:
    ingester = DatasheetManifestIngester.from_config("configs/datasheet.manifest.rlalab.toml")
    for doc in ingester.fetch():
        process(doc)
"""

from __future__ import annotations

import csv
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pipelines.acquisition.cache_layout import manifest_csv_path
from pipelines.corpus_cache import PARSER_VERSIONS, CorpusCache
from pipelines.discovery.manifest_csv import NOT_REPORTED
from pipelines.discovery.relevance import MENTIONS, STUDIES
from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)

# Relevance verdicts, weakest first. `min_relevance` names the weakest verdict a
# row may carry and still be ingested; `unknown` is deliberately absent from the
# ordering because it means "not judged", not "judged weakly" — it is admitted
# whenever mentions are, matching relevance.is_included.
_RELEVANCE_RANK = {MENTIONS: 0, STUDIES: 1}


@dataclass(frozen=True)
class ManifestRow:
    """One row of a discovery manifest CSV, with `Not reported` read as absent."""

    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    journal: str | None = None
    publisher: str | None = None
    year: int | None = None
    found_in: tuple[str, ...] = ()
    included: bool = False
    relevance: str | None = None
    relevance_reason: str | None = None
    doc_type: str | None = None
    is_review: bool = False
    is_retracted: bool = False
    is_preprint: bool = False
    preprint_doi: str | None = None
    version_of_record_doi: str | None = None
    oa_status: str | None = None
    license: str | None = None
    url: str | None = None

    @property
    def identifier(self) -> str | None:
        """The identifier this row's cached asset was filed under."""
        return self.doi or self.pmid or self.pmc_id


def _cell(value: str | None) -> str | None:
    """`Not reported` is the curators' way of writing None; do not index it."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned == NOT_REPORTED:
        return None
    return cleaned


def _flag(value: str | None) -> bool:
    return _cell(value) == "yes"


def _int(value: str | None) -> int | None:
    cleaned = _cell(value)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_manifest_row(row: dict[str, str]) -> ManifestRow:
    found_in = _cell(row.get("found_in")) or ""
    return ManifestRow(
        doi=_cell(row.get("doi")),
        pmid=_cell(row.get("pmid")),
        pmc_id=_cell(row.get("pmc_id")),
        title=_cell(row.get("title")),
        journal=_cell(row.get("journal")),
        publisher=_cell(row.get("publisher")),
        year=_int(row.get("year")),
        found_in=tuple(part.strip() for part in found_in.split(";") if part.strip()),
        included=_flag(row.get("included")),
        relevance=_cell(row.get("relevance")),
        relevance_reason=_cell(row.get("relevance_reason")),
        doc_type=_cell(row.get("doc_type")),
        is_review=_flag(row.get("is_review")),
        is_retracted=_flag(row.get("is_retracted")),
        is_preprint=_flag(row.get("is_preprint")),
        preprint_doi=_cell(row.get("preprint_doi")),
        version_of_record_doi=_cell(row.get("version_of_record_doi")),
        oa_status=_cell(row.get("oa_status")),
        license=_cell(row.get("license")),
        url=_cell(row.get("url")),
    )


def resolve_manifest_path(run_dir: str | Path | None, manifest_csv: str | Path | None) -> Path:
    """Where the manifest is, given a run directory or an explicit path."""
    if manifest_csv:
        return Path(manifest_csv)
    if run_dir:
        return manifest_csv_path(Path(run_dir))
    raise ValueError("datasheet ingestion needs [datasheet].run_dir or [datasheet].manifest_csv")


def read_manifest(path: str | Path) -> list[ManifestRow]:
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(
            f"No discovery manifest at {resolved}. A run writes it at the end of its "
            "discovery phase; older runs can export one from the admin run page."
        )
    with open(resolved, newline="", encoding="utf-8") as handle:
        return [parse_manifest_row(row) for row in csv.DictReader(handle)]


def select_rows(
    rows: list[ManifestRow],
    *,
    min_relevance: str = STUDIES,
    include_reviews: bool = False,
    include_retracted: bool = False,
) -> list[ManifestRow]:
    """The rows a corpus build should take from a manifest.

    `included` is the run's own decision and is respected as the primary filter;
    the rest only narrow it further, never widen it.
    """
    floor = _RELEVANCE_RANK.get(min_relevance, _RELEVANCE_RANK[STUDIES])
    selected: list[ManifestRow] = []
    for row in rows:
        if not row.included:
            continue
        if row.is_retracted and not include_retracted:
            continue
        if row.is_review and not include_reviews:
            continue
        if row.relevance in _RELEVANCE_RANK and _RELEVANCE_RANK[row.relevance] < floor:
            continue
        selected.append(row)
    return selected


def row_to_metadata_document(row: ManifestRow) -> NormalizedDocument:
    """A document built from manifest columns alone — no abstract, no body.

    The manifest carries no abstract, so this is a title plus identifiers. It is
    citable and findable by title, and nothing more; `skip_metadata_only` keeps
    it out of the corpus by default.
    """
    if row.pmid:
        document_id = f"pmid:{row.pmid}"
    elif row.doi:
        document_id = f"doi:{row.doi}"
    else:
        document_id = f"pmc:{row.pmc_id}"

    return NormalizedDocument(
        document_id=document_id,
        source="discovery",
        title=row.title,
        journal=row.journal,
        year=row.year,
        doi=row.doi,
        pmid=row.pmid,
        pmc_id=row.pmc_id,
        url=row.url or (f"https://doi.org/{row.doi}" if row.doi else None),
        license=row.license,
        publisher=row.publisher,
        oa_status=row.oa_status,
        doc_type=row.doc_type,
        is_review=row.is_review,
        is_retracted=row.is_retracted,
        preprint_of_doi=row.version_of_record_doi if row.is_preprint else None,
        full_text_source="abstract_only",
        metadata={
            "found_in": list(row.found_in),
            "relevance": row.relevance,
            "relevance_reason": row.relevance_reason,
            "access_status": "metadata-only",
            "source_system": "datasheet_manifest",
            "parser_version": PARSER_VERSIONS["datasheet_manifest"],
            "metadata_only": True,
        },
    )


class DatasheetManifestIngester(BaseIngester):
    source_name = "datasheet_manifest"

    def __init__(
        self,
        manifest_path: str | Path,
        *,
        fetch_fulltext: bool = True,
        skip_metadata_only: bool = True,
        min_relevance: str = STUDIES,
        include_reviews: bool = False,
        include_retracted: bool = False,
        pubmed_email: str | None = None,
        pubmed_api_key: str | None = None,
        pubmed_batch_size: int = 20,
        pubmed_sleep_s: float = 0.15,
        pmc_sleep_s: float = 0.5,
        cache: CorpusCache | None = None,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.fetch_fulltext = fetch_fulltext
        self.skip_metadata_only = skip_metadata_only
        self.min_relevance = min_relevance
        self.include_reviews = include_reviews
        self.include_retracted = include_retracted
        self.pubmed_email = pubmed_email
        self.pubmed_api_key = pubmed_api_key
        self.pubmed_batch_size = pubmed_batch_size
        self.pubmed_sleep_s = pubmed_sleep_s
        self.pmc_sleep_s = pmc_sleep_s
        self.cache = cache

    @classmethod
    def from_config(
        cls,
        config_path: str,
        cache: CorpusCache | None = None,
    ) -> "DatasheetManifestIngester":
        from dotenv import load_dotenv

        from pipelines.config import load_pipeline_config

        load_dotenv()
        cfg = load_pipeline_config(config_path)
        datasheet_cfg = cfg.get("datasheet", {})
        pubmed_cfg = cfg.get("pubmed", {})
        pmc_cfg = cfg.get("pmc", {})

        return cls(
            manifest_path=resolve_manifest_path(
                datasheet_cfg.get("run_dir"), datasheet_cfg.get("manifest_csv")
            ),
            fetch_fulltext=bool(datasheet_cfg.get("fetch_fulltext", True)),
            skip_metadata_only=bool(datasheet_cfg.get("skip_metadata_only", True)),
            min_relevance=str(datasheet_cfg.get("min_relevance", STUDIES)),
            include_reviews=bool(datasheet_cfg.get("include_reviews", False)),
            include_retracted=bool(datasheet_cfg.get("include_retracted", False)),
            pubmed_email=pubmed_cfg.get("email") or os.environ.get("NCBI_EMAIL"),
            pubmed_api_key=pubmed_cfg.get("api_key") or os.environ.get("NCBI_API_KEY"),
            pubmed_batch_size=int(pubmed_cfg.get("batch_size", 20)),
            pubmed_sleep_s=float(pubmed_cfg.get("sleep_between_batches_s", 0.15)),
            pmc_sleep_s=float(pmc_cfg.get("sleep_between_batches_s", 0.5)),
            cache=cache,
        )

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "manifest_path": str(self.manifest_path),
            "fetch_fulltext": self.fetch_fulltext,
            "skip_metadata_only": self.skip_metadata_only,
            "min_relevance": self.min_relevance,
            "include_reviews": self.include_reviews,
        }

    def fetch(self) -> Iterator[NormalizedDocument]:
        rows = read_manifest(self.manifest_path)
        selected = select_rows(
            rows,
            min_relevance=self.min_relevance,
            include_reviews=self.include_reviews,
            include_retracted=self.include_retracted,
        )
        logger.info(
            "datasheet manifest %s: %d rows, %d selected",
            self.manifest_path,
            len(rows),
            len(selected),
        )

        pmc_rows: list[ManifestRow] = []
        pubmed_rows: list[ManifestRow] = []
        metadata_rows: list[ManifestRow] = []
        for row in selected:
            if self.fetch_fulltext and row.pmc_id:
                pmc_rows.append(row)
            elif row.pmid:
                pubmed_rows.append(row)
            else:
                metadata_rows.append(row)

        yielded = 0
        fetched_pmc_ids: set[str] = set()
        for doc in self._fetch_pmc([row.pmc_id for row in pmc_rows if row.pmc_id]):
            if doc.pmc_id:
                fetched_pmc_ids.add(doc.pmc_id)
            yielded += 1
            yield doc

        # A PMCID in the manifest does not guarantee retrievable full text: the
        # OA subset is smaller than the set of deposited articles. Where the
        # full text did not arrive, fall back to the abstract rather than
        # dropping a paper the run had already judged relevant.
        pmids = [row.pmid for row in pubmed_rows if row.pmid]
        fallback = [
            row.pmid
            for row in pmc_rows
            if row.pmid and row.pmc_id and row.pmc_id not in fetched_pmc_ids
        ]
        if fallback:
            logger.info(
                "datasheet manifest: %d PMC full texts unavailable, falling back to abstracts",
                len(fallback),
            )
        for doc in self._fetch_pubmed(pmids + fallback):
            yielded += 1
            yield doc

        unrecoverable = [
            row
            for row in pmc_rows
            if row.pmc_id and row.pmc_id not in fetched_pmc_ids and not row.pmid
        ]
        if unrecoverable:
            logger.warning(
                "datasheet manifest: %d rows had neither retrievable full text nor a PMID",
                len(unrecoverable),
            )

        if self.skip_metadata_only:
            if metadata_rows:
                # Not silent: these rows are in the manifest and will not be in the
                # corpus, and the count is the only way a curator can see that.
                logger.warning(
                    "datasheet manifest: skipped %d selected rows with neither PMID nor "
                    "PMCID (title-only records; set skip_metadata_only = false to index them)",
                    len(metadata_rows),
                )
        else:
            for row in metadata_rows:
                doc = row_to_metadata_document(row)
                self._write_cache_document(doc, PARSER_VERSIONS["datasheet_manifest"])
                yielded += 1
                yield doc

        logger.info("datasheet manifest: yielded %d documents", yielded)
        if self.cache is not None:
            self.cache.refresh_counts_from_artifacts()

    def _fetch_pmc(self, pmc_ids: list[str]) -> Iterator[NormalizedDocument]:
        if not pmc_ids:
            return
        from pipelines.ingestion.pmc_fulltext import PMCFullTextIngester

        logger.info("datasheet manifest: fetching %d PMC full texts", len(pmc_ids))
        yield from PMCFullTextIngester(
            pmc_ids=pmc_ids,
            sleep_s=self.pmc_sleep_s,
            cache=self.cache,
        ).fetch()

    def _fetch_pubmed(self, pmids: list[str]) -> Iterator[NormalizedDocument]:
        if not pmids:
            return
        if not self.pubmed_email or not self.pubmed_api_key:
            raise ValueError(
                "Fetching abstracts for manifest rows needs NCBI_EMAIL and NCBI_API_KEY; "
                "set them in .env or set [datasheet].skip_metadata_only accordingly."
            )
        from pipelines.ingestion.pubmed_abstract import PubMedAbstractIngester

        logger.info("datasheet manifest: fetching %d PubMed abstracts", len(pmids))
        yield from PubMedAbstractIngester(
            query="",
            year_from=0,
            year_to=0,
            email=self.pubmed_email,
            api_key=self.pubmed_api_key,
            batch_size=self.pubmed_batch_size,
            sleep_s=self.pubmed_sleep_s,
            cache=self.cache,
            pmids=pmids,
        ).fetch()

    def _write_cache_document(self, doc: NormalizedDocument, parser_version: str) -> None:
        if self.cache is None:
            return
        self.cache.write_document(
            doc,
            raw_asset_path=None,
            access_status=doc.metadata.get("access_status", "metadata-only"),
            parser_version=parser_version,
        )
