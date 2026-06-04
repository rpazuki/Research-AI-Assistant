import type {
  AdminStats,
  AdminUserSummary,
  ChatSession,
  ChatSessionWithMessages,
  ChatQuota,
  IngestionConfigContent,
  IngestionConfigDetail,
  IngestionConfigSummary,
  IngestionDefaults,
  IngestionJob,
  IngestionJobCreate,
  IngestionUploadBatch,
  IngestionWorkerStatus,
  InvitationPreview,
  InvitationSendResponse,
  User,
} from "@/types";

/**
 * Typed API client for the frontend proxy layer.
 * Auth is handled by an httpOnly cookie set by /api/auth/login.
 */

const API_PREFIX = "/api/backend";

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const { ...rest } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(rest.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${API_PREFIX}${path}`, { ...rest, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `API error ${res.status}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

async function apiFormFetch<T>(path: string, body: FormData): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    method: "POST",
    body,
  });
  if (!res.ok) {
    const responseBody = await res.json().catch(() => ({}));
    throw new Error(responseBody?.detail ?? `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string) {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `API error ${res.status}`);
  }
}

export async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
}

export async function getMe() {
  return apiFetch<User>("/auth/me");
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export async function listAdminUsers() {
  return apiFetch<AdminUserSummary[]>("/admin/users");
}

export async function getAdminStats() {
  return apiFetch<AdminStats>("/admin/stats");
}

export async function getAdminUser(userId: string) {
  return apiFetch<AdminUserSummary>(`/admin/users/${userId}`);
}

export async function listAdminUserSessions(userId: string) {
  return apiFetch<ChatSession[]>(`/admin/users/${userId}/chat/sessions`);
}

export async function getAdminUserSession(userId: string, sessionId: string) {
  return apiFetch<ChatSessionWithMessages>(
    `/admin/users/${userId}/chat/sessions/${sessionId}`
  );
}

export async function updateAdminUserStatus(userId: string, isActive: boolean) {
  return apiFetch<AdminUserSummary>(`/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export async function updateAdminUserTokenLimit(userId: string, tokenLimit: number) {
  return apiFetch<AdminUserSummary>(`/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ token_limit: tokenLimit }),
  });
}

export async function updateAdminUserRole(userId: string, role: User["role"]) {
  return apiFetch<AdminUserSummary>(`/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export async function sendInvitations(
  recipientEmails: string[],
  subject: string,
  template: string
) {
  return apiFetch<InvitationSendResponse>("/admin/invitations", {
    method: "POST",
    body: JSON.stringify({
      recipient_emails: recipientEmails,
      subject,
      template,
    }),
  });
}

export async function listIngestionConfigs() {
  return apiFetch<IngestionConfigSummary[]>("/admin/ingestion/configs");
}

export async function getIngestionConfig(configName: string) {
  return apiFetch<IngestionConfigDetail>(
    `/admin/ingestion/configs/${encodeURIComponent(configName)}`
  );
}

export async function createIngestionConfig(name: string, content: IngestionConfigContent) {
  return apiFetch<IngestionConfigDetail>("/admin/ingestion/configs", {
    method: "POST",
    body: JSON.stringify({ name, content }),
  });
}

export async function updateIngestionConfig(configName: string, content: IngestionConfigContent) {
  return apiFetch<IngestionConfigDetail>(
    `/admin/ingestion/configs/${encodeURIComponent(configName)}`,
    {
      method: "PUT",
      body: JSON.stringify({ content }),
    }
  );
}

export async function getIngestionDefaults() {
  return apiFetch<IngestionDefaults>("/admin/ingestion/defaults");
}

export async function getIngestionWorkerStatus() {
  return apiFetch<IngestionWorkerStatus>("/admin/ingestion/worker");
}

export async function listIngestionUploads() {
  return apiFetch<IngestionUploadBatch[]>("/admin/ingestion/uploads");
}

export async function uploadIngestionPdfFolder(files: File[], name?: string) {
  const body = new FormData();
  for (const file of files) {
    const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
    body.append("files", file, relativePath || file.name);
  }
  if (name) {
    body.append("name", name);
  }
  return apiFormFetch<IngestionUploadBatch>("/admin/ingestion/pdf-upload-folders", body);
}

export async function listIngestionJobs() {
  return apiFetch<IngestionJob[]>("/admin/ingestion/jobs");
}

export async function createIngestionJob(payload: IngestionJobCreate) {
  return apiFetch<IngestionJob>("/admin/ingestion/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function cancelIngestionJob(jobId: string) {
  return apiFetch<IngestionJob>(`/admin/ingestion/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export async function getInvitation(token: string) {
  const res = await fetch(`/api/auth/invitations/${token}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `API error ${res.status}`);
  }
  return res.json() as Promise<InvitationPreview>;
}

export async function acceptInvitation(
  token: string,
  fullName: string,
  password: string,
  passwordConfirm: string
) {
  const res = await fetch(`/api/auth/invitations/${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      full_name: fullName,
      password,
      password_confirm: passwordConfirm,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((item: { msg?: string }) => item.msg).join("; ")
      : body?.detail;
    throw new Error(detail ?? `API error ${res.status}`);
  }
  return res.json() as Promise<User>;
}

// ── Chat Sessions ─────────────────────────────────────────────────────────────

export async function createSession(mode = "researcher", title?: string) {
  return apiFetch<{ id: string; mode: string; title: string | null }>("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ mode, title }),
  });
}

export async function listSessions() {
  return apiFetch<ChatSession[]>("/chat/sessions");
}

export async function getChatQuota() {
  return apiFetch<ChatQuota>("/chat/quota");
}

export async function getSession(sessionId: string) {
  return apiFetch<ChatSessionWithMessages>(`/chat/sessions/${sessionId}`);
}

export async function deleteSession(sessionId: string) {
  await apiFetch<void>(`/chat/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export async function updateSessionTitle(sessionId: string, title: string) {
  return apiFetch<{ id: string; title: string | null; mode: string; updated_at: string }>(
    `/chat/sessions/${sessionId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }
  );
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
  sessionId: string,
  query: string,
  mode: string = "researcher",
  topK?: number
): Promise<ReadableStream<Uint8Array>> {
  const res = await fetch(`${API_PREFIX}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query, mode, top_k: topK }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `Stream error ${res.status}`);
  }
  if (!res.body) {
    throw new Error("No response body for streaming");
  }
  return res.body;
}

// ── Search ─────────────────────────────────────────────────────────────────────

export async function search(
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
  });
}

// ── Analytics ──────────────────────────────────────────────────────────────────

export async function getTemporalData() {
  return apiFetch<Array<{ year: number; count: number }>>("/analytics/temporal");
}

export async function getJournals(limit = 20) {
  return apiFetch<Array<{ journal: string; count: number }>>(
    `/analytics/journals?limit=${limit}`
  );
}

export async function getMeshTerms(limit = 30) {
  return apiFetch<Array<{ term: string; count: number }>>(`/analytics/mesh_terms?limit=${limit}`);
}

export async function getTopics(limit = 20) {
  return apiFetch<Array<{ topic: string; count: number }>>(`/analytics/topics?limit=${limit}`);
}

export async function getCorpusStats() {
  return apiFetch<{
    document_count: number;
    chunk_count: number;
    year_min: number | null;
    year_max: number | null;
    last_ingestion: string | null;
    last_corpus_name: string | null;
  }>("/analytics/corpus_stats");
}

// ── Feedback ───────────────────────────────────────────────────────────────────

export async function submitFeedback(
  messageId: string, rating: number, comment?: string
) {
  return apiFetch<{ id: string }>("/feedback", {
    method: "POST",
    body: JSON.stringify({ message_id: messageId, rating, comment }),
  });
}
