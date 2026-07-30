"""
app/rag/retrieval.py
--------------------
Hybrid retrieval: vector search + full-text search + Reciprocal Rank Fusion.

Retrieval flow:
1. Embed the query with the active embedding model.
2. Run cosine-similarity vector search against document_chunks.embedding (pgvector).
3. Run BM25-approximation full-text search via Postgres tsvector.
4. Merge results with Reciprocal Rank Fusion (RRF).
5. Optionally rerank with a cross-encoder (if RERANKER_ENABLED).
6. Return top-k chunks with metadata.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import bindparam, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log
from app.db.models import Document, DocumentChunk
from app.embeddings.base import EmbeddingModel


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: str
    pmid: str | None
    doi: str | None
    title: str | None
    journal: str | None
    year: int | None
    url: str | None
    content: str
    score: float
    chunk_type: str
    # Sidecar fields (datasheet round 1). Defaults keep older constructors valid.
    section_label: str | None = None
    is_review: bool = False
    metadata: dict = field(default_factory=dict)


async def retrieve(
    query: str,
    db: AsyncSession,
    embedding_model: EmbeddingModel,
    vector_top_k: int | None = None,
    lexical_top_k: int | None = None,
    final_top_k: int | None = None,
    filters: dict | None = None,
) -> list[RetrievedChunk]:
    """
    Hybrid retrieval entry point.

    Args:
        query: User's natural language query.
        db: Async database session.
        embedding_model: Active embedding model instance.
        vector_top_k: Override for RETRIEVAL_VECTOR_TOP_K.
        lexical_top_k: Override for RETRIEVAL_LEXICAL_TOP_K.
        final_top_k: Override for RETRIEVAL_FINAL_TOP_K.
        filters: Optional dict with keys year_from, year_to, source, taxid,
            product_class, doc_type, section_label, exclude_reviews. Retracted and
            non-chat-visible documents are always excluded, regardless of filters.

    Returns:
        List of RetrievedChunk ordered by RRF score, descending.
    """
    v_k = vector_top_k or settings.retrieval_vector_top_k
    l_k = lexical_top_k or settings.retrieval_lexical_top_k
    f_k = final_top_k or settings.retrieval_final_top_k

    # Step 1: embed query
    query_embedding = await embedding_model.async_embed_query(query)

    # Step 2: vector search
    vector_results = await _vector_search(db, query_embedding, top_k=v_k, filters=filters)
    log.debug("vector_search_results", count=len(vector_results))

    # Step 3: lexical search
    lexical_results = await _lexical_search(db, query, top_k=l_k, filters=filters)
    log.debug("lexical_search_results", count=len(lexical_results))

    # Step 4: Reciprocal Rank Fusion
    fused = _reciprocal_rank_fusion(vector_results, lexical_results, top_k=f_k)
    log.info("retrieval_complete", final_count=len(fused), query_preview=query[:80])

    return fused


async def _vector_search(
    db: AsyncSession,
    embedding: list[float],
    top_k: int,
    filters: dict | None,
) -> list[RetrievedChunk]:
    """Cosine similarity search via pgvector <=> operator."""
    distance_expr = DocumentChunk.embedding.cosine_distance(embedding)
    score_expr = (1 - distance_expr).label("score")

    # Base query — join to documents for metadata
    q = (
        select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.chunk_type,
            DocumentChunk.embedding_model,
            DocumentChunk.section_label,
            Document.document_id,
            Document.pmid,
            Document.doi,
            Document.title,
            Document.journal,
            Document.year,
            Document.url,
            Document.is_review,
            score_expr,
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.embedding.isnot(None))
        .order_by(distance_expr)
        .limit(top_k)
    )

    q = _apply_corpus_visibility(q)
    q = _apply_filters(q, filters)
    result = await db.execute(q)
    rows = result.all()

    return [
        RetrievedChunk(
            chunk_id=r.id,
            document_id=r.document_id,
            pmid=r.pmid,
            doi=r.doi,
            title=r.title,
            journal=r.journal,
            year=r.year,
            url=r.url,
            content=r.content,
            score=float(r.score),
            chunk_type=r.chunk_type,
            section_label=r.section_label,
            is_review=bool(r.is_review),
        )
        for r in rows
    ]


async def _lexical_search(
    db: AsyncSession,
    query: str,
    top_k: int,
    filters: dict | None,
) -> list[RetrievedChunk]:
    """BM25-approximation via Postgres full-text search (tsvector/tsquery)."""
    tsquery = func.plainto_tsquery("english", bindparam("query"))
    tsvector = func.to_tsvector("english", DocumentChunk.content)
    score_expr = func.ts_rank(tsvector, tsquery).label("score")

    q = (
        select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.chunk_type,
            DocumentChunk.section_label,
            Document.document_id,
            Document.pmid,
            Document.doi,
            Document.title,
            Document.journal,
            Document.year,
            Document.url,
            Document.is_review,
            score_expr,
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(tsvector.op("@@")(tsquery))
        .order_by(desc(score_expr))
        .limit(top_k)
    )

    q = _apply_corpus_visibility(q)
    q = _apply_filters(q, filters)
    result = await db.execute(q, {"query": query})
    rows = result.all()

    return [
        RetrievedChunk(
            chunk_id=r.id,
            document_id=r.document_id,
            pmid=r.pmid,
            doi=r.doi,
            title=r.title,
            journal=r.journal,
            year=r.year,
            url=r.url,
            content=r.content,
            score=float(r.score),
            chunk_type=r.chunk_type,
            section_label=r.section_label,
            is_review=bool(r.is_review),
        )
        for r in rows
    ]


def _apply_corpus_visibility(query):
    """Restrict a query to documents chat is allowed to cite.

    Applied unconditionally by both search paths, and deliberately kept out of
    `_apply_filters` so that "no filters" still means "no caller-supplied filters".

    Two exclusions:
      - retracted work — citing a retracted yield is the worst failure this system
        has (docs/INGESTION_PLAN.md §5);
      - `chat_visible = false` — documents acquired by an off-domain datasheet run
        stay out of chat retrieval until an admin promotes them.
    """
    return query.where(
        Document.is_retracted.is_(False),
        Document.chat_visible.is_(True),
    )


def _apply_filters(query, filters: dict | None):
    """Apply optional metadata filters to a SQLAlchemy query."""
    if not filters:
        return query
    if year_from := filters.get("year_from"):
        query = query.where(Document.year >= year_from)
    if year_to := filters.get("year_to"):
        query = query.where(Document.year <= year_to)
    if source := filters.get("source"):
        query = query.where(Document.source == source)
    if taxid := filters.get("taxid"):
        query = query.where(Document.taxids.any(int(taxid)))
    if product_class := filters.get("product_class"):
        query = query.where(Document.product_classes.any(product_class))
    if doc_type := filters.get("doc_type"):
        query = query.where(Document.doc_type == doc_type)
    if section_label := filters.get("section_label"):
        query = query.where(DocumentChunk.section_label == section_label)
    # Explicit `is True` rather than truthiness: an absent key and an explicit
    # False must behave identically (no clause), and only True excludes reviews.
    if filters.get("exclude_reviews") is True:
        query = query.where(Document.is_review.is_(False))
    return query


def _reciprocal_rank_fusion(
    vector_results: list[RetrievedChunk],
    lexical_results: list[RetrievedChunk],
    top_k: int,
    k: int = 60,
) -> list[RetrievedChunk]:
    """
    Reciprocal Rank Fusion (RRF) over two ranked lists.

    RRF score = 1/(k + rank_in_list_1) + 1/(k + rank_in_list_2)
    k=60 is the standard RRF constant (Cormack et al. 2009).
    """
    scores: dict[uuid.UUID, float] = {}
    chunks: dict[uuid.UUID, RetrievedChunk] = {}

    for rank, chunk in enumerate(vector_results, 1):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0) + 1.0 / (k + rank)
        chunks[chunk.chunk_id] = chunk

    for rank, chunk in enumerate(lexical_results, 1):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0) + 1.0 / (k + rank)
        if chunk.chunk_id not in chunks:
            chunks[chunk.chunk_id] = chunk

    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]
    results = []
    for cid in sorted_ids:
        chunk = chunks[cid]
        chunk.score = scores[cid]
        results.append(chunk)

    return results
