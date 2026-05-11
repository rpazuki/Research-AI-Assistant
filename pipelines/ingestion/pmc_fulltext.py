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

import httpx

from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)

PMC_OA_BASE = "https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi"


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
    ) -> None:
        self.pmc_ids = pmc_ids
        self.sleep_s = sleep_s

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
                    yield doc
                time.sleep(self.sleep_s)
            except Exception as exc:
                logger.error(f"Failed to fetch PMC {pmc_id}: {exc}")

    def _fetch_one(self, pmc_id: str) -> NormalizedDocument | None:
        """Fetch and parse one PMC article."""
        url = f"{PMC_OA_BASE}?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:{pmc_id.replace('PMC', '')}&metadataPrefix=pmc"

        with httpx.Client(timeout=30) as client:
            response = client.get(url)
            response.raise_for_status()

        # TODO: Parse JATS XML response
        # For now, return the raw XML as full_text for inspection.
        # The implementing agent should extract:
        # - Abstract section
        # - Introduction, Methods, Results, Discussion sections
        # - Figure and table captions (optional)

        logger.info(f"Fetched PMC {pmc_id}: {len(response.text)} chars")

        return NormalizedDocument(
            document_id=f"pmc:{pmc_id}",
            source="pmc",
            pmc_id=pmc_id,
            full_text=response.text,  # Replace with parsed text
            license="open-access",    # PMC OA subset is always OA
            url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/",
        )
