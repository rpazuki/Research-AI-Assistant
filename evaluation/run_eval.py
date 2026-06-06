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
import json
import time
from datetime import datetime

import httpx

from evaluation.config import EvaluationConfig, load_evaluation_config


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


def load_questions(
    question_id: str | None = None,
    config: EvaluationConfig | None = None,
) -> list[dict]:
    active_config = config or load_evaluation_config()
    questions = []
    with active_config.benchmark_file.open(encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            if question_id is None or q["id"] == question_id:
                questions.append(q)
    return questions


def compute_recall_at_k(retrieved_pmids: list[str], expected_pmids: list[str], k: int) -> float:
    """1.0 if any expected PMID appears in top-k retrieved, else 0.0."""
    if not expected_pmids:
        return float("nan")
    top_k = set(retrieved_pmids[:k])
    return 1.0 if any(p in top_k for p in expected_pmids) else 0.0


def compute_mrr(retrieved_pmids: list[str], expected_pmids: list[str], k: int = 10) -> float:
    if not expected_pmids:
        return float("nan")
    for rank, pmid in enumerate(retrieved_pmids[:k], 1):
        if pmid in expected_pmids:
            return 1.0 / rank
    return 0.0


def run_retrieval_eval(
    questions: list[dict],
    api_url: str,
    token: str,
    config: EvaluationConfig | None = None,
) -> dict:
    """Call /search for each question and compute recall@k and MRR."""
    active_config = config or load_evaluation_config()
    results = []
    recalls_5, recalls_10, mrrs = [], [], []

    with httpx.Client(timeout=active_config.retrieval_timeout_s) as client:
        for q in questions:
            if "expected_pmids" not in q or not q["expected_pmids"]:
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

                retrieved_pmids = [c.get("pmid") for c in chunks if c.get("pmid")]
                r5 = compute_recall_at_k(retrieved_pmids, q["expected_pmids"], 5)
                r10 = compute_recall_at_k(retrieved_pmids, q["expected_pmids"], 10)
                mrr = compute_mrr(retrieved_pmids, q["expected_pmids"], active_config.mrr_at_k)

                recalls_5.append(r5)
                recalls_10.append(r10)
                mrrs.append(mrr)

                result = {
                    "id": q["id"],
                    "question": q["question"],
                    "recall_at_5": r5,
                    "recall_at_10": r10,
                    "mrr": mrr,
                    "latency_ms": latency_ms,
                    "retrieved_pmids": retrieved_pmids[:10],
                    "expected_pmids": q["expected_pmids"],
                }
                results.append(result)
                print(f"[{q['id']}] R@5={r5:.2f} R@10={r10:.2f} MRR={mrr:.2f} ({latency_ms}ms)")

            except Exception as exc:
                print(f"[{q['id']}] ERROR: {exc}")

    n = len([r for r in recalls_5 if r == r])  # non-NaN count
    summary = {
        "mode": "retrieval",
        "n_questions": n,
        "mean_recall_at_5": sum(r for r in recalls_5 if r == r) / n if n else 0,
        "mean_recall_at_10": sum(r for r in recalls_10 if r == r) / n if n else 0,
        "mean_mrr": sum(r for r in mrrs if r == r) / n if n else 0,
    }
    return {"summary": summary, "results": results}


def run_rag_eval(
    questions: list[dict],
    api_url: str,
    token: str,
    config: EvaluationConfig | None = None,
) -> dict:
    """
    Create a throwaway session and run each question through the full RAG pipeline.
    Records response text, sources, and latency.
    Human scoring of answer quality is done manually using the saved report.
    """
    active_config = config or load_evaluation_config()
    results = []

    with httpx.Client(timeout=active_config.rag_timeout_s) as client:
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

        for q in questions:
            t0 = time.monotonic()
            try:
                print(f"[{q['id']}] Running: {q['question'][:60]}…")
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

                result = {
                    "id": q["id"],
                    "question": q["question"],
                    "category": q["category"],
                    "response_text": answer_text,
                    "sources": sources,
                    "latency_ms": latency_ms or int((time.monotonic() - t0) * 1000),
                }
                results.append(result)
                print(
                    f"[{q['id']}] sources={len(sources)} latency={result['latency_ms']}ms "
                    f"response_chars={len(answer_text)}"
                )

            except Exception as exc:
                print(f"[{q['id']}] ERROR: {exc}")

    return {"mode": "rag", "results": results}


def main():
    config = load_evaluation_config()
    parser = argparse.ArgumentParser(description="RLALab AI Evaluation Runner")
    parser.add_argument("--mode", choices=["retrieval", "rag"], default=config.default_mode)
    parser.add_argument("--api-url", default=config.api_url)
    parser.add_argument("--token", default=config.token, help="JWT bearer token")
    parser.add_argument("--question-id", default=config.question_id, help="Run a single question by ID")
    args = parser.parse_args()

    if not args.token:
        parser.error("A JWT bearer token is required via --token or EVALUATION_TOKEN")

    questions = load_questions(args.question_id, config)
    print(f"Loaded {len(questions)} questions. Mode: {args.mode}")

    if args.mode == "retrieval":
        report = run_retrieval_eval(questions, args.api_url, args.token, config)
    else:
        report = run_rag_eval(questions, args.api_url, args.token, config)

    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config.reports_dir.mkdir(exist_ok=True)
    report_path = config.reports_dir / f"{config.report_prefix}_{args.mode}_{timestamp}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {report_path}")

    if "summary" in report:
        print("\n── Summary ──")
        for k, v in report["summary"].items():
            print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")


if __name__ == "__main__":
    main()
