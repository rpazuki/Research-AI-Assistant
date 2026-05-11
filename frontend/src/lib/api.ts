/**
 * Typed API client for the FastAPI backend.
 * All fetch calls go through this module.
 * Tokens are read from next-auth session.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_PREFIX = `${API_BASE}/api/v1`;

async function apiFetch<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...rest } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(rest.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${API_PREFIX}${path}`, { ...rest, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string) {
  return apiFetch<{ access_token: string; token_type: string; expires_in: number }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) }
  );
}

export async function getMe(token: string) {
  return apiFetch<{ id: string; email: string; full_name: string | null; role: string }>(
    "/auth/me",
    { token }
  );
}

// ── Chat Sessions ─────────────────────────────────────────────────────────────

export async function createSession(token: string, mode = "researcher", title?: string) {
  return apiFetch<{ id: string; mode: string; title: string | null }>("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ mode, title }),
    token,
  });
}

export async function listSessions(token: string) {
  return apiFetch<Array<{ id: string; title: string | null; mode: string; updated_at: string }>>(
    "/chat/sessions",
    { token }
  );
}

export async function getSession(token: string, sessionId: string) {
  return apiFetch<{
    id: string;
    mode: string;
    messages: Array<{ id: string; role: string; content: string; sources?: unknown[] }>;
  }>(`/chat/sessions/${sessionId}`, { token });
}

// ── Streaming chat ─────────────────────────────────────────────────────────────

/**
 * Open a streaming SSE connection for a chat message.
 * Returns a ReadableStream — the caller is responsible for reading events.
 *
 * Usage:
 *   const stream = await streamMessage(token, sessionId, query, mode);
 *   const reader = stream.getReader();
 *   const decoder = new TextDecoder();
 *   while (true) {
 *     const { done, value } = await reader.read();
 *     if (done) break;
 *     const text = decoder.decode(value);
 *     // parse SSE events from text
 *   }
 */
export async function streamMessage(
  token: string,
  sessionId: string,
  query: string,
  mode: string = "researcher",
  topK?: number
): Promise<ReadableStream<Uint8Array>> {
  const res = await fetch(`${API_PREFIX}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query, mode, top_k: topK }),
  });

  if (!res.ok) {
    throw new Error(`Stream error ${res.status}`);
  }
  if (!res.body) {
    throw new Error("No response body for streaming");
  }
  return res.body;
}

// ── Search ─────────────────────────────────────────────────────────────────────

export async function search(
  token: string,
  query: string,
  topK = 5,
  filters?: Record<string, unknown>
) {
  return apiFetch<Array<{
    chunk_id: string; document_id: string; pmid: string | null;
    title: string | null; content: string; score: number;
  }>>("/search", {
    method: "POST",
    body: JSON.stringify({ query, top_k: topK, filters }),
    token,
  });
}

// ── Analytics ──────────────────────────────────────────────────────────────────

export async function getTemporalData(token: string) {
  return apiFetch<Array<{ year: number; count: number }>>("/analytics/temporal", { token });
}

export async function getJournals(token: string, limit = 20) {
  return apiFetch<Array<{ journal: string; count: number }>>(
    `/analytics/journals?limit=${limit}`,
    { token }
  );
}

export async function getCorpusStats(token: string) {
  return apiFetch<{
    document_count: number; year_min: number | null; year_max: number | null;
    last_ingestion: string | null; last_corpus_name: string | null;
  }>("/analytics/corpus_stats", { token });
}

// ── Feedback ───────────────────────────────────────────────────────────────────

export async function submitFeedback(
  token: string, messageId: string, rating: number, comment?: string
) {
  return apiFetch<{ id: string }>("/feedback", {
    method: "POST",
    body: JSON.stringify({ message_id: messageId, rating, comment }),
    token,
  });
}
