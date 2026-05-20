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
  usage: UserUsageSummary;
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
