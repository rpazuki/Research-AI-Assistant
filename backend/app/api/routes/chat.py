"""
app/api/routes/chat.py
-----------------------
Chat session and message endpoints.

POST /chat/sessions/{id}/messages streams via Server-Sent Events (SSE).
The frontend consumes this with fetch + ReadableStream.

SSE event format:
    data: {"type": "token", "data": "text chunk"}
    data: {"type": "sources", "data": [{pmid, doi, title, ...}]}
    data: {"type": "done", "message_id": "...", "latency_ms": 123}
    data: {"type": "error", "message": "..."}
"""

import json
import time
import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DBSession, EmbeddingDep, LLMDep
from app.db import crud
from app.db.models import ChatSession
from app.rag.pipeline import run_rag_stream
from app.schemas.chat import (
    ChatMessageRequest,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionWithMessages,
)

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: ChatSessionCreate, current_user: CurrentUser, db: DBSession
) -> ChatSessionResponse:
    session = await crud.create_chat_session(
        db, user_id=current_user.id, mode=body.mode, title=body.title
    )
    return ChatSessionResponse.model_validate(session)


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(current_user: CurrentUser, db: DBSession) -> list[ChatSessionResponse]:
    sessions = await crud.get_sessions_for_user(db, user_id=current_user.id)
    return [ChatSessionResponse.model_validate(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionWithMessages)
async def get_session(
    session_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> ChatSessionWithMessages:
    session = await _get_owned_session(session_id, current_user.id, db)
    messages = await crud.get_messages_for_session(db, session_id=session.id)
    result = ChatSessionWithMessages.model_validate(session)
    from app.schemas.chat import ChatMessageResponse
    result.messages = [ChatMessageResponse.model_validate(m) for m in messages]
    return result


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> None:
    session = await _get_owned_session(session_id, current_user.id, db)
    await db.delete(session)


# ── Streaming chat ────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: uuid.UUID,
    body: ChatMessageRequest,
    current_user: CurrentUser,
    db: DBSession,
    llm: LLMDep,
    embedder: EmbeddingDep,
) -> StreamingResponse:
    """
    Stream a RAG response via Server-Sent Events.

    The session's user message is saved before streaming begins.
    The assistant message is saved after streaming completes.
    """
    session = await _get_owned_session(session_id, current_user.id, db)

    # Save the user message immediately
    await crud.create_chat_message(
        db,
        session_id=session.id,
        role="user",
        content=body.query,
    )

    async def event_generator():
        t0 = time.monotonic()
        full_response = []
        final_sources = []
        chunk_ids = []
        llm_model = None

        try:
            async for event_type, data, sources in run_rag_stream(
                query=body.query,
                mode=body.mode or session.mode,
                db=db,
                embedding_model=embedder,
                llm_provider=llm,
                top_k=body.top_k,
            ):
                if event_type == "token":
                    full_response.append(data)
                    payload = json.dumps({"type": "token", "data": data})
                    yield f"data: {payload}\n\n"

                elif event_type == "sources":
                    final_sources = sources or []
                    sources_data = [s.model_dump() for s in final_sources]
                    payload = json.dumps({"type": "sources", "data": sources_data}, default=str)
                    yield f"data: {payload}\n\n"

                elif event_type == "done":
                    payload_data = data if isinstance(data, dict) else {}
                    latency_ms = int(payload_data.get("latency_ms", int((time.monotonic() - t0) * 1000)))
                    chunk_ids = payload_data.get("retrieved_chunk_ids", [])
                    llm_model = payload_data.get("llm_model")
                    # Save assistant message
                    msg = await crud.create_chat_message(
                        db,
                        session_id=session.id,
                        role="assistant",
                        content="".join(full_response),
                        retrieved_chunks=chunk_ids,
                        sources=[s.model_dump() for s in final_sources],
                        llm_model=llm_model,
                        latency_ms=latency_ms,
                    )
                    payload = json.dumps(
                        {"type": "done", "message_id": str(msg.id), "latency_ms": latency_ms}
                    )
                    yield f"data: {payload}\n\n"

                elif event_type == "error":
                    payload = json.dumps({"type": "error", "message": data})
                    yield f"data: {payload}\n\n"

        except Exception as exc:
            payload = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for SSE
        },
    )


# ── Helper ────────────────────────────────────────────────────────────────────

async def _get_owned_session(
    session_id: uuid.UUID, user_id: uuid.UUID, db: DBSession
) -> ChatSession:
    session = await crud.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return session
