/**
 * Unit tests for src/lib/api.ts
 *
 * All network calls are intercepted via vi.stubGlobal("fetch", ...) so no
 * real HTTP traffic occurs. Tests verify request shape, response parsing,
 * and error propagation.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSession,
  createIngestionConfig,
  deleteSession,
  acceptInvitation,
  getAdminStats,
  getAdminUser,
  getAdminUserSession,
  getChatQuota,
  getCorpusStats,
  getIngestionConfig,
  getIngestionDocumentErrors,
  getInvitation,
  getJournals,
  getMeshTerms,
  getMe,
  getSession,
  getTemporalData,
  getTopics,
  listSessions,
  listAdminUsers,
  listAdminUserSessions,
  login,
  logout,
  search,
  sendInvitations,
  streamMessage,
  updateAdminUserRole,
  submitFeedback,
  updateIngestionConfig,
  updateAdminUserStatus,
  updateAdminUserTokenLimit,
  updateSessionTitle,
} from "./api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockFetch(status: number, body: unknown, ok = status >= 200 && status < 300) {
  const bodyStr = JSON.stringify(body);
  const response = {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(bodyStr));
        controller.close();
      },
    }),
  } as unknown as Response;

  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  return response;
}

function mock204() {
  const response = { ok: true, status: 204, json: vi.fn().mockRejectedValue(new Error("no body")) } as unknown as Response;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  return response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── login ─────────────────────────────────────────────────────────────────────

describe("login", () => {
  it("posts credentials to /api/auth/login", async () => {
    mockFetch(200, { ok: true });
    await login("user@lab.ac.uk", "secret");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/auth/login");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ email: "user@lab.ac.uk", password: "secret" });
  });

  it("throws on non-ok response with detail", async () => {
    mockFetch(401, { detail: "Invalid credentials" }, false);
    await expect(login("x@x.com", "bad")).rejects.toThrow("Invalid credentials");
  });

  it("throws generic message when no detail field", async () => {
    mockFetch(500, {}, false);
    await expect(login("x@x.com", "pw")).rejects.toThrow("API error 500");
  });
});

// ── logout ────────────────────────────────────────────────────────────────────

describe("logout", () => {
  it("calls /api/auth/logout with POST", async () => {
    mock204();
    await logout();
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/auth/logout");
    expect(call[1].method).toBe("POST");
  });
});

// ── getMe ─────────────────────────────────────────────────────────────────────

describe("getMe", () => {
  it("returns user profile from backend", async () => {
    mockFetch(200, { id: "u1", email: "me@lab.ac.uk", full_name: "Researcher", role: "researcher" });
    const user = await getMe();
    expect(user.email).toBe("me@lab.ac.uk");
    expect(user.role).toBe("researcher");
  });

  it("throws on 401", async () => {
    mockFetch(401, { detail: "Unauthorized" }, false);
    await expect(getMe()).rejects.toThrow("Unauthorized");
  });
});

// ── admin ─────────────────────────────────────────────────────────────────────

describe("admin user API", () => {
  it("fetches aggregate admin statistics", async () => {
    mockFetch(200, {
      overview: {
        document_count: 17,
        chunk_count: 71,
        indexed_token_count: 12345,
        user_count: 4,
        active_user_count: 3,
        inactive_user_count: 1,
        session_count: 8,
        question_count: 21,
        assistant_message_count: 20,
        prompt_token_count: 900,
        completion_token_count: 300,
        total_chat_token_count: 1200,
        avg_latency_ms: 512.5,
        upload_batch_count: 2,
        uploaded_pdf_file_count: 9,
        uploaded_pdf_bytes: 2048,
        last_ingestion_at: "2026-06-01T10:00:00Z",
        last_corpus_name: "rlalab-pubmed-v1",
        year_min: 2000,
        year_max: 2026,
      },
      content: {
        abstract_only_documents: 10,
        full_text_documents: 3,
        pdf_documents: 4,
        electronic_lab_notebook_documents: 0,
        other_documents: 0,
      },
      sources: [],
      job_statuses: [],
      recent_jobs: [],
    });

    const stats = await getAdminStats();

    expect(stats.overview.document_count).toBe(17);
    expect(stats.content.pdf_documents).toBe(4);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/backend/admin/stats"
    );
  });

  it("fetches ingestion document error reports", async () => {
    mockFetch(200, [
      {
        cache_path: "/app/data/corpora/rlalab-pubmed-v1/cumulative",
        error_file_path: "/app/data/corpora/rlalab-pubmed-v1/cumulative/normalized/documents.errors.jsonl",
        exists: true,
        record_count: 1,
        records: [{ document_id: "pdf:empty", error: "No text extracted" }],
        parse_errors: [],
      },
    ]);

    const reports = await getIngestionDocumentErrors();

    expect(reports[0].record_count).toBe(1);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/backend/admin/stats/ingestion-document-errors"
    );
  });

  it("lists admin users", async () => {
    mockFetch(200, [
      {
        id: "u1",
        email: "admin@lab.ac.uk",
        full_name: "Admin",
        role: "admin",
        is_active: true,
        token_limit: 1_000_000,
        token_limit_reached: false,
        usage: {
          session_count: 3,
          user_message_count: 8,
          assistant_message_count: 8,
          prompt_token_count: 1200,
          completion_token_count: 300,
          total_token_count: 1500,
          last_active_at: "2026-05-20T09:30:00Z",
          avg_latency_ms: 812.5,
        },
      },
    ]);

    const users = await listAdminUsers();

    expect(users).toHaveLength(1);
    expect(users[0].email).toBe("admin@lab.ac.uk");
    expect(users[0].usage.session_count).toBe(3);
    expect(users[0].usage.total_token_count).toBe(1500);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/backend/admin/users");
  });

  it("fetches one admin user", async () => {
    mockFetch(200, {
      id: "u1",
      email: "researcher@lab.ac.uk",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 1,
        user_message_count: 2,
        assistant_message_count: 2,
        prompt_token_count: 400,
        completion_token_count: 100,
        total_token_count: 500,
        last_active_at: null,
        avg_latency_ms: null,
      },
    });

    const user = await getAdminUser("u1");

    expect(user.id).toBe("u1");
    expect(user.usage.session_count).toBe(1);
    expect(user.usage.prompt_token_count).toBe(400);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/backend/admin/users/u1"
    );
  });

  it("lists a user's sessions for admin read-only viewing", async () => {
    mockFetch(200, [
      {
        id: "s1",
        user_id: "u1",
        title: "User chat",
        mode: "researcher",
        created_at: "2026-05-20T09:00:00Z",
        updated_at: "2026-05-20T09:30:00Z",
      },
    ]);

    const sessions = await listAdminUserSessions("u1");

    expect(sessions[0].title).toBe("User chat");
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/backend/admin/users/u1/chat/sessions"
    );
  });

  it("fetches a user's session with messages for admin read-only viewing", async () => {
    mockFetch(200, {
      id: "s1",
      user_id: "u1",
      title: "User chat",
      mode: "researcher",
      created_at: "2026-05-20T09:00:00Z",
      updated_at: "2026-05-20T09:30:00Z",
      messages: [
        {
          id: "m1",
          session_id: "s1",
          role: "user",
          content: "What did I ask?",
          sources: null,
          created_at: "2026-05-20T09:00:00Z",
        },
      ],
    });

    const session = await getAdminUserSession("u1", "s1");

    expect(session.messages[0].content).toBe("What did I ask?");
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/backend/admin/users/u1/chat/sessions/s1"
    );
  });

  it("updates admin user active status", async () => {
    mockFetch(200, {
      id: "u1",
      email: "researcher@lab.ac.uk",
      full_name: "Researcher",
      role: "researcher",
      is_active: false,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 1,
        user_message_count: 2,
        assistant_message_count: 2,
        prompt_token_count: 400,
        completion_token_count: 100,
        total_token_count: 500,
        last_active_at: null,
        avg_latency_ms: null,
      },
    });

    const user = await updateAdminUserStatus("u1", false);

    expect(user.is_active).toBe(false);
    expect(user.usage.user_message_count).toBe(2);
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/backend/admin/users/u1");
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(call[1].body)).toEqual({ is_active: false });
  });

  it("updates admin user token limit", async () => {
    mockFetch(200, {
      id: "u1",
      email: "researcher@lab.ac.uk",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 5_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 1,
        user_message_count: 2,
        assistant_message_count: 2,
        prompt_token_count: 400,
        completion_token_count: 100,
        total_token_count: 500,
        last_active_at: null,
        avg_latency_ms: null,
      },
    });

    const user = await updateAdminUserTokenLimit("u1", 5_000_000);

    expect(user.token_limit).toBe(5_000_000);
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/backend/admin/users/u1");
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(call[1].body)).toEqual({ token_limit: 5000000 });
  });

  it("updates admin user role", async () => {
    mockFetch(200, {
      id: "u1",
      email: "researcher@lab.ac.uk",
      full_name: "Researcher",
      role: "admin",
      is_active: true,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 1,
        user_message_count: 2,
        assistant_message_count: 2,
        prompt_token_count: 400,
        completion_token_count: 100,
        total_token_count: 500,
        last_active_at: null,
        avg_latency_ms: null,
      },
    });

    const user = await updateAdminUserRole("u1", "admin");

    expect(user.role).toBe("admin");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/backend/admin/users/u1");
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(call[1].body)).toEqual({ role: "admin" });
  });

  it("sends invitations", async () => {
    mockFetch(200, {
      sent: [{ email: "new@lab.ac.uk", status: "sent", expires_at: "2026-05-27T00:00:00Z", detail: null }],
      failed: [],
    });

    const result = await sendInvitations(["new@lab.ac.uk"], "Join", "Use {invite_link}");

    expect(result.sent[0].email).toBe("new@lab.ac.uk");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/backend/admin/invitations");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({
      recipient_emails: ["new@lab.ac.uk"],
      subject: "Join",
      template: "Use {invite_link}",
    });
  });

  it("loads, creates, and updates ingestion TOML configs", async () => {
    const content = {
      corpus: {
        name: "rlalab-test",
        source: "pubmed_abstract",
        embedding_model: "pubmedbert",
      },
      pubmed: {
        query: '"Yarrowia"[Title/Abstract]',
        year_from: 2024,
        year_to: 2026,
        batch_size: 20,
        sleep_between_batches_s: 0.15,
      },
    };

    mockFetch(200, { name: "test.toml", path: "/app/pipelines/configs/test.toml", content });
    await getIngestionConfig("test.toml");
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/backend/admin/ingestion/configs/test.toml"
    );

    mockFetch(201, { name: "new.toml", path: "/app/pipelines/configs/new.toml", content });
    await createIngestionConfig("new.toml", content);
    const createCall = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(createCall[0]).toBe("/api/backend/admin/ingestion/configs");
    expect(createCall[1].method).toBe("POST");
    expect(JSON.parse(createCall[1].body)).toEqual({ name: "new.toml", content });

    mockFetch(200, { name: "test.toml", path: "/app/pipelines/configs/test.toml", content });
    await updateIngestionConfig("test.toml", content);
    const updateCall = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(updateCall[0]).toBe("/api/backend/admin/ingestion/configs/test.toml");
    expect(updateCall[1].method).toBe("PUT");
    expect(JSON.parse(updateCall[1].body)).toEqual({ content });
  });
});

// ── invitations ──────────────────────────────────────────────────────────────

describe("invitation acceptance API", () => {
  it("loads an invitation through the public auth route", async () => {
    mockFetch(200, { email: "new@lab.ac.uk", expires_at: "2026-05-27T00:00:00Z" });

    const invitation = await getInvitation("token-1");

    expect(invitation.email).toBe("new@lab.ac.uk");
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/auth/invitations/token-1"
    );
  });

  it("accepts an invitation through the public auth route", async () => {
    mockFetch(201, {
      id: "u1",
      email: "new@lab.ac.uk",
      full_name: "New Researcher",
      role: "researcher",
      is_active: true,
    });

    const user = await acceptInvitation("token-1", "New Researcher", "password123", "password123");

    expect(user.email).toBe("new@lab.ac.uk");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/auth/invitations/token-1");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({
      full_name: "New Researcher",
      password: "password123",
      password_confirm: "password123",
    });
  });
});

// ── createSession ─────────────────────────────────────────────────────────────

describe("createSession", () => {
  it("posts to /api/backend/chat/sessions with default mode", async () => {
    mockFetch(201, { id: "s1", mode: "researcher", title: null });
    const session = await createSession();
    expect(session.id).toBe("s1");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain("/chat/sessions");
    expect(JSON.parse(call[1].body).mode).toBe("researcher");
  });

  it("accepts custom mode and title", async () => {
    mockFetch(201, { id: "s2", mode: "lab_manager", title: "Admin session" });
    await createSession("lab_manager", "Admin session");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.mode).toBe("lab_manager");
    expect(body.title).toBe("Admin session");
  });
});

// ── listSessions ──────────────────────────────────────────────────────────────

describe("listSessions", () => {
  it("returns array of sessions", async () => {
    const sessions = [{ id: "s1", title: "Chat 1", mode: "researcher", updated_at: "2026-01-01" }];
    mockFetch(200, sessions);
    const result = await listSessions();
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("s1");
  });
});

// ── getChatQuota ─────────────────────────────────────────────────────────────

describe("getChatQuota", () => {
  it("fetches the current user's token quota", async () => {
    mockFetch(200, {
      token_limit: 1_000_000,
      total_token_count: 1_000_000,
      token_limit_reached: true,
      message: "Your token limit has been reached. Please ask your lab admin for more tokens.",
    });

    const result = await getChatQuota();

    expect(result.token_limit_reached).toBe(true);
    expect(result.total_token_count).toBe(1_000_000);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      "/api/backend/chat/quota"
    );
  });
});

// ── getSession ────────────────────────────────────────────────────────────────

describe("getSession", () => {
  it("fetches session by id", async () => {
    const payload = { id: "s1", mode: "researcher", messages: [] };
    mockFetch(200, payload);
    const result = await getSession("s1");
    expect(result.id).toBe("s1");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain("/chat/sessions/s1");
  });
});

// ── deleteSession ─────────────────────────────────────────────────────────────

describe("deleteSession", () => {
  it("sends DELETE and returns void", async () => {
    mock204();
    await deleteSession("s1");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].method).toBe("DELETE");
    expect(call[0]).toContain("/chat/sessions/s1");
  });
});

// ── updateSessionTitle ────────────────────────────────────────────────────────

describe("updateSessionTitle", () => {
  it("sends PATCH with new title", async () => {
    mockFetch(200, { id: "s1", title: "New title", mode: "researcher", updated_at: "2026-01-01" });
    const result = await updateSessionTitle("s1", "New title");
    expect(result.title).toBe("New title");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(call[1].body).title).toBe("New title");
  });
});

// ── streamMessage ─────────────────────────────────────────────────────────────

describe("streamMessage", () => {
  it("returns a ReadableStream on success", async () => {
    const stream = new ReadableStream();
    const response = { ok: true, status: 200, json: vi.fn(), body: stream } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    const result = await streamMessage("s1", "What is lipid production?");
    expect(result).toBe(stream);
  });

  it("throws when response is not ok", async () => {
    mockFetch(500, { detail: "Server error" }, false);
    await expect(streamMessage("s1", "query")).rejects.toThrow("Server error");
  });

  it("throws when response body is null", async () => {
    const response = { ok: true, status: 200, json: vi.fn(), body: null } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(streamMessage("s1", "query")).rejects.toThrow("No response body");
  });
});

// ── search ────────────────────────────────────────────────────────────────────

describe("search", () => {
  it("posts query and returns results", async () => {
    const results = [{ chunk_id: "c1", document_id: "pmid:1", pmid: "1", title: "T", content: "C", score: 0.9 }];
    mockFetch(200, results);
    const data = await search("Yarrowia", 5);
    expect(data).toHaveLength(1);
    expect(data[0].pmid).toBe("1");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(call[1].body)).toMatchObject({ query: "Yarrowia", top_k: 5 });
  });
});

// ── analytics ─────────────────────────────────────────────────────────────────

describe("getTemporalData", () => {
  it("fetches temporal publication data", async () => {
    mockFetch(200, [{ year: 2024, count: 42 }]);
    const data = await getTemporalData();
    expect(data[0].year).toBe(2024);
    expect(data[0].count).toBe(42);
  });
});

describe("getJournals", () => {
  it("fetches top journals with default limit", async () => {
    mockFetch(200, [{ journal: "Nature Biotech", count: 10 }]);
    const data = await getJournals();
    expect(data[0].journal).toBe("Nature Biotech");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain("limit=20");
  });
});

describe("getMeshTerms", () => {
  it("fetches MeSH terms", async () => {
    mockFetch(200, [{ term: "Lipid Metabolism", count: 5 }]);
    const data = await getMeshTerms();
    expect(data[0].term).toBe("Lipid Metabolism");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain("limit=30");
  });
});

describe("getTopics", () => {
  it("fetches topic distribution", async () => {
    mockFetch(200, [{ topic: "lipid biosynthesis", count: 7 }]);
    const data = await getTopics();
    expect(data[0].topic).toBe("lipid biosynthesis");
  });
});

describe("getCorpusStats", () => {
  it("fetches corpus statistics", async () => {
    const stats = {
      document_count: 1000,
      chunk_count: 5000,
      year_min: 2000,
      year_max: 2026,
      last_ingestion: "2026-05-01T00:00:00Z",
      last_corpus_name: "rlalab-v1",
    };
    mockFetch(200, stats);
    const data = await getCorpusStats();
    expect(data.document_count).toBe(1000);
    expect(data.chunk_count).toBe(5000);
    expect(data.last_corpus_name).toBe("rlalab-v1");
  });
});

// ── submitFeedback ────────────────────────────────────────────────────────────

describe("submitFeedback", () => {
  it("posts feedback and returns id", async () => {
    mockFetch(201, { id: "f1" });
    const result = await submitFeedback("msg-id", 5, "Great answer");
    expect(result.id).toBe("f1");
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.message_id).toBe("msg-id");
    expect(body.rating).toBe(5);
    expect(body.comment).toBe("Great answer");
  });

  it("omits comment when not provided", async () => {
    mockFetch(201, { id: "f2" });
    await submitFeedback("msg-id", 3);
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.comment).toBeUndefined();
  });
});
