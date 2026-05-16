"""Unit tests for app/rag/citations.py."""

from __future__ import annotations

import uuid

from app.rag.retrieval import RetrievedChunk
from app.rag.citations import build_sources


def make_chunk(
    *,
    document_id: str = "pmid:1234",
    pmid: str | None = "1234",
    doi: str | None = None,
    title: str | None = "A paper",
    journal: str | None = "Nature Biotech",
    year: int | None = 2024,
    url: str | None = None,
    content: str = "Short content.",
    chunk_id: uuid.UUID | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id,
        pmid=pmid,
        doi=doi,
        title=title,
        journal=journal,
        year=year,
        url=url,
        content=content,
        score=0.9,
        chunk_type="abstract",
    )


# ── Source building ───────────────────────────────────────────────────────────

def test_build_sources_returns_one_source_per_chunk() -> None:
    chunks = [make_chunk(), make_chunk(document_id="pmid:9999", pmid="9999")]
    sources = build_sources(chunks)
    assert len(sources) == 2


def test_build_sources_deduplicates_same_document_id() -> None:
    doc_id = "pmid:1234"
    chunks = [
        make_chunk(document_id=doc_id, content="First chunk."),
        make_chunk(document_id=doc_id, content="Second chunk."),
    ]
    sources = build_sources(chunks)
    assert len(sources) == 1
    # First chunk wins
    assert sources[0].snippet.startswith("First chunk")


def test_build_sources_constructs_pubmed_url_from_pmid() -> None:
    chunk = make_chunk(pmid="98765", url=None)
    sources = build_sources([chunk])
    assert sources[0].url == "https://pubmed.ncbi.nlm.nih.gov/98765/"


def test_build_sources_falls_back_to_chunk_url_when_no_pmid() -> None:
    chunk = make_chunk(pmid=None, url="https://doi.org/10.1000/test")
    sources = build_sources([chunk])
    assert sources[0].url == "https://doi.org/10.1000/test"


def test_build_sources_truncates_long_content_to_400_chars() -> None:
    long_content = "x" * 500
    chunk = make_chunk(content=long_content)
    sources = build_sources([chunk])
    assert len(sources[0].snippet) <= 404  # 400 chars + "…"
    assert sources[0].snippet.endswith("…")


def test_build_sources_no_ellipsis_for_short_content() -> None:
    chunk = make_chunk(content="Short.")
    sources = build_sources([chunk])
    assert not sources[0].snippet.endswith("…")
    assert sources[0].snippet == "Short."


def test_build_sources_empty_list_returns_empty() -> None:
    assert build_sources([]) == []


def test_build_sources_preserves_metadata_fields() -> None:
    chunk = make_chunk(pmid="111", doi="10.1/x", title="T", journal="J", year=2020)
    sources = build_sources([chunk])
    s = sources[0]
    assert s.pmid == "111"
    assert s.doi == "10.1/x"
    assert s.title == "T"
    assert s.journal == "J"
    assert s.year == 2020
