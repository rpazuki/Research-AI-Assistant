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
              production:
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
    monkeypatch.setenv("PIPELINE_ENV", "production")
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
