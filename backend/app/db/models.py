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
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, SmallInteger,
    String, Text, ARRAY, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector


DEFAULT_USER_TOKEN_LIMIT = 1_000_000


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
    token_limit = Column(Integer, nullable=False, default=DEFAULT_USER_TOKEN_LIMIT)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    feedback = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")
    sent_invitations = relationship("UserInvitation", back_populates="invited_by")
    ingestion_jobs = relationship("IngestionJob", back_populates="requested_by")
    ingestion_upload_batches = relationship("IngestionUploadBatch", back_populates="created_by")
    evaluation_question_sets = relationship("EvaluationQuestionSet", back_populates="created_by")
    evaluation_questions = relationship(
        "EvaluationQuestion",
        foreign_keys="EvaluationQuestion.created_by_user_id",
        back_populates="created_by",
    )
    owned_evaluation_questions = relationship(
        "EvaluationQuestion",
        foreign_keys="EvaluationQuestion.expert_owner_user_id",
        back_populates="expert_owner",
    )
    evaluation_runs = relationship("EvaluationRun", back_populates="started_by")
    assigned_evaluation_reviews = relationship(
        "EvaluationReviewAssignment",
        foreign_keys="EvaluationReviewAssignment.assigned_to_user_id",
        back_populates="assigned_to",
    )


# ── User Invitations ──────────────────────────────────────────────────────────

class UserInvitation(Base):
    __tablename__ = "user_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    subject = Column(String, nullable=False)
    template = Column(Text, nullable=False)
    invited_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    sent_at = Column(DateTime(timezone=True))

    invited_by = relationship("User", back_populates="sent_invitations")


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


# ── Ingestion Operations ─────────────────────────────────────────────────────

class IngestionUploadBatch(Base):
    __tablename__ = "ingestion_upload_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    name = Column(String, nullable=False)
    directory_path = Column(Text, nullable=False)
    file_count = Column(Integer, nullable=False, default=0)
    total_bytes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    metadata_ = Column("metadata", JSONB)

    created_by = relationship("User", back_populates="ingestion_upload_batches")
    jobs = relationship("IngestionJob", back_populates="pdf_upload_batch")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(String, nullable=False, default="queued", index=True)
    config_name = Column(String, nullable=False)
    config_path = Column(Text, nullable=False)
    config_snapshot = Column(JSONB)
    source = Column(String, nullable=False)
    mode = Column(String, nullable=False, default="full")
    from_date = Column(Date)
    year = Column(Integer)
    cache_path = Column(Text)
    pdf_upload_batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_upload_batches.id", ondelete="SET NULL"),
    )
    options = Column(JSONB)
    manifest_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_manifests.id", ondelete="SET NULL"))
    document_count = Column(Integer)
    chunk_count = Column(Integer)
    progress_message = Column(Text)
    log_tail = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    requested_by = relationship("User", back_populates="ingestion_jobs")
    manifest = relationship("IngestionManifest")
    pdf_upload_batch = relationship("IngestionUploadBatch", back_populates="jobs")


# ── Evaluation Workflow ──────────────────────────────────────────────────────

class EvaluationQuestionSet(Base):
    __tablename__ = "evaluation_question_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text)
    status = Column(String, nullable=False, default="draft", index=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    metadata_ = Column("metadata", JSONB)

    created_by = relationship("User", back_populates="evaluation_question_sets")
    questions = relationship(
        "EvaluationQuestion",
        back_populates="question_set",
        cascade="all, delete-orphan",
    )
    runs = relationship("EvaluationRun", back_populates="question_set")


class EvaluationQuestion(Base):
    __tablename__ = "evaluation_questions"
    __table_args__ = (
        UniqueConstraint(
            "question_set_id",
            "external_id",
            name="uq_evaluation_questions_set_external_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_set_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_question_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id = Column(String, nullable=False)
    question = Column(Text, nullable=False)
    category = Column(String, nullable=False, index=True)
    difficulty = Column(String, nullable=False, index=True)
    domain_fit = Column(String, nullable=False, default="core", index=True)
    expected_behavior = Column(String, nullable=False, default="answer", index=True)
    expected_keywords = Column(ARRAY(String), nullable=False, default=list)
    expected_pmids = Column(ARRAY(String), nullable=False, default=list)
    expected_dois = Column(ARRAY(String), nullable=False, default=list)
    gold_answer_outline = Column(Text)
    supporting_evidence = Column(JSONB)
    requires_full_text = Column(Boolean, nullable=False, default=False, index=True)
    review_status = Column(String, nullable=False, default="draft", index=True)
    expert_owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    notes = Column(Text)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    archived_at = Column(DateTime(timezone=True))

    question_set = relationship("EvaluationQuestionSet", back_populates="questions")
    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id],
        back_populates="evaluation_questions",
    )
    expert_owner = relationship(
        "User",
        foreign_keys=[expert_owner_user_id],
        back_populates="owned_evaluation_questions",
    )
    run_results = relationship("EvaluationRunResult", back_populates="question")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    mode = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    question_set_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_question_sets.id", ondelete="SET NULL"),
        index=True,
    )
    started_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    corpus_manifest_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_manifests.id", ondelete="SET NULL"),
    )
    document_count = Column(Integer)
    chunk_count = Column(Integer)
    embedding_model = Column(String)
    chunk_size = Column(Integer)
    chunk_overlap = Column(Integer)
    retrieval_config = Column(JSONB)
    reranker_config = Column(JSONB)
    llm_provider = Column(String)
    llm_model = Column(String)
    prompt_version = Column(String)
    git_commit = Column(String)
    runner_version = Column(String)
    summary_metrics = Column(JSONB)
    error_message = Column(Text)
    artifact_paths = Column(JSONB)
    metadata_ = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    question_set = relationship("EvaluationQuestionSet", back_populates="runs")
    started_by = relationship("User", back_populates="evaluation_runs")
    corpus_manifest = relationship("IngestionManifest")
    results = relationship("EvaluationRunResult", back_populates="run", cascade="all, delete-orphan")


