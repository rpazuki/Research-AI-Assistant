"""Record a candidate's preprint DOI alongside its version of record.

Discovery collapses a preprint into its published version so the paper is not
counted or acquired twice, but the preprint DOI stays useful: bioRxiv/medRxiv serve
JATS XML for it openly, which is often the only free full text for a paywalled
version of record. Without a column for it, that acquisition route is lost at the
moment the two records merge.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasheet_candidates", sa.Column("preprint_doi", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("datasheet_candidates", "preprint_doi")
