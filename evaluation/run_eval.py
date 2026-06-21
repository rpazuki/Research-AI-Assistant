"""
evaluation/run_eval.py
-----------------------
CLI evaluation runner.

Usage:
    python evaluation/run_eval.py --mode retrieval --api-url http://localhost:8000 --token <jwt>
    python evaluation/run_eval.py --mode rag --api-url http://localhost:8000 --token <jwt>
    python evaluation/run_eval.py --mode retrieval --question-id q001 ...

Outputs:
    - Console summary (recall@k, MRR, latency)
    - evaluation/reports/eval_{mode}_{timestamp}.json (full results)
"""

import argparse
import csv
import json
import math
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

try:
    from evaluation.config import EvaluationConfig, load_evaluation_config
except ModuleNotFoundError:  # pragma: no cover - used for direct script execution
    from config import EvaluationConfig, load_evaluation_config

RUNNER_VERSION = "0.2.0"
SUPPORTED_OUTPUT_FORMATS = {"json", "jsonl", "markdown", "csv"}


def _parse_sse_stream(response: httpx.Response) -> tuple[str, list[dict], int | None]:
    answer_parts: list[str] = []
    sources: list[dict] = []
    latency_ms: int | None = None

    for line in response.iter_lines():
        if not line or not line.startswith("data: "):
            continue

        payload = json.loads(line[6:])
        event_type = payload.get("type")
        if event_type == "token":
            answer_parts.append(payload.get("data", ""))
        elif event_type == "sources":
            sources = payload.get("data", [])
        elif event_type == "done":
            latency_ms = payload.get("latency_ms")
            break
        elif event_type == "error":
            raise RuntimeError(payload.get("message", "Unknown SSE error"))

    return "".join(answer_parts), sources, latency_ms


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def _normalise_pmid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    return match.group(1) if match else text


