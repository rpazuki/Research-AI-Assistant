"""
pipelines/ingestion/pubmed_abstract.py
----------------------------------------
PubMed abstract ingester.

Fetches metadata + abstracts from NCBI PubMed via Biopython Entrez.
Inherits the battle-tested approach from GutFeeling, extended with:
  - Checkpointing (saves PMIDs per year so partial runs can resume)
  - Configurable query, date range, and batch size from config file
  - Incremental mode (fetch only from a given date forward)
  - Structured logging
  - Resilience decorators from app.core.resilience (shared with backend)

Usage:
    ingester = PubMedAbstractIngester.from_config("configs/corpus.rlalab.toml")
    for doc in ingester.fetch():
        process(doc)
"""

import calendar
import io
import json
import os
import time
from collections.abc import Iterator
from datetime import date
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path

from Bio import Entrez

from pipelines.ingestion.base import BaseIngester
from pipelines.corpus_cache import CorpusCache, PARSER_VERSIONS, sha256_bytes
from pipelines.processing.normalizer import AuthorRecord, NormalizedDocument

import logging
logger = logging.getLogger(__name__)

# PubMed hard-caps retstart at this value; beyond it ESearch raises a RuntimeError.
_PUBMED_MAX_RETSTART = 9998


class PubMedAbstractIngester(BaseIngester):
    source_name = "pubmed"

    def __init__(
        self,
        query: str,
        year_from: int,
        year_to: int,
        email: str,
        api_key: str,
        batch_size: int = 20,
        sleep_s: float = 0.15,
        checkpoint_dir: str = "./data/checkpoints",
        incremental_from: date | None = None,
        cache: CorpusCache | None = None,
    ) -> None:
        self.query = query
        self.year_from = year_from
        self.year_to = year_to
        self.batch_size = batch_size
        self.sleep_s = sleep_s
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.incremental_from = incremental_from
        self.cache = cache

        Entrez.email = email
        Entrez.api_key = api_key

    @classmethod
    def from_config(
        cls,
        config_path: str,
        incremental_from: date | None = None,
        cache: CorpusCache | None = None,
    ) -> "PubMedAbstractIngester":
        """Instantiate from a TOML config file."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)

        pm = cfg["pubmed"]
        return cls(
            query=pm["query"].strip(),
            year_from=pm.get("year_from", 2000),
            year_to=pm.get("year_to", date.today().year),
            email=os.environ["NCBI_EMAIL"],
            api_key=os.environ["NCBI_API_KEY"],
            batch_size=pm.get("batch_size", 20),
            sleep_s=pm.get("sleep_between_batches_s", 0.15),
            incremental_from=incremental_from,
            cache=cache,
        )

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "query": self.query,
            "year_from": self.year_from,
            "year_to": self.year_to,
            "batch_size": self.batch_size,
        }

    def fetch(self) -> Iterator[NormalizedDocument]:
        """Yield NormalizedDocument objects for all matching PubMed articles."""
        all_pmids = self._collect_pmids()
        logger.info(f"Total PMIDs collected: {len(all_pmids)}")

        # Deduplicate
        seen: set[str] = set()
        unique_pmids = []
        for pmid in all_pmids:
            if pmid not in seen:
                seen.add(pmid)
                unique_pmids.append(pmid)
        logger.info(f"Unique PMIDs after dedup: {len(unique_pmids)}")

        raw_count = 0
        normalized_count = 0
        for start in range(0, len(unique_pmids), self.batch_size):
            batch = unique_pmids[start : start + self.batch_size]
            logger.info(f"Fetching metadata: {start}–{start + len(batch)}")
            try:
                batch_number = start // self.batch_size + 1
                raw_xml, raw_asset_path = self._get_or_fetch_batch_xml(batch, batch_number)
                raw_count += 1
                records = self.parse_efetch_xml(raw_xml)
                for article_record in records.get("PubmedArticle", []):
                    doc = self._parse_article(article_record)
                    if doc is not None:
                        normalized_count += 1
                        if self.cache is not None:
                            self.cache.write_document(
                                doc,
                                raw_asset_path=raw_asset_path,
                                access_status="metadata-only",
                                parser_version=PARSER_VERSIONS["pubmed"],
                            )
                        yield doc
            except Exception as exc:
                logger.error(f"Failed batch {start}: {exc}")
            time.sleep(self.sleep_s)

        if self.cache is not None:
            self.cache.update_counts(
                pmids=len(unique_pmids),
                raw_records=raw_count,
                normalized_documents=normalized_count,
            )
            self.cache.refresh_counts_from_artifacts()

    def _collect_pmids(self) -> list[str]:
        """Collect all PMIDs for the configured query, splitting by year.

        When a year has more than _PUBMED_MAX_RETSTART results (PubMed's hard
        pagination cap), it is automatically split into monthly sub-queries so
        that no single ESearch call exceeds the limit.
        """
        all_pmids: list[str] = []
        for year in range(self.year_from, self.year_to + 1):
            if self.incremental_from and year < self.incremental_from.year:
                continue

            checkpoint_file = self._checkpoint_file_for_year(year)
            if checkpoint_file.exists():
                with open(checkpoint_file) as f:
                    year_pmids = json.load(f)
                logger.info(f"Year {year}: loaded {len(year_pmids)} PMIDs from checkpoint")
                all_pmids.extend(year_pmids)
                continue

            year_query = self._build_year_query(year)
            count_record = self._safe_esearch(year_query, retmax=1)
            total = int(count_record.get("Count", 0))
            if total == 0:
                logger.info(f"Year {year}: 0 articles")
                continue

            logger.info(f"Year {year}: {total} articles")

            if total > _PUBMED_MAX_RETSTART:
                # Split into monthly sub-queries to stay within PubMed's limit.
                logger.info(f"Year {year}: exceeds {_PUBMED_MAX_RETSTART} — splitting into monthly queries")
                year_pmids = self._collect_pmids_monthly(year)
            else:
                year_pmids = self._paginate_query(year_query, total)

            # Checkpoint
            with open(checkpoint_file, "w") as f:
                json.dump(year_pmids, f)
            if self.cache is not None:
                self.cache.write_json(self._cache_esearch_relative_path_for_year(year), {"pmids": year_pmids})
            all_pmids.extend(year_pmids)

        return all_pmids

    def _collect_pmids_monthly(self, year: int) -> list[str]:
        """Fetch PMIDs for a single year by issuing one query per month."""
        pmids: list[str] = []
        for month in range(1, 13):
            # Skip months before the incremental_from date.
            if self.incremental_from and year == self.incremental_from.year:
                if month < self.incremental_from.month:
                    continue

            last_day = calendar.monthrange(year, month)[1]
            start_date = f"{year}/{month:02d}/01"
            end_date = f"{year}/{month:02d}/{last_day:02d}"
            month_query = (
                f"({self.query}) AND "
                f'("{start_date}"[PDAT] : "{end_date}"[PDAT])'
            )
            count_record = self._safe_esearch(month_query, retmax=1)
            month_total = int(count_record.get("Count", 0))
            logger.info(f"  {year}/{month:02d}: {month_total} articles")
            if month_total == 0:
                continue
            pmids.extend(self._paginate_query(month_query, month_total))
        return pmids

    def _paginate_query(self, query: str, total: int) -> list[str]:
        """Paginate a single ESearch query and return all PMIDs.

        Caps retstart at _PUBMED_MAX_RETSTART as a safety measure.
        """
        pmids: list[str] = []
        cap = min(total, _PUBMED_MAX_RETSTART + self.batch_size)
        for start in range(0, cap, self.batch_size):
            record = self._safe_esearch(query, retstart=start, retmax=self.batch_size)
            pmids.extend(record.get("IdList", []))
            time.sleep(self.sleep_s)
        return pmids

    def _checkpoint_file_for_year(self, year: int) -> Path:
        if self.incremental_from is None:
            return self.checkpoint_dir / f"pmids_{year}.json"
        return self.checkpoint_dir / f"pmids_{year}_{self.incremental_from.isoformat()}.json"

    def _cache_esearch_relative_path_for_year(self, year: int) -> str:
        if self.incremental_from is None:
            return f"raw/pubmed/esearch/pmids_{year}.json"
        return f"raw/pubmed/esearch/pmids_{year}_{self.incremental_from.isoformat()}.json"

    def _build_year_query(self, year: int) -> str:
        year_query = f"({self.query}) AND {year}[PDAT]"
        if self.incremental_from is None:
            return year_query

        start_date = self.incremental_from if year == self.incremental_from.year else date(year, 1, 1)
        end_date = date.today() if year == date.today().year else date(year, 12, 31)
        return (
            year_query
            + f' AND ("{start_date.isoformat()}"[Date - Publication] : '
            + f'"{end_date.isoformat()}"[Date - Publication])'
        )

    def _safe_esearch(self, term: str, retstart: int = 0, retmax: int = 1) -> dict:
        """Entrez esearch with retry."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                handle = Entrez.esearch(db="pubmed", term=term, retstart=retstart, retmax=retmax)
                record = Entrez.read(handle)
                handle.close()
                return record
            except (RemoteDisconnected, OSError) as exc:
                logger.warning(f"esearch attempt {attempt+1}/{max_retries}: {exc}")
                time.sleep(2 ** attempt)
        raise RuntimeError("esearch failed after retries")

    def _safe_efetch(self, id_list: list[str]) -> dict:
        """Entrez efetch with retry."""
        return self.parse_efetch_xml(self._safe_efetch_xml(id_list))

    def _safe_efetch_xml(self, id_list: list[str]) -> str:
        """Entrez efetch with retry, returning the raw XML payload."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                handle = Entrez.efetch(db="pubmed", id=id_list, retmode="xml")
                raw = handle.read()
                handle.close()
                return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            except (IncompleteRead, RemoteDisconnected, OSError) as exc:
                logger.warning(f"efetch attempt {attempt+1}/{max_retries}: {exc}")
                time.sleep(2 ** attempt)
        raise RuntimeError("efetch failed after retries")

    @staticmethod
    def parse_efetch_xml(xml_text: str) -> dict:
        """Parse a raw PubMed efetch XML payload into Biopython records."""
        return Entrez.read(io.BytesIO(xml_text.encode("utf-8")))

    def _get_or_fetch_batch_xml(self, id_list: list[str], _batch_number: int) -> tuple[str, str | None]:
        """Load cached efetch XML for a batch or fetch and cache it."""
        if self.cache is None:
            return self._safe_efetch_xml(id_list), None

        batch_digest = sha256_bytes("\n".join(id_list).encode("utf-8"))[:16]
        relative_path = f"raw/pubmed/efetch/batch_{batch_digest}.xml"
        path = self.cache.root / relative_path
        if path.exists():
            logger.info(f"Using cached PubMed efetch XML: {relative_path}")
            return path.read_text(), relative_path

        xml_text = self._safe_efetch_xml(id_list)
        self.cache.write_bytes(relative_path, xml_text.encode("utf-8"))
        self.cache.record_asset(
            document_id=None,
            asset_type="pubmed_xml",
            relative_path=relative_path,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            access_status="metadata-only",
            license="metadata-only",
            terms_note="NCBI PubMed metadata",
        )
        return xml_text, relative_path

    @staticmethod
    def _parse_article(article: dict) -> NormalizedDocument | None:
        """Parse a single PubmedArticle record into NormalizedDocument."""
        try:
            medline = article["MedlineCitation"]
            article_data = medline["Article"]
            pmid = str(medline["PMID"])

            title = str(article_data.get("ArticleTitle", "") or "")

            abstract_text = ""
            if "Abstract" in article_data:
                abstract_text = " ".join(
                    str(x) for x in article_data["Abstract"]["AbstractText"]
                )

            journal = str(article_data["Journal"]["Title"])
            pub_date = article_data["Journal"]["JournalIssue"]["PubDate"]
            year_str = pub_date.get("Year", "")
            year = int(year_str) if year_str.isdigit() else None

            mesh_terms = []
            if "MeshHeadingList" in medline:
                mesh_terms = [str(mh["DescriptorName"]) for mh in medline["MeshHeadingList"]]

            doi = ""
            pmc_id = ""
            if "ArticleIdList" in article.get("PubmedData", {}):
                for aid in article["PubmedData"]["ArticleIdList"]:
                    id_type = aid.attributes.get("IdType", "")
                    if id_type == "doi":
                        doi = str(aid)
                    elif id_type == "pmc":
                        pmc_id = str(aid)

            authors = []
            if "AuthorList" in article_data:
                for a in article_data["AuthorList"]:
                    authors.append(AuthorRecord(
                        last_name=str(a.get("LastName", "")),
                        fore_name=str(a.get("ForeName", "")),
                        initials=str(a.get("Initials", "")),
                    ))

            return NormalizedDocument(
                document_id=f"pmid:{pmid}",
                source="pubmed",
                title=title or None,
                abstract=abstract_text or None,
                authors=authors,
                journal=journal or None,
                year=year,
                doi=doi or None,
                pmid=pmid,
                pmc_id=pmc_id or None,
                mesh_terms=mesh_terms,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            )
        except Exception as exc:
            logger.warning(f"Failed to parse article: {exc}")
            return None
