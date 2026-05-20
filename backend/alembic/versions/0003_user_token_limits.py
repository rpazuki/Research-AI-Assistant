"""Add per-user token limits

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_limit",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1000000"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_limit")
