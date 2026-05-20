"""Add user invitations

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("invited_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_user_invitations_email", "user_invitations", ["email"])
    op.create_unique_constraint(
        "uq_user_invitations_token_hash",
        "user_invitations",
        ["token_hash"],
    )
    op.create_index("ix_user_invitations_token_hash", "user_invitations", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_user_invitations_token_hash", table_name="user_invitations")
    op.drop_constraint("uq_user_invitations_token_hash", "user_invitations", type_="unique")
    op.drop_index("ix_user_invitations_email", table_name="user_invitations")
    op.drop_table("user_invitations")
