import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminEvaluationClient from "./AdminEvaluationClient";

const push = vi.fn();
const refresh = vi.fn();
const logout = vi.fn();
const cancelEvaluationRun = vi.fn();
const compareEvaluationRuns = vi.fn();
const createEvaluationQuestion = vi.fn();
const createEvaluationQuestionSet = vi.fn();
const createEvaluationRun = vi.fn();
const createEvaluationReviewAssignment = vi.fn();
const downloadEvaluationQuestionSet = vi.fn();
const downloadEvaluationRunReviews = vi.fn();
const executeEvaluationRun = vi.fn();
const getEvaluationReleaseGate = vi.fn();
const getEvaluationWorkerStatus = vi.fn();
const importEvaluationQuestions = vi.fn();
const importEvaluationReport = vi.fn();
const listAdminEvaluationReviewTasks = vi.fn();
const listAdminUsers = vi.fn();
const listEvaluationQuestions = vi.fn();
const listEvaluationQuestionSets = vi.fn();
const listEvaluationReviewAssignments = vi.fn();
const listEvaluationRunResults = vi.fn();
const listEvaluationRuns = vi.fn();
const saveEvaluationReview = vi.fn();
const setEvaluationReleaseDecision = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/api", () => ({
  cancelEvaluationRun: (...args: unknown[]) => cancelEvaluationRun(...args),
  compareEvaluationRuns: (...args: unknown[]) => compareEvaluationRuns(...args),
  createEvaluationQuestion: (...args: unknown[]) => createEvaluationQuestion(...args),
  createEvaluationQuestionSet: (...args: unknown[]) => createEvaluationQuestionSet(...args),
  createEvaluationRun: (...args: unknown[]) => createEvaluationRun(...args),
  createEvaluationReviewAssignment: (...args: unknown[]) => createEvaluationReviewAssignment(...args),
  downloadEvaluationQuestionSet: (...args: unknown[]) => downloadEvaluationQuestionSet(...args),
  downloadEvaluationRunReviews: (...args: unknown[]) => downloadEvaluationRunReviews(...args),
  executeEvaluationRun: (...args: unknown[]) => executeEvaluationRun(...args),
  getEvaluationReleaseGate: (...args: unknown[]) => getEvaluationReleaseGate(...args),
  getEvaluationWorkerStatus: (...args: unknown[]) => getEvaluationWorkerStatus(...args),
  importEvaluationQuestions: (...args: unknown[]) => importEvaluationQuestions(...args),
  importEvaluationReport: (...args: unknown[]) => importEvaluationReport(...args),
  listAdminEvaluationReviewTasks: (...args: unknown[]) => listAdminEvaluationReviewTasks(...args),
  listAdminUsers: (...args: unknown[]) => listAdminUsers(...args),
  listEvaluationQuestions: (...args: unknown[]) => listEvaluationQuestions(...args),
  listEvaluationQuestionSets: (...args: unknown[]) => listEvaluationQuestionSets(...args),
  listEvaluationReviewAssignments: (...args: unknown[]) => listEvaluationReviewAssignments(...args),
  listEvaluationRunResults: (...args: unknown[]) => listEvaluationRunResults(...args),
  listEvaluationRuns: (...args: unknown[]) => listEvaluationRuns(...args),
  logout: (...args: unknown[]) => logout(...args),
  saveEvaluationReview: (...args: unknown[]) => saveEvaluationReview(...args),
  setEvaluationReleaseDecision: (...args: unknown[]) => setEvaluationReleaseDecision(...args),
}));

const questionSet = {
  id: "set-1",
  name: "seed-v1",
  description: "Seed benchmark",
  status: "draft",
  created_by_user_id: "admin-1",
  created_at: "2026-06-20T10:00:00Z",
  updated_at: "2026-06-20T10:00:00Z",
  metadata: {},
  question_count: 1,
  label_complete_count: 0,
};

const question = {
  id: "question-1",
  question_set_id: "set-1",
  external_id: "q001",
  question: "Which interventions improve lipid accumulation in Yarrowia lipolytica?",
  category: "factual",
  difficulty: "medium",
  domain_fit: "core",
  expected_behavior: "answer",
  expected_keywords: ["lipid"],
  expected_pmids: ["12345678"],
  expected_dois: [],
  gold_answer_outline: "Mention TAG synthesis and nitrogen limitation.",
  supporting_evidence: [],
  requires_full_text: false,
  review_status: "expert_review_needed",
  expert_owner_user_id: null,
  notes: null,
  created_by_user_id: "admin-1",
  created_at: "2026-06-20T10:00:00Z",
  updated_at: "2026-06-20T10:00:00Z",
  archived_at: null,
};

