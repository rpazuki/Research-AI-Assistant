"""Datasheet extraction state: batch lifecycle, per-candidate outcome, result cache.

Three things S5 could not survive without, all of which only bite once
`DATASHEET_EXTRACTION_ENABLED` is on:

- **Batch columns on `datasheet_runs`.** The batch id lived in a local variable, so
  a worker restart mid-batch lost it: results sit unreachable on Anthropic's side
  for 29 days and the whole run's cost is thrown away. It is a column rather than
  a `config_snapshot` key because the worker's claim query filters on it.
- **`extraction_status` / `extraction_error` on `datasheet_candidates`.** A paper
  that fails extraction gets no `datasheet_rows` row by design — writing one with
  empty cells would put a fabricated line in the datasheet — so the candidate is
  the only place the reason can live. Without it a run reports `3 failed` and
  there is no way to learn which three.
- **`datasheet_extraction_cache`.** Keyed on the hash of the text actually sent,
  so a re-run (or a second run whose seed overlaps the first) re-extracts only
  what changed. A table rather than a file under the run's cache directory:
  a per-run file would only help re-running the same run, which is the case that
  matters least.

Hand-written, and checked against the ORM by an `ast` column diff rather than by
trusting `alembic autogenerate` (see mistakes.md).

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Batch lifecycle on the run ────────────────────────────────────────────
    op.add_column("datasheet_runs", sa.Column("extraction_batch_id", sa.String(), nullable=True))
    op.add_column(
        "datasheet_runs",
        sa.Column("extraction_batch_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Throttles re-claiming a parked run: without it the worker would re-claim the
    # same run on every loop and hammer the batch endpoint.
    op.add_column(
        "datasheet_runs",
        sa.Column("extraction_batch_polled_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Per-candidate extraction outcome ─────────────────────────────────────
    # NULL means "not attempted" and is distinct from every recorded outcome.
    op.add_column(
        "datasheet_candidates", sa.Column("extraction_status", sa.String(), nullable=True)
    )
    op.add_column("datasheet_candidates", sa.Column("extraction_error", sa.Text(), nullable=True))

    # ── Result cache ─────────────────────────────────────────────────────────
    op.create_table(
        "datasheet_extraction_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # sha256 of the exact prompt text that was sent, not of the document: if
        # section selection or budgeting changes, the prompt changes and the cache
        # must miss rather than serve a result today's code would not produce.
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("cells", postgresql.JSONB(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        # How many cells came from the escalation model. Recorded because the key
        # carries the bulk model only: changing DATASHEET_ESCALATION_MODEL does not
        # invalidate an entry, so what an entry was produced by must stay visible.
        sa.Column("escalated_cells", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "content_sha256",
            "template_version",
            "model",
            name="uq_datasheet_extraction_cache_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("datasheet_extraction_cache")
    op.drop_column("datasheet_candidates", "extraction_error")
    op.drop_column("datasheet_candidates", "extraction_status")
    op.drop_column("datasheet_runs", "extraction_batch_polled_at")
    op.drop_column("datasheet_runs", "extraction_batch_submitted_at")
    op.drop_column("datasheet_runs", "extraction_batch_id")
