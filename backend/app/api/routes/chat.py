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
import re
import time
import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DBSession, EmbeddingDep, LLMDep
from app.core.logging import log
from app.db import crud
from app.db.models import DEFAULT_USER_TOKEN_LIMIT, ChatSession, User
from app.rag.pipeline import _format_exception_message, run_rag_stream
from app.schemas.chat import (
    ChatMessageRequest,
    ChatSessionCreate,
    ChatQuotaResponse,
    ChatSessionResponse,
    ChatSessionUpdate,
    ChatSessionWithMessages,
)

router = APIRouter(prefix="/chat", tags=["chat"])

TOKEN_LIMIT_REACHED_MESSAGE = (
    "Your token limit has been reached. Please ask your lab admin for more tokens."
)


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.get("/quota", response_model=ChatQuotaResponse)
async def get_chat_quota(current_user: CurrentUser, db: DBSession) -> ChatQuotaResponse:
    return await _get_chat_quota(current_user, db)


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: ChatSessionCreate, current_user: CurrentUser, db: DBSession
) -> ChatSessionResponse:
    await _ensure_user_under_token_limit(current_user, db)
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
    from app.schemas.chat import ChatMessageResponse

    return ChatSessionWithMessages(
        id=session.id,
        user_id=session.user_id,
        title=session.title,
        mode=session.mode,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[ChatMessageResponse.model_validate(m) for m in messages],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> None:
    session = await _get_owned_session(session_id, current_user.id, db)
    await db.delete(session)


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: uuid.UUID,
    body: ChatSessionUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> ChatSessionResponse:
    session = await _get_owned_session(session_id, current_user.id, db)
    session = await crud.update_chat_session_title(db, session=session, title=body.title)
    return ChatSessionResponse.model_validate(session)


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
    await _ensure_user_under_token_limit(current_user, db)
    existing_message_count = await crud.get_message_count_for_session(db, session.id)
    should_auto_title = existing_message_count == 0 and not (session.title or "").strip()

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
                    prompt_tokens = payload_data.get("prompt_tokens")
                    completion_tokens = payload_data.get("completion_tokens")
                    # Save assistant message
                    msg = await crud.create_chat_message(
                        db,
                        session_id=session.id,
                        role="assistant",
                        content="".join(full_response),
                        retrieved_chunks=chunk_ids,
                        sources=[s.model_dump() for s in final_sources],
                        llm_model=llm_model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=latency_ms,
                    )
                    if should_auto_title and full_response:
                        generated_title = await _generate_session_title(
                            llm=llm,
                            user_query=body.query,
                            assistant_response="".join(full_response),
                        )
                        if generated_title:
                            await crud.update_chat_session_title(
                                db,
                                session=session,
                                title=generated_title,
                            )
                    payload = json.dumps(
                        {
                            "type": "done",
                            "message_id": str(msg.id),
                            "latency_ms": latency_ms,
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                        }
                    )
                    yield f"data: {payload}\n\n"

                elif event_type == "error":
                    payload = json.dumps({"type": "error", "message": data})
                    yield f"data: {payload}\n\n"

        except Exception as exc:
            log.error(
                "chat_stream_route_error",
                error=_format_exception_message(exc),
                error_repr=repr(exc),
                exception_type=type(exc).__name__,
                exc_info=True,
            )
            payload = json.dumps({"type": "error", "message": _format_exception_message(exc)})
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


async def _ensure_user_under_token_limit(user: User, db: DBSession) -> None:
    quota = await _get_chat_quota(user, db)
    if quota.token_limit_reached:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TOKEN_LIMIT_REACHED_MESSAGE,
        )


async def _get_chat_quota(user: User, db: DBSession) -> ChatQuotaResponse:
    token_limit = int(getattr(user, "token_limit", None) or DEFAULT_USER_TOKEN_LIMIT)
    usage_by_user = await crud.get_usage_by_user(db, [user.id])
    total_tokens = int(usage_by_user.get(user.id, {}).get("total_token_count", 0))
    token_limit_reached = total_tokens >= token_limit
    return ChatQuotaResponse(
        token_limit=token_limit,
        total_token_count=total_tokens,
        token_limit_reached=token_limit_reached,
        message=TOKEN_LIMIT_REACHED_MESSAGE if token_limit_reached else None,
    )


async def _generate_session_title(llm: LLMDep, user_query: str, assistant_response: str) -> str | None:
    try:
        title_text, _usage = await llm.complete(
            system=(
                "You create concise scientific chat titles. "
                "Return exactly one short title in plain text, no quotes and no markdown."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Generate a chat title (max 70 chars) based on this first exchange.\n\n"
                        f"User question: {user_query}\n\n"
                        f"Assistant answer: {assistant_response}"
                    ),
                }
            ],
            max_tokens=32,
            temperature=0.1,
        )
    except Exception as exc:
        log.warning(
            "chat_auto_title_generation_failed",
            error=_format_exception_message(exc),
            exception_type=type(exc).__name__,
        )
        return None

    return _sanitize_title(title_text)


def _sanitize_title(raw_title: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", raw_title).strip()
    cleaned = cleaned.strip("\"'`#*_-:;,.[](){}")
    if not cleaned:
        return None
    return cleaned[:120]
