// Shared TypeScript types — mirrors backend Pydantic schemas

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: "researcher" | "evaluator" | "admin";
  is_active: boolean;
}

export interface UserUsageSummary {
  session_count: number;
  user_message_count: number;
  assistant_message_count: number;
  prompt_token_count: number;
  completion_token_count: number;
  total_token_count: number;
  last_active_at: string | null;
  avg_latency_ms: number | null;
}

export interface AdminUserSummary extends User {
  token_limit: number;
  token_limit_reached: boolean;
  usage: UserUsageSummary;
}

export interface AdminStatsOverview {
  document_count: number;
  chunk_count: number;
  indexed_token_count: number;
  user_count: number;
  active_user_count: number;
  inactive_user_count: number;
  session_count: number;
  question_count: number;
  assistant_message_count: number;
  prompt_token_count: number;
  completion_token_count: number;
  total_chat_token_count: number;
  avg_latency_ms: number | null;
  upload_batch_count: number;
  uploaded_pdf_file_count: number;
  uploaded_pdf_bytes: number;
  last_ingestion_at: string | null;
  last_corpus_name: string | null;
  year_min: number | null;
  year_max: number | null;
}

export interface AdminStatsContentBreakdown {
  abstract_only_documents: number;
  full_text_documents: number;
  pdf_documents: number;
  electronic_lab_notebook_documents: number;
  other_documents: number;
}

export interface AdminStatsSourceBreakdownItem {
  source: string;
  document_count: number;
  chunk_count: number;
  indexed_token_count: number;
}

export interface AdminStatsJobStatusItem {
  status: string;
  count: number;
}

export interface AdminStatsRecentJob {
  id: string;
  status: string;
  source: string;
  mode: string;
  document_count: number | null;
  chunk_count: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress_message: string | null;
  error: string | null;
}

export interface AdminStats {
  overview: AdminStatsOverview;
  content: AdminStatsContentBreakdown;
  sources: AdminStatsSourceBreakdownItem[];
  job_statuses: AdminStatsJobStatusItem[];
  recent_jobs: AdminStatsRecentJob[];
}

export interface IngestionDocumentErrorReport {
  cache_path: string;
  error_file_path: string;
  exists: boolean;
  record_count: number;
  records: Record<string, unknown>[];
  parse_errors: string[];
}

export interface IngestionAcquisitionQueueReport {
  cache_path: string;
  queue_file_path: string;
  exists: boolean;
  record_count: number;
  records: Record<string, unknown>[];
  parse_errors: string[];
}

export interface IngestionConfigSummary {
  name: string;
  path: string;
  corpus_name: string;
  source: string;
  embedding_model: string;
  year_from: number | null;
  year_to: number | null;
  pdf_dir: string | null;
  supports_pdf_upload: boolean;
}

export type TomlPrimitive = string | number | boolean | null;
export type TomlValue = TomlPrimitive | TomlPrimitive[];
export type IngestionConfigContent = Record<string, Record<string, TomlValue>>;

export interface IngestionConfigDetail {
  name: string;
  path: string;
  content: IngestionConfigContent;
}

export interface IngestionDefaults {
  config_name: string;
  mode: IngestionJobMode;
  cache_path: string;
  write_acquisition_queue: boolean;
  include_cached_fulltext: boolean;
}

export interface IngestionWorkerStatus {
  active: boolean;
  state: string;
  job_id: string | null;
  updated_at: string | null;
  seconds_since_heartbeat: number | null;
  message: string;
}

export interface IngestionUploadBatch {
  id: string;
  name: string;
  directory_path: string;
  file_count: number;
  total_bytes: number;
  created_at: string;
}

export type IngestionJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancel_requested"
  | "cancelled";

export type IngestionJobMode =
  | "full"
  | "incremental"
  | "test_year"
  | "local_only"
  | "queue_only";

