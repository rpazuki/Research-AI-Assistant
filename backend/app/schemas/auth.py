"""app/schemas/auth.py — Auth request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: str = "researcher"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class InvitationPreview(BaseModel):
    email: EmailStr
    expires_at: datetime


class InvitationAcceptRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    password_confirm: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def passwords_match(self) -> "InvitationAcceptRequest":
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match")
        return self
