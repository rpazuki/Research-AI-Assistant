"""Initial schema with pgvector

Revision ID: 0001
Revises:
Create Date: 2026-05-04

IMPORTANT NOTES FOR IMPLEMENTER:
1. Run `CREATE EXTENSION IF NOT EXISTS vector;` on the database BEFORE this migration.
2. The IVFFlat index on document_chunks.embedding must be created AFTER initial data load.
   It is NOT created in this migration. See the comment at the bottom.
3. If you change the embedding model and dimension (currently 768 for PubMedBERT),
   you must update the vector(768) column manually — alembic cannot auto-detect this.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
from pgvector.sqlalchemy import Vector


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # users
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('full_name', sa.String()),
        sa.Column('role', sa.String(), nullable=False, server_default='researcher'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_unique_constraint('uq_users_email', 'users', ['email'])
    op.create_index('ix_users_email', 'users', ['email'])

    # ingestion_manifests
    op.create_table(
        'ingestion_manifests',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('query', sa.Text()),
        sa.Column('date_from', sa.Date()),
        sa.Column('date_to', sa.Date()),
        sa.Column('embedding_model', sa.String(), nullable=False),
        sa.Column('chunk_size', sa.Integer()),
        sa.Column('chunk_overlap', sa.Integer()),
        sa.Column('document_count', sa.Integer()),
        sa.Column('chunk_count', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('metadata', JSONB),
    )

    # documents
    op.create_table(
        'documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('manifest_id', UUID(as_uuid=True), sa.ForeignKey('ingestion_manifests.id', ondelete='SET NULL')),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('title', sa.Text()),
        sa.Column('abstract', sa.Text()),
        sa.Column('full_text', sa.Text()),
        sa.Column('authors', JSONB),
        sa.Column('journal', sa.String()),
        sa.Column('publication_date', sa.Date()),
        sa.Column('year', sa.Integer()),
        sa.Column('doi', sa.String()),
        sa.Column('pmid', sa.String()),
        sa.Column('pmc_id', sa.String()),
        sa.Column('mesh_terms', ARRAY(sa.String())),
        sa.Column('keywords', ARRAY(sa.String())),
        sa.Column('url', sa.String()),
        sa.Column('license', sa.String()),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('metadata', JSONB),
    )
    op.create_unique_constraint('uq_documents_document_id', 'documents', ['document_id'])
    op.create_index('ix_documents_document_id', 'documents', ['document_id'])
    op.create_index('ix_documents_pmid', 'documents', ['pmid'])
    op.create_index('ix_documents_doi', 'documents', ['doi'])
    op.create_index('ix_documents_year', 'documents', ['year'])

    # document_chunks
    op.create_table(
        'document_chunks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('manifest_id', UUID(as_uuid=True), sa.ForeignKey('ingestion_manifests.id', ondelete='SET NULL')),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_type', sa.String(), nullable=False, server_default='abstract'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer()),
        sa.Column('embedding_model', sa.String(), nullable=False),
        sa.Column('embedding', Vector(768)),  # PubMedBERT = 768 dims
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )
    # Full-text search index (can be created immediately)
    op.execute(
        "CREATE INDEX ix_chunks_content_fts ON document_chunks "
        "USING gin(to_tsvector('english', content))"
    )
    # NOTE: IVFFlat vector index must be created AFTER loading data.
    # Run this manually after first ingestion:
    #   CREATE INDEX ix_chunks_embedding ON document_chunks
    #   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    # chat_sessions
    op.create_table(
        'chat_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String()),
        sa.Column('mode', sa.String(), nullable=False, server_default='researcher'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

    # chat_messages
    op.create_table(
        'chat_messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('retrieved_chunks', ARRAY(UUID(as_uuid=True))),
        sa.Column('sources', JSONB),
        sa.Column('llm_model', sa.String()),
        sa.Column('prompt_tokens', sa.Integer()),
        sa.Column('completion_tokens', sa.Integer()),
        sa.Column('latency_ms', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_index('ix_messages_session', 'chat_messages', ['session_id'])

    # feedback
    op.create_table(
        'feedback',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('message_id', UUID(as_uuid=True), sa.ForeignKey('chat_messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rating', sa.SmallInteger()),
        sa.Column('comment', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )


def downgrade() -> None:
    op.drop_table('feedback')
    op.drop_table('chat_messages')
    op.drop_table('chat_sessions')
    op.drop_table('document_chunks')
    op.drop_table('documents')
    op.drop_table('ingestion_manifests')
    op.drop_table('users')
    op.execute("DROP EXTENSION IF EXISTS vector")
