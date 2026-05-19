"""app/schemas/admin.py — Admin request/response schemas."""

from pydantic import BaseModel


class UserStatusUpdate(BaseModel):
    is_active: bool
