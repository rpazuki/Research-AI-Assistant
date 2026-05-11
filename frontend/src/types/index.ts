// Shared TypeScript types — mirrors backend Pydantic schemas

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: "researcher" | "admin";
  is_active: boolean;
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
  year_min: number | null;
  year_max: number | null;
  last_ingestion: string | null;
  last_corpus_name: string | null;
}
