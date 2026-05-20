"""app/schemas/chat.py — Chat request/response schemas."""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class ChatMessageRequest(BaseModel):
    query: str
    mode: str = "researcher"  # 'researcher' | 'lab_manager'
    top_k: int | None = None  # overrides server default if provided


class SourceSchema(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    url: str | None = None
    snippet: str | None = None  # The retrieved chunk text shown as evidence


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    sources: list[SourceSchema] | None = None
    llm_model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionCreate(BaseModel):
    mode: str = "researcher"
    title: str | None = None


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Title must not be empty")
        return cleaned


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    mode: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionWithMessages(ChatSessionResponse):
    messages: list[ChatMessageResponse] = Field(default_factory=list)


# SSE event payloads

class SSETokenEvent(BaseModel):
    type: str = "token"
    data: str


class SSESourcesEvent(BaseModel):
    type: str = "sources"
    data: list[SourceSchema]


class SSEDoneEvent(BaseModel):
    type: str = "done"
    message_id: uuid.UUID
    latency_ms: int


class SSEErrorEvent(BaseModel):
    type: str = "error"
    message: str
