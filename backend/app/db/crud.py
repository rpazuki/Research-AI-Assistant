"""
app/db/crud.py
--------------
Data-access layer. All database reads and writes go through functions here.
Route handlers must not use SQLAlchemy queries directly.

All functions accept an AsyncSession argument — never create sessions here.
"""

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import and_, distinct, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChatMessage,
    ChatSession,
    Document,
    DocumentChunk,
    Feedback,
    IngestionJob,
    IngestionManifest,
    IngestionUploadBatch,
    User,
    UserInvitation,
)
from app.schemas.auth import UserCreate
from app.core.security import hash_password


# ── Users ────────────────────────────────────────────────────────────────────

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
    )
    db.add(user)
    await db.flush()
    return user


async def list_users(db: AsyncSession) -> Sequence[User]:
    result = await db.execute(select(User).order_by(User.email))
    return result.scalars().all()


async def get_usage_by_user(
    db: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    if not user_ids:
        return {}

    result = await db.execute(
        select(
            ChatSession.user_id,
            func.count(distinct(ChatSession.id)).label("session_count"),
            func.count(ChatMessage.id)
            .filter(ChatMessage.role == "user")
            .label("user_message_count"),
            func.count(ChatMessage.id)
            .filter(ChatMessage.role == "assistant")
            .label("assistant_message_count"),
            func.coalesce(func.sum(ChatMessage.prompt_tokens), 0).label("prompt_token_count"),
            func.coalesce(func.sum(ChatMessage.completion_tokens), 0).label(
                "completion_token_count"
            ),
            func.max(func.coalesce(ChatMessage.created_at, ChatSession.updated_at)).label(
                "last_active_at"
            ),
            func.avg(ChatMessage.latency_ms)
            .filter(ChatMessage.role == "assistant", ChatMessage.latency_ms.isnot(None))
            .label("avg_latency_ms"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id.in_(list(user_ids)))
        .group_by(ChatSession.user_id)
    )

    return {
        row.user_id: {
            "session_count": row.session_count or 0,
            "user_message_count": row.user_message_count or 0,
            "assistant_message_count": row.assistant_message_count or 0,
            "prompt_token_count": int(row.prompt_token_count or 0),
            "completion_token_count": int(row.completion_token_count or 0),
            "total_token_count": int(row.prompt_token_count or 0)
            + int(row.completion_token_count or 0),
            "last_active_at": row.last_active_at,
            "avg_latency_ms": float(row.avg_latency_ms) if row.avg_latency_ms is not None else None,
        }
        for row in result
    }


async def update_user_active(db: AsyncSession, user: User, is_active: bool) -> User:
    user.is_active = is_active
    await db.flush()
    return user


async def update_user_token_limit(db: AsyncSession, user: User, token_limit: int) -> User:
    user.token_limit = token_limit
    await db.flush()
    return user


async def update_user_role(db: AsyncSession, user: User, role: str) -> User:
    user.role = role
    await db.flush()
    return user


# ── Invitations ───────────────────────────────────────────────────────────────

async def create_user_invitation(
    db: AsyncSession,
    *,
    email: str,
    token_hash: str,
    subject: str,
    template: str,
    invited_by_user_id: uuid.UUID,
    expires_at: datetime,
) -> UserInvitation:
    invitation = UserInvitation(
        email=email,
        token_hash=token_hash,
        subject=subject,
        template=template,
        invited_by_user_id=invited_by_user_id,
        expires_at=expires_at,
    )
    db.add(invitation)
    await db.flush()
    return invitation


async def get_invitation_by_token_hash(
    db: AsyncSession, token_hash: str
) -> UserInvitation | None:
    result = await db.execute(
        select(UserInvitation).where(UserInvitation.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def mark_invitation_sent(
    db: AsyncSession, invitation: UserInvitation, sent_at: datetime
) -> UserInvitation:
    invitation.sent_at = sent_at
    await db.flush()
    return invitation


async def mark_invitation_accepted(
    db: AsyncSession, invitation: UserInvitation, accepted_at: datetime
) -> UserInvitation:
    invitation.accepted_at = accepted_at
    await db.flush()
    return invitation


# ── Ingestion operations ─────────────────────────────────────────────────────

async def create_ingestion_upload_batch(
    db: AsyncSession,
    *,
    upload_batch_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID,
    name: str,
    directory_path: str,
    file_count: int,
    total_bytes: int,
    metadata: dict | None = None,
) -> IngestionUploadBatch:
    batch = IngestionUploadBatch(
        id=upload_batch_id or uuid.uuid4(),
        created_by_user_id=created_by_user_id,
        name=name,
        directory_path=directory_path,
        file_count=file_count,
        total_bytes=total_bytes,
        metadata_=metadata or {},
    )
    db.add(batch)
    await db.flush()
    return batch


async def get_ingestion_upload_batch(
    db: AsyncSession, upload_batch_id: uuid.UUID
) -> IngestionUploadBatch | None:
    result = await db.execute(
        select(IngestionUploadBatch).where(IngestionUploadBatch.id == upload_batch_id)
    )
    return result.scalar_one_or_none()


async def list_ingestion_upload_batches(
    db: AsyncSession, limit: int = 50
) -> Sequence[IngestionUploadBatch]:
    result = await db.execute(
        select(IngestionUploadBatch)
        .order_by(IngestionUploadBatch.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def create_ingestion_job(
    db: AsyncSession,
    *,
    requested_by_user_id: uuid.UUID,
    config_name: str,
    config_path: str,
    config_snapshot: dict,
    source: str,
    mode: str,
    from_date,
    year: int | None,
    cache_path: str | None,
    pdf_upload_batch_id: uuid.UUID | None,
    options: dict | None = None,
) -> IngestionJob:
    job = IngestionJob(
        requested_by_user_id=requested_by_user_id,
        config_name=config_name,
        config_path=config_path,
        config_snapshot=config_snapshot,
        source=source,
        mode=mode,
        from_date=from_date,
        year=year,
        cache_path=cache_path,
        pdf_upload_batch_id=pdf_upload_batch_id,
        options=options or {},
        progress_message="Queued",
    )
    db.add(job)
    await db.flush()
    return job


async def get_ingestion_job(db: AsyncSession, job_id: uuid.UUID) -> IngestionJob | None:
    result = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
    return result.scalar_one_or_none()


async def list_ingestion_jobs(db: AsyncSession, limit: int = 50) -> Sequence[IngestionJob]:
    result = await db.execute(
        select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


async def request_ingestion_job_cancel(
    db: AsyncSession, job: IngestionJob, now: datetime
) -> IngestionJob:
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = now
        job.progress_message = "Cancelled before worker picked it up"
    elif job.status == "running":
        job.status = "cancel_requested"
        job.progress_message = "Cancellation requested"
    await db.flush()
    return job


async def get_admin_stats(db: AsyncSession) -> dict:
    """Return aggregate admin dashboard stats from persisted operational data."""
    notebook_sources = ("eln", "electronic_lab_notebook", "lab_notebook", "notebook")
    full_text_condition = and_(
        Document.full_text.isnot(None),
        Document.full_text != "",
        Document.source.notin_(("pdf", *notebook_sources)),
    )
    pdf_condition = Document.source == "pdf"
    notebook_condition = Document.source.in_(notebook_sources)
    abstract_only_condition = and_(
        Document.abstract.isnot(None),
        Document.abstract != "",
        or_(Document.full_text.is_(None), Document.full_text == ""),
        Document.source.notin_(("pdf", *notebook_sources)),
    )
    known_content_condition = or_(
        abstract_only_condition,
        full_text_condition,
        pdf_condition,
        notebook_condition,
    )

    document_result = await db.execute(
        select(
            func.count(Document.id).label("document_count"),
            func.min(Document.year).label("year_min"),
            func.max(Document.year).label("year_max"),
        )
    )
    document_row = document_result.one()

    chunk_result = await db.execute(
        select(
            func.count(DocumentChunk.id).label("chunk_count"),
            func.coalesce(func.sum(DocumentChunk.token_count), 0).label("indexed_token_count"),
        )
    )
    chunk_row = chunk_result.one()

    content_result = await db.execute(
        select(
            func.count(Document.id)
            .filter(abstract_only_condition)
            .label("abstract_only_documents"),
            func.count(Document.id)
            .filter(full_text_condition)
            .label("full_text_documents"),
            func.count(Document.id).filter(pdf_condition).label("pdf_documents"),
            func.count(Document.id)
            .filter(notebook_condition)
            .label("electronic_lab_notebook_documents"),
            func.count(Document.id)
            .filter(not_(known_content_condition))
            .label("other_documents"),
        )
    )
    content_row = content_result.one()

    source_result = await db.execute(
        select(
            Document.source,
            func.count(distinct(Document.id)).label("document_count"),
            func.count(DocumentChunk.id).label("chunk_count"),
            func.coalesce(func.sum(DocumentChunk.token_count), 0).label("indexed_token_count"),
        )
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .group_by(Document.source)
        .order_by(func.count(distinct(Document.id)).desc(), Document.source)
    )

    usage_result = await db.execute(
        select(
            func.count(distinct(User.id)).label("user_count"),
            func.count(distinct(User.id)).filter(User.is_active.is_(True)).label("active_user_count"),
            func.count(distinct(User.id))
            .filter(User.is_active.is_(False))
            .label("inactive_user_count"),
            func.count(distinct(ChatSession.id)).label("session_count"),
            func.count(ChatMessage.id)
            .filter(ChatMessage.role == "user")
            .label("question_count"),
            func.count(ChatMessage.id)
            .filter(ChatMessage.role == "assistant")
            .label("assistant_message_count"),
            func.coalesce(func.sum(ChatMessage.prompt_tokens), 0).label("prompt_token_count"),
            func.coalesce(func.sum(ChatMessage.completion_tokens), 0).label(
                "completion_token_count"
            ),
            func.avg(ChatMessage.latency_ms)
            .filter(ChatMessage.role == "assistant", ChatMessage.latency_ms.isnot(None))
            .label("avg_latency_ms"),
        )
        .select_from(User)
        .outerjoin(ChatSession, ChatSession.user_id == User.id)
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
    )
    usage_row = usage_result.one()

    upload_result = await db.execute(
        select(
            func.count(IngestionUploadBatch.id).label("upload_batch_count"),
            func.coalesce(func.sum(IngestionUploadBatch.file_count), 0).label(
                "uploaded_pdf_file_count"
            ),
            func.coalesce(func.sum(IngestionUploadBatch.total_bytes), 0).label(
                "uploaded_pdf_bytes"
            ),
        )
    )
    upload_row = upload_result.one()

    last_manifest_result = await db.execute(
        select(IngestionManifest.created_at, IngestionManifest.name)
        .order_by(IngestionManifest.created_at.desc())
        .limit(1)
    )
    last_manifest = last_manifest_result.one_or_none()

    job_status_result = await db.execute(
        select(IngestionJob.status, func.count(IngestionJob.id).label("count"))
        .group_by(IngestionJob.status)
        .order_by(func.count(IngestionJob.id).desc(), IngestionJob.status)
    )
    recent_jobs_result = await db.execute(
        select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(5)
    )
    prompt_tokens = int(usage_row.prompt_token_count or 0)
    completion_tokens = int(usage_row.completion_token_count or 0)

    return {
        "overview": {
            "document_count": int(document_row.document_count or 0),
            "chunk_count": int(chunk_row.chunk_count or 0),
            "indexed_token_count": int(chunk_row.indexed_token_count or 0),
            "user_count": int(usage_row.user_count or 0),
            "active_user_count": int(usage_row.active_user_count or 0),
            "inactive_user_count": int(usage_row.inactive_user_count or 0),
            "session_count": int(usage_row.session_count or 0),
            "question_count": int(usage_row.question_count or 0),
            "assistant_message_count": int(usage_row.assistant_message_count or 0),
            "prompt_token_count": prompt_tokens,
            "completion_token_count": completion_tokens,
            "total_chat_token_count": prompt_tokens + completion_tokens,
            "avg_latency_ms": (
                float(usage_row.avg_latency_ms)
                if usage_row.avg_latency_ms is not None
                else None
            ),
            "upload_batch_count": int(upload_row.upload_batch_count or 0),
            "uploaded_pdf_file_count": int(upload_row.uploaded_pdf_file_count or 0),
            "uploaded_pdf_bytes": int(upload_row.uploaded_pdf_bytes or 0),
            "last_ingestion_at": last_manifest.created_at if last_manifest else None,
            "last_corpus_name": last_manifest.name if last_manifest else None,
            "year_min": document_row.year_min,
            "year_max": document_row.year_max,
        },
        "content": {
            "abstract_only_documents": int(content_row.abstract_only_documents or 0),
            "full_text_documents": int(content_row.full_text_documents or 0),
            "pdf_documents": int(content_row.pdf_documents or 0),
            "electronic_lab_notebook_documents": int(
                content_row.electronic_lab_notebook_documents or 0
            ),
            "other_documents": int(content_row.other_documents or 0),
        },
        "sources": [
            {
                "source": row.source or "unknown",
                "document_count": int(row.document_count or 0),
                "chunk_count": int(row.chunk_count or 0),
                "indexed_token_count": int(row.indexed_token_count or 0),
            }
            for row in source_result
        ],
        "job_statuses": [
            {"status": row.status, "count": int(row.count or 0)}
            for row in job_status_result
        ],
        "recent_jobs": [
            {
                "id": job.id,
                "status": job.status,
                "source": job.source,
                "mode": job.mode,
                "document_count": job.document_count,
                "chunk_count": job.chunk_count,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "progress_message": job.progress_message,
                "error": job.error,
            }
            for job in recent_jobs_result.scalars().all()
        ],
    }


# ── Chat Sessions ─────────────────────────────────────────────────────────────

async def create_chat_session(
    db: AsyncSession, user_id: uuid.UUID, mode: str = "researcher", title: str | None = None
) -> ChatSession:
    session = ChatSession(user_id=user_id, mode=mode, title=title)
    db.add(session)
    await db.flush()
    return session


async def get_sessions_for_user(db: AsyncSession, user_id: uuid.UUID) -> Sequence[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
    )
    return result.scalars().all()


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession | None:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    return result.scalar_one_or_none()


async def update_chat_session_title(
    db: AsyncSession, session: ChatSession, title: str
) -> ChatSession:
    session.title = title
    await db.flush()
    return session


# ── Chat Messages ─────────────────────────────────────────────────────────────

async def create_chat_message(db: AsyncSession, **kwargs) -> ChatMessage:
    msg = ChatMessage(**kwargs)
    db.add(msg)
    await db.flush()
    return msg


async def get_messages_for_session(
    db: AsyncSession, session_id: uuid.UUID
) -> Sequence[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return result.scalars().all()


async def get_message_count_for_session(db: AsyncSession, session_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    return int(result.scalar_one() or 0)


# ── Feedback ──────────────────────────────────────────────────────────────────

async def create_feedback(
    db: AsyncSession, message_id: uuid.UUID, user_id: uuid.UUID, rating: int, comment: str | None
) -> Feedback:
    fb = Feedback(message_id=message_id, user_id=user_id, rating=rating, comment=comment)
    db.add(fb)
    await db.flush()
    return fb


# ── Analytics helpers ─────────────────────────────────────────────────────────

async def count_documents_by_year(db: AsyncSession) -> list[dict]:
    from sqlalchemy import func
    result = await db.execute(
        select(Document.year, func.count(Document.id).label("count"))
        .where(Document.year.isnot(None))
        .group_by(Document.year)
        .order_by(Document.year)
    )
    return [{"year": r.year, "count": r.count} for r in result]


async def top_journals(db: AsyncSession, limit: int = 20) -> list[dict]:
    from sqlalchemy import func
    result = await db.execute(
        select(Document.journal, func.count(Document.id).label("count"))
        .where(Document.journal.isnot(None))
        .group_by(Document.journal)
        .order_by(func.count(Document.id).desc())
        .limit(limit)
    )
    return [{"journal": r.journal, "count": r.count} for r in result]
