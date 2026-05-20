"""app/schemas/admin.py — Admin request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserStatusUpdate(BaseModel):
    is_active: bool


class InvitationSendRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    template: str = Field(min_length=1, max_length=8000)
    recipient_emails: list[EmailStr] = Field(min_length=1, max_length=50)


class InvitationSendItem(BaseModel):
    email: EmailStr
    status: str
    expires_at: datetime | None = None
    detail: str | None = None


class InvitationSendResponse(BaseModel):
    sent: list[InvitationSendItem]
    failed: list[InvitationSendItem]


class UserUsageSummary(BaseModel):
    session_count: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    prompt_token_count: int = 0
    completion_token_count: int = 0
    total_token_count: int = 0
    last_active_at: datetime | None = None
    avg_latency_ms: float | None = None


class AdminUserSummary(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    usage: UserUsageSummary = Field(default_factory=UserUsageSummary)
