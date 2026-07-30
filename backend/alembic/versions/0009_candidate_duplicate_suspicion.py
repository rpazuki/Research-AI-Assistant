"""Record duplicate *suspicion* on a candidate without merging it.

Identity matching now uses strong identifiers only (DOI, PMID, PMCID). Title
matching used to merge distinct works — four separate peer-review reports into one
row, two book front-matter sections into another, papers with their figshare/Zenodo
deposits. Owner decision (2026-07-30): a preprint and its published version
ingested twice is strictly better than two distinct works merged once.

So the title signal is kept, demoted to a flag a human acts on.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasheet_candidates",
        sa.Column("possible_duplicate_of", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column("datasheet_candidates", sa.Column("duplicate_evidence", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("datasheet_candidates", "duplicate_evidence")
    op.drop_column("datasheet_candidates", "possible_duplicate_of")
