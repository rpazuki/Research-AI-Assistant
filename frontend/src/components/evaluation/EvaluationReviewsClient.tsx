"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  listMyEvaluationReviewTasks,
  logout,
  saveMyEvaluationReview,
  submitMyEvaluationReview,
} from "@/lib/api";
import type { EvaluationReviewPayload, EvaluationReviewTask } from "@/types";

function statusClass(status: string) {
  if (status === "submitted") return "bg-green-50 text-green-700";
  if (status === "returned") return "bg-red-50 text-red-700";
  if (status === "in_progress") return "bg-blue-50 text-blue-700";
  return "bg-yellow-50 text-yellow-700";
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${statusClass(status)}`}>
      {status}
    </span>
  );
}

function getSnapshotText(task: EvaluationReviewTask | null, key: string) {
  const value = task?.result.question_snapshot[key];
  return typeof value === "string" ? value : "";
}

function scoreNumber(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function metricValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(value >= 10 ? 0 : 3);
  }
  if (typeof value === "string" && value) return value;
  return "-";
}

export default function EvaluationReviewsClient() {
  const router = useRouter();
  const [tasks, setTasks] = useState<EvaluationReviewTask[]>([]);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [scores, setScores] = useState({
    correctness: "3",
    completeness: "3",
    citationSupport: "3",
    grounding: "3",
    usefulness: "3",
    confidence: "3",
  });
  const [flags, setFlags] = useState({
    hallucination: false,
    citationIssue: false,
    corpusGap: false,
    retrievalIssue: false,
    generationIssue: false,
    latencyIssue: false,
  });
  const [failureCategory, setFailureCategory] = useState("");
  const [feedback, setFeedback] = useState("");
  const [suggestedAnswer, setSuggestedAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedTask = useMemo(
    () => tasks.find((task) => task.assignment.id === selectedAssignmentId) ?? tasks[0] ?? null,
    [tasks, selectedAssignmentId]
  );

  const pendingCount = tasks.filter((task) => task.assignment.status !== "submitted").length;

  useEffect(() => {
    void loadTasks();
  }, []);

  useEffect(() => {
    if (!selectedTask) return;
    const review = selectedTask.review;
    if (!review) return;
    setScores({
      correctness: String(review.correctness_score ?? 3),
      completeness: String(review.completeness_score ?? 3),
      citationSupport: String(review.citation_support_score ?? 3),
      grounding: String(review.grounding_score ?? 3),
      usefulness: String(review.usefulness_score ?? 3),
      confidence: String(review.reviewer_confidence ?? 3),
    });
    setFlags({
      hallucination: Boolean(review.hallucination_flag),
      citationIssue: Boolean(review.citation_issue_flag),
      corpusGap: Boolean(review.corpus_gap_flag),
      retrievalIssue: Boolean(review.retrieval_issue_flag),
      generationIssue: Boolean(review.generation_issue_flag),
      latencyIssue: Boolean(review.latency_issue_flag),
    });
    setFailureCategory(review.recommended_failure_category || "");
    setFeedback(review.free_text_feedback || "");
    setSuggestedAnswer(review.suggested_answer || "");
  }, [selectedTask]);

  async function loadTasks() {
    try {
      setLoading(true);
      const data = await listMyEvaluationReviewTasks();
      setTasks(data);
      setSelectedAssignmentId((current) => current || data[0]?.assignment.id || "");
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load evaluation reviews");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  function buildPayload(): EvaluationReviewPayload {
    return {
      correctness_score: scoreNumber(scores.correctness),
      completeness_score: scoreNumber(scores.completeness),
      citation_support_score: scoreNumber(scores.citationSupport),
      grounding_score: scoreNumber(scores.grounding),
      usefulness_score: scoreNumber(scores.usefulness),
      reviewer_confidence: scoreNumber(scores.confidence),
      hallucination_flag: flags.hallucination,
      citation_issue_flag: flags.citationIssue,
      corpus_gap_flag: flags.corpusGap,
      retrieval_issue_flag: flags.retrievalIssue,
      generation_issue_flag: flags.generationIssue,
      latency_issue_flag: flags.latencyIssue,
      recommended_failure_category: failureCategory || null,
      free_text_feedback: feedback || null,
      suggested_answer: suggestedAnswer || null,
    };
  }

  async function handleSave(submit: boolean) {
    if (!selectedTask) return;
    try {
      setSubmitting(true);
      if (submit) {
        await submitMyEvaluationReview(selectedTask.assignment.id, buildPayload());
      } else {
        await saveMyEvaluationReview(selectedTask.assignment.id, buildPayload());
      }
      await loadTasks();
      setMessage(submit ? "Review submitted" : "Review draft saved");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save review");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Evaluation Reviews</h1>
            <p className="text-sm text-gray-500">{pendingCount} pending assignments</p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/chat" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Chat
            </Link>
            <button type="button" onClick={handleLogout} className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl space-y-4 px-6 py-6">
        {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        {message && <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">{message}</div>}

        {loading ? (
          <div className="rounded-lg border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
            Loading assigned reviews...
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
            <aside className="rounded-lg border border-gray-200 bg-white">
              <div className="border-b border-gray-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-gray-800">My queue</h2>
              </div>
              <div className="max-h-[720px] overflow-auto">
                {tasks.map((task) => (
                  <button
                    key={task.assignment.id}
                    type="button"
                    onClick={() => setSelectedAssignmentId(task.assignment.id)}
                    className={`block w-full border-b border-gray-100 px-4 py-3 text-left last:border-b-0 hover:bg-gray-50 ${task.assignment.id === selectedTask?.assignment.id ? "bg-blue-50" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-medium text-gray-900">
                        {getSnapshotText(task, "id") || task.result.id}
                      </div>
                      <StatusPill status={task.assignment.status} />
                    </div>
                    <div className="mt-2 line-clamp-3 text-sm text-gray-600">
                      {getSnapshotText(task, "question")}
                    </div>
                  </button>
                ))}
                {tasks.length === 0 && (
                  <div className="px-4 py-8 text-sm text-gray-500">
                    No review assignments are currently assigned to you.
                  </div>
                )}
              </div>
            </aside>

            <section className="space-y-4">
              {selectedTask ? (
                <>
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h2 className="text-sm font-semibold text-gray-800">
                          {getSnapshotText(selectedTask, "id") || "Evaluation result"}
                        </h2>
                        <p className="mt-1 text-sm text-gray-600">
                          {getSnapshotText(selectedTask, "question")}
                        </p>
                      </div>
                      <StatusPill status={selectedTask.assignment.status} />
                    </div>
                    <div className="mt-4 grid gap-3 text-sm md:grid-cols-3">
                      <div className="rounded-md bg-gray-50 px-3 py-2">
                        <div className="text-xs font-semibold uppercase text-gray-500">Coverage</div>
                        <div className="mt-1 text-gray-900">{selectedTask.result.coverage_status}</div>
                      </div>
                      <div className="rounded-md bg-gray-50 px-3 py-2">
                        <div className="text-xs font-semibold uppercase text-gray-500">Recall@20</div>
                        <div className="mt-1 text-gray-900">{metricValue(selectedTask.result.recall_at_20)}</div>
                      </div>
                      <div className="rounded-md bg-gray-50 px-3 py-2">
                        <div className="text-xs font-semibold uppercase text-gray-500">Latency</div>
                        <div className="mt-1 text-gray-900">{metricValue(selectedTask.result.latency_ms)} ms</div>
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="rounded-lg border border-gray-200 bg-white p-4">
                      <h3 className="text-sm font-semibold text-gray-800">Generated answer</h3>
                      <div className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-sm text-gray-700">
                        {selectedTask.result.response_text || selectedTask.result.failure_category || selectedTask.result.status}
                      </div>
                      <h3 className="mt-4 text-sm font-semibold text-gray-800">Gold outline</h3>
                      <div className="mt-3 whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-sm text-gray-700">
                        {getSnapshotText(selectedTask, "gold_answer_outline") || "No gold outline recorded."}
                      </div>
                      <h3 className="mt-4 text-sm font-semibold text-gray-800">Sources</h3>
                      <div className="mt-3 space-y-2">
                        {(selectedTask.result.response_sources.length ? selectedTask.result.response_sources : selectedTask.result.retrieved_sources).slice(0, 5).map((source, index) => (
                          <div key={index} className="rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-700">
                            <div className="font-medium">{String(source.title || source.pmid || source.doi || `Source ${index + 1}`)}</div>
                            <div className="text-xs text-gray-500">
                              PMID {String(source.pmid || "-")} · DOI {String(source.doi || "-")}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="rounded-lg border border-gray-200 bg-white p-4">
                      <h3 className="text-sm font-semibold text-gray-800">Your review</h3>
                      <div className="mt-3 grid gap-2 md:grid-cols-3">
                        {[
                          ["correctness", "Correctness"],
                          ["completeness", "Completeness"],
                          ["citationSupport", "Citations"],
                          ["grounding", "Grounding"],
                          ["usefulness", "Usefulness"],
                          ["confidence", "Confidence"],
                        ].map(([key, label]) => (
                          <label key={key} className="text-xs font-medium text-gray-600">
                            {label}
                            <input
                              aria-label={`${label} score`}
                              type="number"
                              min={1}
                              max={5}
                              value={scores[key as keyof typeof scores]}
                              onChange={(event) =>
                                setScores((current) => ({
                                  ...current,
                                  [key]: event.target.value,
                                }))
                              }
                              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                            />
                          </label>
                        ))}
                      </div>
                      <div className="mt-4 grid gap-2 md:grid-cols-2">
                        {[
                          ["hallucination", "Hallucination"],
                          ["citationIssue", "Citation issue"],
                          ["corpusGap", "Corpus gap"],
                          ["retrievalIssue", "Retrieval issue"],
                          ["generationIssue", "Generation issue"],
                          ["latencyIssue", "Latency issue"],
                        ].map(([key, label]) => (
                          <label key={key} className="flex items-center gap-2 text-sm text-gray-700">
                            <input
                              type="checkbox"
                              checked={flags[key as keyof typeof flags]}
                              onChange={(event) =>
                                setFlags((current) => ({
                                  ...current,
                                  [key]: event.target.checked,
                                }))
                              }
                            />
                            {label}
                          </label>
                        ))}
                      </div>
                      <input
                        aria-label="Recommended failure category"
                        value={failureCategory}
                        onChange={(event) => setFailureCategory(event.target.value)}
                        placeholder="Recommended failure category"
                        className="mt-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      />
                      <textarea
                        aria-label="Review feedback"
                        value={feedback}
                        onChange={(event) => setFeedback(event.target.value)}
                        placeholder="What should be fixed or trusted?"
                        rows={4}
                        className="mt-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      />
                      <textarea
                        aria-label="Suggested answer"
                        value={suggestedAnswer}
                        onChange={(event) => setSuggestedAnswer(event.target.value)}
                        placeholder="Optional corrected answer"
                        rows={4}
                        className="mt-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      />
                      <div className="mt-4 flex gap-2">
                        <button
                          type="button"
                          onClick={() => handleSave(false)}
                          disabled={submitting}
                          className="rounded-md border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Save draft
                        </button>
                        <button
                          type="button"
                          onClick={() => handleSave(true)}
                          disabled={submitting}
                          className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Submit review
                        </button>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="rounded-lg border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
                  Select an assigned review.
                </div>
              )}
            </section>
          </div>
        )}
      </section>
    </main>
  );
}
