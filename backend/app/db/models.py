"""
app/db/models.py
----------------
SQLAlchemy ORM models.

Corresponds 1:1 with the schema defined in CLAUDE.md §5.
The pgvector column type requires the pgvector package and the
`CREATE EXTENSION vector` migration to run first.

Implementer note:
    - Run `alembic upgrade head` to create tables.
    - Create the IVFFlat index AFTER initial data load (not in migrations).
    - If adding a second embedding model with different dimensions,
      add a new vector column or a separate table.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, SmallInteger,
    String, Text, ARRAY,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String, nullable=False, default="researcher")  # 'researcher' | 'admin'
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    feedback = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")


# ── Ingestion Manifests ───────────────────────────────────────────────────────

class IngestionManifest(Base):
    __tablename__ = "ingestion_manifests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    source = Column(String, nullable=False)          # 'pubmed_abstract' | 'pmc_fulltext' | 'pdf'
    query = Column(Text)
    date_from = Column(Date)
    date_to = Column(Date)
    embedding_model = Column(String, nullable=False)
    chunk_size = Column(Integer)
    chunk_overlap = Column(Integer)
    document_count = Column(Integer)
    chunk_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    metadata_ = Column("metadata", JSONB)

    documents = relationship("Document", back_populates="manifest")
    chunks = relationship("DocumentChunk", back_populates="manifest")


# ── Documents ─────────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manifest_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_manifests.id", ondelete="SET NULL"))
    document_id = Column(String, nullable=False, unique=True, index=True)
    source = Column(String, nullable=False)          # 'pubmed' | 'pmc' | 'pdf'
    title = Column(Text)
    abstract = Column(Text)
    full_text = Column(Text)
    authors = Column(JSONB)
    journal = Column(String)
    publication_date = Column(Date)
    year = Column(Integer, index=True)
    doi = Column(String, index=True)
    pmid = Column(String, index=True)
    pmc_id = Column(String)
    mesh_terms = Column(ARRAY(String))
    keywords = Column(ARRAY(String))
    url = Column(String)
    license = Column(String)
    ingested_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    metadata_ = Column("metadata", JSONB)

    manifest = relationship("IngestionManifest", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


# ── Document Chunks ───────────────────────────────────────────────────────────

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    manifest_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_manifests.id", ondelete="SET NULL"))
    chunk_index = Column(Integer, nullable=False)
    chunk_type = Column(String, nullable=False, default="abstract")
    content = Column(Text, nullable=False)
    token_count = Column(Integer)
    embedding_model = Column(String, nullable=False)
    # 768 dimensions for PubMedBERT. See CLAUDE.md §17 before changing.
    embedding = Column(Vector(768))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    document = relationship("Document", back_populates="chunks")
    manifest = relationship("IngestionManifest", back_populates="chunks")


# ── Chat Sessions ─────────────────────────────────────────────────────────────

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String)
    mode = Column(String, nullable=False, default="researcher")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="ChatMessage.created_at")


# ── Chat Messages ─────────────────────────────────────────────────────────────

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)           # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    retrieved_chunks = Column(ARRAY(UUID(as_uuid=True)))
    sources = Column(JSONB)
    llm_model = Column(String)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    session = relationship("ChatSession", back_populates="messages")
    feedback = relationship("Feedback", back_populates="message", uselist=False)


# ── Feedback ──────────────────────────────────────────────────────────────────

class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(SmallInteger)
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    message = relationship("ChatMessage", back_populates="feedback")
    user = relationship("User", back_populates="feedback")
