from __future__ import annotations

import textwrap

from app.core.config import Settings


def test_backend_yaml_defaults_are_loaded(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "backend.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            defaults:
              app_name: "Configured Assistant"
              app_env: "development"
              log_level: "INFO"
              cors_origins:
                - "http://localhost:3000"
              retrieval_final_top_k: 7
            environments:
              production:
                app_env: "production"
                log_level: "WARNING"
                cors_origins:
                  - "https://assistant.example"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKEND_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = Settings(_env_file=())

    assert settings.app_name == "Configured Assistant"
    assert settings.app_env == "development"
    assert settings.retrieval_final_top_k == 7


def test_backend_environment_section_and_env_vars_override_yaml(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "backend.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            defaults:
              app_env: "development"
              log_level: "INFO"
              retrieval_vector_top_k: 4
            environments:
              production:
                app_env: "production"
                log_level: "WARNING"
                retrieval_vector_top_k: 11
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKEND_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=())

    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.retrieval_vector_top_k == 11
