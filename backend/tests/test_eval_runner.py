import httpx

from evaluation.run_eval import (
    _parse_sse_stream,
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
    run_retrieval_eval,
)


def test_parse_sse_stream_collects_tokens_sources_and_done_latency() -> None:
    response = httpx.Response(
        200,
        content=(
            'data: {"type":"token","data":"Hello"}\n\n'
            'data: {"type":"token","data":" world"}\n\n'
            'data: {"type":"sources","data":[{"pmid":"123"}]}\n\n'
            'data: {"type":"done","latency_ms":42}\n\n'
        ).encode(),
    )

    answer, sources, latency_ms = _parse_sse_stream(response)

    assert answer == "Hello world"
    assert sources == [{"pmid": "123"}]
    assert latency_ms == 42


def test_identifier_metrics_support_pmids_and_dois() -> None:
    retrieved_pmids = ["111", "222", "333"]
    retrieved_dois = ["10.1/alpha", "10.1/beta", "10.1/gamma"]

    assert compute_recall_at_k(retrieved_pmids, ["999"], 2, retrieved_dois, ["10.1/beta"])
    assert compute_mrr(retrieved_pmids, ["999"], 10, retrieved_dois, ["10.1/beta"]) == 0.5
    assert compute_precision_at_k(retrieved_pmids, ["222"], 2, retrieved_dois, []) == 0.5


def test_retrieval_eval_reports_skipped_unlabelled_questions(monkeypatch) -> None:
    question = {
        "id": "q-unlabelled",
        "question": "What is known about lipid production?",
        "category": "factual",
        "difficulty": "easy",
    }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, headers):
            return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr("evaluation.run_eval.httpx.Client", FakeClient)

    report = run_retrieval_eval([question], "https://assistant.example", "token")

    assert report["summary"]["n_scorable"] == 0
    assert report["summary"]["n_skipped_missing_labels"] == 1
    assert report["results"][0]["status"] == "skipped"
    assert report["summary"]["warning"].startswith("No retrieval questions")
