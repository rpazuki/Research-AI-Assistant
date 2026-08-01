"""
app/db/preflight.py
-------------------
Fail with a sentence instead of a traceback when the database will not have us.

Every container's command starts with this check, because the two failures that
actually happen in deployment — a password the database never accepted, and a
database that is not up yet — both surfaced as a forty-line asyncpg traceback
ending in `InvalidPasswordError`, which says what happened but not what to do.

The password case is worth naming explicitly. `POSTGRES_PASSWORD` is read by the
Postgres image *only* when it initialises an empty data directory. Once `pgdata`
exists, editing `.env` changes the password the backend presents and nothing at
all about the password the server expects, so the two drift apart silently and
the whole stack sits in a restart loop.

    python -m app.db.preflight        # exit 0 = the database accepted us
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

# The db service has a healthcheck and the workers a `depends_on`, so a refused
# connection here means a genuinely slow start rather than a race. Short, few.
CONNECT_ATTEMPTS = 10
RETRY_DELAY_S = 2.0
CONNECT_TIMEOUT_S = 5

# SQLSTATE rather than asyncpg exception classes: the codes are the wire
# protocol's own and survive both driver upgrades and SQLAlchemy's wrapping.
INVALID_PASSWORD = "28P01"
INVALID_AUTHORIZATION = "28000"
UNDEFINED_DATABASE = "3D000"
TOO_MANY_CONNECTIONS = "53300"


@dataclass(frozen=True)
class Diagnosis:
    """What went wrong, and the command that fixes it."""

    headline: str
    detail: str
    transient: bool = False

    def render(self, url: str) -> str:
        return f"\ndatabase preflight failed: {self.headline}\n\n{self.detail}\n\nURL: {redact(url)}\n"


def redact(url: str) -> str:
    """The URL is worth printing; the password in it never is."""
    parts = urlsplit(url)
    if not parts.password:
        return url
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
    return urlunsplit(parts._replace(netloc=netloc))


def _chain(exc: BaseException) -> list[BaseException]:
    """Every exception behind this one.

    SQLAlchemy wraps the driver error in `.orig`, and `raise ... from ...` hangs
    it off `__cause__`; which of those carries the SQLSTATE depends on where the
    failure happened, so walk all of them.
    """
    stack: list[BaseException | None] = [exc]
    seen: set[int] = set()
    found: list[BaseException] = []
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        found.append(current)
        stack.extend(
            [getattr(current, "orig", None), current.__cause__, current.__context__]
        )
    return found


def _sqlstate(exc: BaseException) -> str | None:
    for link in _chain(exc):
        code = getattr(link, "sqlstate", None)
        if code:
            return str(code)
    return None


def _is_unreachable(exc: BaseException) -> bool:
    return any(isinstance(link, (OSError, ConnectionError, TimeoutError)) for link in _chain(exc))


def classify(exc: BaseException, url: str) -> Diagnosis:
    """Turn a connection failure into an instruction."""
    parts = urlsplit(url)
    user = parts.username or "postgres"
    database = (parts.path or "/").lstrip("/") or "?"

    code = _sqlstate(exc)

    if code == INVALID_PASSWORD:
        return Diagnosis(
            headline="database password mismatch",
            detail=(
                f'The server rejected the password for user "{user}".\n\n'
                "POSTGRES_PASSWORD is applied only when the data volume is first\n"
                "created. Editing .env after that changes the password this process\n"
                "sends and not the one the database expects. Set it on the running\n"
                "server, which authenticates over the unix socket without a password:\n\n"
                "    docker compose exec db psql -U postgres\n"
                "    \\password postgres      # enter the value from .env\n\n"
                "See run_and_deploy.md §7."
            ),
        )

    if code == INVALID_AUTHORIZATION:
        return Diagnosis(
            headline=f'no such database role "{user}"',
            detail=(
                "POSTGRES_USER also applies only at first initialisation, so renaming\n"
                "it in .env leaves the original role in place. Either restore the old\n"
                "name or create the new role:\n\n"
                f"    docker compose exec db psql -U postgres -c 'CREATE ROLE \"{user}\" LOGIN'"
            ),
        )

    if code == UNDEFINED_DATABASE:
        return Diagnosis(
            headline=f'no such database "{database}"',
            detail=(
                "POSTGRES_DB is applied only at first initialisation. Either point\n"
                "DATABASE_URL at the database that exists, or create this one:\n\n"
                f"    docker compose exec db psql -U postgres -c 'CREATE DATABASE \"{database}\"'"
            ),
        )

    if code == TOO_MANY_CONNECTIONS:
        return Diagnosis(
            headline="the database is out of connection slots",
            detail=(
                "Every backend worker holds a pool. Reduce --workers or pool_size,\n"
                "or raise max_connections on the server."
            ),
            transient=True,
        )

    if _is_unreachable(exc):
        return Diagnosis(
            headline="the database is unreachable",
            detail=(
                f"Nothing answered at {parts.hostname}:{parts.port or 5432}.\n\n"
                "Inside Compose the host is the service name `db`; on the host it is\n"
                "localhost:5433. A service name reaching a host process means an\n"
                "address leaked into your shell — see run_and_deploy.md §7."
            ),
            transient=True,
        )

    return Diagnosis(headline=type(exc).__name__, detail=str(exc))


async def check(url: str, *, attempts: int = CONNECT_ATTEMPTS, delay: float = RETRY_DELAY_S) -> Diagnosis | None:
    """Connect once. Retry only what waiting can fix."""
    engine = create_async_engine(
        url,
        pool_pre_ping=False,
        connect_args={"timeout": CONNECT_TIMEOUT_S},
    )
    try:
        for attempt in range(1, attempts + 1):
            try:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                return None
            except Exception as exc:  # noqa: BLE001 - every failure is classified below
                diagnosis = classify(exc, url)
                if not diagnosis.transient or attempt == attempts:
                    return diagnosis
                print(
                    f"waiting for the database ({attempt}/{attempts}): {diagnosis.headline}",
                    file=sys.stderr,
                    flush=True,
                )
                await asyncio.sleep(delay)
        return None
    finally:
        await engine.dispose()


def main() -> int:
    url = settings.database_url
    diagnosis = asyncio.run(check(url))
    if diagnosis is None:
        print(f"database ready: {redact(url)}", flush=True)
        return 0
    print(diagnosis.render(url), file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
