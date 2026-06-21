"""In-app evaluation execution and scoring helpers."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import crud
from app.db.models import EvaluationQuestion, EvaluationRun, utcnow
from app.embeddings.registry import get_embedding_model
from app.providers.registry import get_llm_provider
from app.rag.pipeline import run_rag_stream
from app.rag.retrieval import RetrievedChunk, retrieve

RUNNER_VERSION = "0.2.0"


DEFAULT_RELEASE_THRESHOLDS = {
    "mean_recall_at_20": 0.75,
    "mean_mrr_at_10": 0.45,
    "n_failed": 0,
}


class EvaluationCancelled(Exception):
    """Raised when a running evaluation observes a cancellation request."""


async def execute_evaluation_run(db: AsyncSession, *, run_id: uuid.UUID) -> EvaluationRun:
    """Execute a queued/running evaluation run and persist per-question results."""
    run = await crud.get_evaluation_run(db, run_id)
    if run is None:
        raise ValueError(f"Evaluation run {run_id} was not found")
    if run.question_set_id is None:
        raise ValueError("Evaluation run must be linked to a question set before execution")
    if run.status == "cancel_requested":
        return await _mark_run_cancelled(db, run)

    questions = await crud.list_evaluation_questions(
        db,
        question_set_id=run.question_set_id,
        include_archived=False,
    )
    executable_questions = [
        question for question in questions if question.review_status != "retired"
    ]
    if not executable_questions:
        raise ValueError("Evaluation question set has no executable questions")

    await crud.delete_evaluation_run_results(db, run_id=run.id)
    await crud.update_evaluation_run(
        db,
        run=run,
        status="running",
        started_at=run.started_at or utcnow(),
        completed_at=None,
        runner_version=f"in-app/{RUNNER_VERSION}",
        metadata={
            **(run.metadata_ or {}),
            "progress_message": "Starting evaluation",
            "question_count": len(executable_questions),
        },
    )
    await db.flush()

    embedder = get_embedding_model()
    llm_provider = get_llm_provider() if run.mode in {"rag", "combined"} else None
    all_results: list[dict[str, Any]] = []

    if run.mode in {"retrieval", "combined"}:
        retrieval_results = await _run_retrieval_phase(db, run, executable_questions, embedder)
        all_results.extend(retrieval_results)

    if run.mode in {"rag", "combined"}:
        if llm_provider is None:
            raise ValueError("RAG evaluation requires an LLM provider")
        rag_results = await _run_rag_phase(db, run, executable_questions, embedder, llm_provider)
        all_results.extend(rag_results)

    summary = _summarise_results(run.mode, all_results)
    release_gate = evaluate_release_gate(summary)
    completed_run = await crud.update_evaluation_run(
        db,
        run=run,
        status="completed",
        completed_at=utcnow(),
        summary_metrics={**summary, "release_gate": release_gate},
        embedding_model=getattr(embedder, "model_name", settings.embedding_model),
        retrieval_config={
            **(run.retrieval_config or {}),
            "retrieval_final_top_k": settings.retrieval_final_top_k,
            "retrieval_vector_top_k": settings.retrieval_vector_top_k,
            "retrieval_lexical_top_k": settings.retrieval_lexical_top_k,
        },
        llm_provider=settings.llm_provider if run.mode in {"rag", "combined"} else run.llm_provider,
        llm_model=settings.llm_model if run.mode in {"rag", "combined"} else run.llm_model,
        metadata={
            **(run.metadata_ or {}),
            "progress_message": "Evaluation completed",
            "completed_question_count": len(all_results),
        },
    )
    return completed_run


async def _run_retrieval_phase(
    db: AsyncSession,
    run: EvaluationRun,
    questions: list[EvaluationQuestion],
    embedder,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    top_k = int((run.retrieval_config or {}).get("top_k") or settings.retrieval_final_top_k)
    for index, question in enumerate(questions, 1):
        await _raise_if_cancelled(db, run)
        await crud.update_evaluation_run_progress(
            db,
            run,
            f"Retrieval {index}/{len(questions)}: {question.external_id}",
        )
        await db.flush()
        if not question.expected_pmids and not question.expected_dois:
            result = await crud.create_evaluation_run_result(
                db,
                run_id=run.id,
                question_id=question.id,
                status="skipped",
                question_snapshot=_question_snapshot(question),
                coverage_status="missing_gold_labels",
                failure_category="missing_gold_labels",
                error_message="Question has no expected PMIDs or DOIs for retrieval scoring",
            )
            results.append(_result_record(result))
            continue

        started = time.monotonic()
        try:
            chunks = await retrieve(
                query=question.question,
                db=db,
                embedding_model=embedder,
                final_top_k=top_k,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            retrieved_pmids = [_normalise_pmid(chunk.pmid) for chunk in chunks if _normalise_pmid(chunk.pmid)]
            retrieved_dois = [_normalise_doi(chunk.doi) for chunk in chunks if _normalise_doi(chunk.doi)]
            expected_pmids = [_normalise_pmid(pmid) for pmid in question.expected_pmids if _normalise_pmid(pmid)]
            expected_dois = [_normalise_doi(doi) for doi in question.expected_dois if _normalise_doi(doi)]
            recall_at_5 = compute_recall_at_k(
                retrieved_pmids, expected_pmids, 5, retrieved_dois, expected_dois
            )
            recall_at_10 = compute_recall_at_k(
                retrieved_pmids, expected_pmids, 10, retrieved_dois, expected_dois
            )
            recall_at_20 = compute_recall_at_k(
                retrieved_pmids, expected_pmids, 20, retrieved_dois, expected_dois
            )
            mrr_at_10 = compute_mrr(
                retrieved_pmids, expected_pmids, 10, retrieved_dois, expected_dois
            )
            precision_at_5 = compute_precision_at_k(
                retrieved_pmids, expected_pmids, 5, retrieved_dois, expected_dois
            )
            coverage_status = (
                "gold_retrieved"
                if _has_any_match(retrieved_pmids, expected_pmids, retrieved_dois, expected_dois)
                else "not_retrieved_or_missing"
            )
            result = await crud.create_evaluation_run_result(
                db,
                run_id=run.id,
                question_id=question.id,
                status="completed",
                question_snapshot=_question_snapshot(question),
                retrieved_sources=[_chunk_to_source(chunk) for chunk in chunks],
                retrieved_pmids=retrieved_pmids,
                retrieved_dois=retrieved_dois,
                retrieved_chunk_ids=[chunk.chunk_id for chunk in chunks],
                expected_pmids_present=bool(set(retrieved_pmids).intersection(expected_pmids)),
                expected_dois_present=bool(set(retrieved_dois).intersection(expected_dois)),
                coverage_status=coverage_status,
                recall_at_5=recall_at_5,
                recall_at_10=recall_at_10,
                recall_at_20=recall_at_20,
                mrr_at_10=mrr_at_10,
                precision_at_k=precision_at_5,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            result = await crud.create_evaluation_run_result(
                db,
                run_id=run.id,
                question_id=question.id,
                status="failed",
                question_snapshot=_question_snapshot(question),
                coverage_status="not_applicable",
                failure_category="retrieval_error",
                error_message=str(exc),
            )
        results.append(_result_record(result))
    return results


async def _run_rag_phase(
    db: AsyncSession,
    run: EvaluationRun,
    questions: list[EvaluationQuestion],
    embedder,
    llm_provider,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    top_k = int((run.retrieval_config or {}).get("top_k") or settings.retrieval_final_top_k)
    for index, question in enumerate(questions, 1):
        await _raise_if_cancelled(db, run)
        await crud.update_evaluation_run_progress(
            db,
            run,
            f"RAG {index}/{len(questions)}: {question.external_id}",
        )
        await db.flush()
        started = time.monotonic()
        response_parts: list[str] = []
        sources: list[dict[str, Any]] = []
        done_payload: dict[str, Any] = {}
        try:
            async for event_type, data, event_sources in run_rag_stream(
                query=question.question,
                mode="researcher",
                db=db,
                embedding_model=embedder,
                llm_provider=llm_provider,
                top_k=top_k,
            ):
                if event_type == "token":
                    response_parts.append(str(data or ""))
                elif event_type == "sources":
                    sources = [
                        source.model_dump() if hasattr(source, "model_dump") else dict(source)
                        for source in (event_sources or [])
                    ]
                elif event_type == "done" and isinstance(data, dict):
                    done_payload = data
                elif event_type == "error":
                    raise RuntimeError(str(data))

            latency_ms = int(done_payload.get("latency_ms") or ((time.monotonic() - started) * 1000))
            result = await crud.create_evaluation_run_result(
                db,
                run_id=run.id,
                question_id=question.id,
                status="completed",
                question_snapshot=_question_snapshot(question),
                response_text="".join(response_parts),
                response_sources=sources,
                retrieved_pmids=[pmid for source in sources if (pmid := _normalise_pmid(source.get("pmid")))],
                retrieved_dois=[doi for source in sources if (doi := _normalise_doi(source.get("doi")))],
                retrieved_chunk_ids=[
                    uuid.UUID(chunk_id)
                    for chunk_id in done_payload.get("retrieved_chunk_ids", [])
                    if _is_uuid(chunk_id)
                ],
                coverage_status=_rag_coverage_status(question, sources),
                latency_ms=latency_ms,
            )
        except Exception as exc:
            result = await crud.create_evaluation_run_result(
                db,
                run_id=run.id,
                question_id=question.id,
                status="failed",
                question_snapshot=_question_snapshot(question),
                coverage_status="not_applicable",
                failure_category="generation_error",
                error_message=str(exc),
            )
        results.append(_result_record(result))
    return results


def evaluate_release_gate(summary: dict[str, Any], thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    active_thresholds = {**DEFAULT_RELEASE_THRESHOLDS, **(thresholds or {})}
    checks = []
    for metric, threshold in active_thresholds.items():
        value = summary.get(metric)
        if value is None:
            passed = False
        elif metric == "n_failed":
            passed = float(value) <= float(threshold)
        else:
            passed = float(value) >= float(threshold)
        checks.append(
            {
                "metric": metric,
                "value": value,
                "threshold": threshold,
                "passed": passed,
            }
        )
    return {
        "status": "passed" if all(check["passed"] for check in checks) else "failed",
        "checks": checks,
    }


async def _raise_if_cancelled(db: AsyncSession, run: EvaluationRun) -> None:
    await db.refresh(run)
    if run.status == "cancel_requested":
        await _mark_run_cancelled(db, run)
        raise EvaluationCancelled()


async def _mark_run_cancelled(db: AsyncSession, run: EvaluationRun) -> EvaluationRun:
    return await crud.update_evaluation_run(
        db,
        run=run,
        status="cancelled",
        completed_at=utcnow(),
        metadata={**(run.metadata_ or {}), "progress_message": "Evaluation cancelled"},
    )


def compare_run_summaries(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    baseline_results: list[Any],
    candidate_results: list[Any],
) -> dict[str, Any]:
    metrics = [
        "mean_recall_at_5",
        "mean_recall_at_10",
        "mean_recall_at_20",
        "mean_mrr_at_10",
        "mean_precision_at_5",
        "mean_latency_ms",
        "n_failed",
    ]
    metric_deltas = []
    baseline_summary = baseline.summary_metrics or {}
    candidate_summary = candidate.summary_metrics or {}
    for metric in metrics:
        before = baseline_summary.get(metric)
        after = candidate_summary.get(metric)
        delta = after - before if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
        metric_deltas.append({"metric": metric, "baseline": before, "candidate": after, "delta": delta})

    baseline_by_question = {
        str((result.question_snapshot or {}).get("id") or result.question_id): result
        for result in baseline_results
    }
    question_deltas = []
    for result in candidate_results:
        key = str((result.question_snapshot or {}).get("id") or result.question_id)
        previous = baseline_by_question.get(key)
        question_deltas.append(
            {
                "question_id": key,
                "baseline_coverage": previous.coverage_status if previous else None,
                "candidate_coverage": result.coverage_status,
                "baseline_recall_at_20": previous.recall_at_20 if previous else None,
                "candidate_recall_at_20": result.recall_at_20,
                "baseline_mrr_at_10": previous.mrr_at_10 if previous else None,
                "candidate_mrr_at_10": result.mrr_at_10,
            }
        )

    return {
        "baseline_run_id": baseline.id,
        "candidate_run_id": candidate.id,
        "metric_deltas": metric_deltas,
        "question_deltas": question_deltas,
        "recommendation": _comparison_recommendation(metric_deltas),
    }


def compute_recall_at_k(
    retrieved_pmids: list[str],
    expected_pmids: list[str],
    k: int,
    retrieved_dois: list[str] | None = None,
    expected_dois: list[str] | None = None,
) -> float:
    expected_dois = expected_dois or []
    retrieved_dois = retrieved_dois or []
    if not expected_pmids and not expected_dois:
        return float("nan")
    top_pmids = set(retrieved_pmids[:k])
    top_dois = set(retrieved_dois[:k])
    return 1.0 if top_pmids.intersection(expected_pmids) or top_dois.intersection(expected_dois) else 0.0


def compute_mrr(
    retrieved_pmids: list[str],
    expected_pmids: list[str],
    k: int = 10,
    retrieved_dois: list[str] | None = None,
    expected_dois: list[str] | None = None,
) -> float:
    expected_dois = expected_dois or []
    retrieved_dois = retrieved_dois or []
    if not expected_pmids and not expected_dois:
        return float("nan")
    for rank in range(min(k, max(len(retrieved_pmids), len(retrieved_dois)))):
        pmid = retrieved_pmids[rank] if rank < len(retrieved_pmids) else None
        doi = retrieved_dois[rank] if rank < len(retrieved_dois) else None
        if pmid in expected_pmids or doi in expected_dois:
            return 1.0 / (rank + 1)
    return 0.0


def compute_precision_at_k(
    retrieved_pmids: list[str],
    expected_pmids: list[str],
    k: int,
    retrieved_dois: list[str] | None = None,
    expected_dois: list[str] | None = None,
) -> float:
    expected_dois = expected_dois or []
    retrieved_dois = retrieved_dois or []
    if not expected_pmids and not expected_dois:
        return float("nan")
    matches = 0
    for rank in range(min(k, max(len(retrieved_pmids), len(retrieved_dois)))):
        pmid = retrieved_pmids[rank] if rank < len(retrieved_pmids) else None
        doi = retrieved_dois[rank] if rank < len(retrieved_dois) else None
        if pmid in expected_pmids or doi in expected_dois:
            matches += 1
    return matches / k if k else float("nan")


def _comparison_recommendation(metric_deltas: list[dict[str, Any]]) -> str:
    failed_delta = next((item["delta"] for item in metric_deltas if item["metric"] == "n_failed"), None)
    recall_delta = next((item["delta"] for item in metric_deltas if item["metric"] == "mean_recall_at_20"), None)
    mrr_delta = next((item["delta"] for item in metric_deltas if item["metric"] == "mean_mrr_at_10"), None)
    if failed_delta is not None and failed_delta > 0:
        return "investigate_candidate"
    if recall_delta is not None and recall_delta < -0.05:
        return "reject_candidate"
    if mrr_delta is not None and mrr_delta < -0.05:
        return "investigate_candidate"
    if recall_delta is not None and recall_delta > 0.02:
        return "candidate_improves_retrieval"
    return "no_material_change"


def _summarise_results(mode: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [result for result in results if result.get("status") == "completed"]
    failed = [result for result in results if result.get("status") == "failed"]
    skipped = [result for result in results if result.get("status") == "skipped"]
    return {
        "mode": mode,
        "n_loaded": len(results),
        "n_questions": len(completed),
        "n_failed": len(failed),
        "n_skipped": len(skipped),
        "mean_recall_at_5": _mean([result.get("recall_at_5") for result in completed]),
        "mean_recall_at_10": _mean([result.get("recall_at_10") for result in completed]),
        "mean_recall_at_20": _mean([result.get("recall_at_20") for result in completed]),
        "mean_mrr_at_10": _mean([result.get("mrr_at_10") for result in completed]),
        "mean_precision_at_5": _mean([result.get("precision_at_k") for result in completed]),
        "mean_latency_ms": int(_mean([result.get("latency_ms") for result in completed])),
    }


def _mean(values: list[Any]) -> float:
    numeric = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not math.isnan(float(value))
    ]
    return sum(numeric) / len(numeric) if numeric else 0.0


def _question_snapshot(question: EvaluationQuestion) -> dict[str, Any]:
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
        "requires_full_text": question.requires_full_text,
        "review_status": question.review_status,
    }


def _chunk_to_source(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.chunk_id),
        "document_id": chunk.document_id,
        "pmid": chunk.pmid,
        "doi": chunk.doi,
        "title": chunk.title,
        "journal": chunk.journal,
        "year": chunk.year,
        "url": chunk.url,
        "content": chunk.content,
        "score": chunk.score,
        "chunk_type": chunk.chunk_type,
    }


def _result_record(result) -> dict[str, Any]:
    return {
        "status": result.status,
        "recall_at_5": result.recall_at_5,
        "recall_at_10": result.recall_at_10,
        "recall_at_20": result.recall_at_20,
        "mrr_at_10": result.mrr_at_10,
        "precision_at_k": result.precision_at_k,
        "latency_ms": result.latency_ms,
    }


def _rag_coverage_status(question: EvaluationQuestion, sources: list[dict[str, Any]]) -> str:
    expected_pmids = [_normalise_pmid(pmid) for pmid in question.expected_pmids if _normalise_pmid(pmid)]
    expected_dois = [_normalise_doi(doi) for doi in question.expected_dois if _normalise_doi(doi)]
    if not expected_pmids and not expected_dois:
        return "not_applicable"
    source_pmids = [pmid for source in sources if (pmid := _normalise_pmid(source.get("pmid")))]
    source_dois = [doi for source in sources if (doi := _normalise_doi(source.get("doi")))]
    return (
        "gold_retrieved"
        if _has_any_match(source_pmids, expected_pmids, source_dois, expected_dois)
        else "not_retrieved_or_missing"
    )


def _has_any_match(
    retrieved_pmids: list[str],
    expected_pmids: list[str],
    retrieved_dois: list[str],
    expected_dois: list[str],
) -> bool:
    return bool(set(retrieved_pmids).intersection(expected_pmids) or set(retrieved_dois).intersection(expected_dois))


def _normalise_pmid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.removeprefix("pmid:").strip()


def _normalise_doi(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    return text.removeprefix("doi:").removeprefix("https://doi.org/").strip()


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True
