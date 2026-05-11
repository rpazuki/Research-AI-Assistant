"""
app/rag/citations.py
--------------------
Build source citation objects from retrieved chunks.

Each source includes:
- PMID / DOI for linking
- Title, journal, year for display
- The retrieved snippet (the chunk text used as evidence)

Deduplicates by document_id (multiple chunks from the same article → one source).
"""

from app.rag.retrieval import RetrievedChunk
from app.schemas.chat import SourceSchema


def build_sources(chunks: list[RetrievedChunk]) -> list[SourceSchema]:
    """
    Convert retrieved chunks to deduplicated source citations.

    Deduplication: first chunk encountered per document_id wins.
    The snippet is trimmed to 400 characters for display.
    """
    seen: set[str] = set()
    sources: list[SourceSchema] = []

    for chunk in chunks:
        doc_key = chunk.document_id
        if doc_key in seen:
            continue
        seen.add(doc_key)

        pubmed_url = (
            f"https://pubmed.ncbi.nlm.nih.gov/{chunk.pmid}/"
            if chunk.pmid
            else chunk.url
        )

        sources.append(
            SourceSchema(
                pmid=chunk.pmid,
                doi=chunk.doi,
                title=chunk.title,
                journal=chunk.journal,
                year=chunk.year,
                url=pubmed_url,
                snippet=chunk.content[:400].strip() + ("…" if len(chunk.content) > 400 else ""),
            )
        )

    return sources
