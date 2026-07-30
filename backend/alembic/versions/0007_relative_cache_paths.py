"""Store ingestion cache paths repo-relative instead of absolute.

An absolute path in a shared column means "wherever the writing process's
filesystem was". A containerised worker (repo root ``/app``) and a host backend
(repo root the checkout) therefore disagree about the same cache, and the reader
rejects the writer's value with "Cache path must live under data/corpora".

This rewrites every stored path to the portable ``data/corpora/<name>`` form.
Readers resolve it against their own cache root, so both topologies agree.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# Everything up to and including the `data/corpora` segment pair is the part
# that varies per topology, so it is exactly the part that must go. Anchored on
# a leading slash so an already-relative value is left untouched, and lazy so it
# splits on the first `data/corpora` — the same one `_cache_root_tail` finds.
_TO_RELATIVE = (
    "regexp_replace(cache_path, '^/.*?/data/corpora(/|$)', 'data/corpora\\1')"
)
_ABSOLUTE = "cache_path LIKE '/%/data/corpora' OR cache_path LIKE '/%/data/corpora/%'"

_TABLES = ("ingestion_jobs", "datasheet_runs")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"UPDATE {table} SET cache_path = {_TO_RELATIVE} WHERE {_ABSOLUTE}")


def downgrade() -> None:
    """No-op.

    The absolute prefixes are not recoverable, and they are not needed: the
    readers accept the relative form. Downgrading the schema does not require
    reintroducing the ambiguity this revision removed.
    """
