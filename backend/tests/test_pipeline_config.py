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
