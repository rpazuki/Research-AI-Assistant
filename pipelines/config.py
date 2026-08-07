"""
pipelines/config.py
-------------------
Shared pipeline configuration loader.

Pipeline defaults live in YAML. Corpus-specific TOML files are merged on top,
and environment variables remain the final override for secrets and deployment
specific values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from pipelines.corpus_cache import load_toml


PIPELINES_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = PIPELINES_ROOT / "configs" / "pipeline.defaults.yaml"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def pipeline_environment() -> str:
    """The one scenario selector: local | compose | server.

    Shared with the backend, frontend and evaluation components so a single value
    describes the whole system. Defaults to `local`, because Compose always sets it
    explicitly and a bare shell cannot.
    """
    return os.environ.get("RLALAB_ENV") or "local"


def pipeline_defaults_path() -> Path:
    return Path(os.environ.get("PIPELINE_CONFIG_FILE", DEFAULT_CONFIG_FILE)).expanduser()


def load_pipeline_defaults(environment: str | None = None) -> dict[str, Any]:
    config_path = pipeline_defaults_path()
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

    selected_environment = environment or pipeline_environment()
    selected = environments.get(selected_environment, {})
    if selected is None:
        selected = {}
    if not isinstance(selected, dict):
        raise ValueError(f"{config_path} environment '{selected_environment}' must be a mapping")

    return deep_merge(defaults, selected)


def apply_pipeline_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    runtime = dict(config.get("runtime", {}))
    if os.environ.get("DATABASE_URL"):
        runtime["database_url"] = os.environ["DATABASE_URL"]
    if runtime:
        config = {**config, "runtime": runtime}

    pubmed = dict(config.get("pubmed", {}))
    if os.environ.get("NCBI_EMAIL"):
        pubmed["email"] = os.environ["NCBI_EMAIL"]
    if os.environ.get("NCBI_API_KEY"):
        pubmed["api_key"] = os.environ["NCBI_API_KEY"]
    if pubmed:
        config = {**config, "pubmed": pubmed}

    # Contact addresses for the polite pools. Not secrets, but they belong with
    # the other .env values rather than in a committed config, and both fall
    # back to the NCBI address — the one guaranteed to be set.
    discovery = dict(config.get("discovery", {}))
    if os.environ.get("NCBI_EMAIL"):
        discovery["ncbi_email"] = os.environ["NCBI_EMAIL"]
    if os.environ.get("NCBI_API_KEY"):
        discovery["ncbi_api_key"] = os.environ["NCBI_API_KEY"]
    if os.environ.get("CROSSREF_MAILTO"):
        discovery["crossref_mailto"] = os.environ["CROSSREF_MAILTO"]
    if os.environ.get("OPENALEX_MAILTO"):
        discovery["openalex_mailto"] = os.environ["OPENALEX_MAILTO"]
    if discovery:
        config = {**config, "discovery": discovery}

    return config


def load_pipeline_config(
    corpus_config_path: str | Path,
    *,
    environment: str | None = None,
) -> dict[str, Any]:
    defaults = load_pipeline_defaults(environment)
    corpus_config = load_toml(corpus_config_path)
    return apply_pipeline_env_overrides(deep_merge(defaults, corpus_config))
