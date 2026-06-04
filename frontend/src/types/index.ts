// Shared TypeScript types — mirrors backend Pydantic schemas

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: "researcher" | "admin";
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
