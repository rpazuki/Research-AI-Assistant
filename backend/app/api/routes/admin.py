"""
app/api/routes/admin.py
-----------------------
Admin-only endpoints for user management.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, DBSession
from app.core.config import settings
from app.core.security import create_invitation_token, hash_invitation_token
from app.db import crud
from app.db.models import DEFAULT_USER_TOKEN_LIMIT, User
from app.email.sendgrid import send_invitation_email
from app.schemas.admin import (
    AdminUserSummary,
    InvitationSendItem,
    InvitationSendRequest,
    InvitationSendResponse,
    UserUsageSummary,
    UserAdminUpdate,
)
from app.schemas.chat import ChatMessageResponse, ChatSessionResponse, ChatSessionWithMessages

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[AdminUserSummary])
async def list_admin_users(_admin: AdminUser, db: DBSession) -> list[AdminUserSummary]:
    users = await crud.list_users(db)
    usage_by_user = await crud.get_usage_by_user(db, [user.id for user in users])
    return [
        _build_admin_user_summary(user=user, usage=usage_by_user.get(user.id, {}))
        for user in users
    ]


@router.get("/users/{user_id}", response_model=AdminUserSummary)
async def get_admin_user(
    user_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> AdminUserSummary:
    user = await crud.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    usage_by_user = await crud.get_usage_by_user(db, [user.id])
    return _build_admin_user_summary(user=user, usage=usage_by_user.get(user.id, {}))


@router.get("/users/{user_id}/chat/sessions", response_model=list[ChatSessionResponse])
async def list_admin_user_chat_sessions(
    user_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> list[ChatSessionResponse]:
    user = await _get_user_or_404(db, user_id)
    sessions = await crud.get_sessions_for_user(db, user_id=user.id)
    return [ChatSessionResponse.model_validate(session) for session in sessions]


@router.get(
    "/users/{user_id}/chat/sessions/{session_id}",
    response_model=ChatSessionWithMessages,
)
async def get_admin_user_chat_session(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> ChatSessionWithMessages:
    user = await _get_user_or_404(db, user_id)
    session = await crud.get_session(db, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    messages = await crud.get_messages_for_session(db, session_id=session.id)
    return ChatSessionWithMessages(
        id=session.id,
        user_id=session.user_id,
        title=session.title,
        mode=session.mode,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[ChatMessageResponse.model_validate(message) for message in messages],
    )


@router.patch("/users/{user_id}", response_model=AdminUserSummary)
async def update_admin_user_status(
    user_id: uuid.UUID,
    body: UserAdminUpdate,
    _admin: AdminUser,
    db: DBSession,
) -> AdminUserSummary:
    user = await crud.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updated_user = user
    if body.is_active is not None:
        updated_user = await crud.update_user_active(db, user=updated_user, is_active=body.is_active)
    if body.token_limit is not None:
        updated_user = await crud.update_user_token_limit(
            db, user=updated_user, token_limit=body.token_limit
        )
    if body.role is not None:
        updated_user = await crud.update_user_role(db, user=updated_user, role=body.role)
    usage_by_user = await crud.get_usage_by_user(db, [updated_user.id])
    return _build_admin_user_summary(
        user=updated_user, usage=usage_by_user.get(updated_user.id, {})
    )


@router.post("/invitations", response_model=InvitationSendResponse)
async def send_user_invitations(
    body: InvitationSendRequest,
    admin: AdminUser,
    db: DBSession,
) -> InvitationSendResponse:
    sent: list[InvitationSendItem] = []
    failed: list[InvitationSendItem] = []
    seen: set[str] = set()

    for raw_email in body.recipient_emails:
        email = str(raw_email).strip().lower()
        if email in seen:
            failed.append(
                InvitationSendItem(email=email, status="failed", detail="Duplicate recipient")
            )
            continue
        seen.add(email)

        existing_user = await crud.get_user_by_email(db, email)
        if existing_user is not None:
            failed.append(
                InvitationSendItem(email=email, status="failed", detail="User already exists")
            )
            continue

        token = create_invitation_token()
        invite_link = f"{settings.app_public_url.rstrip('/')}/invite/{token}"
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=settings.invitation_token_expire_hours
        )
        rendered_template = _render_invitation_template(
            body.template,
            email=email,
            invite_link=invite_link,
        )
        invitation = await crud.create_user_invitation(
            db,
            email=email,
            token_hash=hash_invitation_token(token),
            subject=body.subject,
            template=body.template,
            invited_by_user_id=admin.id,
            expires_at=expires_at,
        )

        try:
            await send_invitation_email(
                to_email=email,
                subject=body.subject,
                body=rendered_template,
            )
            await crud.mark_invitation_sent(db, invitation, sent_at=datetime.now(timezone.utc))
            sent.append(InvitationSendItem(email=email, status="sent", expires_at=expires_at))
        except Exception as exc:
            await db.delete(invitation)
            failed.append(InvitationSendItem(email=email, status="failed", detail=str(exc)))

    return InvitationSendResponse(sent=sent, failed=failed)


def _render_invitation_template(template: str, *, email: str, invite_link: str) -> str:
    return (
        template.replace("{invite_link}", invite_link)
        .replace("{email}", email)
        .replace("{app_name}", settings.app_name)
    )


async def _get_user_or_404(db: DBSession, user_id: uuid.UUID) -> User:
    user = await crud.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _build_admin_user_summary(user: User, usage: dict | None = None) -> AdminUserSummary:
    usage_summary = UserUsageSummary(**(usage or {}))
    token_limit = int(getattr(user, "token_limit", None) or DEFAULT_USER_TOKEN_LIMIT)
    return AdminUserSummary(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        token_limit=token_limit,
        token_limit_reached=usage_summary.total_token_count >= token_limit,
        usage=usage_summary,
    )
