"""
evaluation/config.py
--------------------
YAML-backed configuration for the evaluation runner.

Precedence is: CLI arguments, environment variables, YAML environment section,
YAML defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml


EVALUATION_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = EVALUATION_ROOT / "configs" / "evaluation.yaml"


@dataclass(frozen=True)
class EvaluationConfig:
    evaluation_env: str = "development"
    api_url: str = "http://localhost:8000"
    default_mode: str = "retrieval"
    question_id: str | None = None
    token: str = ""
    benchmark_file: Path = EVALUATION_ROOT / "benchmark" / "questions.jsonl"
    reports_dir: Path = EVALUATION_ROOT / "reports"
    report_prefix: str = "eval"
    retrieval_timeout_s: int = 30
    rag_timeout_s: int = 120
    retrieval_top_k: int = 20
    mrr_at_k: int = 10
    session_mode: str = "researcher"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _config_environment() -> str:
    return (
        os.environ.get("EVALUATION_ENV")
        or os.environ.get("APP_ENV")
        or os.environ.get("ENVIRONMENT")
        or "development"
    )


def _config_file_path() -> Path:
    return Path(os.environ.get("EVALUATION_CONFIG_FILE", DEFAULT_CONFIG_FILE)).expanduser()


def _coerce_path(value: Any, base_dir: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else base_dir / path


def _read_yaml(environment: str) -> dict[str, Any]:
    config_path = _config_file_path()
    if not config_path.exists():
        return {}

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    defaults = raw.get("defaults", {})
    environments = raw.get("environments", {})
    if not isinstance(defaults, dict):
        raise ValueError(f"{config_path} must contain a mapping under 'defaults'")
    if not isinstance(environments, dict):
        raise ValueError(f"{config_path} must contain a mapping under 'environments'")

    selected = environments.get(environment, {})
    if selected is None:
        selected = {}
    if not isinstance(selected, dict):
        raise ValueError(f"{config_path} environment '{environment}' must be a mapping")
    return _deep_merge(defaults, selected)


def load_evaluation_config(environment: str | None = None) -> EvaluationConfig:
    selected_environment = environment or _config_environment()
    values = _read_yaml(selected_environment)

    base_dir = EVALUATION_ROOT
    config = EvaluationConfig(
        evaluation_env=str(values.get("evaluation_env", selected_environment)),
        api_url=str(values.get("api_url", "http://localhost:8000")),
        default_mode=str(values.get("default_mode", "retrieval")),
        question_id=values.get("question_id"),
        token=str(values.get("token", "")),
        benchmark_file=_coerce_path(
            values.get("benchmark_file", "benchmark/questions.jsonl"),
            base_dir,
        ),
        reports_dir=_coerce_path(values.get("reports_dir", "reports"), base_dir),
        report_prefix=str(values.get("report_prefix", "eval")),
        retrieval_timeout_s=int(values.get("retrieval_timeout_s", 30)),
        rag_timeout_s=int(values.get("rag_timeout_s", 120)),
        retrieval_top_k=int(values.get("retrieval_top_k", 20)),
        mrr_at_k=int(values.get("mrr_at_k", 10)),
        session_mode=str(values.get("session_mode", "researcher")),
    )

    env_overrides: dict[str, Any] = {}
    if os.environ.get("EVALUATION_API_URL"):
        env_overrides["api_url"] = os.environ["EVALUATION_API_URL"]
    if os.environ.get("EVALUATION_TOKEN"):
        env_overrides["token"] = os.environ["EVALUATION_TOKEN"]
    if os.environ.get("EVALUATION_QUESTION_ID"):
        env_overrides["question_id"] = os.environ["EVALUATION_QUESTION_ID"]
    if os.environ.get("EVALUATION_REPORTS_DIR"):
        env_overrides["reports_dir"] = Path(os.environ["EVALUATION_REPORTS_DIR"]).expanduser()
    if os.environ.get("EVALUATION_BENCHMARK_FILE"):
        env_overrides["benchmark_file"] = Path(os.environ["EVALUATION_BENCHMARK_FILE"]).expanduser()
    if os.environ.get("EVALUATION_RETRIEVAL_TOP_K"):
        env_overrides["retrieval_top_k"] = int(os.environ["EVALUATION_RETRIEVAL_TOP_K"])

    return replace(config, **env_overrides) if env_overrides else config