def _normalise_doi(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text or None


def _expected_pmids(question: dict) -> list[str]:
    return [pmid for value in question.get("expected_pmids", []) if (pmid := _normalise_pmid(value))]


def _expected_dois(question: dict) -> list[str]:
    return [doi for value in question.get("expected_dois", []) if (doi := _normalise_doi(value))]


def _retrieved_pmids(items: list[dict]) -> list[str]:
    return [pmid for item in items if (pmid := _normalise_pmid(item.get("pmid")))]


def _retrieved_dois(items: list[dict]) -> list[str]:
    return [doi for item in items if (doi := _normalise_doi(item.get("doi")))]


def _has_gold_labels(question: dict) -> bool:
    return bool(_expected_pmids(question) or _expected_dois(question))


def _question_snapshot(question: dict) -> dict:
    keys = [
        "id",
        "question",
        "category",
        "difficulty",
        "domain_fit",
        "expected_behavior",
        "expected_pmids",
        "expected_dois",
        "expected_keywords",
        "gold_answer_outline",
        "requires_full_text",
        "review_status",
        "notes",
    ]
    return {key: question.get(key) for key in keys if key in question}


def _mean(values: list[float]) -> float:
    usable = [value for value in values if not math.isnan(value)]
    return sum(usable) / len(usable) if usable else 0.0


def _fetch_backend_metadata(client: httpx.Client, api_url: str, token: str) -> dict:
    try:
        response = client.get(
            f"{api_url}/api/v1/analytics/corpus_stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def _base_metadata(
    *,
    mode: str,
    api_url: str,
    config: EvaluationConfig,
    questions: list[dict],
    filters: dict[str, str | None] | None = None,
    backend_metadata: dict | None = None,
) -> dict:
    return {
        "runner_version": RUNNER_VERSION,
        "timestamp": _now_iso(),
        "git_commit": _safe_git_commit(),
        "mode": mode,
        "api_url": api_url,
        "question_count": len(questions),
        "filters": filters or {},
        "config": {
            "benchmark_file": str(config.benchmark_file),
            "retrieval_top_k": config.retrieval_top_k,
            "mrr_at_k": config.mrr_at_k,
            "session_mode": config.session_mode,
            "evaluation_env": config.evaluation_env,
        },
        "backend": backend_metadata or {},
        "question_snapshot": [_question_snapshot(question) for question in questions],
    }


def load_questions(
    question_id: str | None = None,
    category: str | None = None,
    difficulty: str | None = None,
    limit: int | None = None,
    config: EvaluationConfig | None = None,
) -> list[dict]:
    active_config = config or load_evaluation_config()
    questions = []
    with active_config.benchmark_file.open(encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            if question_id is not None and q["id"] != question_id:
                continue
            if category is not None and q.get("category") != category:
                continue
            if difficulty is not None and q.get("difficulty") != difficulty:
                continue
            questions.append(q)
            if limit is not None and len(questions) >= limit:
                break
    return questions


def compute_recall_at_k(
    retrieved_pmids: list[str],
    expected_pmids: list[str],
    k: int,
    retrieved_dois: list[str] | None = None,
    expected_dois: list[str] | None = None,
) -> float:
    """1.0 if any expected PMID/DOI appears in top-k retrieved, else 0.0."""
    expected_dois = expected_dois or []
    retrieved_dois = retrieved_dois or []
    if not expected_pmids and not expected_dois:
        return float("nan")
    top_pmids = set(retrieved_pmids[:k])
    top_dois = set(retrieved_dois[:k])
    pmid_match = any(pmid in top_pmids for pmid in expected_pmids)
    doi_match = any(doi in top_dois for doi in expected_dois)
    return 1.0 if pmid_match or doi_match else 0.0


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


def _extract_source_pmids(sources: list[dict]) -> list[str]:
    return [pmid for source in sources if (pmid := _normalise_pmid(source.get("pmid")))]


def _extract_source_dois(sources: list[dict]) -> list[str]:
    return [doi for source in sources if (doi := _normalise_doi(source.get("doi")))]


def _source_alignment(question: dict, sources: list[dict]) -> dict:
    expected_pmids = _expected_pmids(question)
    expected_dois = _expected_dois(question)
    source_pmids = _extract_source_pmids(sources)
    source_dois = _extract_source_dois(sources)
    if not expected_pmids and not expected_dois:
        return {
            "has_gold_labels": False,
            "gold_source_match": None,
            "matched_pmids": [],
            "matched_dois": [],
        }
    matched_pmids = sorted(set(source_pmids).intersection(expected_pmids))
    matched_dois = sorted(set(source_dois).intersection(expected_dois))
    return {
        "has_gold_labels": True,
        "gold_source_match": bool(matched_pmids or matched_dois),
        "matched_pmids": matched_pmids,
        "matched_dois": matched_dois,
    }


def _classify_refusal(response_text: str) -> bool:
    refusal_markers = [
        "outside the retrieved context",
        "outside the corpus",
        "not covered by the provided context",
        "cannot answer",
        "can't answer",
        "do not have enough evidence",
        "insufficient evidence",
        "not supported by the retrieved",
    ]
    text = response_text.lower()
    return any(marker in text for marker in refusal_markers)


def _cleanup_eval_session(client: httpx.Client, api_url: str, token: str, session_id: str) -> dict:
    try:
        response = client.delete(
            f"{api_url}/api/v1/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return {"status": "deleted", "session_id": session_id}
    except Exception as exc:
        return {"status": "failed", "session_id": session_id, "error": str(exc)}


def run_retrieval_eval(
    questions: list[dict],
    api_url: str,
    token: str,
    config: EvaluationConfig | None = None,
) -> dict:
    """Call /search for each question and compute recall@k and MRR."""
    active_config = config or load_evaluation_config()
    results = []
    recalls_5: list[float] = []
    recalls_10: list[float] = []
    recalls_20: list[float] = []
    mrrs: list[float] = []
    precisions_5: list[float] = []
    latency_values: list[int] = []
    skipped_missing_labels = 0
    error_count = 0

    with httpx.Client(timeout=active_config.retrieval_timeout_s) as client:
        backend_metadata = _fetch_backend_metadata(client, api_url, token)
        for q in questions:
            expected_pmids = _expected_pmids(q)
            expected_dois = _expected_dois(q)
            if not _has_gold_labels(q):
                skipped_missing_labels += 1
                result = {
                    "id": q["id"],
                    "question": q["question"],
                    "category": q.get("category"),
                    "difficulty": q.get("difficulty"),
                    "status": "skipped",
                    "skip_reason": "missing_gold_pmids_or_dois",
                }
                results.append(result)
                print(f"[{q['id']}] SKIP: missing expected_pmids or expected_dois")
                continue

            t0 = time.monotonic()
            try:
                resp = client.post(
                    f"{api_url}/api/v1/search",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": q["question"], "top_k": active_config.retrieval_top_k},
                )
                resp.raise_for_status()
                chunks = resp.json()
                latency_ms = int((time.monotonic() - t0) * 1000)

                retrieved_pmids = _retrieved_pmids(chunks)
                retrieved_dois = _retrieved_dois(chunks)
                r5 = compute_recall_at_k(
                    retrieved_pmids, expected_pmids, 5, retrieved_dois, expected_dois
                )
                r10 = compute_recall_at_k(
                    retrieved_pmids, expected_pmids, 10, retrieved_dois, expected_dois
                )
                r20 = compute_recall_at_k(
                    retrieved_pmids, expected_pmids, 20, retrieved_dois, expected_dois
                )
                mrr = compute_mrr(
                    retrieved_pmids,
                    expected_pmids,
                    active_config.mrr_at_k,
                    retrieved_dois,
                    expected_dois,
                )
                precision_5 = compute_precision_at_k(
                    retrieved_pmids, expected_pmids, 5, retrieved_dois, expected_dois
                )

                recalls_5.append(r5)
                recalls_10.append(r10)
                recalls_20.append(r20)
                mrrs.append(mrr)
                precisions_5.append(precision_5)
                latency_values.append(latency_ms)
                gold_retrieved_anywhere = bool(
                    set(retrieved_pmids).intersection(expected_pmids)
                    or set(retrieved_dois).intersection(expected_dois)
                )

                result = {
                    "id": q["id"],
                    "question": q["question"],
                    "category": q.get("category"),
                    "difficulty": q.get("difficulty"),
                    "status": "completed",
                    "coverage_status": (
                        "gold_retrieved" if gold_retrieved_anywhere else "not_retrieved_or_missing"
                    ),
                    "recall_at_5": r5,
                    "recall_at_10": r10,
                    "recall_at_20": r20,
                    "mrr_at_10": mrr,
                    "precision_at_5": precision_5,
                    "latency_ms": latency_ms,
                    "retrieved_pmids": retrieved_pmids[: active_config.retrieval_top_k],
                    "retrieved_dois": retrieved_dois[: active_config.retrieval_top_k],
                    "retrieved_sources": chunks[: active_config.retrieval_top_k],
                    "expected_pmids": expected_pmids,
                    "expected_dois": expected_dois,
                    "question_snapshot": _question_snapshot(q),
                }
                results.append(result)
                print(
                    f"[{q['id']}] R@5={r5:.2f} R@10={r10:.2f} "
                    f"R@20={r20:.2f} MRR@10={mrr:.2f} ({latency_ms}ms)"
                )

            except Exception as exc:
                error_count += 1
                results.append(
                    {
                        "id": q["id"],
                        "question": q["question"],
                        "category": q.get("category"),
                        "difficulty": q.get("difficulty"),
                        "status": "failed",
                        "error_message": str(exc),
                        "question_snapshot": _question_snapshot(q),
                    }
                )
                print(f"[{q['id']}] ERROR: {exc}")

    n = len([r for r in recalls_5 if not math.isnan(r)])
    summary = {
        "mode": "retrieval",
        "n_loaded": len(questions),
        "n_questions": n,
        "n_scorable": n,
        "n_skipped_missing_labels": skipped_missing_labels,
        "n_failed": error_count,
        "mean_recall_at_5": _mean(recalls_5),
        "mean_recall_at_10": _mean(recalls_10),
        "mean_recall_at_20": _mean(recalls_20),
        "mean_mrr_at_10": _mean(mrrs),
        "mean_precision_at_5": _mean(precisions_5),
        "mean_latency_ms": int(sum(latency_values) / len(latency_values)) if latency_values else 0,
    }
    if not n:
        summary["warning"] = "No retrieval questions were scored; add expected_pmids or expected_dois."

    metadata = _base_metadata(
        mode="retrieval",
        api_url=api_url,
        config=active_config,
        questions=questions,
        backend_metadata=backend_metadata,
    )
    return {"metadata": metadata, "summary": summary, "results": results}


def run_rag_eval(
    questions: list[dict],
    api_url: str,
    token: str,
    config: EvaluationConfig | None = None,
    cleanup_session: bool = False,
) -> dict:
    """
    Create a throwaway session and run each question through the full RAG pipeline.
    Records response text, sources, and latency.
    Human scoring of answer quality is done manually using the saved report.
    """
    active_config = config or load_evaluation_config()
    results = []
    latencies: list[int] = []
    refusal_checks = 0
    refusal_passes = 0
    gold_source_checks = 0
    gold_source_matches = 0
    error_count = 0
    cleanup_result: dict | None = None

    with httpx.Client(timeout=active_config.rag_timeout_s) as client:
        backend_metadata = _fetch_backend_metadata(client, api_url, token)
        # Create an evaluation session
        session_resp = client.post(
            f"{api_url}/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "mode": active_config.session_mode,
                "title": f"{active_config.report_prefix}_{datetime.now().isoformat()}",
            },
        )
        session_resp.raise_for_status()
        session_id = session_resp.json()["id"]
        print(f"Created eval session: {session_id}")

        try:
            for q in questions:
                t0 = time.monotonic()
                try:
                    print(f"[{q['id']}] Running: {q['question'][:60]}...")
                    with client.stream(
                        "POST",
                        f"{api_url}/api/v1/chat/sessions/{session_id}/messages",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                        json={"query": q["question"], "mode": active_config.session_mode},
                    ) as response:
                        response.raise_for_status()
                        answer_text, sources, latency_ms = _parse_sse_stream(response)

                    result_latency = latency_ms or int((time.monotonic() - t0) * 1000)
                    latencies.append(result_latency)
                    source_alignment = _source_alignment(q, sources)
                    if source_alignment["has_gold_labels"]:
                        gold_source_checks += 1
                        if source_alignment["gold_source_match"]:
                            gold_source_matches += 1

                    expected_behavior = q.get("expected_behavior")
                    refusal_observed = _classify_refusal(answer_text)
                    refusal_correct = None
                    if expected_behavior == "refuse":
                        refusal_checks += 1
                        refusal_correct = refusal_observed
                        if refusal_correct:
                            refusal_passes += 1

                    result = {
                        "id": q["id"],
                        "question": q["question"],
                        "category": q.get("category"),
                        "difficulty": q.get("difficulty"),
                        "status": "completed",
                        "expected_behavior": expected_behavior,
                        "response_text": answer_text,
                        "sources": sources,
                        "source_alignment": source_alignment,
                        "refusal_observed": refusal_observed,
                        "refusal_correct": refusal_correct,
                        "latency_ms": result_latency,
                        "question_snapshot": _question_snapshot(q),
                    }
                    results.append(result)
                    print(
                        f"[{q['id']}] sources={len(sources)} latency={result_latency}ms "
                        f"response_chars={len(answer_text)}"
                    )

                except Exception as exc:
                    error_count += 1
                    results.append(
                        {
                            "id": q["id"],
                            "question": q["question"],
                            "category": q.get("category"),
                            "difficulty": q.get("difficulty"),
                            "status": "failed",
                            "error_message": str(exc),
                            "question_snapshot": _question_snapshot(q),
                        }
                    )
                    print(f"[{q['id']}] ERROR: {exc}")
        finally:
            if cleanup_session:
                cleanup_result = _cleanup_eval_session(client, api_url, token, session_id)
                print(f"Cleanup session: {cleanup_result['status']} ({session_id})")

    summary = {
        "mode": "rag",
        "n_loaded": len(questions),
        "n_questions": len([r for r in results if r.get("status") == "completed"]),
        "n_failed": error_count,
        "mean_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "gold_source_match_rate": (
            gold_source_matches / gold_source_checks if gold_source_checks else None
        ),
        "out_of_scope_refusal_rate": refusal_passes / refusal_checks if refusal_checks else None,
        "session_id": session_id,
        "cleanup": cleanup_result,
    }
    metadata = _base_metadata(
        mode="rag",
        api_url=api_url,
        config=active_config,
        questions=questions,
        backend_metadata=backend_metadata,
    )
    return {"metadata": metadata, "summary": summary, "results": results}


def _flatten_for_csv(report: dict) -> list[dict]:
    rows = []
    for result in report.get("results", []):
        snapshot = result.get("question_snapshot", {})
        sources = result.get("sources") or result.get("retrieved_sources") or []
        rows.append(
            {
                "id": result.get("id"),
                "status": result.get("status"),
                "category": result.get("category"),
                "difficulty": result.get("difficulty"),
                "expected_behavior": result.get("expected_behavior")
                or snapshot.get("expected_behavior"),
                "question": result.get("question"),
                "gold_answer_outline": snapshot.get("gold_answer_outline"),
                "expected_pmids": ";".join(snapshot.get("expected_pmids") or result.get("expected_pmids") or []),
                "expected_dois": ";".join(snapshot.get("expected_dois") or result.get("expected_dois") or []),
                "response_text": result.get("response_text"),
                "source_pmids": ";".join(_extract_source_pmids(sources)),
                "source_dois": ";".join(_extract_source_dois(sources)),
                "retrieved_pmids": ";".join(result.get("retrieved_pmids") or []),
                "retrieved_dois": ";".join(result.get("retrieved_dois") or []),
                "recall_at_5": result.get("recall_at_5"),
                "recall_at_10": result.get("recall_at_10"),
                "recall_at_20": result.get("recall_at_20"),
                "mrr_at_10": result.get("mrr_at_10"),
                "latency_ms": result.get("latency_ms"),
                "reviewer_correctness_score": "",
                "reviewer_completeness_score": "",
                "reviewer_citation_support_score": "",
                "reviewer_grounding_score": "",
                "reviewer_usefulness_score": "",
                "reviewer_notes": "",
            }
        )
    return rows


def _markdown_report(report: dict) -> str:
    summary = report.get("summary", {})
    lines = [
        f"# Evaluation Report: {summary.get('mode', report.get('metadata', {}).get('mode'))}",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- **{key}**: {value}")
    lines.extend(["", "## Results", ""])
    for result in report.get("results", []):
        lines.append(f"### {result.get('id')} — {result.get('status')}")
        lines.append("")
        lines.append(result.get("question", ""))
        lines.append("")
        if result.get("response_text"):
            lines.append("**Response**")
            lines.append("")
            lines.append(result["response_text"])
            lines.append("")
        metrics = [
            key
            for key in ["recall_at_5", "recall_at_10", "recall_at_20", "mrr_at_10", "latency_ms"]
            if key in result
        ]
        if metrics:
            lines.append("**Metrics**")
            lines.append("")
            for key in metrics:
                lines.append(f"- {key}: {result.get(key)}")
            lines.append("")
    return "\n".join(lines)


def save_report(report: dict, output_format: str, config: EvaluationConfig, mode: str) -> Path:
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(f"Unsupported output format: {output_format}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "md" if output_format == "markdown" else output_format
    config.reports_dir.mkdir(exist_ok=True)
    report_path = config.reports_dir / f"{config.report_prefix}_{mode}_{timestamp}.{suffix}"

    if output_format == "json":
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    elif output_format == "jsonl":
        with report_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "metadata", "data": report.get("metadata", {})}) + "\n")
            f.write(json.dumps({"type": "summary", "data": report.get("summary", {})}) + "\n")
            for result in report.get("results", []):
                f.write(json.dumps({"type": "result", "data": result}) + "\n")
    elif output_format == "markdown":
        report_path.write_text(_markdown_report(report), encoding="utf-8")
    elif output_format == "csv":
        rows = _flatten_for_csv(report)
        with report_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
            writer.writeheader()
            writer.writerows(rows)

    return report_path


