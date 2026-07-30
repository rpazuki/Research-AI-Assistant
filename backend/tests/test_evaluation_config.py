from __future__ import annotations

import textwrap

import httpx

from evaluation.config import load_evaluation_config
from evaluation.run_eval import run_retrieval_eval


def test_evaluation_yaml_environment_and_env_overrides(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "evaluation.yaml"
    reports_dir = tmp_path / "reports"
    config_path.write_text(
        textwrap.dedent(
            f"""
            defaults:
              evaluation_env: "local"
              api_url: "http://localhost:8000"
              retrieval_top_k: 12
              reports_dir: "{reports_dir}"
            environments:
              server:
                evaluation_env: "server"
                api_url: "https://assistant.example"
                retrieval_top_k: 25
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATION_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("RLALAB_ENV", "server")
    monkeypatch.setenv("EVALUATION_API_URL", "https://override.example")

    config = load_evaluation_config()

    assert config.evaluation_env == "server"
    assert config.api_url == "https://override.example"
    assert config.retrieval_top_k == 25
    assert config.reports_dir == reports_dir


def test_retrieval_eval_uses_configured_top_k_and_timeout(monkeypatch, tmp_path) -> None:
    question = {
        "id": "q1",
        "question": "What is known about Yarrowia lipolytica lipid production?",
        "expected_pmids": ["123"],
    }
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            defaults:
              retrieval_timeout_s: 9
              retrieval_top_k: 3
              mrr_at_k: 3
            environments: {}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATION_CONFIG_FILE", str(config_path))
    config = load_evaluation_config()
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            calls.append({"timeout": self.timeout})
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return httpx.Response(200, json=[{"pmid": "123"}], request=httpx.Request("POST", url))

    monkeypatch.setattr("evaluation.run_eval.httpx.Client", FakeClient)

    report = run_retrieval_eval([question], "https://assistant.example", "token", config)

    assert calls[0]["timeout"] == 9
    assert calls[1]["url"] == "https://assistant.example/api/v1/search"
    assert calls[1]["json"]["top_k"] == 3
    assert report["summary"]["mean_recall_at_5"] == 1.0
