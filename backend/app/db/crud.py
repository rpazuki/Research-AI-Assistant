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

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession, Document, Feedback, User, UserInvitation
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
