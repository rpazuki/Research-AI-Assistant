"""
app/rag/pipeline.py
--------------------
Main RAG orchestrator.

Coordinates: retrieval → context assembly → streaming generation → citation extraction.

This module is the single entry point for RAG logic.
Route handlers call run_rag_stream() and consume the async generator.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log
from app.embeddings.base import EmbeddingModel
from app.providers.base import LLMProvider
from app.rag.citations import build_sources
from app.rag.prompts import build_context_block, get_system_prompt
from app.rag.retrieval import RetrievedChunk, retrieve
from app.schemas.chat import SourceSchema


@dataclass
class RAGResult:
    """Final result after non-streaming completion (for evaluation/testing)."""
    response_text: str
    sources: list[SourceSchema]
    retrieved_chunks: list[RetrievedChunk]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


async def run_rag_stream(
    query: str,
    mode: str,
    db: AsyncSession,
    embedding_model: EmbeddingModel,
    llm_provider: LLMProvider,
    top_k: int | None = None,
    filters: dict | None = None,
) -> AsyncIterator[tuple[str, object | None, list[SourceSchema] | None]]:
    """
    Stream RAG results as (event_type, data, sources) tuples.

    Event types:
        "token"   — data is a text chunk from the LLM
        "sources" — data is None, sources is the list of SourceSchema
        "done"    — data is None, signals end of stream
        "error"   — data is an error message string

    Caller example:
        async for event_type, data, sources in run_rag_stream(...):
            if event_type == "token":
                yield SSE token
            elif event_type == "sources":
                yield SSE sources
    """
    t0 = time.monotonic()

    try:
        # 1. Retrieve
        chunks = await retrieve(
            query=query,
            db=db,
            embedding_model=embedding_model,
            final_top_k=top_k or settings.retrieval_final_top_k,
            filters=filters,
        )

        # 2. Build context and system prompt
        context_block = build_context_block([_chunk_to_dict(c) for c in chunks])
        system_prompt = get_system_prompt(mode)
        full_system = f"{system_prompt}\n\n{context_block}"

        messages = [{"role": "user", "content": query}]

        # 3. Stream generation
        async for token in llm_provider.stream(
            system=full_system,
            messages=messages,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        ):
            yield ("token", token, None)

        # 4. Emit sources after streaming completes
        sources = build_sources(chunks)
        yield ("sources", None, sources)

        latency_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "rag_stream_complete",
            mode=mode,
            chunks_retrieved=len(chunks),
            latency_ms=latency_ms,
        )
        yield (
            "done",
            {
                "retrieved_chunk_ids": [str(chunk.chunk_id) for chunk in chunks],
                "llm_model": getattr(llm_provider, "model", None),
                "latency_ms": latency_ms,
            },
            None,
        )

    except Exception as exc:
        log.error("rag_stream_error", error=str(exc))
        yield ("error", str(exc), None)


def _chunk_to_dict(chunk: RetrievedChunk) -> dict:
    return {
        "pmid": chunk.pmid,
        "doi": chunk.doi,
        "title": chunk.title,
        "journal": chunk.journal,
        "year": chunk.year,
        "content": chunk.content,
    }
