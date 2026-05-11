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
    - evaluation/reports/eval_{timestamp}.jsonl (full results)
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

BENCHMARK_FILE = Path(__file__).parent / "benchmark" / "questions.jsonl"
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def load_questions(question_id: str | None = None) -> list[dict]:
    questions = []
    with open(BENCHMARK_FILE) as f:
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


def run_retrieval_eval(questions: list[dict], api_url: str, token: str) -> dict:
    """Call /search for each question and compute recall@k and MRR."""
    results = []
    recalls_5, recalls_10, mrrs = [], [], []

    with httpx.Client(timeout=30) as client:
        for q in questions:
            if "expected_pmids" not in q or not q["expected_pmids"]:
                continue

            t0 = time.monotonic()
            try:
                resp = client.post(
                    f"{api_url}/api/v1/search",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": q["question"], "top_k": 20},
                )
                resp.raise_for_status()
                chunks = resp.json()
                latency_ms = int((time.monotonic() - t0) * 1000)

                retrieved_pmids = [c.get("pmid") for c in chunks if c.get("pmid")]
                r5 = compute_recall_at_k(retrieved_pmids, q["expected_pmids"], 5)
                r10 = compute_recall_at_k(retrieved_pmids, q["expected_pmids"], 10)
                mrr = compute_mrr(retrieved_pmids, q["expected_pmids"])

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


def run_rag_eval(questions: list[dict], api_url: str, token: str) -> dict:
    """
    Create a throwaway session and run each question through the full RAG pipeline.
    Records response text, sources, and latency.
    Human scoring of answer quality is done manually using the saved report.
    """
    results = []

    with httpx.Client(timeout=120) as client:
        # Create an evaluation session
        session_resp = client.post(
            f"{api_url}/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={"mode": "researcher", "title": f"eval_{datetime.now().isoformat()}"},
        )
        session_resp.raise_for_status()
        session_id = session_resp.json()["id"]
        print(f"Created eval session: {session_id}")

        for q in questions:
            t0 = time.monotonic()
            try:
                # Non-streaming call for eval simplicity
                # In production, use streaming — but for eval, a non-streaming endpoint is simpler.
                # TODO: Add a /chat/sessions/{id}/messages/sync endpoint for evaluation use.
                print(f"[{q['id']}] Running: {q['question'][:60]}…")
                # Placeholder: streaming eval requires consuming SSE
                # This section should be implemented by the agent using the streaming API
                result = {
                    "id": q["id"],
                    "question": q["question"],
                    "category": q["category"],
                    "note": "RAG eval requires streaming consumption — implement in agent",
                }
                results.append(result)

            except Exception as exc:
                print(f"[{q['id']}] ERROR: {exc}")

    return {"mode": "rag", "results": results}


def main():
    parser = argparse.ArgumentParser(description="RLALab AI Evaluation Runner")
    parser.add_argument("--mode", choices=["retrieval", "rag"], required=True)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--token", required=True, help="JWT bearer token")
    parser.add_argument("--question-id", help="Run a single question by ID")
    args = parser.parse_args()

    questions = load_questions(args.question_id)
    print(f"Loaded {len(questions)} questions. Mode: {args.mode}")

    if args.mode == "retrieval":
        report = run_retrieval_eval(questions, args.api_url, args.token)
    else:
        report = run_rag_eval(questions, args.api_url, args.token)

    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"eval_{args.mode}_{timestamp}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {report_path}")

    if "summary" in report:
        print("\n── Summary ──")
        for k, v in report["summary"].items():
            print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")


if __name__ == "__main__":
    main()
