"""
app/api/routes/admin.py
-----------------------
Admin-only endpoints for user management.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.deps import AdminUser, DBSession
from app.core.config import settings
from app.core.security import create_invitation_token, hash_invitation_token
from app.db import crud
from app.db.models import DEFAULT_USER_TOKEN_LIMIT, IngestionJob, IngestionUploadBatch, User
from app.email.sendgrid import send_invitation_email
from app.ingestion.admin_service import (
    get_approved_config,
    get_ingestion_config_detail,
    get_worker_status,
    list_approved_configs,
    load_ingestion_defaults,
    read_cache_document_error_reports,
    save_ingestion_config,
    save_pdf_upload_folder,
    validate_cache_path,
)
from app.schemas.admin import (
    AdminStatsResponse,
    AdminUserSummary,
    IngestionDocumentErrorReport,
    IngestionConfigCreateRequest,
    IngestionConfigDetail,
    IngestionConfigSaveRequest,
    IngestionConfigSummary,
    IngestionDefaultsResponse,
    IngestionJobCreate,
    IngestionJobResponse,
    IngestionUploadBatchResponse,
    IngestionWorkerStatusResponse,
    InvitationSendItem,
    InvitationSendRequest,
    InvitationSendResponse,
    UserUsageSummary,
    UserAdminUpdate,
)
from app.schemas.chat import ChatMessageResponse, ChatSessionResponse, ChatSessionWithMessages

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(_admin: AdminUser, db: DBSession) -> AdminStatsResponse:
    """Return admin-only corpus, usage, and ingestion operations statistics."""
    return AdminStatsResponse(**await crud.get_admin_stats(db))


@router.get(
    "/stats/ingestion-document-errors",
    response_model=list[IngestionDocumentErrorReport],
)
async def get_ingestion_document_errors(
    _admin: AdminUser, db: DBSession
) -> list[IngestionDocumentErrorReport]:
    """Return cached normalized document parsing errors grouped by ingestion cache path."""
    cache_paths = await crud.list_ingestion_cache_paths(db)
    return [
        IngestionDocumentErrorReport(**report)
        for report in read_cache_document_error_reports(cache_paths)
    ]


@router.get("/ingestion/configs", response_model=list[IngestionConfigSummary])
async def list_ingestion_configs(_admin: AdminUser) -> list[IngestionConfigSummary]:
    """List approved ingestion configs exposed to the admin UI."""
    return [IngestionConfigSummary(**config) for config in list_approved_configs()]


@router.post(
    "/ingestion/configs",
    response_model=IngestionConfigDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_ingestion_config(
    body: IngestionConfigCreateRequest, _admin: AdminUser
) -> IngestionConfigDetail:
    """Create a new approved ingestion config with a non-conflicting TOML filename."""
    return IngestionConfigDetail(
        **save_ingestion_config(body.name, body.content, create=True)
    )


@router.get("/ingestion/configs/{config_name}", response_model=IngestionConfigDetail)
async def get_ingestion_config(config_name: str, _admin: AdminUser) -> IngestionConfigDetail:
    """Load one approved ingestion config for editing."""
    return IngestionConfigDetail(**get_ingestion_config_detail(config_name))


@router.put("/ingestion/configs/{config_name}", response_model=IngestionConfigDetail)
async def update_ingestion_config(
    config_name: str, body: IngestionConfigSaveRequest, _admin: AdminUser
) -> IngestionConfigDetail:
    """Replace one approved ingestion config after source-aware validation."""
    return IngestionConfigDetail(
        **save_ingestion_config(config_name, body.content, create=False)
    )


@router.get("/ingestion/defaults", response_model=IngestionDefaultsResponse)
async def get_ingestion_defaults(_admin: AdminUser) -> IngestionDefaultsResponse:
    """Return committed defaults used to prefill admin ingestion controls."""
    return IngestionDefaultsResponse(**load_ingestion_defaults())


@router.get("/ingestion/worker", response_model=IngestionWorkerStatusResponse)
async def get_ingestion_worker_status(_admin: AdminUser) -> IngestionWorkerStatusResponse:
    """Return whether an ingestion worker heartbeat is visible to the backend."""
    return IngestionWorkerStatusResponse(**get_worker_status())


@router.get("/ingestion/uploads", response_model=list[IngestionUploadBatchResponse])
async def list_ingestion_uploads(
    _admin: AdminUser, db: DBSession
) -> list[IngestionUploadBatchResponse]:
    batches = await crud.list_ingestion_upload_batches(db)
    return [_build_upload_batch_response(batch) for batch in batches]


@router.post("/ingestion/pdf-upload-folders", response_model=IngestionUploadBatchResponse)
async def upload_ingestion_pdf_folder(
    admin: AdminUser,
    db: DBSession,
    files: list[UploadFile] = File(...),
    name: str | None = Form(None),
) -> IngestionUploadBatchResponse:
    """Stage an admin-uploaded folder of already acquired PDFs for PDF ingestion."""
    batch_id = uuid.uuid4()
    directory_path, file_count, total_bytes = await save_pdf_upload_folder(
        files,
        batch_id=batch_id,
    )
    batch = await crud.create_ingestion_upload_batch(
        db,
        upload_batch_id=batch_id,
        created_by_user_id=admin.id,
        name=name or f"PDF upload {batch_id}",
        directory_path=str(directory_path),
        file_count=file_count,
        total_bytes=total_bytes,
        metadata={
            "workflow": "admin-pdf-folder-upload",
            "guidance": (
                "This only stages already downloaded PDFs for local ingestion. "
                "It does not perform publisher or library acquisition."
            ),
        },
    )
    return _build_upload_batch_response(batch)


@router.get("/ingestion/jobs", response_model=list[IngestionJobResponse])
async def list_ingestion_jobs(
    _admin: AdminUser, db: DBSession
) -> list[IngestionJobResponse]:
    jobs = await crud.list_ingestion_jobs(db)
    return [_build_ingestion_job_response(job) for job in jobs]


@router.post("/ingestion/jobs", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
async def create_ingestion_job(
    body: IngestionJobCreate,
    admin: AdminUser,
    db: DBSession,
) -> IngestionJobResponse:
    config_path, config_snapshot = get_approved_config(body.config_name)
    corpus = config_snapshot.get("corpus", {})
    source = str(corpus.get("source", ""))

    if body.mode == "incremental":
        if source != "pubmed_abstract":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incremental ingestion is only supported for PubMed abstract configs",
            )
        if body.from_date is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="from_date is required")

    if body.mode == "test_year":
        if source != "pubmed_abstract":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Year-limited test runs are only supported for PubMed abstract configs",
            )
        if body.year is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="year is required")

    if body.mode in {"local_only", "queue_only"} and not body.cache_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cache_path is required for local-only and queue-only jobs",
        )

    upload_batch = None
    if body.pdf_upload_batch_id is not None:
        if source != "pdf":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF uploads can only be used with an approved PDF ingestion config",
            )
        upload_batch = await crud.get_ingestion_upload_batch(db, body.pdf_upload_batch_id)
        if upload_batch is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF upload batch not found")

    cache_path = validate_cache_path(body.cache_path)
    options = {
        "write_acquisition_queue": body.write_acquisition_queue or body.mode == "queue_only",
        "include_cached_fulltext": body.include_cached_fulltext,
    }
    if upload_batch is not None:
        options["pdf_dir_override"] = upload_batch.directory_path
        config_snapshot = {
            **config_snapshot,
            "pdf": {
                **config_snapshot.get("pdf", {}),
                "dir": upload_batch.directory_path,
            },
        }

    job = await crud.create_ingestion_job(
        db,
        requested_by_user_id=admin.id,
        config_name=Path(config_path).name,
        config_path=str(config_path),
        config_snapshot=config_snapshot,
        source=source,
        mode=body.mode,
        from_date=body.from_date if body.mode == "incremental" else None,
        year=body.year if body.mode == "test_year" else None,
        cache_path=cache_path,
        pdf_upload_batch_id=body.pdf_upload_batch_id,
        options=options,
    )
    return _build_ingestion_job_response(job)


@router.get("/ingestion/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(
    job_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> IngestionJobResponse:
    job = await crud.get_ingestion_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
    return _build_ingestion_job_response(job)


@router.post("/ingestion/jobs/{job_id}/cancel", response_model=IngestionJobResponse)
async def cancel_ingestion_job(
    job_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> IngestionJobResponse:
    job = await crud.get_ingestion_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
    if job.status not in {"queued", "running"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only queued or running jobs can be cancelled",
        )
    updated = await crud.request_ingestion_job_cancel(db, job, datetime.now(timezone.utc))
    return _build_ingestion_job_response(updated)


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


def _build_upload_batch_response(batch: IngestionUploadBatch) -> IngestionUploadBatchResponse:
    return IngestionUploadBatchResponse(
        id=batch.id,
        name=batch.name,
        directory_path=batch.directory_path,
        file_count=batch.file_count,
        total_bytes=batch.total_bytes,
        created_at=batch.created_at,
    )


def _build_ingestion_job_response(job: IngestionJob) -> IngestionJobResponse:
    return IngestionJobResponse(
        id=job.id,
        requested_by_user_id=job.requested_by_user_id,
        status=job.status,
        config_name=job.config_name,
        config_path=job.config_path,
        source=job.source,
        mode=job.mode,
        from_date=job.from_date,
        year=job.year,
        cache_path=job.cache_path,
        pdf_upload_batch_id=job.pdf_upload_batch_id,
        options=job.options,
        manifest_id=job.manifest_id,
        document_count=job.document_count,
        chunk_count=job.chunk_count,
        progress_message=job.progress_message,
        log_tail=job.log_tail,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )
