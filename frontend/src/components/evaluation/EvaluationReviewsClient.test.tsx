import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import EvaluationReviewsClient from "./EvaluationReviewsClient";

const push = vi.fn();
const refresh = vi.fn();
const listMyEvaluationReviewTasks = vi.fn();
const logout = vi.fn();
const saveMyEvaluationReview = vi.fn();
const submitMyEvaluationReview = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/api", () => ({
  listMyEvaluationReviewTasks: (...args: unknown[]) => listMyEvaluationReviewTasks(...args),
  logout: (...args: unknown[]) => logout(...args),
  saveMyEvaluationReview: (...args: unknown[]) => saveMyEvaluationReview(...args),
  submitMyEvaluationReview: (...args: unknown[]) => submitMyEvaluationReview(...args),
}));

const task = {
  assignment: {
    id: "assignment-1",
    run_result_id: "result-1",
    assigned_to_user_id: "user-1",
    assigned_by_user_id: "admin-1",
    status: "assigned",
    due_at: null,
    created_at: "2026-06-20T10:00:00Z",
    updated_at: "2026-06-20T10:00:00Z",
    submitted_at: null,
    notes: null,
  },
  result: {
    id: "result-1",
    run_id: "run-1",
    question_id: "question-1",
    status: "completed",
    question_snapshot: {
      id: "q001",
      question: "Why is Yarrowia lipolytica useful for sustainable bioproduction?",
      gold_answer_outline: "Mention chassis traits and caveats.",
    },
    retrieved_sources: [{ pmid: "12345", title: "Example paper" }],
    retrieved_pmids: ["12345"],
    retrieved_dois: [],
    retrieved_chunk_ids: [],
    expected_pmids_present: true,
    expected_dois_present: null,
    coverage_status: "gold_retrieved",
    recall_at_5: 1,
    recall_at_10: 1,
    recall_at_20: 1,
    mrr_at_10: 1,
    precision_at_k: 0.2,
    response_text: "Yarrowia lipolytica is a useful non-conventional yeast.",
    response_sources: [{ pmid: "12345", title: "Example paper" }],
    latency_ms: 100,
    time_to_first_token_ms: null,
    failure_category: null,
    error_message: null,
    created_at: "2026-06-20T10:00:00Z",
    updated_at: "2026-06-20T10:00:00Z",
  },
  review: null,
};

describe("EvaluationReviewsClient", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    listMyEvaluationReviewTasks.mockReset();
    logout.mockReset();
    saveMyEvaluationReview.mockReset();
    submitMyEvaluationReview.mockReset();
    listMyEvaluationReviewTasks.mockResolvedValue([task]);
    logout.mockResolvedValue(undefined);
  });

  it("loads assigned review tasks", async () => {
    render(<EvaluationReviewsClient />);

    expect(await screen.findByText("Evaluation Reviews")).toBeInTheDocument();
    expect(screen.getAllByText("q001").length).toBeGreaterThan(0);
    expect(screen.getByText("Yarrowia lipolytica is a useful non-conventional yeast.")).toBeInTheDocument();
    expect(listMyEvaluationReviewTasks).toHaveBeenCalled();
  });

  it("submits a review", async () => {
    submitMyEvaluationReview.mockResolvedValue({
      id: "review-1",
      assignment_id: "assignment-1",
      run_result_id: "result-1",
      reviewer_user_id: "user-1",
      created_at: "2026-06-20T10:00:00Z",
      updated_at: "2026-06-20T10:00:00Z",
      submitted_at: "2026-06-20T10:00:00Z",
    });

    render(<EvaluationReviewsClient />);

    fireEvent.change(await screen.findByLabelText("Review feedback"), {
      target: { value: "Good answer, citation support is acceptable." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit review" }));

    await waitFor(() => {
      expect(submitMyEvaluationReview).toHaveBeenCalledWith(
        "assignment-1",
        expect.objectContaining({
          correctness_score: 3,
          free_text_feedback: "Good answer, citation support is acceptable.",
        })
      );
    });
    expect(await screen.findByText("Review submitted")).toBeInTheDocument();
  });
});
