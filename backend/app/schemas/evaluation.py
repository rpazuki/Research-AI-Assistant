"""Schemas for evaluation question banks, runs, and expert review workflow."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


QuestionSetStatus = Literal["draft", "active", "archived"]
QuestionCategory = Literal[
    "factual",
    "review",
    "out_of_scope",
    "citation_stress",
    "methodology",
]
QuestionDifficulty = Literal["easy", "medium", "hard"]
QuestionDomainFit = Literal["core", "adjacent", "out_of_scope", "remove"]
ExpectedBehavior = Literal[
    "answer",
    "refuse",
    "correct_false_premise",
    "partial_answer_with_gap",
]
QuestionReviewStatus = Literal[
    "draft",
    "expert_review_needed",
    "expert_reviewed",
    "label_complete",
    "retired",
]
EvaluationRunMode = Literal["retrieval", "rag", "combined"]
EvaluationRunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "cancel_requested",
]
ReviewAssignmentStatus = Literal["assigned", "in_progress", "submitted", "returned", "cancelled"]


class EvaluationQuestionSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: QuestionSetStatus = "draft"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question set name must not be empty")
        return cleaned


class EvaluationQuestionSetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: QuestionSetStatus | None = None
    metadata: dict[str, Any] | None = None


class EvaluationQuestionSetResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    question_count: int = 0
    label_complete_count: int = 0


class SupportingEvidenceItem(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    section: str | None = None
    evidence_note: str | None = None
    text: str | None = None


class EvaluationQuestionBase(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1)
    category: QuestionCategory
    difficulty: QuestionDifficulty
    domain_fit: QuestionDomainFit = "core"
    expected_behavior: ExpectedBehavior = "answer"
    expected_keywords: list[str] = Field(default_factory=list)
    expected_pmids: list[str] = Field(default_factory=list)
    expected_dois: list[str] = Field(default_factory=list)
    gold_answer_outline: str | None = None
    supporting_evidence: list[SupportingEvidenceItem] = Field(default_factory=list)
    requires_full_text: bool = False
    review_status: QuestionReviewStatus = "draft"
    expert_owner_user_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("external_id", "question")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value must not be empty")
        return cleaned

    @field_validator("expected_keywords", "expected_pmids", "expected_dois")
    @classmethod
    def clean_string_lists(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class EvaluationQuestionCreate(EvaluationQuestionBase):
    pass


class EvaluationQuestionUpdate(BaseModel):
    external_id: str | None = Field(default=None, min_length=1, max_length=100)
    question: str | None = Field(default=None, min_length=1)
    category: QuestionCategory | None = None
    difficulty: QuestionDifficulty | None = None
    domain_fit: QuestionDomainFit | None = None
    expected_behavior: ExpectedBehavior | None = None
    expected_keywords: list[str] | None = None
    expected_pmids: list[str] | None = None
    expected_dois: list[str] | None = None
    gold_answer_outline: str | None = None
    supporting_evidence: list[SupportingEvidenceItem] | None = None
    requires_full_text: bool | None = None
    review_status: QuestionReviewStatus | None = None
    expert_owner_user_id: uuid.UUID | None = None
    notes: str | None = None
    archived: bool | None = None


class EvaluationQuestionResponse(EvaluationQuestionBase):
    id: uuid.UUID
    question_set_id: uuid.UUID
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class EvaluationQuestionImportRequest(BaseModel):
    questions: list[EvaluationQuestionCreate] = Field(min_length=1)


class EvaluationQuestionImportResponse(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    questions: list[EvaluationQuestionResponse] = Field(default_factory=list)


class EvaluationRunSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    mode: str
    status: str
    question_set_id: uuid.UUID | None = None
    started_by_user_id: uuid.UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary_metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EvaluationRunCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mode: EvaluationRunMode = "retrieval"
    status: EvaluationRunStatus = "queued"
    question_set_id: uuid.UUID | None = None
    corpus_manifest_id: uuid.UUID | None = None
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    reranker_config: dict[str, Any] = Field(default_factory=dict)
    llm_provider: str | None = None
    llm_model: str | None = None
    prompt_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def clean_run_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Run name must not be empty")
        return cleaned


class EvaluationRunResponse(EvaluationRunSummaryResponse):
    corpus_manifest_id: uuid.UUID | None = None
    document_count: int | None = None
    chunk_count: int | None = None
    embedding_model: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    reranker_config: dict[str, Any] = Field(default_factory=dict)
    llm_provider: str | None = None
    llm_model: str | None = None
    prompt_version: str | None = None
    git_commit: str | None = None
    runner_version: str | None = None
    error_message: str | None = None
    artifact_paths: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationRunResultResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    question_id: uuid.UUID | None = None
    status: str
    question_snapshot: dict[str, Any]
    retrieved_sources: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_pmids: list[str] = Field(default_factory=list)
    retrieved_dois: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[uuid.UUID] = Field(default_factory=list)
    expected_pmids_present: bool | None = None
    expected_dois_present: bool | None = None
    coverage_status: str = "not_applicable"
    recall_at_5: float | None = None
    recall_at_10: float | None = None
    recall_at_20: float | None = None
    mrr_at_10: float | None = None
    precision_at_k: float | None = None
    response_text: str | None = None
    response_sources: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: int | None = None
    time_to_first_token_ms: int | None = None
    failure_category: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class EvaluationReportImportRequest(BaseModel):
    report: dict[str, Any]
    name: str | None = Field(default=None, max_length=200)
    question_set_id: uuid.UUID | None = None
    artifact_paths: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationReportImportResponse(BaseModel):
    run: EvaluationRunResponse
    result_count: int = 0
    linked_question_count: int = 0


class EvaluationReviewAssignmentCreate(BaseModel):
    assigned_to_user_id: uuid.UUID
    due_at: datetime | None = None
    notes: str | None = None


class EvaluationReviewAssignmentResponse(BaseModel):
    id: uuid.UUID
    run_result_id: uuid.UUID
    assigned_to_user_id: uuid.UUID
    assigned_by_user_id: uuid.UUID | None = None
    status: str
    due_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None = None
    notes: str | None = None


class EvaluationReviewTaskResponse(BaseModel):
    assignment: EvaluationReviewAssignmentResponse
    result: EvaluationRunResultResponse
    review: "EvaluationReviewResponse | None" = None


class EvaluationReviewBase(BaseModel):
    correctness_score: int | None = Field(default=None, ge=1, le=5)
    completeness_score: int | None = Field(default=None, ge=1, le=5)
    citation_support_score: int | None = Field(default=None, ge=1, le=5)
    grounding_score: int | None = Field(default=None, ge=1, le=5)
    usefulness_score: int | None = Field(default=None, ge=1, le=5)
    refusal_behavior: str | None = None
    false_premise_handling: str | None = None
    hallucination_flag: bool = False
    citation_issue_flag: bool = False
    corpus_gap_flag: bool = False
    retrieval_issue_flag: bool = False
    generation_issue_flag: bool = False
    latency_issue_flag: bool = False
    recommended_failure_category: str | None = None
    reviewer_confidence: int | None = Field(default=None, ge=1, le=5)
    free_text_feedback: str | None = None
    suggested_answer: str | None = None


class EvaluationReviewCreate(EvaluationReviewBase):
    pass


class EvaluationReviewUpdate(BaseModel):
    correctness_score: int | None = Field(default=None, ge=1, le=5)
    completeness_score: int | None = Field(default=None, ge=1, le=5)
    citation_support_score: int | None = Field(default=None, ge=1, le=5)
    grounding_score: int | None = Field(default=None, ge=1, le=5)
    usefulness_score: int | None = Field(default=None, ge=1, le=5)
    refusal_behavior: str | None = None
    false_premise_handling: str | None = None
    hallucination_flag: bool | None = None
    citation_issue_flag: bool | None = None
    corpus_gap_flag: bool | None = None
    retrieval_issue_flag: bool | None = None
    generation_issue_flag: bool | None = None
    latency_issue_flag: bool | None = None
    recommended_failure_category: str | None = None
    reviewer_confidence: int | None = Field(default=None, ge=1, le=5)
    free_text_feedback: str | None = None
    suggested_answer: str | None = None


class EvaluationReviewResponse(EvaluationReviewBase):
    id: uuid.UUID
    assignment_id: uuid.UUID
    run_result_id: uuid.UUID
    reviewer_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None = None


class EvaluationComparisonRequest(BaseModel):
    baseline_run_id: uuid.UUID
    candidate_run_id: uuid.UUID


class EvaluationMetricDelta(BaseModel):
    metric: str
    baseline: Any = None
    candidate: Any = None
    delta: float | None = None


class EvaluationQuestionDelta(BaseModel):
    question_id: str
    baseline_coverage: str | None = None
    candidate_coverage: str | None = None
    baseline_recall_at_20: float | None = None
    candidate_recall_at_20: float | None = None
    baseline_mrr_at_10: float | None = None
    candidate_mrr_at_10: float | None = None


class EvaluationComparisonResponse(BaseModel):
    baseline_run_id: uuid.UUID
    candidate_run_id: uuid.UUID
    metric_deltas: list[EvaluationMetricDelta]
    question_deltas: list[EvaluationQuestionDelta]
    recommendation: str


class EvaluationReleaseGateResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    checks: list[dict[str, Any]]
    release_decision: dict[str, Any] | None = None


class EvaluationReleaseDecisionRequest(BaseModel):
    status: Literal["approved", "waived", "rejected"]
    note: str | None = None


class EvaluationWorkerStatusResponse(BaseModel):
    active: bool
    state: str
    run_id: str | None = None
    updated_at: str | None = None
    seconds_since_heartbeat: int | None = None
    message: str
