"""
app/api/routes/search.py
-------------------------
Direct semantic + hybrid search endpoint (no LLM generation).
Useful for power users who want raw retrieval results, or for evaluation.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DBSession, EmbeddingDep
from app.rag.retrieval import retrieve
from app.schemas.document import SearchRequest, SearchResultItem

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=list[SearchResultItem])
async def search(
    body: SearchRequest,
    current_user: CurrentUser,
    db: DBSession,
    embedder: EmbeddingDep,
) -> list[SearchResultItem]:
    """
    Hybrid retrieval (vector + BM25 + RRF) without LLM generation.
    Returns ranked chunks with metadata and relevance scores.
    """
    chunks = await retrieve(
        query=body.query,
        db=db,
        embedding_model=embedder,
        final_top_k=body.top_k,
        filters=body.filters,
    )
    return [
        SearchResultItem(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            pmid=c.pmid,
            doi=c.doi,
            title=c.title,
            journal=c.journal,
            year=c.year,
            url=c.url,
            content=c.content,
            score=c.score,
            chunk_type=c.chunk_type,
        )
        for c in chunks
    ]