const run = {
  id: "run-1",
  name: "retrieval smoke",
  mode: "retrieval",
  status: "completed",
  question_set_id: "set-1",
  started_by_user_id: "admin-1",
  started_at: "2026-06-20T10:00:00Z",
  completed_at: "2026-06-20T10:02:00Z",
  corpus_manifest_id: null,
  document_count: 100,
  chunk_count: 1000,
  embedding_model: "pubmedbert",
  chunk_size: 512,
  chunk_overlap: 64,
  retrieval_config: {},
  reranker_config: {},
  llm_provider: null,
  llm_model: null,
  prompt_version: null,
  git_commit: null,
  runner_version: "evaluation-runner/1",
  summary_metrics: {
    mean_recall_at_5: 0.2,
    mean_recall_at_10: 0.4,
    mean_recall_at_20: 0.6,
    mean_mrr_at_10: 0.3,
  },
  error_message: null,
  artifact_paths: {},
  metadata: {},
  created_at: "2026-06-20T10:00:00Z",
  updated_at: "2026-06-20T10:02:00Z",
};

const result = {
  id: "result-1",
  run_id: "run-1",
  question_id: "question-1",
  status: "completed",
  question_snapshot: {
    id: "q001",
    question: "Which interventions improve lipid accumulation in Yarrowia lipolytica?",
  },
  retrieved_sources: [],
  retrieved_pmids: ["12345678"],
  retrieved_dois: [],
  retrieved_chunk_ids: [],
  expected_pmids_present: true,
  expected_dois_present: null,
  coverage_status: "covered",
  recall_at_5: 0,
  recall_at_10: 1,
  recall_at_20: 1,
  mrr_at_10: 0.5,
  precision_at_k: 0.2,
  response_text: null,
  response_sources: [],
  latency_ms: 120,
  time_to_first_token_ms: null,
  failure_category: null,
  error_message: null,
  created_at: "2026-06-20T10:00:00Z",
  updated_at: "2026-06-20T10:02:00Z",
};

const assignment = {
  id: "assignment-1",
  run_result_id: "result-1",
  assigned_to_user_id: "reviewer-1",
  assigned_by_user_id: "admin-1",
  status: "assigned",
  due_at: null,
  created_at: "2026-06-20T10:00:00Z",
  updated_at: "2026-06-20T10:00:00Z",
  submitted_at: null,
  notes: null,
};

const reviewerUser = {
  id: "reviewer-uuid",
  email: "reviewer@example.org",
  full_name: "RLA Evaluator",
  role: "evaluator",
  is_active: true,
  token_limit: 100000,
  token_limit_reached: false,
  usage: {
    session_count: 0,
    user_message_count: 0,
    assistant_message_count: 0,
    prompt_token_count: 0,
    completion_token_count: 0,
    total_token_count: 0,
    last_active_at: null,
    avg_latency_ms: null,
  },
};

function setupApi() {
  listEvaluationQuestionSets.mockResolvedValue([questionSet]);
  listEvaluationQuestions.mockResolvedValue([question]);
  listEvaluationRuns.mockResolvedValue([run]);
  listEvaluationRunResults.mockResolvedValue([result]);
  listEvaluationReviewAssignments.mockResolvedValue([assignment]);
  listAdminEvaluationReviewTasks.mockResolvedValue([
    {
      assignment,
      result,
      review: null,
    },
  ]);
  listAdminUsers.mockResolvedValue([reviewerUser]);
  getEvaluationReleaseGate.mockResolvedValue({
    run_id: "run-1",
    status: "failed",
    checks: [{ metric: "mean_recall_at_20", value: 0.6, threshold: 0.75, passed: false }],
    release_decision: null,
  });
  getEvaluationWorkerStatus.mockResolvedValue({
    active: true,
    state: "polling",
    run_id: null,
    updated_at: "2026-06-20T10:00:00Z",
    seconds_since_heartbeat: 1,
    message: "Worker heartbeat is current.",
  });
  logout.mockResolvedValue(undefined);
}

