"""
pipelines/processing/normalizer.py
------------------------------------
Unified document schema.

All ingesters convert their source-specific formats into NormalizedDocument.
This is the contract between ingestion and indexing.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AuthorRecord:
    last_name: str = ""
    fore_name: str = ""
    initials: str = ""
    orcid: str | None = None

    def display_name(self) -> str:
        if self.fore_name:
            return f"{self.last_name}, {self.fore_name}"
        return f"{self.last_name} {self.initials}".strip()


@dataclass
class NormalizedDocument:
    """
    Unified document schema for all sources.

    document_id format:
        PubMed:  'pmid:12345678'
        PMC:     'pmc:PMC1234567'
        PDF:     'pdf:filename_without_extension'
        DOI:     'doi:10.xxxx/...' (fallback if no PMID)
    """
    document_id: str
    source: str                          # 'pubmed' | 'pmc' | 'pdf' | 'discovery' | ...
    title: str | None = None
    abstract: str | None = None
    full_text: str | None = None         # None for abstract-only ingestion
    authors: list[AuthorRecord] = field(default_factory=list)
    journal: str | None = None
    publication_date: date | None = None
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    mesh_terms: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    url: str | None = None
    license: str | None = None
    ingested_at: datetime = field(default_factory=utc_now)
    metadata: dict = field(default_factory=dict)

    # ── Bibliographic sidecar ─────────────────────────────────────────────────
    # These map onto columns the `documents` table has carried since migration
    # 0006 but that no ingester could reach. `is_retracted` in particular is not
    # cosmetic: retrieval hides retracted work (`app/rag/retrieval.py`), so a
    # source that knows a paper is retracted must be able to say so.
    publisher: str | None = None
    oa_status: str | None = None         # gold|hybrid|green|bronze|closed
    doc_type: str | None = None          # primary|review|other
    is_review: bool = False
    is_retracted: bool = False
    preprint_of_doi: str | None = None
    full_text_source: str | None = None  # pmc_jats|publisher_xml|pdf_text|abstract_only
    access_route: str | None = None

    # Section-split body, as [{"label": "methods", "text": "..."}]. Not a column:
    # the text is already in `full_text`, and this only tells the chunker where
    # each part came from so chunks can carry a section label. Sources that
    # cannot tell sections apart leave it empty and are chunked as one block.
    sections: list[dict] = field(default_factory=list)

    def text_for_indexing(self, mode: str = "abstract") -> str:
        """
        Return the text content to be chunked and embedded.

        mode='abstract': title + abstract + MeSH terms (default, lower storage)
        mode='fulltext': title + full_text (if available, else falls back to abstract)
        """
        parts = []
        if self.title:
            parts.append(self.title.strip())
        if mode == "fulltext" and self.full_text:
            parts.append(self.full_text.strip())
        else:
            if self.abstract:
                parts.append(self.abstract.strip())
            if self.mesh_terms:
                parts.append("MeSH: " + "; ".join(self.mesh_terms))
        return "\n\n".join(parts)

    def to_db_dict(self) -> dict:
        """Convert to a dict suitable for inserting into the documents table."""
        return {
            "document_id": self.document_id,
            "source": self.source,
            "title": self.title,
            "abstract": self.abstract,
            "full_text": self.full_text,
            "authors": [
                {
                    "last_name": a.last_name,
                    "fore_name": a.fore_name,
                    "initials": a.initials,
                    "orcid": a.orcid,
                }
                for a in self.authors
            ],
            "journal": self.journal,
            "publication_date": self.publication_date,
            "year": self.year,
            "doi": self.doi,
            "pmid": self.pmid,
            "pmc_id": self.pmc_id,
            "mesh_terms": self.mesh_terms,
            "keywords": self.keywords,
            "url": self.url,
            "license": self.license,
            "ingested_at": self.ingested_at,
            "metadata": self.metadata,
            "publisher": self.publisher,
            "oa_status": self.oa_status,
            "doc_type": self.doc_type,
            "is_review": self.is_review,
            "is_retracted": self.is_retracted,
            "preprint_of_doi": self.preprint_of_doi,
            "full_text_source": self.full_text_source,
            "access_route": self.access_route,
        }