def main():
    config = load_evaluation_config()
    parser = argparse.ArgumentParser(description="RLALab AI Evaluation Runner")
    parser.add_argument("--mode", choices=["retrieval", "rag"], default=config.default_mode)
    parser.add_argument("--api-url", default=config.api_url)
    parser.add_argument("--token", default=config.token, help="JWT bearer token")
    parser.add_argument("--question-id", default=config.question_id, help="Run a single question by ID")
    parser.add_argument("--category", help="Filter questions by category")
    parser.add_argument("--difficulty", help="Filter questions by difficulty")
    parser.add_argument("--limit", type=int, help="Limit the number of loaded questions")
    parser.add_argument(
        "--output-format",
        choices=sorted(SUPPORTED_OUTPUT_FORMATS),
        default=config.output_format,
        help="Report format to write",
    )
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        default=config.fail_on_empty,
        help="Exit with an error if no retrieval questions are scorable",
    )
    parser.add_argument(
        "--cleanup-session",
        action="store_true",
        help="Delete the throwaway RAG chat session after the run",
    )
    args = parser.parse_args()

    if not args.token:
        parser.error("A JWT bearer token is required via --token or EVALUATION_TOKEN")

    questions = load_questions(
        question_id=args.question_id,
        category=args.category,
        difficulty=args.difficulty,
        limit=args.limit,
        config=config,
    )
    print(f"Loaded {len(questions)} questions. Mode: {args.mode}")

    if args.mode == "retrieval":
        report = run_retrieval_eval(questions, args.api_url, args.token, config)
    else:
        report = run_rag_eval(
            questions,
            args.api_url,
            args.token,
            config,
            cleanup_session=args.cleanup_session,
        )

    report_path = save_report(report, args.output_format, config, args.mode)
    print(f"\nReport saved: {report_path}")

    if "summary" in report:
        print("\n── Summary ──")
        for k, v in report["summary"].items():
            print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    if (
        args.mode == "retrieval"
        and args.fail_on_empty
        and report.get("summary", {}).get("n_scorable", 0) == 0
    ):
        raise SystemExit("No scorable retrieval questions; failing because --fail-on-empty is set.")


if __name__ == "__main__":
    main()
