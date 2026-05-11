"""
pipelines/processing/deduplicator.py
--------------------------------------
Deduplication for ingested documents.

Two strategies:
1. PMID-based: exact match on `pmid` field (fast, zero false positives)
2. Title-based: fuzzy match on normalized title (catches duplicates without PMID)

Typical usage in the indexing pipeline:
    dedup = Deduplicator()
    for doc in ingester.fetch():
        if dedup.is_duplicate(doc):
            continue
        dedup.register(doc)
        process(doc)
"""

import re
import unicodedata


class Deduplicator:
    def __init__(self, title_threshold: float = 0.92) -> None:
        self._seen_pmids: set[str] = set()
        self._seen_doc_ids: set[str] = set()
        self._seen_title_keys: set[str] = set()
        self.title_threshold = title_threshold

    def is_duplicate(self, doc) -> bool:
        """Return True if this document has been seen before."""
        # Exact PMID match
        if doc.pmid and doc.pmid in self._seen_pmids:
            return True
        # Exact document_id match
        if doc.document_id in self._seen_doc_ids:
            return True
        # Normalized title match (only for documents with a title)
        if doc.title:
            key = _normalize_title(doc.title)
            if key in self._seen_title_keys:
                return True
        return False

    def register(self, doc) -> None:
        """Mark a document as seen so future duplicates are detected."""
        if doc.pmid:
            self._seen_pmids.add(doc.pmid)
        self._seen_doc_ids.add(doc.document_id)
        if doc.title:
            self._seen_title_keys.add(_normalize_title(doc.title))

    def seen_count(self) -> int:
        return len(self._seen_doc_ids)

    def load_existing_pmids(self, pmids: list[str]) -> None:
        """Pre-populate with PMIDs already in the database (for incremental runs)."""
        self._seen_pmids.update(pmids)


def _normalize_title(title: str) -> str:
    """
    Normalize a title for fuzzy comparison.
    Lowercases, strips accents, removes punctuation and extra whitespace.
    """
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    lower = ascii_str.lower()
    no_punct = re.sub(r"[^\w\s]", "", lower)
    collapsed = re.sub(r"\s+", " ", no_punct).strip()
    return collapsed
