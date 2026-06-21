"""Add evaluation workflow tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluation_question_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("metadata", JSONB),
    )
    op.create_index("ix_evaluation_question_sets_name", "evaluation_question_sets", ["name"], unique=True)
    op.create_index("ix_evaluation_question_sets_status", "evaluation_question_sets", ["status"])

    op.create_table(
        "evaluation_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "question_set_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evaluation_question_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("difficulty", sa.String(), nullable=False),
        sa.Column("domain_fit", sa.String(), nullable=False, server_default="core"),
        sa.Column("expected_behavior", sa.String(), nullable=False, server_default="answer"),
        sa.Column("expected_keywords", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("expected_pmids", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("expected_dois", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("gold_answer_outline", sa.Text()),
        sa.Column("supporting_evidence", JSONB),
        sa.Column("requires_full_text", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("review_status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("expert_owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "question_set_id",
            "external_id",
            name="uq_evaluation_questions_set_external_id",
        ),
    )
    op.create_index("ix_evaluation_questions_question_set_id", "evaluation_questions", ["question_set_id"])
    op.create_index("ix_evaluation_questions_category", "evaluation_questions", ["category"])
    op.create_index("ix_evaluation_questions_difficulty", "evaluation_questions", ["difficulty"])
    op.create_index("ix_evaluation_questions_domain_fit", "evaluation_questions", ["domain_fit"])
    op.create_index("ix_evaluation_questions_expected_behavior", "evaluation_questions", ["expected_behavior"])
    op.create_index("ix_evaluation_questions_requires_full_text", "evaluation_questions", ["requires_full_text"])
    op.create_index("ix_evaluation_questions_review_status", "evaluation_questions", ["review_status"])

    op.create_table(
        "evaluation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column(
            "question_set_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evaluation_question_sets.id", ondelete="SET NULL"),
        ),
        sa.Column("started_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("corpus_manifest_id", UUID(as_uuid=True), sa.ForeignKey("ingestion_manifests.id", ondelete="SET NULL")),
        sa.Column("document_count", sa.Integer()),
        sa.Column("chunk_count", sa.Integer()),
        sa.Column("embedding_model", sa.String()),
        sa.Column("chunk_size", sa.Integer()),
        sa.Column("chunk_overlap", sa.Integer()),
        sa.Column("retrieval_config", JSONB),
        sa.Column("reranker_config", JSONB),
        sa.Column("llm_provider", sa.String()),
        sa.Column("llm_model", sa.String()),
        sa.Column("prompt_version", sa.String()),
        sa.Column("git_commit", sa.String()),
        sa.Column("runner_version", sa.String()),
        sa.Column("summary_metrics", JSONB),
        sa.Column("error_message", sa.Text()),
        sa.Column("artifact_paths", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_evaluation_runs_mode", "evaluation_runs", ["mode"])
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])
    op.create_index("ix_evaluation_runs_question_set_id", "evaluation_runs", ["question_set_id"])

    op.create_table(
        "evaluation_run_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_id", UUID(as_uuid=True), sa.ForeignKey("evaluation_questions.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("question_snapshot", JSONB, nullable=False),
        sa.Column("retrieved_sources", JSONB),
        sa.Column("retrieved_pmids", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("retrieved_dois", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("retrieved_chunk_ids", ARRAY(UUID(as_uuid=True))),
        sa.Column("expected_pmids_present", sa.Boolean()),
        sa.Column("expected_dois_present", sa.Boolean()),
        sa.Column("coverage_status", sa.String(), nullable=False, server_default="not_applicable"),
        sa.Column("recall_at_5", sa.Float()),
        sa.Column("recall_at_10", sa.Float()),
        sa.Column("recall_at_20", sa.Float()),
        sa.Column("mrr_at_10", sa.Float()),
        sa.Column("precision_at_k", sa.Float()),
        sa.Column("response_text", sa.Text()),
        sa.Column("response_sources", JSONB),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("time_to_first_token_ms", sa.Integer()),
        sa.Column("failure_category", sa.String()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_evaluation_run_results_run_id", "evaluation_run_results", ["run_id"])
    op.create_index("ix_evaluation_run_results_question_id", "evaluation_run_results", ["question_id"])
    op.create_index("ix_evaluation_run_results_status", "evaluation_run_results", ["status"])
    op.create_index("ix_evaluation_run_results_coverage_status", "evaluation_run_results", ["coverage_status"])
    op.create_index("ix_evaluation_run_results_failure_category", "evaluation_run_results", ["failure_category"])

    op.create_table(
        "evaluation_review_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "run_result_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evaluation_run_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("assigned_to_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(), nullable=False, server_default="assigned"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
    )
    op.create_index("ix_evaluation_review_assignments_run_result_id", "evaluation_review_assignments", ["run_result_id"])
    op.create_index("ix_evaluation_review_assignments_assigned_to_user_id", "evaluation_review_assignments", ["assigned_to_user_id"])
    op.create_index("ix_evaluation_review_assignments_status", "evaluation_review_assignments", ["status"])
    op.create_index("ix_evaluation_review_assignments_due_at", "evaluation_review_assignments", ["due_at"])

    op.create_table(
        "evaluation_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "assignment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evaluation_review_assignments.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "run_result_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evaluation_run_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("correctness_score", sa.SmallInteger()),
        sa.Column("completeness_score", sa.SmallInteger()),
        sa.Column("citation_support_score", sa.SmallInteger()),
        sa.Column("grounding_score", sa.SmallInteger()),
        sa.Column("usefulness_score", sa.SmallInteger()),
        sa.Column("refusal_behavior", sa.String()),
        sa.Column("false_premise_handling", sa.String()),
        sa.Column("hallucination_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("citation_issue_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("corpus_gap_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("retrieval_issue_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("generation_issue_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("latency_issue_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("recommended_failure_category", sa.String()),
        sa.Column("reviewer_confidence", sa.SmallInteger()),
        sa.Column("free_text_feedback", sa.Text()),
        sa.Column("suggested_answer", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_evaluation_reviews_run_result_id", "evaluation_reviews", ["run_result_id"])
    op.create_index("ix_evaluation_reviews_reviewer_user_id", "evaluation_reviews", ["reviewer_user_id"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_reviews_reviewer_user_id", table_name="evaluation_reviews")
    op.drop_index("ix_evaluation_reviews_run_result_id", table_name="evaluation_reviews")
    op.drop_table("evaluation_reviews")

    op.drop_index("ix_evaluation_review_assignments_due_at", table_name="evaluation_review_assignments")
    op.drop_index("ix_evaluation_review_assignments_status", table_name="evaluation_review_assignments")
    op.drop_index("ix_evaluation_review_assignments_assigned_to_user_id", table_name="evaluation_review_assignments")
    op.drop_index("ix_evaluation_review_assignments_run_result_id", table_name="evaluation_review_assignments")
    op.drop_table("evaluation_review_assignments")

    op.drop_index("ix_evaluation_run_results_failure_category", table_name="evaluation_run_results")
    op.drop_index("ix_evaluation_run_results_coverage_status", table_name="evaluation_run_results")
    op.drop_index("ix_evaluation_run_results_status", table_name="evaluation_run_results")
    op.drop_index("ix_evaluation_run_results_question_id", table_name="evaluation_run_results")
    op.drop_index("ix_evaluation_run_results_run_id", table_name="evaluation_run_results")
    op.drop_table("evaluation_run_results")

    op.drop_index("ix_evaluation_runs_question_set_id", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_status", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_mode", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")

    op.drop_index("ix_evaluation_questions_review_status", table_name="evaluation_questions")
    op.drop_index("ix_evaluation_questions_requires_full_text", table_name="evaluation_questions")
    op.drop_index("ix_evaluation_questions_expected_behavior", table_name="evaluation_questions")
    op.drop_index("ix_evaluation_questions_domain_fit", table_name="evaluation_questions")
    op.drop_index("ix_evaluation_questions_difficulty", table_name="evaluation_questions")
    op.drop_index("ix_evaluation_questions_category", table_name="evaluation_questions")
    op.drop_index("ix_evaluation_questions_question_set_id", table_name="evaluation_questions")
    op.drop_table("evaluation_questions")

    op.drop_index("ix_evaluation_question_sets_status", table_name="evaluation_question_sets")
    op.drop_index("ix_evaluation_question_sets_name", table_name="evaluation_question_sets")
    op.drop_table("evaluation_question_sets")