class EvaluationRunResult(Base):
    __tablename__ = "evaluation_run_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_questions.id", ondelete="SET NULL"),
        index=True,
    )
    status = Column(String, nullable=False, default="pending", index=True)
    question_snapshot = Column(JSONB, nullable=False)
    retrieved_sources = Column(JSONB)
    retrieved_pmids = Column(ARRAY(String), nullable=False, default=list)
    retrieved_dois = Column(ARRAY(String), nullable=False, default=list)
    retrieved_chunk_ids = Column(ARRAY(UUID(as_uuid=True)))
    expected_pmids_present = Column(Boolean)
    expected_dois_present = Column(Boolean)
    coverage_status = Column(String, nullable=False, default="not_applicable", index=True)
    recall_at_5 = Column(Float)
    recall_at_10 = Column(Float)
    recall_at_20 = Column(Float)
    mrr_at_10 = Column(Float)
    precision_at_k = Column(Float)
    response_text = Column(Text)
    response_sources = Column(JSONB)
    latency_ms = Column(Integer)
    time_to_first_token_ms = Column(Integer)
    failure_category = Column(String, index=True)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    run = relationship("EvaluationRun", back_populates="results")
    question = relationship("EvaluationQuestion", back_populates="run_results")
    assignments = relationship(
        "EvaluationReviewAssignment",
        back_populates="run_result",
        cascade="all, delete-orphan",
    )


class EvaluationReviewAssignment(Base):
    __tablename__ = "evaluation_review_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_result_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_run_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_to_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(String, nullable=False, default="assigned", index=True)
    due_at = Column(DateTime(timezone=True), index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    submitted_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    run_result = relationship("EvaluationRunResult", back_populates="assignments")
    assigned_to = relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
        back_populates="assigned_evaluation_reviews",
    )
    assigned_by = relationship("User", foreign_keys=[assigned_by_user_id])
    review = relationship("EvaluationReview", back_populates="assignment", uselist=False)


class EvaluationReview(Base):
    __tablename__ = "evaluation_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_review_assignments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    run_result_id = Column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_run_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    correctness_score = Column(SmallInteger)
    completeness_score = Column(SmallInteger)
    citation_support_score = Column(SmallInteger)
    grounding_score = Column(SmallInteger)
    usefulness_score = Column(SmallInteger)
    refusal_behavior = Column(String)
    false_premise_handling = Column(String)
    hallucination_flag = Column(Boolean, nullable=False, default=False)
    citation_issue_flag = Column(Boolean, nullable=False, default=False)
    corpus_gap_flag = Column(Boolean, nullable=False, default=False)
    retrieval_issue_flag = Column(Boolean, nullable=False, default=False)
    generation_issue_flag = Column(Boolean, nullable=False, default=False)
    latency_issue_flag = Column(Boolean, nullable=False, default=False)
    recommended_failure_category = Column(String)
    reviewer_confidence = Column(SmallInteger)
    free_text_feedback = Column(Text)
    suggested_answer = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    submitted_at = Column(DateTime(timezone=True))

    assignment = relationship("EvaluationReviewAssignment", back_populates="review")
    run_result = relationship("EvaluationRunResult")
    reviewer = relationship("User")


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
