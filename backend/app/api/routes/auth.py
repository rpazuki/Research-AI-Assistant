"""
app/api/routes/auth.py
-----------------------
Authentication endpoints: login, logout (client-side), current user.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DBSession
from app.core.config import settings
from app.core.security import create_access_token, hash_invitation_token, verify_password
from app.db import crud
from app.db.crud import get_user_by_email
from app.db.models import UserInvitation
from app.schemas.auth import (
    InvitationAcceptRequest,
    InvitationPreview,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DBSession) -> TokenResponse:
    """Authenticate with email + password. Returns a JWT bearer token."""
    user = await get_user_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact your lab admin.",
        )
    token = create_access_token(subject=str(user.id))
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    """JWT logout is handled client-side by deleting the stored token."""
    return None


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return UserResponse.model_validate(current_user)


@router.get("/invitations/{token}", response_model=InvitationPreview)
async def get_invitation(token: str, db: DBSession) -> InvitationPreview:
    invitation = await _get_valid_invitation(db, token)
    return InvitationPreview(email=invitation.email, expires_at=invitation.expires_at)


@router.post(
    "/invitations/{token}/accept",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_invitation(
    token: str,
    body: InvitationAcceptRequest,
    db: DBSession,
) -> UserResponse:
    invitation = await _get_valid_invitation(db, token)
    existing_user = await crud.get_user_by_email(db, invitation.email)
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    user = await crud.create_user(
        db,
        UserCreate(
            email=invitation.email,
            password=body.password,
            full_name=body.full_name.strip(),
            role="researcher",
        ),
    )
    await crud.mark_invitation_accepted(db, invitation, accepted_at=datetime.now(timezone.utc))
    return UserResponse.model_validate(user)


async def _get_valid_invitation(db: AsyncSession, token: str) -> UserInvitation:
    invitation = await crud.get_invitation_by_token_hash(db, hash_invitation_token(token))
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if invitation.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invitation has already been used",
        )
    if _as_aware_utc(invitation.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation has expired")
    return invitation


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
