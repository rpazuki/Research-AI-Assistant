import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminStatsClient from "./AdminStatsClient";

const push = vi.fn();
const refresh = vi.fn();
const getAdminStats = vi.fn();
const logout = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/api", () => ({
  getAdminStats: (...args: unknown[]) => getAdminStats(...args),
  logout: (...args: unknown[]) => logout(...args),
}));

const stats = {
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
  sources: [
    {
      source: "pubmed",
      document_count: 10,
      chunk_count: 30,
      indexed_token_count: 6000,
    },
    {
      source: "pdf",
      document_count: 4,
      chunk_count: 20,
      indexed_token_count: 3000,
    },
  ],
  job_statuses: [
    { status: "succeeded", count: 2 },
    { status: "failed", count: 1 },
  ],
  recent_jobs: [
    {
      id: "job-1",
      status: "succeeded",
      source: "pubmed_abstract",
      mode: "incremental",
      document_count: 17,
      chunk_count: 71,
      created_at: "2026-06-01T09:00:00Z",
      started_at: "2026-06-01T09:01:00Z",
      finished_at: "2026-06-01T09:05:30Z",
      progress_message: "Succeeded",
      error: null,
    },
  ],
};

describe("AdminStatsClient", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    getAdminStats.mockReset();
    logout.mockReset();
  });

  it("renders corpus, usage, source, and ingestion statistics", async () => {
    getAdminStats.mockResolvedValue(stats);

    render(<AdminStatsClient />);

    await waitFor(() => {
      expect(screen.getByText("Corpus documents")).toBeInTheDocument();
    });
    expect(screen.getAllByText("17").length).toBeGreaterThan(0);
    expect(screen.getByText("71 chunks")).toBeInTheDocument();
    expect(screen.getByText("12,345")).toBeInTheDocument();
    expect(screen.getByText("1,200")).toBeInTheDocument();
    expect(screen.getByText("21 questions")).toBeInTheDocument();
    expect(screen.getByText("Abstract-only articles")).toBeInTheDocument();
    expect(screen.getByText("Full-text articles")).toBeInTheDocument();
    expect(screen.getByText("Electronic lab notebooks")).toBeInTheDocument();
    expect(screen.getByText("513 ms")).toBeInTheDocument();
    expect(screen.getByText("9 files - 2 KB")).toBeInTheDocument();
    expect(screen.getByText("rlalab-pubmed-v1")).toBeInTheDocument();
    expect(screen.getByText("pubmed")).toBeInTheDocument();
    expect(screen.getByText("pdf")).toBeInTheDocument();
    expect(screen.getByText("incremental")).toBeInTheDocument();
    expect(screen.getByText("4m 30s")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage ingestion" })).toHaveAttribute(
      "href",
      "/admin/ingestion"
    );
  });

  it("redirects to login when unauthorized", async () => {
    getAdminStats.mockRejectedValue(new Error("Unauthorized"));

    render(<AdminStatsClient />);

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/login");
    });
  });
});
