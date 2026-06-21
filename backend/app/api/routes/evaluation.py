"""Researcher-facing evaluation review endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DBSession, EvaluationReviewerUser
from app.db import crud
from app.db.models import EvaluationReview, EvaluationReviewAssignment
from app.schemas.evaluation import (
    EvaluationReviewCreate,
    EvaluationReviewResponse,
    EvaluationReviewTaskResponse,
    EvaluationReviewUpdate,
)
from app.api.routes.admin_evaluation import (
    _build_assignment_response,
    _build_review_response,
    _build_run_result_response,
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/reviews", response_model=list[EvaluationReviewTaskResponse])
async def list_my_review_tasks(
    current_user: EvaluationReviewerUser,
    db: DBSession,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[EvaluationReviewTaskResponse]:
    assignments = await crud.list_evaluation_review_assignments(
        db,
        assigned_to_user_id=current_user.id,
        status=status_filter,
    )
    tasks = []
    for assignment in assignments:
        task = await _build_review_task(db, assignment)
        if task is not None:
            tasks.append(task)
    return tasks


@router.get("/reviews/{assignment_id}", response_model=EvaluationReviewTaskResponse)
async def get_my_review_task(
    assignment_id: uuid.UUID,
    current_user: EvaluationReviewerUser,
    db: DBSession,
) -> EvaluationReviewTaskResponse:
    assignment = await _get_owned_assignment_or_404(db, assignment_id, current_user.id)
    task = await _build_review_task(db, assignment)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation review task result not found",
        )
    return task


@router.patch("/reviews/{assignment_id}", response_model=EvaluationReviewResponse)
async def save_my_review(
    assignment_id: uuid.UUID,
    body: EvaluationReviewUpdate,
    current_user: EvaluationReviewerUser,
    db: DBSession,
) -> EvaluationReviewResponse:
    assignment = await _get_owned_assignment_or_404(db, assignment_id, current_user.id)
    review = await crud.upsert_evaluation_review(
        db,
        assignment=assignment,
        data=body,
        reviewer_user_id=current_user.id,
        submitted=False,
    )
    if assignment.status == "assigned":
        await crud.update_evaluation_review_assignment_status(
            db,
            assignment=assignment,
            status="in_progress",
        )
    return _build_review_response(review)


@router.post("/reviews/{assignment_id}/submit", response_model=EvaluationReviewResponse)
async def submit_my_review(
    assignment_id: uuid.UUID,
    body: EvaluationReviewCreate,
    current_user: EvaluationReviewerUser,
    db: DBSession,
) -> EvaluationReviewResponse:
    assignment = await _get_owned_assignment_or_404(db, assignment_id, current_user.id)
    review = await crud.upsert_evaluation_review(
        db,
        assignment=assignment,
        data=body,
        reviewer_user_id=current_user.id,
        submitted=True,
    )
    return _build_review_response(review)


async def _get_owned_assignment_or_404(
    db: DBSession,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EvaluationReviewAssignment:
    assignment = await crud.get_evaluation_review_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation review assignment not found",
        )
    if assignment.assigned_to_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evaluation review assignment is not assigned to this user",
        )
    return assignment


async def _build_review_task(
    db: DBSession,
    assignment: EvaluationReviewAssignment,
) -> EvaluationReviewTaskResponse | None:
    result = await crud.get_evaluation_run_result(db, assignment.run_result_id)
    if result is None:
        return None
    review = await crud.get_evaluation_review_by_assignment(db, assignment.id)
    return EvaluationReviewTaskResponse(
        assignment=_build_assignment_response(assignment),
        result=_build_run_result_response(result),
        review=_build_review_response(review) if isinstance(review, EvaluationReview) else None,
    )
