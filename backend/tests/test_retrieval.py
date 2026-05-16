"""Unit tests for app/rag/retrieval.py — pure logic functions."""

from __future__ import annotations

import uuid

import pytest

from app.rag.retrieval import RetrievedChunk, _apply_filters, _reciprocal_rank_fusion


def make_chunk(chunk_id: uuid.UUID | None = None, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id="pmid:1",
        pmid="1",
        doi=None,
        title="Title",
        journal="Journal",
        year=2024,
        url=None,
        content="Content.",
        score=score,
        chunk_type="abstract",
    )


# ── _reciprocal_rank_fusion ───────────────────────────────────────────────────

def test_rrf_returns_at_most_top_k_results() -> None:
    vector = [make_chunk() for _ in range(10)]
    lexical = [make_chunk() for _ in range(10)]
    result = _reciprocal_rank_fusion(vector, lexical, top_k=3)
    assert len(result) <= 3


def test_rrf_boosts_chunk_appearing_in_both_lists() -> None:
    shared_id = uuid.uuid4()
    shared = make_chunk(chunk_id=shared_id)

    # shared chunk is rank 5 in vector and rank 5 in lexical
    vector = [make_chunk() for _ in range(4)] + [shared]
    lexical = [make_chunk() for _ in range(4)] + [shared]

    unique_vector_top = vector[0]
    result = _reciprocal_rank_fusion(vector, lexical, top_k=5)
    ids = [c.chunk_id for c in result]

    # shared chunk must beat a chunk that appears in only one list
    assert shared_id in ids
    shared_pos = ids.index(shared_id)
    # unique_vector_top is rank 1 in vector only → shared should beat it or tie
    if unique_vector_top.chunk_id in ids:
        unique_pos = ids.index(unique_vector_top.chunk_id)
        assert shared_pos <= unique_pos


def test_rrf_empty_lists_returns_empty() -> None:
    assert _reciprocal_rank_fusion([], [], top_k=5) == []


def test_rrf_one_empty_list_still_works() -> None:
    chunks = [make_chunk() for _ in range(3)]
    result = _reciprocal_rank_fusion(chunks, [], top_k=3)
    assert len(result) == 3


def test_rrf_scores_are_set_on_returned_chunks() -> None:
    chunks = [make_chunk() for _ in range(2)]
    result = _reciprocal_rank_fusion(chunks, [], top_k=2)
    for chunk in result:
        assert chunk.score > 0


def test_rrf_descending_score_order() -> None:
    vector = [make_chunk() for _ in range(5)]
    lexical = [make_chunk() for _ in range(5)]
    result = _reciprocal_rank_fusion(vector, lexical, top_k=5)
    scores = [c.score for c in result]
    assert scores == sorted(scores, reverse=True)


# ── _apply_filters ────────────────────────────────────────────────────────────

class FakeQuery:
    """Captures filter calls without an actual DB session."""
    def __init__(self):
        self.clauses: list[str] = []

    def where(self, clause) -> "FakeQuery":
        self.clauses.append(str(clause))
        return self


def test_apply_filters_none_returns_query_unchanged() -> None:
    q = FakeQuery()
    result = _apply_filters(q, None)
    assert result is q
    assert result.clauses == []


def test_apply_filters_empty_dict_returns_query_unchanged() -> None:
    q = FakeQuery()
    result = _apply_filters(q, {})
    assert result.clauses == []


def test_apply_filters_year_from_adds_clause() -> None:
    from app.db.models import Document

    from sqlalchemy import select
    base_q = select(Document.id)
    filtered = _apply_filters(base_q, {"year_from": 2020})
    compiled = str(filtered.compile())
    assert "year" in compiled.lower()


def test_apply_filters_source_adds_clause() -> None:
    from app.db.models import Document
    from sqlalchemy import select
    base_q = select(Document.id)
    filtered = _apply_filters(base_q, {"source": "pubmed"})
    compiled = str(filtered.compile())
    assert "source" in compiled.lower()
