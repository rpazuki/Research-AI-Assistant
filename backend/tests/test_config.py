from __future__ import annotations

from app.core.config import Settings


def test_backend_settings_use_defaults_without_environment(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RETRIEVAL_FINAL_TOP_K", raising=False)

    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url == "postgresql+asyncpg://postgres:postgres@db:5432/rlalab_ai"
    assert settings.retrieval_final_top_k == 5


def test_backend_settings_are_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/custom")
    monkeypatch.setenv("RETRIEVAL_FINAL_TOP_K", "9")
    monkeypatch.setenv("CORS_ORIGINS", '["https://assistant.example"]')

    settings = Settings()

    assert settings.app_env == "production"
    assert settings.database_url == "postgresql+asyncpg://postgres:postgres@db:5432/custom"
    assert settings.retrieval_final_top_k == 9
    assert settings.cors_origins == ["https://assistant.example"]
