from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.api import deps
from app.db.models import User
from app.main import app


class DummyDB:
    pass


def make_user(role: str = "researcher") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="hashed",
        full_name="Researcher",
        role=role,
        is_active=True,
        token_limit=1_000_000,
    )


def make_assignment(user_id: uuid.UUID, **overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "run_result_id": uuid.uuid4(),
        "assigned_to_user_id": user_id,
        "assigned_by_user_id": uuid.uuid4(),
        "status": "assigned",
        "due_at": None,
        "created_at": now,
        "updated_at": now,
        "submitted_at": None,
        "notes": "Please score this answer.",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_result(result_id: uuid.UUID):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=result_id,
        run_id=uuid.uuid4(),
        question_id=uuid.uuid4(),
        status="completed",
        question_snapshot={
            "id": "q001",
            "question": "How should Yarrowia lipolytica be used for sustainable bioproduction?",
            "gold_answer_outline": "Discuss chassis traits and caveats.",
        },
        retrieved_sources=[{"pmid": "12345", "title": "Example paper"}],
        retrieved_pmids=["12345"],
        retrieved_dois=[],
        retrieved_chunk_ids=[],
        expected_pmids_present=True,
        expected_dois_present=None,
        coverage_status="gold_retrieved",
        recall_at_5=1.0,
        recall_at_10=1.0,
        recall_at_20=1.0,
        mrr_at_10=1.0,
        precision_at_k=0.2,
        response_text="Yarrowia lipolytica is useful but context dependent.",
        response_sources=[{"pmid": "12345"}],
        latency_ms=100,
        time_to_first_token_ms=None,
        failure_category=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def make_review(assignment, reviewer_id: uuid.UUID, **overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "assignment_id": assignment.id,
        "run_result_id": assignment.run_result_id,
        "reviewer_user_id": reviewer_id,
        "correctness_score": 4,
        "completeness_score": 4,
        "citation_support_score": 3,
        "grounding_score": 4,
        "usefulness_score": 4,
        "refusal_behavior": None,
        "false_premise_handling": None,
        "hallucination_flag": False,
        "citation_issue_flag": False,
        "corpus_gap_flag": False,
        "retrieval_issue_flag": False,
        "generation_issue_flag": False,
        "latency_issue_flag": False,
        "recommended_failure_category": None,
        "reviewer_confidence": 4,
        "free_text_feedback": "Looks useful.",
        "suggested_answer": None,
        "created_at": now,
        "updated_at": now,
        "submitted_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@asynccontextmanager
async def make_client(user: User):
    async def override_current_user():
        return user

    async def override_db():
        yield DummyDB()

    app.dependency_overrides[deps.get_current_user] = override_current_user
    app.dependency_overrides[deps.get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_researcher_lists_only_own_evaluation_review_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(role="evaluator")
    assignment = make_assignment(user.id)
    result = make_result(assignment.run_result_id)

    async def fake_list_assignments(_db, *, assigned_to_user_id, **_kwargs):
        assert assigned_to_user_id == user.id
        return [assignment]

    async def fake_get_result(_db, result_id):
        assert result_id == assignment.run_result_id
        return result

    async def fake_get_review(_db, assignment_id):
        assert assignment_id == assignment.id
        return None

    monkeypatch.setattr("app.db.crud.list_evaluation_review_assignments", fake_list_assignments)
    monkeypatch.setattr("app.db.crud.get_evaluation_run_result", fake_get_result)
    monkeypatch.setattr("app.db.crud.get_evaluation_review_by_assignment", fake_get_review)

    async with make_client(user) as client:
        response = await client.get("/api/v1/evaluation/reviews")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["assignment"]["assigned_to_user_id"] == str(user.id)
    assert body[0]["result"]["question_snapshot"]["id"] == "q001"


@pytest.mark.asyncio
async def test_researcher_cannot_open_another_review_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(role="evaluator")
    assignment = make_assignment(uuid.uuid4())

    async def fake_get_assignment(_db, assignment_id):
        assert assignment_id == assignment.id
        return assignment

    monkeypatch.setattr("app.db.crud.get_evaluation_review_assignment", fake_get_assignment)

    async with make_client(user) as client:
        response = await client.get(f"/api/v1/evaluation/reviews/{assignment.id}")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_researcher_submits_evaluation_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(role="evaluator")
    assignment = make_assignment(user.id)
    review = make_review(assignment, user.id)

    async def fake_get_assignment(_db, assignment_id):
        assert assignment_id == assignment.id
        return assignment

    async def fake_upsert(_db, *, data, reviewer_user_id, submitted, **_kwargs):
        assert data.correctness_score == 4
        assert reviewer_user_id == user.id
        assert submitted is True
        return review

    monkeypatch.setattr("app.db.crud.get_evaluation_review_assignment", fake_get_assignment)
    monkeypatch.setattr("app.db.crud.upsert_evaluation_review", fake_upsert)

    async with make_client(user) as client:
        response = await client.post(
            f"/api/v1/evaluation/reviews/{assignment.id}/submit",
            json={
                "correctness_score": 4,
                "completeness_score": 4,
                "citation_support_score": 3,
                "grounding_score": 4,
                "usefulness_score": 4,
                "reviewer_confidence": 4,
                "free_text_feedback": "Looks useful.",
            },
        )

    assert response.status_code == 200
    assert response.json()["reviewer_user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_researcher_role_cannot_access_evaluation_reviews() -> None:
    user = make_user(role="researcher")

    async with make_client(user) as client:
        response = await client.get("/api/v1/evaluation/reviews")

    assert response.status_code == 403
    assert response.json()["detail"] == "Evaluator access required"
