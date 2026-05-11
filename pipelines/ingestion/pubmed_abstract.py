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

import json
import os
import time
from collections.abc import Iterator
from datetime import date
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path

from Bio import Entrez

from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import AuthorRecord, NormalizedDocument

import logging
logger = logging.getLogger(__name__)


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
    ) -> None:
        self.query = query
        self.year_from = year_from
        self.year_to = year_to
        self.batch_size = batch_size
        self.sleep_s = sleep_s
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.incremental_from = incremental_from

        Entrez.email = email
        Entrez.api_key = api_key

    @classmethod
    def from_config(cls, config_path: str, incremental_from: date | None = None) -> "PubMedAbstractIngester":
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

        for start in range(0, len(unique_pmids), self.batch_size):
            batch = unique_pmids[start : start + self.batch_size]
            logger.info(f"Fetching metadata: {start}–{start + len(batch)}")
            try:
                records = self._safe_efetch(batch)
                for article_record in records.get("PubmedArticle", []):
                    doc = self._parse_article(article_record)
                    if doc is not None:
                        yield doc
            except Exception as exc:
                logger.error(f"Failed batch {start}: {exc}")
            time.sleep(self.sleep_s)

    def _collect_pmids(self) -> list[str]:
        """Collect all PMIDs for the configured query, splitting by year."""
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
            year_pmids: list[str] = []
            for start in range(0, total, self.batch_size):
                record = self._safe_esearch(year_query, retstart=start, retmax=self.batch_size)
                year_pmids.extend(record.get("IdList", []))
                time.sleep(self.sleep_s)

            # Checkpoint
            with open(checkpoint_file, "w") as f:
                json.dump(year_pmids, f)
            all_pmids.extend(year_pmids)

        return all_pmids

    def _checkpoint_file_for_year(self, year: int) -> Path:
        if self.incremental_from is None:
            return self.checkpoint_dir / f"pmids_{year}.json"
        return self.checkpoint_dir / f"pmids_{year}_{self.incremental_from.isoformat()}.json"

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
        max_retries = 5
        for attempt in range(max_retries):
            try:
                handle = Entrez.efetch(db="pubmed", id=id_list, retmode="xml")
                records = Entrez.read(handle)
                handle.close()
                return records
            except (IncompleteRead, RemoteDisconnected, OSError) as exc:
                logger.warning(f"efetch attempt {attempt+1}/{max_retries}: {exc}")
                time.sleep(2 ** attempt)
        raise RuntimeError("efetch failed after retries")

    def _parse_article(self, article: dict) -> NormalizedDocument | None:
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
