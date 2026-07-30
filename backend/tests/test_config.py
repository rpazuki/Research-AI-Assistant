from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

LOCAL_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/rlalab_ai"


def _clear_env(monkeypatch) -> None:
    for name in ("RLALAB_ENV", "DATABASE_URL", "ALEMBIC_DATABASE_URL", "RETRIEVAL_FINAL_TOP_K"):
        monkeypatch.delenv(name, raising=False)


def test_backend_settings_use_defaults_without_environment(monkeypatch) -> None:
    """Defaults serve the `local` scenario: Compose always injects values explicitly,
    a bare shell cannot. See run_and_deploy.md §2."""
    _clear_env(monkeypatch)

    settings = Settings()

    assert settings.rlalab_env == "local"
    assert settings.database_url == LOCAL_DATABASE_URL
    assert settings.retrieval_final_top_k == 5


def test_default_database_url_is_host_reachable_not_a_compose_hostname(monkeypatch) -> None:
    """Regression guard for the inversion this refactor removed: the default used to be
    `@db:5432`, which resolves only inside Compose — the one place that never needs a
    default."""
    _clear_env(monkeypatch)

    assert "@localhost:" in Settings().database_url
    assert "@db:" not in Settings().database_url


def test_backend_settings_are_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("RLALAB_ENV", "server")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/custom")
    monkeypatch.setenv("RETRIEVAL_FINAL_TOP_K", "9")
    monkeypatch.setenv("CORS_ORIGINS", '["https://assistant.example"]')

    settings = Settings()

    assert settings.rlalab_env == "server"
    assert settings.database_url == "postgresql+asyncpg://postgres:postgres@db:5432/custom"
    assert settings.retrieval_final_top_k == 9
    assert settings.cors_origins == ["https://assistant.example"]


@pytest.mark.parametrize("scenario", ["local", "compose", "server"])
def test_all_three_scenarios_are_accepted(monkeypatch, scenario: str) -> None:
    monkeypatch.setenv("RLALAB_ENV", scenario)
    assert Settings().rlalab_env == scenario


def test_unknown_scenario_is_rejected_at_startup(monkeypatch) -> None:
    """A typo must fail loudly rather than silently selecting a default and, with it,
    the wrong addresses and cookie flags."""
    monkeypatch.setenv("RLALAB_ENV", "prodction")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("scenario", "is_production", "is_containerised"),
    [
        ("local", False, False),
        ("compose", False, True),
        ("server", True, True),
    ],
)
def test_derived_flags(
    monkeypatch, scenario: str, is_production: bool, is_containerised: bool
) -> None:
    """Call sites use these instead of comparing the selector string, so adding a
    scenario later does not mean auditing every comparison in the codebase."""
    monkeypatch.setenv("RLALAB_ENV", scenario)

    settings = Settings()

    assert settings.is_production is is_production
    assert settings.is_containerised is is_containerised


def test_alembic_url_falls_back_to_database_url(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/main")

    assert Settings().alembic_database_url == (
        "postgresql+asyncpg://postgres:postgres@db:5432/main"
    )


def test_alembic_url_env_var_wins(monkeypatch) -> None:
    """One-off migrations against another database must not require editing config."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/main")
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@other/db")

    assert Settings().alembic_database_url == "postgresql+asyncpg://postgres:postgres@other/db"
