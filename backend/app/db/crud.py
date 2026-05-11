"""
app/db/crud.py
--------------
Data-access layer. All database reads and writes go through functions here.
Route handlers must not use SQLAlchemy queries directly.

All functions accept an AsyncSession argument — never create sessions here.
"""

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession, Document, Feedback, User
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
    from sqlalchemy import func, text
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
