"""app/schemas/admin.py — Admin request/response schemas."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    token_limit: int | None = Field(default=None, ge=0)
    role: Literal["researcher", "evaluator", "admin"] | None = None


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
    token_limit: int
    token_limit_reached: bool = False
    usage: UserUsageSummary = Field(default_factory=UserUsageSummary)


class AdminStatsOverview(BaseModel):
    document_count: int = 0
    chunk_count: int = 0
    indexed_token_count: int = 0
    user_count: int = 0
    active_user_count: int = 0
    inactive_user_count: int = 0
    session_count: int = 0
    question_count: int = 0
    assistant_message_count: int = 0
    prompt_token_count: int = 0
    completion_token_count: int = 0
    total_chat_token_count: int = 0
    avg_latency_ms: float | None = None
    upload_batch_count: int = 0
    uploaded_pdf_file_count: int = 0
    uploaded_pdf_bytes: int = 0
    last_ingestion_at: datetime | None = None
    last_corpus_name: str | None = None
    year_min: int | None = None
    year_max: int | None = None


class AdminStatsContentBreakdown(BaseModel):
    abstract_only_documents: int = 0
    full_text_documents: int = 0
    pdf_documents: int = 0
    electronic_lab_notebook_documents: int = 0
    other_documents: int = 0


class AdminStatsSourceBreakdownItem(BaseModel):
    source: str
    document_count: int = 0
    chunk_count: int = 0
    indexed_token_count: int = 0


class AdminStatsJobStatusItem(BaseModel):
    status: str
    count: int = 0


class AdminStatsRecentJob(BaseModel):
    id: uuid.UUID
    status: str
    source: str
    mode: str
    document_count: int | None = None
    chunk_count: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress_message: str | None = None
    error: str | None = None


class AdminStatsResponse(BaseModel):
    overview: AdminStatsOverview = Field(default_factory=AdminStatsOverview)
    content: AdminStatsContentBreakdown = Field(default_factory=AdminStatsContentBreakdown)
    sources: list[AdminStatsSourceBreakdownItem] = Field(default_factory=list)
    job_statuses: list[AdminStatsJobStatusItem] = Field(default_factory=list)
    recent_jobs: list[AdminStatsRecentJob] = Field(default_factory=list)


class IngestionDocumentErrorReport(BaseModel):
    cache_path: str
    error_file_path: str
    exists: bool = False
    record_count: int = 0
    records: list[dict[str, Any]] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)


class IngestionAcquisitionQueueReport(BaseModel):
    cache_path: str
    queue_file_path: str
    exists: bool = False
    record_count: int = 0
    records: list[dict[str, Any]] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)


IngestionJobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
]

IngestionJobMode = Literal[
    "full",
    "incremental",
    "test_year",
    "local_only",
    "queue_only",
]


class IngestionConfigSummary(BaseModel):
    name: str
    path: str
    corpus_name: str
    source: str
    embedding_model: str
    year_from: int | None = None
    year_to: int | None = None
    pdf_dir: str | None = None
    supports_pdf_upload: bool = False


class IngestionConfigDetail(BaseModel):
    name: str
    path: str
    content: dict[str, Any]


class IngestionConfigSaveRequest(BaseModel):
    content: dict[str, Any]


class IngestionConfigCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: dict[str, Any]


class IngestionDefaultsResponse(BaseModel):
    config_name: str = ""
    mode: IngestionJobMode = "full"
    cache_path: str = ""
    write_acquisition_queue: bool = False
    include_cached_fulltext: bool = False


class IngestionWorkerStatusResponse(BaseModel):
    active: bool
    state: str
    job_id: str | None = None
    updated_at: datetime | None = None
    seconds_since_heartbeat: int | None = None
    message: str


class IngestionUploadBatchResponse(BaseModel):
    id: uuid.UUID
    name: str
    directory_path: str
    file_count: int
    total_bytes: int
    created_at: datetime


class IngestionJobCreate(BaseModel):
    config_name: str = Field(min_length=1, max_length=200)
    mode: IngestionJobMode = "full"
    from_date: date | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    cache_path: str | None = Field(default=None, max_length=2000)
    pdf_upload_batch_id: uuid.UUID | None = None
    write_acquisition_queue: bool = False
    include_cached_fulltext: bool = False


class IngestionJobResponse(BaseModel):
    id: uuid.UUID
    requested_by_user_id: uuid.UUID | None
    status: IngestionJobStatus
    config_name: str
    config_path: str
    source: str
    mode: str
    from_date: date | None
    year: int | None
    cache_path: str | None
    pdf_upload_batch_id: uuid.UUID | None
    options: dict | None = None
    manifest_id: uuid.UUID | None
    document_count: int | None
    chunk_count: int | None
    progress_message: str | None
    log_tail: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime
