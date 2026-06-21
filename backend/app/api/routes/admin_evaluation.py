"""Admin evaluation workflow endpoints."""

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import AdminUser, DBSession
from app.db import crud
from app.db.models import (
    EvaluationQuestion,
    EvaluationQuestionSet,
    EvaluationReview,
    EvaluationReviewAssignment,
    EvaluationRun,
    EvaluationRunResult,
)
from app.evaluation.admin_service import get_worker_status
from app.evaluation.executor import (
    compare_run_summaries,
    evaluate_release_gate,
)
from app.schemas.evaluation import (
    EvaluationComparisonRequest,
    EvaluationComparisonResponse,
    EvaluationQuestionCreate,
    EvaluationQuestionImportRequest,
    EvaluationQuestionImportResponse,
    EvaluationQuestionResponse,
    EvaluationQuestionSetCreate,
    EvaluationQuestionSetResponse,
    EvaluationQuestionSetUpdate,
    EvaluationQuestionUpdate,
    EvaluationReportImportRequest,
    EvaluationReportImportResponse,
    EvaluationReviewAssignmentCreate,
    EvaluationReviewAssignmentResponse,
    EvaluationReviewCreate,
    EvaluationReviewResponse,
    EvaluationReviewTaskResponse,
    EvaluationReviewUpdate,
    EvaluationRunCreate,
    EvaluationRunResponse,
    EvaluationRunResultResponse,
    EvaluationReleaseDecisionRequest,
    EvaluationReleaseGateResponse,
    EvaluationWorkerStatusResponse,
)

router = APIRouter(prefix="/admin/evaluation", tags=["admin-evaluation"])


@router.get("/runs", response_model=list[EvaluationRunResponse])
async def list_runs(
    _admin: AdminUser,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    mode: str | None = None,
    question_set_id: uuid.UUID | None = None,
) -> list[EvaluationRunResponse]:
    runs = await crud.list_evaluation_runs(
        db,
        limit=limit,
        status=status,
        mode=mode,
        question_set_id=question_set_id,
    )
    return [_build_run_response(run) for run in runs]


@router.post("/runs", response_model=EvaluationRunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: EvaluationRunCreate,
    admin: AdminUser,
    db: DBSession,
) -> EvaluationRunResponse:
    if body.question_set_id is not None:
        await _get_question_set_or_404(db, body.question_set_id)
    now = datetime.now(timezone.utc)
    run = await crud.create_evaluation_run(
        db,
        data=body,
        started_by_user_id=admin.id,
        started_at=now if body.status in {"running", "completed", "failed"} else None,
        completed_at=now if body.status in {"completed", "failed", "cancelled"} else None,
    )
    return _build_run_response(run)


@router.post(
    "/runs/import-report",
    response_model=EvaluationReportImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_report(
    body: EvaluationReportImportRequest,
    admin: AdminUser,
    db: DBSession,
) -> EvaluationReportImportResponse:
    report = body.report
    summary = report.get("summary") or {}
    metadata = report.get("metadata") or {}
    results = report.get("results") or []
    if not isinstance(summary, dict) or not isinstance(metadata, dict) or not isinstance(results, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Report must contain object metadata, object summary, and list results",
        )

    if body.question_set_id is not None:
        await _get_question_set_or_404(db, body.question_set_id)

    mode = str(summary.get("mode") or metadata.get("mode") or "retrieval")
    run_name = body.name or _default_imported_run_name(report)
    backend_metadata = metadata.get("backend") if isinstance(metadata.get("backend"), dict) else {}
    config_metadata = metadata.get("config") if isinstance(metadata.get("config"), dict) else {}
    merged_metadata = {
        "source": "imported_report",
        "report_metadata": metadata,
        **body.metadata,
    }
    run_data = EvaluationRunCreate(
        name=run_name,
        mode=mode if mode in {"retrieval", "rag", "combined"} else "retrieval",
        status="completed",
        question_set_id=body.question_set_id,
        retrieval_config=_dict_or_empty(config_metadata),
        metadata=merged_metadata,
    )
    now = datetime.now(timezone.utc)
    run = await crud.create_evaluation_run(
        db,
        data=run_data,
        started_by_user_id=admin.id,
        started_at=now,
        completed_at=now,
        document_count=_optional_int(backend_metadata.get("document_count")),
        chunk_count=_optional_int(backend_metadata.get("chunk_count")),
        embedding_model=config_metadata.get("embedding_model"),
        chunk_size=_optional_int(config_metadata.get("chunk_size")),
        chunk_overlap=_optional_int(config_metadata.get("chunk_overlap")),
        git_commit=metadata.get("git_commit"),
        runner_version=metadata.get("runner_version"),
        summary_metrics=summary,
        artifact_paths=body.artifact_paths,
    )

    question_map: dict[str, EvaluationQuestion] = {}
    if body.question_set_id is not None:
        external_ids = [
            str(result.get("id"))
            for result in results
            if isinstance(result, dict) and result.get("id") is not None
        ]
        question_map = await crud.get_evaluation_questions_by_external_ids(
            db,
            question_set_id=body.question_set_id,
            external_ids=external_ids,
        )

    linked_count = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        external_id = str(result.get("id")) if result.get("id") is not None else None
        question = question_map.get(external_id or "")
        if question is not None:
            linked_count += 1
        await crud.create_evaluation_run_result(
            db,
            run_id=run.id,
            question_id=question.id if question is not None else None,
            status=str(result.get("status") or "completed"),
            question_snapshot=_question_snapshot_from_result(result),
            retrieved_sources=_list_of_dicts(result.get("retrieved_sources")),
            retrieved_pmids=_list_of_strings(result.get("retrieved_pmids")),
            retrieved_dois=_list_of_strings(result.get("retrieved_dois")),
            retrieved_chunk_ids=_list_of_uuids(result.get("retrieved_chunk_ids")),
            coverage_status=str(result.get("coverage_status") or "not_applicable"),
            recall_at_5=_optional_float(result.get("recall_at_5")),
            recall_at_10=_optional_float(result.get("recall_at_10")),
            recall_at_20=_optional_float(result.get("recall_at_20")),
            mrr_at_10=_optional_float(result.get("mrr_at_10")),
            precision_at_k=_optional_float(
                result.get("precision_at_k", result.get("precision_at_5"))
            ),
            response_text=result.get("response_text"),
            response_sources=_list_of_dicts(result.get("sources") or result.get("response_sources")),
            latency_ms=_optional_int(result.get("latency_ms")),
            time_to_first_token_ms=_optional_int(result.get("time_to_first_token_ms")),
            failure_category=result.get("failure_category"),
            error_message=result.get("error_message"),
        )

    return EvaluationReportImportResponse(
        run=_build_run_response(run),
        result_count=len([result for result in results if isinstance(result, dict)]),
        linked_question_count=linked_count,
    )


@router.get("/runs/{run_id}", response_model=EvaluationRunResponse)
async def get_run(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationRunResponse:
    run = await _get_run_or_404(db, run_id)
    return _build_run_response(run)


@router.post("/runs/{run_id}/execute", response_model=EvaluationRunResponse)
async def execute_run(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationRunResponse:
    run = await _get_run_or_404(db, run_id)
    if run.question_set_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evaluation run must be linked to a question set before execution",
        )
    if run.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evaluation run is already running",
        )
    queued = await crud.update_evaluation_run(
        db,
        run=run,
        status="queued",
        completed_at=None,
        error_message="",
        summary_metrics={},
        metadata={**(run.metadata_ or {}), "progress_message": "Queued for evaluation worker"},
    )
    return _build_run_response(queued)


@router.post("/runs/{run_id}/cancel", response_model=EvaluationRunResponse)
async def cancel_run(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationRunResponse:
    run = await _get_run_or_404(db, run_id)
    if run.status not in {"queued", "running", "cancel_requested"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only queued or running evaluation runs can be cancelled",
        )
    if run.status == "running":
        cancelled = await crud.update_evaluation_run(
            db,
            run=run,
            status="cancel_requested",
            metadata={**(run.metadata_ or {}), "progress_message": "Cancellation requested"},
        )
        return _build_run_response(cancelled)
    cancelled = await crud.update_evaluation_run(
        db,
        run=run,
        status="cancelled",
        completed_at=datetime.now(timezone.utc),
        metadata={**(run.metadata_ or {}), "progress_message": "Cancellation requested"},
    )
    return _build_run_response(cancelled)


@router.get("/worker", response_model=EvaluationWorkerStatusResponse)
async def get_evaluation_worker_status(_admin: AdminUser) -> EvaluationWorkerStatusResponse:
    return EvaluationWorkerStatusResponse(**get_worker_status())


@router.get("/runs/{run_id}/release-gate", response_model=EvaluationReleaseGateResponse)
async def get_release_gate(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationReleaseGateResponse:
    run = await _get_run_or_404(db, run_id)
    gate = (run.summary_metrics or {}).get("release_gate")
    if not isinstance(gate, dict):
        gate = evaluate_release_gate(run.summary_metrics or {})
    return EvaluationReleaseGateResponse(
        run_id=run.id,
        status=str(gate.get("status", "failed")),
        checks=_list_of_dicts(gate.get("checks")),
        release_decision=_release_decision_from_run(run),
    )


@router.post("/runs/{run_id}/release-decision", response_model=EvaluationRunResponse)
async def set_release_decision(
    run_id: uuid.UUID,
    body: EvaluationReleaseDecisionRequest,
    admin: AdminUser,
    db: DBSession,
) -> EvaluationRunResponse:
    run = await _get_run_or_404(db, run_id)
    now = datetime.now(timezone.utc)
    metadata = {
        **(run.metadata_ or {}),
        "release_decision": {
            "status": body.status,
            "note": body.note,
            "decided_by_user_id": str(admin.id),
            "decided_at": now.isoformat(),
        },
    }
    updated = await crud.update_evaluation_run(db, run=run, metadata=metadata)
    return _build_run_response(updated)


@router.get("/runs/{run_id}/results", response_model=list[EvaluationRunResultResponse])
async def list_run_results(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> list[EvaluationRunResultResponse]:
    await _get_run_or_404(db, run_id)
    results = await crud.list_evaluation_run_results(db, run_id=run_id)
    return [_build_run_result_response(result) for result in results]


@router.get("/runs/{run_id}/review-tasks", response_model=list[EvaluationReviewTaskResponse])
async def list_run_review_tasks(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> list[EvaluationReviewTaskResponse]:
    await _get_run_or_404(db, run_id)
    assignments = await crud.list_evaluation_review_assignments(db, run_id=run_id)
    return [await _build_review_task_response(db, assignment) for assignment in assignments]


@router.get("/runs/{run_id}/reviews/export")
async def export_run_reviews(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
) -> Response:
    await _get_run_or_404(db, run_id)
    assignments = await crud.list_evaluation_review_assignments(db, run_id=run_id)
    tasks = [await _build_review_task_response(db, assignment) for assignment in assignments]
    rows = [_review_task_to_export_row(task) for task in tasks]
    if format == "json":
        return Response(
            json.dumps(rows, default=str, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="evaluation_run_{run_id}_reviews.json"'},
        )

    buffer = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else _review_export_fieldnames()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="evaluation_run_{run_id}_reviews.csv"'},
    )


@router.post(
    "/results/{result_id}/assignments",
    response_model=EvaluationReviewAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review_assignment(
    result_id: uuid.UUID,
    body: EvaluationReviewAssignmentCreate,
    admin: AdminUser,
    db: DBSession,
) -> EvaluationReviewAssignmentResponse:
    result = await crud.get_evaluation_run_result(db, result_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run result not found",
        )
    reviewer = await crud.get_user_by_id(db, body.assigned_to_user_id)
    if reviewer is None or not reviewer.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reviewer user not found or inactive",
        )
    if reviewer.role not in {"admin", "evaluator"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evaluation reviews can only be assigned to admin or evaluator users",
        )
    assignment = await crud.create_evaluation_review_assignment(
        db,
        run_result_id=result.id,
        assigned_to_user_id=reviewer.id,
        assigned_by_user_id=admin.id,
        due_at=body.due_at,
        notes=body.notes,
    )
    return _build_assignment_response(assignment)


@router.get("/assignments", response_model=list[EvaluationReviewAssignmentResponse])
async def list_review_assignments(
    _admin: AdminUser,
    db: DBSession,
    run_id: uuid.UUID | None = None,
    assigned_to_user_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[EvaluationReviewAssignmentResponse]:
    assignments = await crud.list_evaluation_review_assignments(
        db,
        run_id=run_id,
        assigned_to_user_id=assigned_to_user_id,
        status=status,
    )
    return [_build_assignment_response(assignment) for assignment in assignments]


@router.post("/assignments/{assignment_id}/review", response_model=EvaluationReviewResponse)
async def save_review(
    assignment_id: uuid.UUID,
    body: EvaluationReviewCreate,
    admin: AdminUser,
    db: DBSession,
    submit: bool = Query(default=False),
) -> EvaluationReviewResponse:
    assignment = await _get_assignment_or_404(db, assignment_id)
    review = await crud.upsert_evaluation_review(
        db,
        assignment=assignment,
        data=body,
        reviewer_user_id=admin.id,
        submitted=submit,
    )
    if not submit and assignment.status == "assigned":
        await crud.update_evaluation_review_assignment_status(
            db,
            assignment=assignment,
            status="in_progress",
        )
    return _build_review_response(review)


@router.patch("/assignments/{assignment_id}/review", response_model=EvaluationReviewResponse)
async def update_review(
    assignment_id: uuid.UUID,
    body: EvaluationReviewUpdate,
    admin: AdminUser,
    db: DBSession,
    submit: bool = Query(default=False),
) -> EvaluationReviewResponse:
    assignment = await _get_assignment_or_404(db, assignment_id)
    review = await crud.upsert_evaluation_review(
        db,
        assignment=assignment,
        data=body,
        reviewer_user_id=admin.id,
        submitted=submit,
    )
    return _build_review_response(review)


@router.post("/compare", response_model=EvaluationComparisonResponse)
async def compare_runs(
    body: EvaluationComparisonRequest,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationComparisonResponse:
    baseline = await _get_run_or_404(db, body.baseline_run_id)
    candidate = await _get_run_or_404(db, body.candidate_run_id)
    baseline_results = await crud.list_evaluation_run_results(db, run_id=baseline.id)
    candidate_results = await crud.list_evaluation_run_results(db, run_id=candidate.id)
    return EvaluationComparisonResponse(
        **compare_run_summaries(
            baseline,
            candidate,
            list(baseline_results),
            list(candidate_results),
        )
    )


@router.get("/question-sets", response_model=list[EvaluationQuestionSetResponse])
async def list_question_sets(
    _admin: AdminUser, db: DBSession
) -> list[EvaluationQuestionSetResponse]:
    question_sets = await crud.list_evaluation_question_sets(db)
    counts = await crud.get_evaluation_question_set_counts(
        db, [question_set.id for question_set in question_sets]
    )
    return [
        _build_question_set_response(
            question_set,
            counts.get(question_set.id, {}),
        )
        for question_set in question_sets
    ]


@router.post(
    "/question-sets",
    response_model=EvaluationQuestionSetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question_set(
    body: EvaluationQuestionSetCreate,
    admin: AdminUser,
    db: DBSession,
) -> EvaluationQuestionSetResponse:
    existing = await crud.get_evaluation_question_set_by_name(db, body.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evaluation question set name already exists",
        )
    question_set = await crud.create_evaluation_question_set(
        db,
        data=body,
        created_by_user_id=admin.id,
    )
    return _build_question_set_response(question_set, {})


@router.get(
    "/question-sets/{question_set_id}",
    response_model=EvaluationQuestionSetResponse,
)
async def get_question_set(
    question_set_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationQuestionSetResponse:
    question_set = await _get_question_set_or_404(db, question_set_id)
    counts = await crud.get_evaluation_question_set_counts(db, [question_set.id])
    return _build_question_set_response(question_set, counts.get(question_set.id, {}))


@router.patch(
    "/question-sets/{question_set_id}",
    response_model=EvaluationQuestionSetResponse,
)
async def update_question_set(
    question_set_id: uuid.UUID,
    body: EvaluationQuestionSetUpdate,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationQuestionSetResponse:
    question_set = await _get_question_set_or_404(db, question_set_id)
    if body.name and body.name != question_set.name:
        existing = await crud.get_evaluation_question_set_by_name(db, body.name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evaluation question set name already exists",
            )
    updated = await crud.update_evaluation_question_set(
        db,
        question_set=question_set,
        data=body,
    )
    counts = await crud.get_evaluation_question_set_counts(db, [updated.id])
    return _build_question_set_response(updated, counts.get(updated.id, {}))


@router.delete("/question-sets/{question_set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_question_set(
    question_set_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> None:
    question_set = await _get_question_set_or_404(db, question_set_id)
    await crud.update_evaluation_question_set(
        db,
        question_set=question_set,
        data=EvaluationQuestionSetUpdate(status="archived"),
    )


@router.get(
    "/question-sets/{question_set_id}/questions",
    response_model=list[EvaluationQuestionResponse],
)
async def list_questions(
    question_set_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
    include_archived: bool = False,
    category: str | None = None,
    difficulty: str | None = None,
    review_status: str | None = None,
) -> list[EvaluationQuestionResponse]:
    await _get_question_set_or_404(db, question_set_id)
    questions = await crud.list_evaluation_questions(
        db,
        question_set_id=question_set_id,
        include_archived=include_archived,
        category=category,
        difficulty=difficulty,
        review_status=review_status,
    )
    return [_build_question_response(question) for question in questions]


@router.post(
    "/question-sets/{question_set_id}/questions",
    response_model=EvaluationQuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    question_set_id: uuid.UUID,
    body: EvaluationQuestionCreate,
    admin: AdminUser,
    db: DBSession,
) -> EvaluationQuestionResponse:
    await _get_question_set_or_404(db, question_set_id)
    existing = await crud.get_evaluation_question_by_external_id(
        db,
        question_set_id=question_set_id,
        external_id=body.external_id,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evaluation question external_id already exists in this set",
        )
    question = await crud.create_evaluation_question(
        db,
        question_set_id=question_set_id,
        data=body,
        created_by_user_id=admin.id,
    )
    return _build_question_response(question)


@router.post(
    "/question-sets/{question_set_id}/import",
    response_model=EvaluationQuestionImportResponse,
)
async def import_questions(
    question_set_id: uuid.UUID,
    body: EvaluationQuestionImportRequest,
    admin: AdminUser,
    db: DBSession,
    upsert: bool = Query(default=True),
) -> EvaluationQuestionImportResponse:
    await _get_question_set_or_404(db, question_set_id)
    created = 0
    updated = 0
    skipped = 0
    imported_questions: list[EvaluationQuestion] = []

    for item in body.questions:
        existing = await crud.get_evaluation_question_by_external_id(
            db,
            question_set_id=question_set_id,
            external_id=item.external_id,
        )
        if existing is None:
            question = await crud.create_evaluation_question(
                db,
                question_set_id=question_set_id,
                data=item,
                created_by_user_id=admin.id,
            )
            created += 1
        elif upsert:
            question = await crud.update_evaluation_question(
                db,
                question=existing,
                data=EvaluationQuestionUpdate(**item.model_dump()),
            )
            updated += 1
        else:
            skipped += 1
            continue
        imported_questions.append(question)

    return EvaluationQuestionImportResponse(
        created=created,
        updated=updated,
        skipped=skipped,
        questions=[_build_question_response(question) for question in imported_questions],
    )


@router.get("/question-sets/{question_set_id}/export")
async def export_questions(
    question_set_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
    include_archived: bool = False,
) -> Response:
    question_set = await _get_question_set_or_404(db, question_set_id)
    questions = await crud.list_evaluation_questions(
        db,
        question_set_id=question_set_id,
        include_archived=include_archived,
    )
    lines = [
        json.dumps(_question_to_benchmark_record(question), default=str)
        for question in questions
    ]
    content = "\n".join(lines) + ("\n" if lines else "")
    filename = f"{question_set.name.replace(' ', '_')}.questions.jsonl"
    return Response(
        content=content,
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/questions/{question_id}", response_model=EvaluationQuestionResponse)
async def get_question(
    question_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationQuestionResponse:
    question = await _get_question_or_404(db, question_id)
    return _build_question_response(question)


@router.patch("/questions/{question_id}", response_model=EvaluationQuestionResponse)
async def update_question(
    question_id: uuid.UUID,
    body: EvaluationQuestionUpdate,
    _admin: AdminUser,
    db: DBSession,
) -> EvaluationQuestionResponse:
    question = await _get_question_or_404(db, question_id)
    updated = await crud.update_evaluation_question(
        db,
        question=question,
        data=body,
        archived_at=datetime.now(timezone.utc),
    )
    return _build_question_response(updated)


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_question(
    question_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
) -> None:
    question = await _get_question_or_404(db, question_id)
    await crud.update_evaluation_question(
        db,
        question=question,
        data=EvaluationQuestionUpdate(archived=True),
        archived_at=datetime.now(timezone.utc),
    )


async def _get_question_set_or_404(
    db: DBSession, question_set_id: uuid.UUID
) -> EvaluationQuestionSet:
    question_set = await crud.get_evaluation_question_set(db, question_set_id)
    if question_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation question set not found",
        )
    return question_set


async def _get_run_or_404(db: DBSession, run_id: uuid.UUID) -> EvaluationRun:
    run = await crud.get_evaluation_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run not found",
        )
    return run


async def _get_question_or_404(db: DBSession, question_id: uuid.UUID) -> EvaluationQuestion:
    question = await crud.get_evaluation_question(db, question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation question not found",
        )
    return question


async def _get_assignment_or_404(
    db: DBSession, assignment_id: uuid.UUID
) -> EvaluationReviewAssignment:
    assignment = await crud.get_evaluation_review_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation review assignment not found",
        )
    return assignment


def _build_run_response(run: EvaluationRun) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=run.id,
        name=run.name,
        mode=run.mode,
        status=run.status,
        question_set_id=run.question_set_id,
        started_by_user_id=run.started_by_user_id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        corpus_manifest_id=run.corpus_manifest_id,
        document_count=run.document_count,
        chunk_count=run.chunk_count,
        embedding_model=run.embedding_model,
        chunk_size=run.chunk_size,
        chunk_overlap=run.chunk_overlap,
        retrieval_config=run.retrieval_config or {},
        reranker_config=run.reranker_config or {},
        llm_provider=run.llm_provider,
        llm_model=run.llm_model,
        prompt_version=run.prompt_version,
        git_commit=run.git_commit,
        runner_version=run.runner_version,
        summary_metrics=run.summary_metrics or {},
        error_message=run.error_message,
        artifact_paths=run.artifact_paths or {},
        metadata=run.metadata_ or {},
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _build_run_result_response(result: EvaluationRunResult) -> EvaluationRunResultResponse:
    return EvaluationRunResultResponse(
        id=result.id,
        run_id=result.run_id,
        question_id=result.question_id,
        status=result.status,
        question_snapshot=result.question_snapshot,
        retrieved_sources=result.retrieved_sources or [],
        retrieved_pmids=result.retrieved_pmids or [],
        retrieved_dois=result.retrieved_dois or [],
        retrieved_chunk_ids=result.retrieved_chunk_ids or [],
        expected_pmids_present=result.expected_pmids_present,
        expected_dois_present=result.expected_dois_present,
        coverage_status=result.coverage_status,
        recall_at_5=result.recall_at_5,
        recall_at_10=result.recall_at_10,
        recall_at_20=result.recall_at_20,
        mrr_at_10=result.mrr_at_10,
        precision_at_k=result.precision_at_k,
        response_text=result.response_text,
        response_sources=result.response_sources or [],
        latency_ms=result.latency_ms,
        time_to_first_token_ms=result.time_to_first_token_ms,
        failure_category=result.failure_category,
        error_message=result.error_message,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )


async def _build_review_task_response(
    db: DBSession,
    assignment: EvaluationReviewAssignment,
) -> EvaluationReviewTaskResponse:
    result = await crud.get_evaluation_run_result(db, assignment.run_result_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run result not found",
        )
    review = await crud.get_evaluation_review_by_assignment(db, assignment.id)
    return EvaluationReviewTaskResponse(
        assignment=_build_assignment_response(assignment),
        result=_build_run_result_response(result),
        review=_build_review_response(review) if review is not None else None,
    )


def _build_question_set_response(
    question_set: EvaluationQuestionSet,
    counts: dict[str, int],
) -> EvaluationQuestionSetResponse:
    return EvaluationQuestionSetResponse(
        id=question_set.id,
        name=question_set.name,
        description=question_set.description,
        status=question_set.status,
        created_by_user_id=question_set.created_by_user_id,
        created_at=question_set.created_at,
        updated_at=question_set.updated_at,
        metadata=question_set.metadata_ or {},
        question_count=counts.get("question_count", 0),
        label_complete_count=counts.get("label_complete_count", 0),
    )


def _build_question_response(question: EvaluationQuestion) -> EvaluationQuestionResponse:
    return EvaluationQuestionResponse(
        id=question.id,
        question_set_id=question.question_set_id,
        external_id=question.external_id,
        question=question.question,
        category=question.category,
        difficulty=question.difficulty,
        domain_fit=question.domain_fit,
        expected_behavior=question.expected_behavior,
        expected_keywords=question.expected_keywords or [],
        expected_pmids=question.expected_pmids or [],
        expected_dois=question.expected_dois or [],
        gold_answer_outline=question.gold_answer_outline,
        supporting_evidence=question.supporting_evidence or [],
        requires_full_text=question.requires_full_text,
        review_status=question.review_status,
        expert_owner_user_id=question.expert_owner_user_id,
        notes=question.notes,
        created_by_user_id=question.created_by_user_id,
        created_at=question.created_at,
        updated_at=question.updated_at,
        archived_at=question.archived_at,
    )


def _build_assignment_response(
    assignment: EvaluationReviewAssignment,
) -> EvaluationReviewAssignmentResponse:
    return EvaluationReviewAssignmentResponse(
        id=assignment.id,
        run_result_id=assignment.run_result_id,
        assigned_to_user_id=assignment.assigned_to_user_id,
        assigned_by_user_id=assignment.assigned_by_user_id,
        status=assignment.status,
        due_at=assignment.due_at,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
        submitted_at=assignment.submitted_at,
        notes=assignment.notes,
    )


def _build_review_response(review: EvaluationReview) -> EvaluationReviewResponse:
    return EvaluationReviewResponse(
        id=review.id,
        assignment_id=review.assignment_id,
        run_result_id=review.run_result_id,
        reviewer_user_id=review.reviewer_user_id,
        correctness_score=review.correctness_score,
        completeness_score=review.completeness_score,
        citation_support_score=review.citation_support_score,
        grounding_score=review.grounding_score,
        usefulness_score=review.usefulness_score,
        refusal_behavior=review.refusal_behavior,
        false_premise_handling=review.false_premise_handling,
        hallucination_flag=review.hallucination_flag,
        citation_issue_flag=review.citation_issue_flag,
        corpus_gap_flag=review.corpus_gap_flag,
        retrieval_issue_flag=review.retrieval_issue_flag,
        generation_issue_flag=review.generation_issue_flag,
        latency_issue_flag=review.latency_issue_flag,
        recommended_failure_category=review.recommended_failure_category,
        reviewer_confidence=review.reviewer_confidence,
        free_text_feedback=review.free_text_feedback,
        suggested_answer=review.suggested_answer,
        created_at=review.created_at,
        updated_at=review.updated_at,
        submitted_at=review.submitted_at,
    )


def _release_decision_from_run(run: EvaluationRun) -> dict | None:
    decision = (run.metadata_ or {}).get("release_decision")
    return decision if isinstance(decision, dict) else None


def _review_export_fieldnames() -> list[str]:
    return [
        "assignment_id",
        "run_result_id",
        "question_id",
        "question_external_id",
        "question",
        "assigned_to_user_id",
        "reviewer_user_id",
        "assignment_status",
        "submitted_at",
        "correctness_score",
        "completeness_score",
        "citation_support_score",
        "grounding_score",
        "usefulness_score",
        "reviewer_confidence",
        "hallucination_flag",
        "citation_issue_flag",
        "corpus_gap_flag",
        "retrieval_issue_flag",
        "generation_issue_flag",
        "latency_issue_flag",
        "recommended_failure_category",
        "free_text_feedback",
        "suggested_answer",
    ]


def _review_task_to_export_row(task: EvaluationReviewTaskResponse) -> dict:
    snapshot = task.result.question_snapshot or {}
    review = task.review
    row = {
        "assignment_id": str(task.assignment.id),
        "run_result_id": str(task.assignment.run_result_id),
        "question_id": str(task.result.question_id) if task.result.question_id else "",
        "question_external_id": str(snapshot.get("id") or ""),
        "question": str(snapshot.get("question") or ""),
        "assigned_to_user_id": str(task.assignment.assigned_to_user_id),
        "reviewer_user_id": str(review.reviewer_user_id) if review else "",
        "assignment_status": task.assignment.status,
        "submitted_at": task.assignment.submitted_at or "",
        "correctness_score": review.correctness_score if review else "",
        "completeness_score": review.completeness_score if review else "",
        "citation_support_score": review.citation_support_score if review else "",
        "grounding_score": review.grounding_score if review else "",
        "usefulness_score": review.usefulness_score if review else "",
        "reviewer_confidence": review.reviewer_confidence if review else "",
        "hallucination_flag": review.hallucination_flag if review else "",
        "citation_issue_flag": review.citation_issue_flag if review else "",
        "corpus_gap_flag": review.corpus_gap_flag if review else "",
        "retrieval_issue_flag": review.retrieval_issue_flag if review else "",
        "generation_issue_flag": review.generation_issue_flag if review else "",
        "latency_issue_flag": review.latency_issue_flag if review else "",
        "recommended_failure_category": review.recommended_failure_category if review else "",
        "free_text_feedback": review.free_text_feedback if review else "",
        "suggested_answer": review.suggested_answer if review else "",
    }
    return {field: row[field] for field in _review_export_fieldnames()}


def _question_to_benchmark_record(question: EvaluationQuestion) -> dict:
    return {
        "id": question.external_id,
        "question": question.question,
        "category": question.category,
        "difficulty": question.difficulty,
        "domain_fit": question.domain_fit,
        "expected_behavior": question.expected_behavior,
        "expected_keywords": question.expected_keywords or [],
        "expected_pmids": question.expected_pmids or [],
        "expected_dois": question.expected_dois or [],
        "gold_answer_outline": question.gold_answer_outline,
        "supporting_snippets": question.supporting_evidence or [],
        "requires_full_text": question.requires_full_text,
        "review_status": question.review_status,
        "notes": question.notes,
    }


def _default_imported_run_name(report: dict) -> str:
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    timestamp = metadata.get("timestamp") or datetime.now(timezone.utc).isoformat()
    mode = summary.get("mode") or metadata.get("mode") or "evaluation"
    return f"Imported {mode} run {timestamp}"


def _dict_or_empty(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list_of_strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _list_of_dicts(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_of_uuids(value) -> list[uuid.UUID]:
    if not isinstance(value, list):
        return []
    parsed = []
    for item in value:
        try:
            parsed.append(uuid.UUID(str(item)))
        except (TypeError, ValueError):
            continue
    return parsed


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _question_snapshot_from_result(result: dict) -> dict:
    snapshot = result.get("question_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    return {
        "id": result.get("id"),
        "question": result.get("question"),
        "category": result.get("category"),
        "difficulty": result.get("difficulty"),
        "expected_behavior": result.get("expected_behavior"),
    }