export interface IngestionJob {
  id: string;
  requested_by_user_id: string | null;
  status: IngestionJobStatus;
  config_name: string;
  config_path: string;
  source: string;
  mode: string;
  from_date: string | null;
  year: number | null;
  cache_path: string | null;
  pdf_upload_batch_id: string | null;
  options: Record<string, unknown> | null;
  manifest_id: string | null;
  document_count: number | null;
  chunk_count: number | null;
  progress_message: string | null;
  log_tail: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface IngestionJobCreate {
  config_name: string;
  mode: IngestionJobMode;
  from_date?: string | null;
  year?: number | null;
  cache_path?: string | null;
  pdf_upload_batch_id?: string | null;
  write_acquisition_queue?: boolean;
  include_cached_fulltext?: boolean;
}

export type EvaluationQuestionSetStatus = "draft" | "active" | "archived";
export type EvaluationQuestionCategory =
  | "factual"
  | "review"
  | "out_of_scope"
  | "citation_stress"
  | "methodology";
export type EvaluationQuestionDifficulty = "easy" | "medium" | "hard";
export type EvaluationQuestionDomainFit = "core" | "adjacent" | "out_of_scope" | "remove";
export type EvaluationExpectedBehavior =
  | "answer"
  | "refuse"
  | "correct_false_premise"
  | "partial_answer_with_gap";
export type EvaluationQuestionReviewStatus =
  | "draft"
  | "expert_review_needed"
  | "expert_reviewed"
  | "label_complete"
  | "retired";
export type EvaluationRunMode = "retrieval" | "rag" | "combined";
export type EvaluationRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "cancel_requested";

export interface EvaluationQuestionSet {
  id: string;
  name: string;
  description: string | null;
  status: EvaluationQuestionSetStatus;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
  question_count: number;
  label_complete_count: number;
}

export interface EvaluationSupportingEvidenceItem {
  pmid?: string | null;
  doi?: string | null;
  section?: string | null;
  evidence_note?: string | null;
  text?: string | null;
}

export interface EvaluationQuestionCreate {
  external_id: string;
  question: string;
  category: EvaluationQuestionCategory;
  difficulty: EvaluationQuestionDifficulty;
  domain_fit: EvaluationQuestionDomainFit;
  expected_behavior: EvaluationExpectedBehavior;
  expected_keywords: string[];
  expected_pmids: string[];
  expected_dois: string[];
  gold_answer_outline?: string | null;
  supporting_evidence: EvaluationSupportingEvidenceItem[];
  requires_full_text: boolean;
  review_status: EvaluationQuestionReviewStatus;
  expert_owner_user_id?: string | null;
  notes?: string | null;
}

export interface EvaluationQuestion extends EvaluationQuestionCreate {
  id: string;
  question_set_id: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface EvaluationQuestionImportResponse {
  created: number;
  updated: number;
  skipped: number;
  questions: EvaluationQuestion[];
}

export interface EvaluationRunCreate {
  name: string;
  mode: EvaluationRunMode;
  status?: EvaluationRunStatus;
  question_set_id?: string | null;
  corpus_manifest_id?: string | null;
  retrieval_config?: Record<string, unknown>;
  reranker_config?: Record<string, unknown>;
  llm_provider?: string | null;
  llm_model?: string | null;
  prompt_version?: string | null;
  metadata?: Record<string, unknown>;
}

export interface EvaluationRun {
  id: string;
  name: string;
  mode: EvaluationRunMode;
  status: EvaluationRunStatus;
  question_set_id: string | null;
  started_by_user_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  corpus_manifest_id: string | null;
  document_count: number | null;
  chunk_count: number | null;
  embedding_model: string | null;
  chunk_size: number | null;
  chunk_overlap: number | null;
  retrieval_config: Record<string, unknown>;
  reranker_config: Record<string, unknown>;
  llm_provider: string | null;
  llm_model: string | null;
  prompt_version: string | null;
  git_commit: string | null;
  runner_version: string | null;
  summary_metrics: Record<string, unknown>;
  error_message: string | null;
  artifact_paths: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EvaluationRunResult {
  id: string;
  run_id: string;
  question_id: string | null;
  status: string;
  question_snapshot: Record<string, unknown>;
  retrieved_sources: Record<string, unknown>[];
  retrieved_pmids: string[];
  retrieved_dois: string[];
  retrieved_chunk_ids: string[];
  expected_pmids_present: boolean | null;
  expected_dois_present: boolean | null;
  coverage_status: string;
  recall_at_5: number | null;
  recall_at_10: number | null;
  recall_at_20: number | null;
  mrr_at_10: number | null;
  precision_at_k: number | null;
  response_text: string | null;
  response_sources: Record<string, unknown>[];
  latency_ms: number | null;
  time_to_first_token_ms: number | null;
  failure_category: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvaluationReportImportResponse {
  run: EvaluationRun;
  result_count: number;
  linked_question_count: number;
}

export interface EvaluationReviewAssignment {
  id: string;
  run_result_id: string;
  assigned_to_user_id: string;
  assigned_by_user_id: string | null;
  status: string;
  due_at: string | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  notes: string | null;
}

export interface EvaluationReviewPayload {
  correctness_score?: number | null;
  completeness_score?: number | null;
  citation_support_score?: number | null;
  grounding_score?: number | null;
  usefulness_score?: number | null;
  reviewer_confidence?: number | null;
  hallucination_flag?: boolean;
  citation_issue_flag?: boolean;
  corpus_gap_flag?: boolean;
  retrieval_issue_flag?: boolean;
  generation_issue_flag?: boolean;
  latency_issue_flag?: boolean;
  recommended_failure_category?: string | null;
  free_text_feedback?: string | null;
  suggested_answer?: string | null;
}

export interface EvaluationReview extends EvaluationReviewPayload {
  id: string;
  assignment_id: string;
  run_result_id: string;
  reviewer_user_id: string;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
}

export interface EvaluationReviewTask {
  assignment: EvaluationReviewAssignment;
  result: EvaluationRunResult;
  review: EvaluationReview | null;
}

export interface EvaluationReleaseDecision {
  status: "approved" | "waived" | "rejected";
  note: string | null;
  decided_by_user_id: string;
  decided_at: string;
}

export interface EvaluationMetricDelta {
  metric: string;
  baseline: unknown;
  candidate: unknown;
  delta: number | null;
}

export interface EvaluationQuestionDelta {
  question_id: string;
  baseline_coverage: string | null;
  candidate_coverage: string | null;
  baseline_recall_at_20: number | null;
  candidate_recall_at_20: number | null;
  baseline_mrr_at_10: number | null;
  candidate_mrr_at_10: number | null;
}

export interface EvaluationComparison {
  baseline_run_id: string;
  candidate_run_id: string;
  metric_deltas: EvaluationMetricDelta[];
  question_deltas: EvaluationQuestionDelta[];
  recommendation: string;
}

export interface EvaluationReleaseGate {
  run_id: string;
  status: string;
  checks: Array<Record<string, unknown>>;
  release_decision: EvaluationReleaseDecision | null;
}

export interface EvaluationWorkerStatus {
  active: boolean;
  state: string;
  run_id: string | null;
  updated_at: string | null;
  seconds_since_heartbeat: number | null;
  message: string;
}

export interface InvitationSendItem {
  email: string;
  status: "sent" | "failed";
  expires_at: string | null;
  detail: string | null;
}

export interface InvitationSendResponse {
  sent: InvitationSendItem[];
  failed: InvitationSendItem[];
}

export interface InvitationPreview {
  email: string;
  expires_at: string;
}

export interface Source {
  pmid: string | null;
  doi: string | null;
  title: string | null;
  journal: string | null;
  year: number | null;
  url: string | null;
  snippet: string | null;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[] | null;
  llm_model?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  latency_ms?: number | null;
  created_at: string;
}

export interface ChatSession {
  id: string;
  user_id: string;
  title: string | null;
  mode: string;
  created_at: string;
  updated_at: string;
}

export interface ChatSessionWithMessages extends ChatSession {
  messages: ChatMessage[];
}

export interface ChatQuota {
  token_limit: number;
  total_token_count: number;
  token_limit_reached: boolean;
  message: string | null;
}

export interface SearchResultItem {
  chunk_id: string;
  document_id: string;
  pmid: string | null;
  doi: string | null;
  title: string | null;
  journal: string | null;
  year: number | null;
  url: string | null;
  content: string;
  score: number;
  chunk_type: string;
}

// SSE event types from streaming chat endpoint
export type SSEEventType = "token" | "sources" | "done" | "error";

export interface SSETokenEvent {
  type: "token";
  data: string;
}

export interface SSESourcesEvent {
  type: "sources";
  data: Source[];
}

export interface SSEDoneEvent {
  type: "done";
  message_id: string;
  latency_ms: number;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
}

export interface SSEErrorEvent {
  type: "error";
  message: string;
}

export type SSEEvent = SSETokenEvent | SSESourcesEvent | SSEDoneEvent | SSEErrorEvent;

// Analytics
export interface TemporalDataPoint {
  year: number;
  count: number;
}

export interface JournalDataPoint {
  journal: string;
  count: number;
}

export interface CorpusStats {
  document_count: number;
  chunk_count: number;
  year_min: number | null;
  year_max: number | null;
  last_ingestion: string | null;
  last_corpus_name: string | null;
}
