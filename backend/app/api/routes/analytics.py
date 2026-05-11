"""
app/api/routes/analytics.py
-----------------------------
Corpus analytics endpoints for the Literature Landscape tab.
All queries run against the documents table (not chunks).
"""

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.api.deps import CurrentUser, DBSession
from app.db.models import Document, DocumentChunk, IngestionManifest

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/temporal")
async def temporal(current_user: CurrentUser, db: DBSession) -> list[dict]:
    """Publications per year."""
    from app.db.crud import count_documents_by_year
    return await count_documents_by_year(db)


@router.get("/journals")
async def journals(current_user: CurrentUser, db: DBSession, limit: int = 20) -> list[dict]:
    """Top journals by publication count."""
    from app.db.crud import top_journals
    return await top_journals(db, limit=limit)


@router.get("/mesh_terms")
async def mesh_terms(current_user: CurrentUser, db: DBSession, limit: int = 30) -> list[dict]:
    """Top MeSH terms by frequency across the corpus."""
    # Unnest the mesh_terms array and count
    result = await db.execute(
        text("""
            SELECT term, COUNT(*) AS count
            FROM documents, unnest(mesh_terms) AS term
            GROUP BY term
            ORDER BY count DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    return [{"term": r.term, "count": r.count} for r in result]


@router.get("/corpus_stats")
async def corpus_stats(current_user: CurrentUser, db: DBSession) -> dict:
    """Summary stats: total documents, chunks, date range, last update."""
    doc_count_result = await db.execute(select(func.count(Document.id)))
    doc_count = doc_count_result.scalar_one()

    chunk_count_result = await db.execute(select(func.count(DocumentChunk.id)))
    chunk_count = chunk_count_result.scalar_one()

    year_range_result = await db.execute(
        select(func.min(Document.year), func.max(Document.year))
    )
    min_year, max_year = year_range_result.one()

    last_manifest = await db.execute(
        select(IngestionManifest.created_at, IngestionManifest.name)
        .order_by(IngestionManifest.created_at.desc())
        .limit(1)
    )
    manifest_row = last_manifest.one_or_none()

    return {
        "document_count": doc_count,
        "chunk_count": chunk_count,
        "year_min": min_year,
        "year_max": max_year,
        "last_ingestion": manifest_row.created_at.isoformat() if manifest_row else None,
        "last_corpus_name": manifest_row.name if manifest_row else None,
    }


@router.get("/topics")
async def topics(current_user: CurrentUser, db: DBSession, limit: int = 20) -> list[dict]:
    """Approximate topic distribution using keywords when present, otherwise MeSH terms."""
    result = await db.execute(
        text(
            """
            SELECT topic, COUNT(*) AS count
            FROM (
                SELECT unnest(
                    CASE
                        WHEN array_length(keywords, 1) IS NOT NULL AND array_length(keywords, 1) > 0
                            THEN keywords
                        ELSE mesh_terms
                    END
                ) AS topic
                FROM documents
            ) AS topics
            WHERE topic IS NOT NULL AND topic <> ''
            GROUP BY topic
            ORDER BY count DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return [{"topic": row.topic, "count": row.count} for row in result]