describe("AdminEvaluationClient", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    logout.mockReset();
    createEvaluationQuestion.mockReset();
    createEvaluationQuestionSet.mockReset();
    createEvaluationRun.mockReset();
    createEvaluationReviewAssignment.mockReset();
    downloadEvaluationRunReviews.mockReset();
    cancelEvaluationRun.mockReset();
    compareEvaluationRuns.mockReset();
    downloadEvaluationQuestionSet.mockReset();
    executeEvaluationRun.mockReset();
    getEvaluationReleaseGate.mockReset();
    getEvaluationWorkerStatus.mockReset();
    importEvaluationQuestions.mockReset();
    importEvaluationReport.mockReset();
    listAdminEvaluationReviewTasks.mockReset();
    listAdminUsers.mockReset();
    listEvaluationQuestions.mockReset();
    listEvaluationQuestionSets.mockReset();
    listEvaluationReviewAssignments.mockReset();
    listEvaluationRunResults.mockReset();
    listEvaluationRuns.mockReset();
    saveEvaluationReview.mockReset();
    setEvaluationReleaseDecision.mockReset();
  });

  it("loads question sets, questions, runs, and run results", async () => {
    setupApi();

    render(<AdminEvaluationClient />);

    expect(await screen.findByText("Evaluation workflow")).toBeInTheDocument();
    expect(screen.getByText("seed-v1")).toBeInTheDocument();
    expect(await screen.findAllByText("q001")).not.toHaveLength(0);
    expect(screen.getAllByText("retrieval smoke").length).toBeGreaterThan(0);
    expect(await screen.findAllByText("covered")).not.toHaveLength(0);
    expect(listEvaluationQuestionSets).toHaveBeenCalled();
    expect(listEvaluationQuestions).toHaveBeenCalledWith("set-1");
    expect(listEvaluationRunResults).toHaveBeenCalledWith("run-1");
    expect(listEvaluationReviewAssignments).toHaveBeenCalledWith({ runId: "run-1" });
  });

  it("creates a question set", async () => {
    setupApi();
    createEvaluationQuestionSet.mockResolvedValue({
      ...questionSet,
      id: "set-2",
      name: "beta-v1",
      question_count: 0,
      label_complete_count: 0,
    });

    render(<AdminEvaluationClient />);

    fireEvent.change(await screen.findByLabelText("Question set name"), {
      target: { value: "beta-v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create set" }));

    await waitFor(() => {
      expect(createEvaluationQuestionSet).toHaveBeenCalledWith("beta-v1", null);
    });
    expect(await screen.findByText("Created question set beta-v1")).toBeInTheDocument();
  });

  it("imports an evaluation runner report", async () => {
    setupApi();
    importEvaluationReport.mockResolvedValue({
      run: { ...run, id: "run-2", name: "imported retrieval" },
      result_count: 1,
      linked_question_count: 1,
    });
    listEvaluationRuns
      .mockResolvedValueOnce([run])
      .mockResolvedValueOnce([{ ...run, id: "run-2", name: "imported retrieval" }, run]);

    render(<AdminEvaluationClient />);

    fireEvent.change(await screen.findByLabelText("Imported report name"), {
      target: { value: "imported retrieval" },
    });
    const file = new File(
      [
        JSON.stringify({
          metadata: { mode: "retrieval" },
          summary: { mode: "retrieval", mean_recall_at_20: 1 },
          results: [{ id: "q001", question: "Example", recall_at_20: 1 }],
        }),
      ],
      "eval.json",
      { type: "application/json" }
    );
    fireEvent.change(screen.getByLabelText("Import evaluation report"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(importEvaluationReport).toHaveBeenCalledWith({
        report: {
          metadata: { mode: "retrieval" },
          summary: { mode: "retrieval", mean_recall_at_20: 1 },
          results: [{ id: "q001", question: "Example", recall_at_20: 1 }],
        },
        name: "imported retrieval",
        question_set_id: "set-1",
        artifact_paths: { imported_filename: "eval.json" },
      });
    });
    expect(await screen.findByText("Imported 1 results, linked 1 to questions")).toBeInTheDocument();
  });

  it("queues a selected run for the evaluation worker", async () => {
    setupApi();
    executeEvaluationRun.mockResolvedValue({ ...run, status: "queued" });

    render(<AdminEvaluationClient />);

    fireEvent.click(await screen.findByRole("button", { name: "Queue run" }));

    await waitFor(() => {
      expect(executeEvaluationRun).toHaveBeenCalledWith("run-1");
    });
    expect(await screen.findByText("Queued retrieval evaluation for the worker")).toBeInTheDocument();
  });

  it("assigns and submits an expert review", async () => {
    setupApi();
    createEvaluationReviewAssignment.mockResolvedValue({
      ...assignment,
      id: "assignment-2",
      assigned_to_user_id: "reviewer-uuid",
    });
    saveEvaluationReview.mockResolvedValue({
      id: "review-1",
      assignment_id: "assignment-1",
      run_result_id: "result-1",
      reviewer_user_id: "admin-1",
      created_at: "2026-06-20T10:00:00Z",
      updated_at: "2026-06-20T10:00:00Z",
      submitted_at: "2026-06-20T10:00:00Z",
    });

    render(<AdminEvaluationClient />);

    fireEvent.change(await screen.findByLabelText("Reviewer"), {
      target: { value: "reviewer-uuid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() => {
      expect(createEvaluationReviewAssignment).toHaveBeenCalledWith({
        run_result_id: "result-1",
        assigned_to_user_id: "reviewer-uuid",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Submit review" }));
    await waitFor(() => {
      expect(saveEvaluationReview).toHaveBeenCalledWith(
        "assignment-2",
        expect.objectContaining({ correctness_score: 3 }),
        true
      );
    });
  });
});
