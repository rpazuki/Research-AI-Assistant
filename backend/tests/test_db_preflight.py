"""Tests for the database preflight check.

No database: what is under test is the translation from a driver failure into an
instruction a person can act on, and the decision about which failures are worth
waiting through.
"""

from __future__ import annotations

import pytest

from app.db import preflight

URL = "postgresql+asyncpg://postgres:s3cr3t-pw@db:5432/rlalab_ai"


class DriverError(Exception):
    """Stands in for an asyncpg error: what matters is that it carries a SQLSTATE."""

    def __init__(self, sqlstate: str, message: str = "boom") -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class WrappedError(Exception):
    """Stands in for SQLAlchemy, which hangs the driver error off `.orig`."""

    def __init__(self, orig: Exception) -> None:
        super().__init__("(psycopg) connection failed")
        self.orig = orig


# ── Redaction ─────────────────────────────────────────────────────────────────


def test_the_password_never_appears_in_the_printed_url() -> None:
    """The URL is worth printing to show which host was tried; the password is not."""
    assert "s3cr3t-pw" not in preflight.redact(URL)
    assert "db:5432/rlalab_ai" in preflight.redact(URL)


def test_a_url_without_a_password_is_left_alone() -> None:
    url = "postgresql+asyncpg://db:5432/rlalab_ai"
    assert preflight.redact(url) == url


def test_the_failure_message_does_not_leak_the_password() -> None:
    diagnosis = preflight.classify(DriverError(preflight.INVALID_PASSWORD), URL)
    assert "s3cr3t-pw" not in diagnosis.render(URL)


# ── Classification ────────────────────────────────────────────────────────────


def test_a_rejected_password_explains_that_editing_env_is_not_enough() -> None:
    """The whole point: POSTGRES_PASSWORD applies at first init only, so the fix
    is on the running server, not in a file."""
    diagnosis = preflight.classify(DriverError(preflight.INVALID_PASSWORD), URL)

    assert diagnosis.headline == "database password mismatch"
    assert "first" in diagnosis.detail and "volume" in diagnosis.detail
    assert "\\password postgres" in diagnosis.detail
    assert diagnosis.transient is False


def test_the_driver_error_is_found_through_sqlalchemys_wrapper() -> None:
    """SQLAlchemy wraps the driver error, so a naive isinstance check would miss it."""
    wrapped = WrappedError(DriverError(preflight.INVALID_PASSWORD))

    assert preflight.classify(wrapped, URL).headline == "database password mismatch"


def test_the_driver_error_is_found_through_a_raise_from_chain() -> None:
    try:
        try:
            raise DriverError(preflight.INVALID_PASSWORD)
        except DriverError as cause:
            raise RuntimeError("connect failed") from cause
    except RuntimeError as exc:
        assert preflight.classify(exc, URL).headline == "database password mismatch"


def test_a_missing_database_names_the_database() -> None:
    diagnosis = preflight.classify(DriverError(preflight.UNDEFINED_DATABASE), URL)
    assert 'no such database "rlalab_ai"' == diagnosis.headline
    assert "CREATE DATABASE" in diagnosis.detail


def test_a_missing_role_names_the_role() -> None:
    diagnosis = preflight.classify(DriverError(preflight.INVALID_AUTHORIZATION), URL)
    assert 'no such database role "postgres"' == diagnosis.headline


def test_an_unreachable_host_is_transient_and_names_the_address() -> None:
    """Worth waiting through: the db container may still be starting."""
    diagnosis = preflight.classify(ConnectionRefusedError(61, "Connection refused"), URL)

    assert diagnosis.headline == "the database is unreachable"
    assert "db:5432" in diagnosis.detail
    assert diagnosis.transient is True


def test_an_unrecognised_failure_still_reports_something_usable() -> None:
    diagnosis = preflight.classify(ValueError("malformed URL"), URL)
    assert diagnosis.headline == "ValueError"
    assert "malformed URL" in diagnosis.detail


# ── Retry behaviour ───────────────────────────────────────────────────────────


class FakeEngine:
    """Raises the queued errors in order, then connects."""

    def __init__(self, errors: list[Exception]) -> None:
        self.errors = list(errors)
        self.attempts = 0
        self.disposed = False

    def connect(self) -> "FakeEngine":
        return self

    async def __aenter__(self):
        self.attempts += 1
        if self.errors:
            raise self.errors.pop(0)
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    async def execute(self, *_args, **_kwargs) -> None:
        return None

    async def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def engine_factory(monkeypatch):
    def install(errors: list[Exception]) -> FakeEngine:
        engine = FakeEngine(errors)
        monkeypatch.setattr(preflight, "create_async_engine", lambda *a, **k: engine)
        return engine

    return install


async def test_a_slow_starting_database_is_waited_for(engine_factory) -> None:
    engine = engine_factory([ConnectionRefusedError(61, "Connection refused")])

    diagnosis = await preflight.check(URL, attempts=3, delay=0)

    assert diagnosis is None
    assert engine.attempts == 2


async def test_a_rejected_password_fails_immediately_rather_than_retrying(engine_factory) -> None:
    """Retrying a wrong password just delays the message that fixes it."""
    engine = engine_factory([DriverError(preflight.INVALID_PASSWORD)] * 5)

    diagnosis = await preflight.check(URL, attempts=3, delay=0)

    assert diagnosis is not None
    assert diagnosis.headline == "database password mismatch"
    assert engine.attempts == 1


async def test_waiting_eventually_gives_up_and_reports(engine_factory) -> None:
    engine = engine_factory([ConnectionRefusedError(61, "refused")] * 10)

    diagnosis = await preflight.check(URL, attempts=3, delay=0)

    assert diagnosis is not None
    assert diagnosis.headline == "the database is unreachable"
    assert engine.attempts == 3


async def test_the_engine_is_disposed_even_when_the_check_fails(engine_factory) -> None:
    """A leaked engine would hold a connection slot in the crash loop."""
    engine = engine_factory([DriverError(preflight.INVALID_PASSWORD)])

    await preflight.check(URL, attempts=1, delay=0)

    assert engine.disposed is True
