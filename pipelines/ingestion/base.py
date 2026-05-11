"""
pipelines/ingestion/base.py
----------------------------
Abstract Ingester interface.

All source-specific ingesters (PubMed, PMC, PDF) implement this interface.
This allows the build_index.py entry point to be source-agnostic.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from pipelines.processing.normalizer import NormalizedDocument


class BaseIngester(ABC):
    """Abstract ingester that yields NormalizedDocument objects."""

    source_name: str  # 'pubmed' | 'pmc' | 'pdf'

    @abstractmethod
    def fetch(self) -> Iterator[NormalizedDocument]:
        """
        Yield NormalizedDocument objects one at a time.

        Implementations must:
        - Handle retries internally for transient network errors.
        - Yield incrementally (do not load all documents into memory at once).
        - Log progress to stderr/stdout at reasonable intervals.
        """
        ...

    @abstractmethod
    def get_config_summary(self) -> dict:
        """Return a dict summarising the ingestion config for the manifest record."""
        ...
