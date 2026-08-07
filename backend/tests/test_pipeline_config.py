from __future__ import annotations

import textwrap

from pipelines.config import load_pipeline_config


def test_pipeline_defaults_merge_with_corpus_toml_and_environment(monkeypatch, tmp_path) -> None:
    defaults_path = tmp_path / "pipeline.defaults.yaml"
    defaults_path.write_text(
        textwrap.dedent(
            """
            defaults:
              runtime:
                database_url: "postgresql+asyncpg://default/default"
                progress_interval_documents: 100
              pubmed:
                batch_size: 20
                sleep_between_batches_s: 0.15
              indexing:
                embedding_batch_size: 2
                embedding_batch_size_by_source:
                  pubmed_abstract: 32
            environments:
              server:
                runtime:
                  progress_interval_documents: 250
                pubmed:
                  sleep_between_batches_s: 0.5
            """
        ),
        encoding="utf-8",
    )
    corpus_path = tmp_path / "corpus.toml"
    corpus_path.write_text(
        textwrap.dedent(
            """
            [corpus]
            name = "test"
            source = "pubmed_abstract"

            [pubmed]
            query = "synthetic biology"
            batch_size = 7
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PIPELINE_CONFIG_FILE", str(defaults_path))
    monkeypatch.setenv("RLALAB_ENV", "server")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://env/env")
    monkeypatch.setenv("NCBI_EMAIL", "lab@example.com")

    config = load_pipeline_config(corpus_path)

    assert config["runtime"]["database_url"] == "postgresql+asyncpg://env/env"
    assert config["runtime"]["progress_interval_documents"] == 250
    assert config["pubmed"]["query"] == "synthetic biology"
    assert config["pubmed"]["batch_size"] == 7
    assert config["pubmed"]["sleep_between_batches_s"] == 0.5
    assert config["pubmed"]["email"] == "lab@example.com"
    assert config["indexing"]["embedding_batch_size_by_source"]["pubmed_abstract"] == 32


def test_discovery_contact_addresses_come_from_the_environment(monkeypatch, tmp_path) -> None:
    """Contact addresses are .env material, never committed config: a shipped
    TOML with someone's address in it is the kind of thing that gets copied."""
    defaults_path = tmp_path / "pipeline.defaults.yaml"
    defaults_path.write_text(
        "defaults:\n  discovery:\n    max_records_per_source: 10\nenvironments:\n  local: {}\n",
        encoding="utf-8",
    )
    corpus_path = tmp_path / "corpus.toml"
    corpus_path.write_text(
        '[corpus]\nname = "c"\nsource = "discovery_search"\n\n'
        '[discovery]\norganism_terms = ["Yarrowia"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PIPELINE_CONFIG_FILE", str(defaults_path))
    monkeypatch.delenv("RLALAB_ENV", raising=False)
    monkeypatch.setenv("NCBI_EMAIL", "lab@example.com")
    monkeypatch.setenv("NCBI_API_KEY", "key-123")
    monkeypatch.setenv("CROSSREF_MAILTO", "crossref@example.com")
    monkeypatch.setenv("OPENALEX_MAILTO", "openalex@example.com")

    config = load_pipeline_config(corpus_path)

    assert config["discovery"]["ncbi_email"] == "lab@example.com"
    assert config["discovery"]["ncbi_api_key"] == "key-123"
    assert config["discovery"]["crossref_mailto"] == "crossref@example.com"
    assert config["discovery"]["openalex_mailto"] == "openalex@example.com"
    assert config["discovery"]["organism_terms"] == ["Yarrowia"]
    assert config["discovery"]["max_records_per_source"] == 10


def test_shipped_configs_carry_no_contact_addresses() -> None:
    from pathlib import Path

    from pipelines.corpus_cache import load_toml

    config_dir = Path(__file__).resolve().parents[2] / "pipelines" / "configs"
    for path in config_dir.glob("*.toml"):
        text = path.read_text()
        assert "@" not in text or "mailto" not in text.lower(), path.name
        discovery = load_toml(path).get("discovery", {})
        assert "crossref_mailto" not in discovery
        assert "openalex_mailto" not in discovery
        assert "ncbi_api_key" not in discovery


def test_pipelines_and_backend_agree_on_the_local_database_default() -> None:
    """The `local` database address is the one fact that must be stated twice.

    `pipelines/` deliberately does not import `backend/app`, so the host-correct
    default appears in both `pipelines/configs/pipeline.defaults.yaml` and
    `Settings.database_url`. They must not drift: if they do, `alembic upgrade head`
    and an ingestion run would silently target different databases.
    """
    from app.core.config import Settings
    from pipelines.config import load_pipeline_defaults

    pipeline_default = load_pipeline_defaults("local")["runtime"]["database_url"]

    assert pipeline_default == Settings().database_url


def test_shipped_pipeline_defaults_restate_no_addresses_per_scenario() -> None:
    """compose/server receive DATABASE_URL from .env.compose / .env.server, so the
    committed YAML must not carry a second answer for them."""
    from pipelines.config import load_pipeline_defaults

    local = load_pipeline_defaults("local")["runtime"]["database_url"]
    for scenario in ("compose", "server"):
        assert load_pipeline_defaults(scenario)["runtime"]["database_url"] == local
