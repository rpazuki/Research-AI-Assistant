from __future__ import annotations

import json
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


def make_admin() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="hashed",
        full_name="Admin",
        role="admin",
        is_active=True,
        token_limit=1_000_000,
    )


def make_user(role: str = "researcher") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role}-{uuid.uuid4()}@example.com",
        hashed_password="hashed",
        full_name=role.title(),
        role=role,
        is_active=True,
        token_limit=1_000_000,
    )


def make_question_set(**overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "name": "seed-v1",
        "description": "Seed benchmark",
        "status": "draft",
        "created_by_user_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
        "metadata_": {"purpose": "beta"},
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_question(**overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "question_set_id": uuid.uuid4(),
        "external_id": "q001",
        "question": "What increases lipid accumulation in Yarrowia lipolytica?",
        "category": "factual",
        "difficulty": "easy",
        "domain_fit": "core",
        "expected_behavior": "answer",
        "expected_keywords": ["DGA1", "ACC1"],
        "expected_pmids": ["12345"],
        "expected_dois": [],
        "gold_answer_outline": "Discuss TAG synthesis and acetyl-CoA supply.",
        "supporting_evidence": [{"pmid": "12345", "evidence_note": "Supports DGA1."}],
        "requires_full_text": False,
        "review_status": "label_complete",
        "expert_owner_user_id": None,
        "notes": "Core domain",
        "created_by_user_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
        "archived_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_run(**overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "name": "Imported retrieval run",
        "mode": "retrieval",
        "status": "completed",
        "question_set_id": uuid.uuid4(),
        "started_by_user_id": uuid.uuid4(),
        "started_at": now,
        "completed_at": now,
        "corpus_manifest_id": None,
        "document_count": 10,
        "chunk_count": 40,
        "embedding_model": "pubmedbert",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "retrieval_config": {"retrieval_top_k": 20},
        "reranker_config": {},
        "llm_provider": None,
        "llm_model": None,
        "prompt_version": None,
        "git_commit": "abc123",
        "runner_version": "0.2.0",
        "summary_metrics": {"mean_recall_at_20": 1.0},
        "error_message": None,
        "artifact_paths": {"json": "evaluation/reports/eval.json"},
        "metadata_": {"source": "imported_report"},
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_run_result(**overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "question_id": uuid.uuid4(),
        "status": "completed",
        "question_snapshot": {"id": "q001", "question": "Question?"},
        "retrieved_sources": [{"pmid": "12345"}],
        "retrieved_pmids": ["12345"],
        "retrieved_dois": [],
        "retrieved_chunk_ids": [],
        "expected_pmids_present": None,
        "expected_dois_present": None,
        "coverage_status": "gold_retrieved",
        "recall_at_5": 1.0,
        "recall_at_10": 1.0,
        "recall_at_20": 1.0,
        "mrr_at_10": 1.0,
        "precision_at_k": 0.2,
        "response_text": None,
        "response_sources": [],
        "latency_ms": 12,
        "time_to_first_token_ms": None,
        "failure_category": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_assignment(**overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "run_result_id": uuid.uuid4(),
        "assigned_to_user_id": uuid.uuid4(),
        "assigned_by_user_id": uuid.uuid4(),
        "status": "assigned",
        "due_at": None,
        "created_at": now,
        "updated_at": now,
        "submitted_at": None,
        "notes": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_review(**overrides):
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    data = {
        "id": uuid.uuid4(),
        "assignment_id": uuid.uuid4(),
        "run_result_id": uuid.uuid4(),
        "reviewer_user_id": uuid.uuid4(),
        "correctness_score": 4,
        "completeness_score": 3,
        "citation_support_score": 4,
        "grounding_score": 4,
        "usefulness_score": 3,
        "refusal_behavior": None,
        "false_premise_handling": None,
        "hallucination_flag": False,
        "citation_issue_flag": False,
        "corpus_gap_flag": True,
        "retrieval_issue_flag": False,
        "generation_issue_flag": False,
        "latency_issue_flag": False,
        "recommended_failure_category": "corpus_gap",
        "reviewer_confidence": 4,
        "free_text_feedback": "Useful but corpus is thin.",
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
async def test_admin_evaluation_question_set_create_and_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_admin()
    question_set = make_question_set(created_by_user_id=admin.id)

    async def fake_get_by_name(_db, name: str):
        assert name == "seed-v1"
        return None

    async def fake_create(_db, *, data, created_by_user_id):
        assert data.name == "seed-v1"
        assert created_by_user_id == admin.id
        return question_set

    async def fake_list(_db):
        return [question_set]

    async def fake_counts(_db, question_set_ids):
        assert question_set.id in question_set_ids
        return {question_set.id: {"question_count": 2, "label_complete_count": 1}}

    monkeypatch.setattr("app.db.crud.get_evaluation_question_set_by_name", fake_get_by_name)
    monkeypatch.setattr("app.db.crud.create_evaluation_question_set", fake_create)
    monkeypatch.setattr("app.db.crud.list_evaluation_question_sets", fake_list)
    monkeypatch.setattr("app.db.crud.get_evaluation_question_set_counts", fake_counts)

    async with make_client(admin) as client:
        created = await client.post(
            "/api/v1/admin/evaluation/question-sets",
            json={"name": "seed-v1", "description": "Seed benchmark"},
        )
        listed = await client.get("/api/v1/admin/evaluation/question-sets")

    assert created.status_code == 201
    assert created.json()["name"] == "seed-v1"
    assert listed.status_code == 200
    assert listed.json()[0]["question_count"] == 2


@pytest.mark.asyncio
async def test_admin_evaluation_import_and_export_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_admin()
    question_set = make_question_set(created_by_user_id=admin.id)
    question = make_question(question_set_id=question_set.id, created_by_user_id=admin.id)

    async def fake_get_set(_db, question_set_id):
        assert question_set_id == question_set.id
        return question_set

    async def fake_get_question_by_external_id(_db, *, question_set_id, external_id):
        assert question_set_id == question_set.id
        assert external_id == "q001"
        return None

    async def fake_create_question(_db, *, question_set_id, data, created_by_user_id):
        assert question_set_id == question_set.id
        assert data.external_id == "q001"
        assert created_by_user_id == admin.id
        return question

    async def fake_list_questions(_db, *, question_set_id, include_archived, **_filters):
        assert question_set_id == question_set.id
        assert include_archived is False
        return [question]

    monkeypatch.setattr("app.db.crud.get_evaluation_question_set", fake_get_set)
    monkeypatch.setattr(
        "app.db.crud.get_evaluation_question_by_external_id",
        fake_get_question_by_external_id,
    )
    monkeypatch.setattr("app.db.crud.create_evaluation_question", fake_create_question)
    monkeypatch.setattr("app.db.crud.list_evaluation_questions", fake_list_questions)

    payload = {
        "questions": [
            {
                "external_id": "q001",
                "question": question.question,
                "category": "factual",
                "difficulty": "easy",
                "expected_pmids": ["12345"],
                "expected_keywords": ["DGA1"],
                "review_status": "label_complete",
            }
        ]
    }

    async with make_client(admin) as client:
        imported = await client.post(
            f"/api/v1/admin/evaluation/question-sets/{question_set.id}/import",
            json=payload,
        )
        exported = await client.get(
            f"/api/v1/admin/evaluation/question-sets/{question_set.id}/export"
        )

    assert imported.status_code == 200
    assert imported.json()["created"] == 1
    assert imported.json()["questions"][0]["external_id"] == "q001"
    assert exported.status_code == 200
    exported_record = json.loads(exported.text.strip())
    assert exported_record["id"] == "q001"
    assert exported_record["expected_pmids"] == ["12345"]


@pytest.mark.asyncio
async def test_admin_evaluation_run_create_and_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_admin()
    question_set = make_question_set(created_by_user_id=admin.id)
    run = make_run(question_set_id=question_set.id, started_by_user_id=admin.id)

    async def fake_get_set(_db, question_set_id):
        assert question_set_id == question_set.id
        return question_set

    async def fake_create_run(_db, *, data, started_by_user_id, **_kwargs):
        assert data.name == "Baseline retrieval"
        assert data.question_set_id == question_set.id
        assert started_by_user_id == admin.id
        return run

    async def fake_list_runs(_db, **kwargs):
        assert kwargs["limit"] == 50
        return [run]

    monkeypatch.setattr("app.db.crud.get_evaluation_question_set", fake_get_set)
    monkeypatch.setattr("app.db.crud.create_evaluation_run", fake_create_run)
    monkeypatch.setattr("app.db.crud.list_evaluation_runs", fake_list_runs)

    async with make_client(admin) as client:
        created = await client.post(
            "/api/v1/admin/evaluation/runs",
            json={
                "name": "Baseline retrieval",
                "mode": "retrieval",
                "status": "queued",
                "question_set_id": str(question_set.id),
            },
        )
        listed = await client.get("/api/v1/admin/evaluation/runs")

    assert created.status_code == 201
    assert created.json()["name"] == "Imported retrieval run"
    assert listed.status_code == 200
    assert listed.json()[0]["summary_metrics"]["mean_recall_at_20"] == 1.0


@pytest.mark.asyncio
async def test_admin_evaluation_import_report_and_list_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_admin()
    question_set = make_question_set(created_by_user_id=admin.id)
    question = make_question(question_set_id=question_set.id, created_by_user_id=admin.id)
    run = make_run(question_set_id=question_set.id, started_by_user_id=admin.id)
    created_results = []

    async def fake_get_set(_db, question_set_id):
        assert question_set_id == question_set.id
        return question_set

    async def fake_get_questions_by_external_ids(_db, *, question_set_id, external_ids):
        assert question_set_id == question_set.id
        assert "q001" in external_ids
        return {"q001": question}

    async def fake_create_run(_db, *, data, started_by_user_id, summary_metrics, **kwargs):
        assert data.status == "completed"
        assert data.name == "Imported run"
        assert data.question_set_id == question_set.id
        assert started_by_user_id == admin.id
        assert summary_metrics["mean_recall_at_20"] == 1.0
        assert kwargs["document_count"] == 10
        return run

    async def fake_create_result(_db, **kwargs):
        assert kwargs["run_id"] == run.id
        assert kwargs["question_id"] == question.id
        assert kwargs["recall_at_20"] == 1.0
        result = make_run_result(run_id=run.id, question_id=question.id)
        created_results.append(result)
        return result

    async def fake_get_run(_db, run_id):
        assert run_id == run.id
        return run

    async def fake_list_results(_db, *, run_id):
        assert run_id == run.id
        return created_results

    monkeypatch.setattr("app.db.crud.get_evaluation_question_set", fake_get_set)
    monkeypatch.setattr(
        "app.db.crud.get_evaluation_questions_by_external_ids",
        fake_get_questions_by_external_ids,
    )
    monkeypatch.setattr("app.db.crud.create_evaluation_run", fake_create_run)
    monkeypatch.setattr("app.db.crud.create_evaluation_run_result", fake_create_result)
    monkeypatch.setattr("app.db.crud.get_evaluation_run", fake_get_run)
    monkeypatch.setattr("app.db.crud.list_evaluation_run_results", fake_list_results)

    report = {
        "metadata": {
            "runner_version": "0.2.0",
            "git_commit": "abc123",
            "mode": "retrieval",
            "backend": {"document_count": 10, "chunk_count": 40},
            "config": {"retrieval_top_k": 20},
        },
        "summary": {"mode": "retrieval", "mean_recall_at_20": 1.0},
        "results": [
            {
                "id": "q001",
                "question": question.question,
                "status": "completed",
                "coverage_status": "gold_retrieved",
                "retrieved_pmids": ["12345"],
                "retrieved_sources": [{"pmid": "12345"}],
                "recall_at_20": 1.0,
                "mrr_at_10": 1.0,
                "latency_ms": 12,
                "question_snapshot": {"id": "q001", "question": question.question},
            }
        ],
    }

    async with make_client(admin) as client:
        imported = await client.post(
            "/api/v1/admin/evaluation/runs/import-report",
            json={
                "name": "Imported run",
                "question_set_id": str(question_set.id),
                "report": report,
            },
        )
        results = await client.get(f"/api/v1/admin/evaluation/runs/{run.id}/results")

    assert imported.status_code == 201
    assert imported.json()["result_count"] == 1
    assert imported.json()["linked_question_count"] == 1
    assert results.status_code == 200
    assert results.json()[0]["retrieved_pmids"] == ["12345"]


@pytest.mark.asyncio
async def test_admin_evaluation_execute_and_release_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_admin()
    run = make_run(started_by_user_id=admin.id, status="failed")

    async def fake_get_run(_db, run_id):
        assert run_id == run.id
        return run

    async def fake_update_run(_db, *, run: SimpleNamespace, **kwargs):
        for key, value in kwargs.items():
            if value is not None:
                setattr(run, "metadata_" if key == "metadata" else key, value)
        return run

    monkeypatch.setattr("app.db.crud.get_evaluation_run", fake_get_run)
    monkeypatch.setattr("app.db.crud.update_evaluation_run", fake_update_run)
    monkeypatch.setattr(
        "app.api.routes.admin_evaluation.get_worker_status",
        lambda: {
            "active": True,
            "state": "polling",
            "run_id": None,
            "updated_at": "2026-06-20T10:00:00+00:00",
            "seconds_since_heartbeat": 1,
            "message": "Worker heartbeat is current.",
        },
    )

    async with make_client(admin) as client:
        executed = await client.post(
            f"/api/v1/admin/evaluation/runs/{run.id}/execute",
        )
        gate = await client.get(f"/api/v1/admin/evaluation/runs/{run.id}/release-gate")
        decision = await client.post(
            f"/api/v1/admin/evaluation/runs/{run.id}/release-decision",
            json={"status": "waived", "note": "Small seed benchmark only."},
        )
        gate_after_decision = await client.get(
            f"/api/v1/admin/evaluation/runs/{run.id}/release-gate"
        )
        worker = await client.get("/api/v1/admin/evaluation/worker")

    assert executed.status_code == 200
    assert executed.json()["status"] == "queued"
    assert gate.status_code == 200
    assert gate.json()["status"] in {"passed", "failed"}
    assert decision.status_code == 200
    assert decision.json()["metadata"]["release_decision"]["status"] == "waived"
    assert gate_after_decision.json()["release_decision"]["note"] == "Small seed benchmark only."
    assert worker.status_code == 200
    assert worker.json()["active"] is True


@pytest.mark.asyncio
async def test_admin_evaluation_assignment_review_and_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_admin()
    reviewer = make_user(role="evaluator")
    run = make_run()
    result = make_run_result(run_id=run.id)
    assignment = make_assignment(
        run_result_id=result.id,
        assigned_to_user_id=reviewer.id,
        assigned_by_user_id=admin.id,
    )
    review = make_review(
        assignment_id=assignment.id,
        run_result_id=result.id,
        reviewer_user_id=admin.id,
    )
    baseline = make_run(summary_metrics={"mean_recall_at_20": 0.4, "n_failed": 0})
    candidate = make_run(summary_metrics={"mean_recall_at_20": 0.7, "n_failed": 0})

    async def fake_get_result(_db, result_id):
        assert result_id == result.id
        return result

    async def fake_get_user(_db, user_id):
        return reviewer if user_id == reviewer.id else admin

    async def fake_create_assignment(_db, **kwargs):
        assert kwargs["assigned_to_user_id"] == reviewer.id
        return assignment

    async def fake_list_assignments(_db, **_kwargs):
        return [assignment]

    async def fake_get_assignment(_db, assignment_id):
        assert assignment_id == assignment.id
        return assignment

    async def fake_get_review(_db, assignment_id):
        assert assignment_id == assignment.id
        return review

    async def fake_upsert_review(_db, *, data, submitted, **_kwargs):
        assert data.correctness_score == 4
        assert submitted is True
        return review

    async def fake_get_run(_db, run_id):
        if run_id == run.id:
            return run
        if run_id == baseline.id:
            return baseline
        if run_id == candidate.id:
            return candidate
        return None

    async def fake_list_results(_db, *, run_id):
        return [make_run_result(run_id=run_id, question_snapshot={"id": "q001"})]

    monkeypatch.setattr("app.db.crud.get_evaluation_run_result", fake_get_result)
    monkeypatch.setattr("app.db.crud.get_user_by_id", fake_get_user)
    monkeypatch.setattr("app.db.crud.create_evaluation_review_assignment", fake_create_assignment)
    monkeypatch.setattr("app.db.crud.list_evaluation_review_assignments", fake_list_assignments)
    monkeypatch.setattr("app.db.crud.get_evaluation_review_assignment", fake_get_assignment)
    monkeypatch.setattr("app.db.crud.get_evaluation_review_by_assignment", fake_get_review)
    monkeypatch.setattr("app.db.crud.upsert_evaluation_review", fake_upsert_review)
    monkeypatch.setattr("app.db.crud.get_evaluation_run", fake_get_run)
    monkeypatch.setattr("app.db.crud.list_evaluation_run_results", fake_list_results)

    async with make_client(admin) as client:
        assigned = await client.post(
            f"/api/v1/admin/evaluation/results/{result.id}/assignments",
            json={"assigned_to_user_id": str(reviewer.id)},
        )
        assignments = await client.get("/api/v1/admin/evaluation/assignments")
        saved = await client.post(
            f"/api/v1/admin/evaluation/assignments/{assignment.id}/review?submit=true",
            json={"correctness_score": 4, "corpus_gap_flag": True},
        )
        tasks = await client.get(f"/api/v1/admin/evaluation/runs/{run.id}/review-tasks")
        exported = await client.get(
            f"/api/v1/admin/evaluation/runs/{run.id}/reviews/export?format=json"
        )
        comparison = await client.post(
            "/api/v1/admin/evaluation/compare",
            json={
                "baseline_run_id": str(baseline.id),
                "candidate_run_id": str(candidate.id),
            },
        )

    assert assigned.status_code == 201
    assert assigned.json()["assigned_to_user_id"] == str(reviewer.id)
    assert assignments.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["recommended_failure_category"] == "corpus_gap"
    assert tasks.status_code == 200
    assert tasks.json()[0]["review"]["correctness_score"] == 4
    assert exported.status_code == 200
    assert exported.json()[0]["free_text_feedback"] == "Useful but corpus is thin."
    assert comparison.status_code == 200
    assert comparison.json()["recommendation"] == "candidate_improves_retrieval"


@pytest.mark.asyncio
async def test_admin_evaluation_assignment_requires_evaluator_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_admin()
    researcher = make_user(role="researcher")
    result = make_run_result()

    async def fake_get_result(_db, result_id):
        assert result_id == result.id
        return result

    async def fake_get_user(_db, user_id):
        assert user_id == researcher.id
        return researcher

    monkeypatch.setattr("app.db.crud.get_evaluation_run_result", fake_get_result)
    monkeypatch.setattr("app.db.crud.get_user_by_id", fake_get_user)

    async with make_client(admin) as client:
        response = await client.post(
            f"/api/v1/admin/evaluation/results/{result.id}/assignments",
            json={"assigned_to_user_id": str(researcher.id)},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Evaluation reviews can only be assigned to admin or evaluator users"
    )
