"""app/schemas/admin.py — Admin request/response schemas."""

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
