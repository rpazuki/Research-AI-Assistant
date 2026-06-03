"""Add ingestion job and upload tracking

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_upload_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("directory_path", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("metadata", JSONB),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("requested_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("config_name", sa.String(), nullable=False),
        sa.Column("config_path", sa.Text(), nullable=False),
        sa.Column("config_snapshot", JSONB),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="full"),
        sa.Column("from_date", sa.Date()),
        sa.Column("year", sa.Integer()),
        sa.Column("cache_path", sa.Text()),
        sa.Column(
            "pdf_upload_batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ingestion_upload_batches.id", ondelete="SET NULL"),
        ),
        sa.Column("options", JSONB),
        sa.Column("manifest_id", UUID(as_uuid=True), sa.ForeignKey("ingestion_manifests.id", ondelete="SET NULL")),
        sa.Column("document_count", sa.Integer()),
        sa.Column("chunk_count", sa.Integer()),
        sa.Column("progress_message", sa.Text()),
        sa.Column("log_tail", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("ix_ingestion_jobs_created_at", "ingestion_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_created_at", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_table("ingestion_upload_batches")
