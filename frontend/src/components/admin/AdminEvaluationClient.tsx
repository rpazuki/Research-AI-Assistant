"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  cancelEvaluationRun,
  compareEvaluationRuns,
  createEvaluationQuestion,
  createEvaluationQuestionSet,
  createEvaluationRun,
  createEvaluationReviewAssignment,
  downloadEvaluationQuestionSet,
  downloadEvaluationRunReviews,
  executeEvaluationRun,
  getEvaluationReleaseGate,
  getEvaluationWorkerStatus,
  importEvaluationQuestions,
  importEvaluationReport,
  listAdminEvaluationReviewTasks,
  listAdminUsers,
  listEvaluationQuestions,
  listEvaluationQuestionSets,
  listEvaluationReviewAssignments,
  listEvaluationRunResults,
  listEvaluationRuns,
  saveEvaluationReview,
  setEvaluationReleaseDecision,
} from "@/lib/api";
import type {
  AdminUserSummary,
  EvaluationComparison,
  EvaluationExpectedBehavior,
  EvaluationQuestion,
  EvaluationQuestionCategory,
  EvaluationQuestionCreate,
  EvaluationQuestionDifficulty,
  EvaluationQuestionDomainFit,
  EvaluationQuestionReviewStatus,
  EvaluationQuestionSet,
  EvaluationReleaseGate,
  EvaluationReviewAssignment,
  EvaluationReviewTask,
  EvaluationRun,
  EvaluationRunMode,
  EvaluationRunResult,
  EvaluationWorkerStatus,
} from "@/types";
import AdminHeader from "./AdminHeader";

const categories: EvaluationQuestionCategory[] = [
  "factual",
  "review",
  "methodology",
  "citation_stress",
  "out_of_scope",
];
const difficulties: EvaluationQuestionDifficulty[] = ["easy", "medium", "hard"];
const domainFits: EvaluationQuestionDomainFit[] = ["core", "adjacent", "out_of_scope", "remove"];
const expectedBehaviors: EvaluationExpectedBehavior[] = [
  "answer",
  "partial_answer_with_gap",
  "correct_false_premise",
  "refuse",
];
const reviewStatuses: EvaluationQuestionReviewStatus[] = [
  "draft",
  "expert_review_needed",
  "expert_reviewed",
  "label_complete",
  "retired",
];
const runModes: EvaluationRunMode[] = ["retrieval", "rag", "combined"];

function formatDate(value: string | null) {
  if (!value) return "Not yet";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatPercent(value: number, total: number) {
  if (total <= 0) return "0%";
  return `${Math.round((value / total) * 100)}%`;
}

function statusClass(status: string) {
  if (status === "completed" || status === "active" || status === "label_complete") {
    return "bg-green-50 text-green-700";
  }
  if (status === "failed" || status === "cancelled" || status === "retired") {
    return "bg-red-50 text-red-700";
  }
  if (status === "running" || status === "expert_reviewed") {
    return "bg-blue-50 text-blue-700";
  }
  if (status === "queued" || status === "expert_review_needed") {
    return "bg-yellow-50 text-yellow-700";
  }
  return "bg-gray-100 text-gray-700";
}

function numberList(value: string) {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function metricValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(value >= 10 ? 0 : 3);
  }
  if (typeof value === "string" && value) return value;
  return "-";
}

function getSnapshotText(result: EvaluationRunResult, key: string) {
  const value = result.question_snapshot[key];
  return typeof value === "string" ? value : "";
}

function getProgressMessage(run: EvaluationRun | null) {
  const value = run?.metadata.progress_message;
  return typeof value === "string" ? value : null;
}

function formatDelta(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(Math.abs(value) >= 10 ? 0 : 3)}`;
}

function scoreNumber(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function reviewerLabel(user: AdminUserSummary | undefined, fallbackId: string) {
  if (!user) return fallbackId;
  const name = user.full_name?.trim() || user.email;
  return `${name} (${user.role})`;
}

function averageScores(task: EvaluationReviewTask) {
  const review = task.review;
  if (!review) return null;
  const scores = [
    review.correctness_score,
    review.completeness_score,
    review.citation_support_score,
    review.grounding_score,
    review.usefulness_score,
  ].filter((value): value is number => typeof value === "number");
  if (scores.length === 0) return null;
  return scores.reduce((total, value) => total + value, 0) / scores.length;
}

function reviewAgreementText(tasks: EvaluationReviewTask[]) {
  if (tasks.length === 0) return "No review assignments";
  const submitted = tasks.filter((task) => task.review);
  const averages = submitted
    .map((task) => averageScores(task))
    .filter((value): value is number => typeof value === "number");
  if (averages.length < 2) {
    return `${submitted.length}/${tasks.length} submitted`;
  }
  const spread = Math.max(...averages) - Math.min(...averages);
  return `${submitted.length}/${tasks.length} submitted · score spread ${spread.toFixed(1)}`;
}

function isCategory(value: unknown): value is EvaluationQuestionCategory {
  return typeof value === "string" && categories.includes(value as EvaluationQuestionCategory);
}

function isDifficulty(value: unknown): value is EvaluationQuestionDifficulty {
  return typeof value === "string" && difficulties.includes(value as EvaluationQuestionDifficulty);
}

function isDomainFit(value: unknown): value is EvaluationQuestionDomainFit {
  return typeof value === "string" && domainFits.includes(value as EvaluationQuestionDomainFit);
}

function isExpectedBehavior(value: unknown): value is EvaluationExpectedBehavior {
  return typeof value === "string" && expectedBehaviors.includes(value as EvaluationExpectedBehavior);
}

function isReviewStatus(value: unknown): value is EvaluationQuestionReviewStatus {
  return typeof value === "string" && reviewStatuses.includes(value as EvaluationQuestionReviewStatus);
}

function stringsFromRecord(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter(Boolean);
}

function parseQuestionRecord(record: Record<string, unknown>): EvaluationQuestionCreate {
  const supportingEvidence =
    Array.isArray(record.supporting_evidence) ? record.supporting_evidence : record.supporting_snippets;

  return {
    external_id: String(record.external_id ?? record.id ?? "").trim(),
    question: String(record.question ?? "").trim(),
    category: isCategory(record.category) ? record.category : "factual",
    difficulty: isDifficulty(record.difficulty) ? record.difficulty : "medium",
    domain_fit: isDomainFit(record.domain_fit) ? record.domain_fit : "core",
    expected_behavior: isExpectedBehavior(record.expected_behavior)
      ? record.expected_behavior
      : "answer",
    expected_keywords: stringsFromRecord(record.expected_keywords),
    expected_pmids: stringsFromRecord(record.expected_pmids),
    expected_dois: stringsFromRecord(record.expected_dois),
    gold_answer_outline:
      typeof record.gold_answer_outline === "string" ? record.gold_answer_outline : null,
    supporting_evidence: Array.isArray(supportingEvidence)
      ? supportingEvidence.filter((item): item is Record<string, unknown> => {
          return item !== null && typeof item === "object" && !Array.isArray(item);
        })
      : [],
    requires_full_text: Boolean(record.requires_full_text),
    review_status: isReviewStatus(record.review_status) ? record.review_status : "draft",
    expert_owner_user_id:
      typeof record.expert_owner_user_id === "string" ? record.expert_owner_user_id : null,
    notes: typeof record.notes === "string" ? record.notes : null,
  };
}

function parseQuestionJsonl(text: string) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parsed = JSON.parse(line) as Record<string, unknown>;
      const question = parseQuestionRecord(parsed);
      if (!question.external_id || !question.question) {
        throw new Error(`Line ${index + 1} is missing id/external_id or question`);
      }
      return question;
    });
}

function downloadTextFile(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/x-ndjson" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function readTextFile(file: File) {
  if (typeof file.text === "function") {
    return file.text();
  }

  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
    reader.readAsText(file);
  });
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase text-gray-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-gray-900">{value}</div>
      {hint && <div className="mt-1 text-sm text-gray-500">{hint}</div>}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${statusClass(status)}`}>
      {status}
    </span>
  );
}

export default function AdminEvaluationClient() {
  const router = useRouter();
  const [questionSets, setQuestionSets] = useState<EvaluationQuestionSet[]>([]);
  const [questions, setQuestions] = useState<EvaluationQuestion[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [results, setResults] = useState<EvaluationRunResult[]>([]);
  const [assignments, setAssignments] = useState<EvaluationReviewAssignment[]>([]);
  const [reviewTasks, setReviewTasks] = useState<EvaluationReviewTask[]>([]);
  const [reviewerOptions, setReviewerOptions] = useState<AdminUserSummary[]>([]);
  const [releaseGate, setReleaseGate] = useState<EvaluationReleaseGate | null>(null);
  const [comparison, setComparison] = useState<EvaluationComparison | null>(null);
  const [workerStatus, setWorkerStatus] = useState<EvaluationWorkerStatus | null>(null);
  const [selectedQuestionSetId, setSelectedQuestionSetId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [baselineRunId, setBaselineRunId] = useState("");
  const [setName, setSetName] = useState("");
  const [setDescription, setSetDescription] = useState("");
  const [questionExternalId, setQuestionExternalId] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [questionCategory, setQuestionCategory] = useState<EvaluationQuestionCategory>("factual");
  const [questionDifficulty, setQuestionDifficulty] = useState<EvaluationQuestionDifficulty>("medium");
  const [questionDomainFit, setQuestionDomainFit] = useState<EvaluationQuestionDomainFit>("core");
  const [questionExpectedBehavior, setQuestionExpectedBehavior] =
    useState<EvaluationExpectedBehavior>("answer");
  const [questionReviewStatus, setQuestionReviewStatus] =
    useState<EvaluationQuestionReviewStatus>("draft");
  const [questionPmids, setQuestionPmids] = useState("");
  const [questionDois, setQuestionDois] = useState("");
  const [questionKeywords, setQuestionKeywords] = useState("");
  const [questionGoldAnswer, setQuestionGoldAnswer] = useState("");
  const [requiresFullText, setRequiresFullText] = useState(false);
  const [runName, setRunName] = useState("");
  const [runMode, setRunMode] = useState<EvaluationRunMode>("retrieval");
  const [reportName, setReportName] = useState("");
  const [reviewerUserId, setReviewerUserId] = useState("");
  const [releaseDecisionStatus, setReleaseDecisionStatus] =
    useState<"approved" | "waived" | "rejected">("approved");
  const [releaseDecisionNote, setReleaseDecisionNote] = useState("");
  const [selectedResultId, setSelectedResultId] = useState("");
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [reviewScores, setReviewScores] = useState({
    correctness: "3",
    completeness: "3",
    citationSupport: "3",
    grounding: "3",
    usefulness: "3",
    confidence: "3",
  });
  const [reviewFlags, setReviewFlags] = useState({
    hallucination: false,
    citationIssue: false,
    corpusGap: false,
    retrievalIssue: false,
    generationIssue: false,
    latencyIssue: false,
  });
  const [reviewFailureCategory, setReviewFailureCategory] = useState("");
  const [reviewFeedback, setReviewFeedback] = useState("");
  const [suggestedAnswer, setSuggestedAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedQuestionSet = useMemo(
    () => questionSets.find((questionSet) => questionSet.id === selectedQuestionSetId) ?? null,
    [questionSets, selectedQuestionSetId]
  );

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedRunId) ?? null,
    [runs, selectedRunId]
  );
  const reviewerById = useMemo(
    () => new Map(reviewerOptions.map((user) => [user.id, user])),
    [reviewerOptions]
  );
  const assignmentProgress = useMemo(
    () =>
      assignments.reduce<Record<string, number>>((counts, assignment) => {
        counts[assignment.status] = (counts[assignment.status] ?? 0) + 1;
        return counts;
      }, {}),
    [assignments]
  );
  const reviewTasksByResultId = useMemo(() => {
    const grouped = new Map<string, EvaluationReviewTask[]>();
    for (const task of reviewTasks) {
      const resultId = task.assignment.run_result_id;
      grouped.set(resultId, [...(grouped.get(resultId) ?? []), task]);
    }
    return grouped;
  }, [reviewTasks]);

  const latestRun = runs[0] ?? null;
  const labelCompleteTotal = questionSets.reduce(
    (total, questionSet) => total + questionSet.label_complete_count,
    0
  );
  const questionTotal = questionSets.reduce((total, questionSet) => total + questionSet.question_count, 0);

  useEffect(() => {
    void loadInitial();
  }, []);

  useEffect(() => {
    if (selectedQuestionSetId) {
      void loadQuestions(selectedQuestionSetId);
    } else {
      setQuestions([]);
    }
  }, [selectedQuestionSetId]);

  useEffect(() => {
    if (selectedRunId) {
      void loadResults(selectedRunId);
      void loadAssignments(selectedRunId);
      void loadReviewTasks(selectedRunId);
      void loadReleaseGate(selectedRunId);
    } else {
      setResults([]);
      setAssignments([]);
      setReviewTasks([]);
      setReleaseGate(null);
    }
  }, [selectedRunId]);

  async function loadInitial() {
    try {
      setLoading(true);
      const [setData, runData, workerData, userData] = await Promise.all([
        listEvaluationQuestionSets(),
        listEvaluationRuns(),
        getEvaluationWorkerStatus(),
        listAdminUsers(),
      ]);
      setQuestionSets(setData);
      setRuns(runData);
      setWorkerStatus(workerData);
      setReviewerOptions(userData.filter((user) => user.is_active && ["admin", "evaluator"].includes(user.role)));
      setSelectedQuestionSetId((current) => current || setData[0]?.id || "");
      setSelectedRunId((current) => current || runData[0]?.id || "");
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load evaluation workflow");
    } finally {
      setLoading(false);
    }
  }

  async function refreshRuns() {
    const runData = await listEvaluationRuns();
    setRuns(runData);
    setSelectedRunId((current) => current || runData[0]?.id || "");
  }

  async function loadQuestions(questionSetId: string) {
    try {
      const data = await listEvaluationQuestions(questionSetId);
      setQuestions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load questions");
    }
  }

  async function loadResults(runId: string) {
    try {
      const data = await listEvaluationRunResults(runId);
      setResults(data);
      setSelectedResultId((current) => current || data[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run results");
    }
  }

  async function loadAssignments(runId: string) {
    try {
      const data = await listEvaluationReviewAssignments({ runId });
      setAssignments(data);
      setSelectedAssignmentId((current) => current || data[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load review assignments");
    }
  }

  async function loadReviewTasks(runId: string) {
    try {
      const data = await listAdminEvaluationReviewTasks(runId);
      setReviewTasks(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load review task details");
    }
  }

  async function loadReleaseGate(runId: string) {
    try {
      const data = await getEvaluationReleaseGate(runId);
      setReleaseGate(data);
      const decision = data.release_decision;
      if (
        decision &&
        ["approved", "waived", "rejected"].includes(decision.status)
      ) {
        setReleaseDecisionStatus(decision.status);
        setReleaseDecisionNote(decision.note ?? "");
      }
    } catch {
      setReleaseGate(null);
    }
  }

  async function handleCreateQuestionSet() {
    if (!setName.trim()) return;
    try {
      setSubmitting(true);
      const questionSet = await createEvaluationQuestionSet(setName, setDescription || null);
      setQuestionSets((current) => [questionSet, ...current]);
      setSelectedQuestionSetId(questionSet.id);
      setSetName("");
      setSetDescription("");
      setMessage(`Created question set ${questionSet.name}`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create question set");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCreateQuestion() {
    if (!selectedQuestionSetId || !questionExternalId.trim() || !questionText.trim()) return;
    const payload: EvaluationQuestionCreate = {
      external_id: questionExternalId,
      question: questionText,
      category: questionCategory,
      difficulty: questionDifficulty,
      domain_fit: questionDomainFit,
      expected_behavior: questionExpectedBehavior,
      expected_keywords: numberList(questionKeywords),
      expected_pmids: numberList(questionPmids),
      expected_dois: numberList(questionDois),
      gold_answer_outline: questionGoldAnswer || null,
      supporting_evidence: [],
      requires_full_text: requiresFullText,
      review_status: questionReviewStatus,
      expert_owner_user_id: null,
      notes: null,
    };
    try {
      setSubmitting(true);
      const question = await createEvaluationQuestion(selectedQuestionSetId, payload);
      setQuestions((current) => [question, ...current]);
      setQuestionSets((current) =>
        current.map((questionSet) =>
          questionSet.id === selectedQuestionSetId
            ? {
                ...questionSet,
                question_count: questionSet.question_count + 1,
                label_complete_count:
                  question.review_status === "label_complete"
                    ? questionSet.label_complete_count + 1
                    : questionSet.label_complete_count,
              }
            : questionSet
        )
      );
      setQuestionExternalId("");
      setQuestionText("");
      setQuestionPmids("");
      setQuestionDois("");
      setQuestionKeywords("");
      setQuestionGoldAnswer("");
      setRequiresFullText(false);
      setMessage(`Added benchmark question ${question.external_id}`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create question");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleQuestionFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !selectedQuestionSetId) return;
    try {
      setSubmitting(true);
      const questionsToImport = parseQuestionJsonl(await readTextFile(file));
      const response = await importEvaluationQuestions(selectedQuestionSetId, questionsToImport, true);
      await loadQuestions(selectedQuestionSetId);
      const setData = await listEvaluationQuestionSets();
      setQuestionSets(setData);
      setMessage(
        `Imported ${response.created} new and ${response.updated} updated questions`
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import question JSONL");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleQuestionExport() {
    if (!selectedQuestionSetId) return;
    try {
      const exportFile = await downloadEvaluationQuestionSet(selectedQuestionSetId);
      downloadTextFile(exportFile.filename, exportFile.text);
      setMessage("Exported question set JSONL");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export question set");
    }
  }

  async function handleCreateRun() {
    if (!runName.trim()) return;
    try {
      setSubmitting(true);
      const run = await createEvaluationRun({
        name: runName,
        mode: runMode,
        status: "queued",
        question_set_id: selectedQuestionSetId || null,
      });
      setRuns((current) => [run, ...current]);
      setSelectedRunId(run.id);
      setRunName("");
      setMessage(`Created queued ${run.mode} run`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create run record");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExecuteRun() {
    if (!selectedRunId) return;
    try {
      setSubmitting(true);
      const run = await executeEvaluationRun(selectedRunId);
      setRuns((current) => current.map((item) => (item.id === run.id ? run : item)));
      setMessage(`Queued ${run.mode} evaluation for the worker`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to execute evaluation run");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancelRun() {
    if (!selectedRunId) return;
    try {
      setSubmitting(true);
      const run = await cancelEvaluationRun(selectedRunId);
      setRuns((current) => current.map((item) => (item.id === run.id ? run : item)));
      setMessage(`Cancelled ${run.name}`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel evaluation run");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAssignReviewer() {
    if (!selectedResultId || !reviewerUserId.trim()) return;
    try {
      setSubmitting(true);
      const assignment = await createEvaluationReviewAssignment({
        run_result_id: selectedResultId,
        assigned_to_user_id: reviewerUserId.trim(),
      });
      setAssignments((current) => [assignment, ...current]);
      setSelectedAssignmentId(assignment.id);
      setReviewerUserId("");
      if (selectedRunId) await loadReviewTasks(selectedRunId);
      setMessage("Created review assignment");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create review assignment");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSaveReview(submit: boolean) {
    if (!selectedAssignmentId) return;
    try {
      setSubmitting(true);
      await saveEvaluationReview(
        selectedAssignmentId,
        {
          correctness_score: scoreNumber(reviewScores.correctness),
          completeness_score: scoreNumber(reviewScores.completeness),
          citation_support_score: scoreNumber(reviewScores.citationSupport),
          grounding_score: scoreNumber(reviewScores.grounding),
          usefulness_score: scoreNumber(reviewScores.usefulness),
          reviewer_confidence: scoreNumber(reviewScores.confidence),
          hallucination_flag: reviewFlags.hallucination,
          citation_issue_flag: reviewFlags.citationIssue,
          corpus_gap_flag: reviewFlags.corpusGap,
          retrieval_issue_flag: reviewFlags.retrievalIssue,
          generation_issue_flag: reviewFlags.generationIssue,
          latency_issue_flag: reviewFlags.latencyIssue,
          recommended_failure_category: reviewFailureCategory || null,
          free_text_feedback: reviewFeedback || null,
          suggested_answer: suggestedAnswer || null,
        },
        submit
      );
      if (selectedRunId) {
        await loadAssignments(selectedRunId);
        await loadReviewTasks(selectedRunId);
      }
      setMessage(submit ? "Submitted review" : "Saved review draft");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save review");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCompareRuns() {
    if (!baselineRunId || !selectedRunId || baselineRunId === selectedRunId) return;
    try {
      setSubmitting(true);
      const data = await compareEvaluationRuns(baselineRunId, selectedRunId);
      setComparison(data);
      setMessage(`Compared runs: ${data.recommendation}`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to compare evaluation runs");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExportReviews(format: "csv" | "json") {
    if (!selectedRunId) return;
    try {
      const exportFile = await downloadEvaluationRunReviews(selectedRunId, format);
      downloadTextFile(exportFile.filename, exportFile.text);
      setMessage(`Exported review ${format.toUpperCase()}`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export reviews");
    }
  }

  async function handleReleaseDecision() {
    if (!selectedRunId) return;
    try {
      setSubmitting(true);
      const run = await setEvaluationReleaseDecision(selectedRunId, {
        status: releaseDecisionStatus,
        note: releaseDecisionNote.trim() || null,
      });
      setRuns((current) => current.map((item) => (item.id === run.id ? run : item)));
      await loadReleaseGate(selectedRunId);
      setMessage(`Recorded release decision: ${releaseDecisionStatus}`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save release decision");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReportFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      setSubmitting(true);
      const report = JSON.parse(await readTextFile(file)) as Record<string, unknown>;
      const response = await importEvaluationReport({
        report,
        name: reportName || null,
        question_set_id: selectedQuestionSetId || null,
        artifact_paths: { imported_filename: file.name },
      });
      await refreshRuns();
      setSelectedRunId(response.run.id);
      setReportName("");
      setMessage(
        `Imported ${response.result_count} results, linked ${response.linked_question_count} to questions`
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import evaluation report");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <AdminHeader subtitle="Evaluation workflow" maxWidthClass="max-w-7xl" />

      <section className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {message && (
          <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
            {message}
          </div>
        )}

        {loading ? (
          <div className="rounded-lg border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
            Loading evaluation workflow...
          </div>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Question sets"
                value={String(questionSets.length)}
                hint={`${questionTotal} total questions`}
              />
              <MetricCard
                label="Label complete"
                value={formatPercent(labelCompleteTotal, questionTotal)}
                hint={`${labelCompleteTotal} of ${questionTotal} questions`}
              />
              <MetricCard
                label="Evaluation runs"
                value={String(runs.length)}
                hint={latestRun ? `${latestRun.mode} ${latestRun.status}` : "No runs yet"}
              />
              <MetricCard
                label="Evaluation worker"
                value={workerStatus?.active ? "Active" : "Inactive"}
                hint={workerStatus ? `${workerStatus.state}: ${workerStatus.message}` : "Status unavailable"}
              />
            </div>

            <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
              <section className="space-y-6">
                <div className="rounded-lg border border-gray-200 bg-white">
                  <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
                    <div>
                      <h2 className="text-sm font-semibold text-gray-800">Question bank</h2>
                      <p className="text-sm text-gray-500">
                        Curate benchmark sets and labels before trusting metrics.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleQuestionExport}
                      disabled={!selectedQuestionSetId || submitting}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Export JSONL
                    </button>
                  </div>

                  <div className="grid gap-4 border-b border-gray-200 p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                    <div>
                      <label className="text-sm font-medium text-gray-700" htmlFor="question-set">
                        Active question set
                      </label>
                      <select
                        id="question-set"
                        value={selectedQuestionSetId}
                        onChange={(event) => setSelectedQuestionSetId(event.target.value)}
                        className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      >
                        <option value="">No question set</option>
                        {questionSets.map((questionSet) => (
                          <option key={questionSet.id} value={questionSet.id}>
                            {questionSet.name}
                          </option>
                        ))}
                      </select>
                      {selectedQuestionSet && (
                        <div className="mt-2 flex items-center gap-2 text-sm text-gray-600">
                          <StatusPill status={selectedQuestionSet.status} />
                          <span>
                            {selectedQuestionSet.label_complete_count} of{" "}
                            {selectedQuestionSet.question_count} label complete
                          </span>
                        </div>
                      )}
                    </div>
                    <div>
                      <label className="text-sm font-medium text-gray-700" htmlFor="question-import">
                        Import benchmark JSONL
                      </label>
                      <input
                        id="question-import"
                        type="file"
                        accept=".jsonl,.ndjson,application/x-ndjson"
                        onChange={handleQuestionFileChange}
                        disabled={!selectedQuestionSetId || submitting}
                        className="mt-1 block w-full text-sm text-gray-700 file:mr-3 file:rounded-md file:border-0 file:bg-blue-600 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-blue-700 disabled:opacity-60"
                      />
                    </div>
                  </div>

                  <div className="grid gap-4 border-b border-gray-200 p-4 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)_auto]">
                    <input
                      aria-label="Question set name"
                      value={setName}
                      onChange={(event) => setSetName(event.target.value)}
                      placeholder="New set name"
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <input
                      aria-label="Question set description"
                      value={setDescription}
                      onChange={(event) => setSetDescription(event.target.value)}
                      placeholder="Description"
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <button
                      type="button"
                      onClick={handleCreateQuestionSet}
                      disabled={!setName.trim() || submitting}
                      className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Create set
                    </button>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200 text-sm">
                      <thead className="bg-gray-50 text-left text-xs font-semibold uppercase text-gray-500">
                        <tr>
                          <th className="px-4 py-3">ID</th>
                          <th className="px-4 py-3">Question</th>
                          <th className="px-4 py-3">Type</th>
                          <th className="px-4 py-3">Labels</th>
                          <th className="px-4 py-3">Gold IDs</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {questions.slice(0, 30).map((question) => (
                          <tr key={question.id} className="align-top hover:bg-gray-50">
                            <td className="px-4 py-3 font-medium text-gray-900">
                              {question.external_id}
                            </td>
                            <td className="max-w-md px-4 py-3 text-gray-700">
                              <div className="line-clamp-3">{question.question}</div>
                              {question.gold_answer_outline && (
                                <div className="mt-2 line-clamp-2 text-xs text-gray-500">
                                  {question.gold_answer_outline}
                                </div>
                              )}
                            </td>
                            <td className="px-4 py-3 text-gray-600">
                              <div>{question.category}</div>
                              <div className="text-xs text-gray-500">{question.difficulty}</div>
                            </td>
                            <td className="px-4 py-3">
                              <StatusPill status={question.review_status} />
                              <div className="mt-2 text-xs text-gray-500">
                                {question.expected_behavior}
                              </div>
                            </td>
                            <td className="px-4 py-3 text-xs text-gray-600">
                              <div>{question.expected_pmids.length} PMIDs</div>
                              <div>{question.expected_dois.length} DOIs</div>
                            </td>
                          </tr>
                        ))}
                        {questions.length === 0 && (
                          <tr>
                            <td className="px-4 py-8 text-sm text-gray-500" colSpan={5}>
                              No questions in this set yet.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-white p-4">
                  <h2 className="text-sm font-semibold text-gray-800">Add one question</h2>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <input
                      aria-label="Question external ID"
                      value={questionExternalId}
                      onChange={(event) => setQuestionExternalId(event.target.value)}
                      placeholder="q021"
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <input
                      aria-label="Expected keywords"
                      value={questionKeywords}
                      onChange={(event) => setQuestionKeywords(event.target.value)}
                      placeholder="Expected keywords, comma separated"
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <select
                      aria-label="Question category"
                      value={questionCategory}
                      onChange={(event) => setQuestionCategory(event.target.value as EvaluationQuestionCategory)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      {categories.map((category) => (
                        <option key={category} value={category}>{category}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Question difficulty"
                      value={questionDifficulty}
                      onChange={(event) => setQuestionDifficulty(event.target.value as EvaluationQuestionDifficulty)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      {difficulties.map((difficulty) => (
                        <option key={difficulty} value={difficulty}>{difficulty}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Domain fit"
                      value={questionDomainFit}
                      onChange={(event) => setQuestionDomainFit(event.target.value as EvaluationQuestionDomainFit)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      {domainFits.map((domainFit) => (
                        <option key={domainFit} value={domainFit}>{domainFit}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Expected behavior"
                      value={questionExpectedBehavior}
                      onChange={(event) => setQuestionExpectedBehavior(event.target.value as EvaluationExpectedBehavior)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      {expectedBehaviors.map((behavior) => (
                        <option key={behavior} value={behavior}>{behavior}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Review status"
                      value={questionReviewStatus}
                      onChange={(event) => setQuestionReviewStatus(event.target.value as EvaluationQuestionReviewStatus)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      {reviewStatuses.map((status) => (
                        <option key={status} value={status}>{status}</option>
                      ))}
                    </select>
                    <label className="flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={requiresFullText}
                        onChange={(event) => setRequiresFullText(event.target.checked)}
                      />
                      Requires full text
                    </label>
                    <textarea
                      aria-label="Question text"
                      value={questionText}
                      onChange={(event) => setQuestionText(event.target.value)}
                      placeholder="Benchmark question"
                      rows={3}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm md:col-span-2"
                    />
                    <textarea
                      aria-label="Expected PMIDs"
                      value={questionPmids}
                      onChange={(event) => setQuestionPmids(event.target.value)}
                      placeholder="Expected PMIDs, comma or newline separated"
                      rows={2}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <textarea
                      aria-label="Expected DOIs"
                      value={questionDois}
                      onChange={(event) => setQuestionDois(event.target.value)}
                      placeholder="Expected DOIs, comma or newline separated"
                      rows={2}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <textarea
                      aria-label="Gold answer outline"
                      value={questionGoldAnswer}
                      onChange={(event) => setQuestionGoldAnswer(event.target.value)}
                      placeholder="Gold answer outline for human scoring"
                      rows={3}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm md:col-span-2"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={handleCreateQuestion}
                    disabled={!selectedQuestionSetId || !questionExternalId.trim() || !questionText.trim() || submitting}
                    className="mt-4 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Add question
                  </button>
                </div>
              </section>

              <section className="space-y-6">
                <div className="rounded-lg border border-gray-200 bg-white">
                  <div className="border-b border-gray-200 px-4 py-3">
                    <h2 className="text-sm font-semibold text-gray-800">Runs</h2>
                    <p className="text-sm text-gray-500">
                      Track queued records and imported CLI evaluation reports.
                    </p>
                  </div>
                  <div className="grid gap-3 border-b border-gray-200 p-4 md:grid-cols-[minmax(0,1fr)_160px_auto]">
                    <input
                      aria-label="Run name"
                      value={runName}
                      onChange={(event) => setRunName(event.target.value)}
                      placeholder="New evaluation run"
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <select
                      aria-label="Run mode"
                      value={runMode}
                      onChange={(event) => setRunMode(event.target.value as EvaluationRunMode)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      {runModes.map((mode) => (
                        <option key={mode} value={mode}>{mode}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={handleCreateRun}
                      disabled={!runName.trim() || submitting}
                      className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Create run
                    </button>
                  </div>
                  <div className="grid gap-3 border-b border-gray-200 p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                    <input
                      aria-label="Imported report name"
                      value={reportName}
                      onChange={(event) => setReportName(event.target.value)}
                      placeholder="Optional imported run name"
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <input
                      aria-label="Import evaluation report"
                      type="file"
                      accept=".json,application/json"
                      onChange={handleReportFileChange}
                      disabled={submitting}
                      className="block w-full text-sm text-gray-700 file:mr-3 file:rounded-md file:border-0 file:bg-blue-600 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-blue-700 disabled:opacity-60"
                    />
                  </div>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200 text-sm">
                      <thead className="bg-gray-50 text-left text-xs font-semibold uppercase text-gray-500">
                        <tr>
                          <th className="px-4 py-3">Run</th>
                          <th className="px-4 py-3">Mode</th>
                          <th className="px-4 py-3">Status</th>
                          <th className="px-4 py-3 text-right">Recall@20</th>
                          <th className="px-4 py-3">Started</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {runs.map((run) => (
                          <tr
                            key={run.id}
                            className={`cursor-pointer hover:bg-gray-50 ${run.id === selectedRunId ? "bg-blue-50" : ""}`}
                            onClick={() => setSelectedRunId(run.id)}
                          >
                            <td className="max-w-xs px-4 py-3 font-medium text-gray-900">
                              <div className="line-clamp-2">{run.name}</div>
                              <div className="text-xs text-gray-500">{run.embedding_model || "model unknown"}</div>
                            </td>
                            <td className="px-4 py-3 text-gray-600">{run.mode}</td>
                            <td className="px-4 py-3"><StatusPill status={run.status} /></td>
                            <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                              {metricValue(run.summary_metrics.mean_recall_at_20)}
                            </td>
                            <td className="px-4 py-3 text-gray-600">{formatDate(run.started_at)}</td>
                          </tr>
                        ))}
                        {runs.length === 0 && (
                          <tr>
                            <td className="px-4 py-8 text-sm text-gray-500" colSpan={5}>
                              No evaluation runs yet.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-white">
                  <div className="border-b border-gray-200 px-4 py-3">
                    <h2 className="text-sm font-semibold text-gray-800">Run detail</h2>
                    <p className="text-sm text-gray-500">
                      Inspect metrics, result coverage, and answer artifacts.
                    </p>
                  </div>
                  {selectedRun ? (
                    <>
                      <div className="grid gap-3 border-b border-gray-200 p-4 text-sm md:grid-cols-[auto_auto_auto_auto_1fr]">
                        <button
                          type="button"
                          onClick={handleExecuteRun}
                          disabled={submitting || ["queued", "running", "cancel_requested"].includes(selectedRun.status)}
                          className="rounded-md bg-blue-600 px-3 py-2 font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Queue run
                        </button>
                        <button
                          type="button"
                          onClick={handleCancelRun}
                          disabled={submitting || !["queued", "running", "cancel_requested"].includes(selectedRun.status)}
                          className="rounded-md border border-gray-300 px-3 py-2 font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleExportReviews("csv")}
                          disabled={submitting}
                          className="rounded-md border border-gray-300 px-3 py-2 font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Export CSV
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleExportReviews("json")}
                          disabled={submitting}
                          className="rounded-md border border-gray-300 px-3 py-2 font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Export JSON
                        </button>
                        <div className="rounded-md bg-gray-50 px-3 py-2 text-gray-600">
                          {getProgressMessage(selectedRun) || "No active progress message"}
                        </div>
                      </div>
                      <div className="grid gap-4 border-b border-gray-200 p-4 md:grid-cols-3">
                        <MetricCard
                          label="Recall@5"
                          value={metricValue(selectedRun.summary_metrics.mean_recall_at_5)}
                        />
                        <MetricCard
                          label="Recall@10"
                          value={metricValue(selectedRun.summary_metrics.mean_recall_at_10)}
                        />
                        <MetricCard
                          label="MRR@10"
                          value={metricValue(selectedRun.summary_metrics.mean_mrr_at_10)}
                        />
                      </div>
                      <div className="grid gap-3 border-b border-gray-200 p-4 text-sm md:grid-cols-2">
                        <div>
                          <div className="text-xs font-semibold uppercase text-gray-500">Run</div>
                          <div className="mt-1 text-gray-900">{selectedRun.name}</div>
                        </div>
                        <div>
                          <div className="text-xs font-semibold uppercase text-gray-500">Completed</div>
                          <div className="mt-1 text-gray-700">{formatDate(selectedRun.completed_at)}</div>
                        </div>
                        <div>
                          <div className="text-xs font-semibold uppercase text-gray-500">Documents</div>
                          <div className="mt-1 text-gray-700">
                            {selectedRun.document_count ?? "-"} docs, {selectedRun.chunk_count ?? "-"} chunks
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-semibold uppercase text-gray-500">LLM</div>
                          <div className="mt-1 text-gray-700">
                            {selectedRun.llm_provider || "-"} {selectedRun.llm_model || ""}
                          </div>
                        </div>
                      </div>
                      <div className="grid gap-4 border-b border-gray-200 p-4 lg:grid-cols-2">
                        <div>
                          <div className="flex items-center justify-between">
                            <h3 className="text-sm font-semibold text-gray-800">Release gate</h3>
                            {releaseGate && <StatusPill status={releaseGate.status} />}
                          </div>
                          <div className="mt-3 space-y-2">
                            {(releaseGate?.checks || []).map((check) => (
                              <div
                                key={String(check.metric)}
                                className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-2 text-sm"
                              >
                                <span className="font-medium text-gray-700">{String(check.metric)}</span>
                                <span className="text-gray-600">
                                  {metricValue(check.value)} / {metricValue(check.threshold)}
                                </span>
                              </div>
                            ))}
                            {!releaseGate && (
                              <div className="rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-500">
                                Gate appears after metrics are available.
                              </div>
                            )}
                            {releaseGate?.release_decision && (
                              <div className="rounded-md border border-gray-200 px-3 py-2 text-sm text-gray-700">
                                <div className="font-medium text-gray-900">
                                  Decision: {releaseGate.release_decision.status}
                                </div>
                                {releaseGate.release_decision.note && (
                                  <div className="mt-1 text-gray-600">
                                    {releaseGate.release_decision.note}
                                  </div>
                                )}
                              </div>
                            )}
                            <div className="grid gap-2 md:grid-cols-[minmax(0,140px)_1fr_auto]">
                              <select
                                aria-label="Release decision"
                                value={releaseDecisionStatus}
                                onChange={(event) =>
                                  setReleaseDecisionStatus(
                                    event.target.value as "approved" | "waived" | "rejected"
                                  )
                                }
                                className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                              >
                                <option value="approved">Approve</option>
                                <option value="waived">Waive</option>
                                <option value="rejected">Reject</option>
                              </select>
                              <input
                                aria-label="Release decision note"
                                value={releaseDecisionNote}
                                onChange={(event) => setReleaseDecisionNote(event.target.value)}
                                placeholder="Decision note"
                                className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                              />
                              <button
                                type="button"
                                onClick={handleReleaseDecision}
                                disabled={submitting}
                                className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                Save
                              </button>
                            </div>
                          </div>
                        </div>
                        <div>
                          <h3 className="text-sm font-semibold text-gray-800">Benchmark comparison</h3>
                          <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                            <select
                              aria-label="Baseline run"
                              value={baselineRunId}
                              onChange={(event) => setBaselineRunId(event.target.value)}
                              className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                            >
                              <option value="">Select baseline</option>
                              {runs.filter((run) => run.id !== selectedRun.id).map((run) => (
                                <option key={run.id} value={run.id}>{run.name}</option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={handleCompareRuns}
                              disabled={!baselineRunId || submitting}
                              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              Compare
                            </button>
                          </div>
                          {comparison && (
                            <div className="mt-3 rounded-md bg-gray-50 p-3">
                              <div className="text-xs font-semibold uppercase text-gray-500">
                                {comparison.recommendation}
                              </div>
                              <div className="mt-2 grid gap-2 text-sm md:grid-cols-2">
                                {comparison.metric_deltas.slice(0, 6).map((item) => (
                                  <div key={item.metric} className="flex justify-between gap-3">
                                    <span className="text-gray-600">{item.metric}</span>
                                    <span className="font-medium text-gray-900">
                                      {formatDelta(item.delta)}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="max-h-[520px] overflow-auto">
                        <table className="min-w-full divide-y divide-gray-200 text-sm">
                          <thead className="sticky top-0 bg-gray-50 text-left text-xs font-semibold uppercase text-gray-500">
                            <tr>
                              <th className="px-4 py-3">Question</th>
                              <th className="px-4 py-3">Coverage</th>
                              <th className="px-4 py-3 text-right">R@20</th>
                              <th className="px-4 py-3 text-right">MRR@10</th>
                              <th className="px-4 py-3">Result</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100">
                            {results.map((result) => (
                              <tr
                                key={result.id}
                                className={`cursor-pointer align-top hover:bg-gray-50 ${result.id === selectedResultId ? "bg-blue-50" : ""}`}
                                onClick={() => setSelectedResultId(result.id)}
                              >
                                <td className="max-w-sm px-4 py-3">
                                  <div className="font-medium text-gray-900">
                                    {getSnapshotText(result, "id") || result.question_id || "unlinked"}
                                  </div>
                                  <div className="mt-1 line-clamp-3 text-gray-600">
                                    {getSnapshotText(result, "question")}
                                  </div>
                                  {result.error_message && (
                                    <div className="mt-2 text-xs text-red-700">{result.error_message}</div>
                                  )}
                                </td>
                                <td className="px-4 py-3">
                                  <StatusPill status={result.coverage_status} />
                                  <div className="mt-2 text-xs text-gray-500">
                                    {result.retrieved_pmids.length} PMIDs, {result.retrieved_dois.length} DOIs
                                  </div>
                                </td>
                                <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                                  {metricValue(result.recall_at_20)}
                                </td>
                                <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                                  {metricValue(result.mrr_at_10)}
                                </td>
                                <td className="max-w-md px-4 py-3 text-gray-600">
                                  <div className="line-clamp-4">
                                    {result.response_text || result.failure_category || result.status}
                                  </div>
                                  {result.latency_ms !== null && (
                                    <div className="mt-2 text-xs text-gray-500">
                                      {result.latency_ms} ms latency
                                    </div>
                                  )}
                                  <div className="mt-2 text-xs text-gray-500">
                                    {reviewAgreementText(reviewTasksByResultId.get(result.id) ?? [])}
                                  </div>
                                </td>
                              </tr>
                            ))}
                            {results.length === 0 && (
                              <tr>
                                <td className="px-4 py-8 text-sm text-gray-500" colSpan={5}>
                                  No results recorded for this run.
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                      <div className="grid gap-4 border-t border-gray-200 p-4 lg:grid-cols-2">
                        <div>
                          <h3 className="text-sm font-semibold text-gray-800">Expert assignment</h3>
                          <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                            <select
                              aria-label="Reviewer"
                              value={reviewerUserId}
                              onChange={(event) => setReviewerUserId(event.target.value)}
                              className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                            >
                              <option value="">Select reviewer</option>
                              {reviewerOptions.map((user) => (
                                <option key={user.id} value={user.id}>
                                  {reviewerLabel(user, user.id)}
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={handleAssignReviewer}
                              disabled={!selectedResultId || !reviewerUserId.trim() || submitting}
                              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              Assign
                            </button>
                          </div>
                          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-gray-600 md:grid-cols-4">
                            {["assigned", "in_progress", "submitted", "returned"].map((status) => (
                              <div key={status} className="rounded-md bg-gray-50 px-3 py-2">
                                <div className="font-semibold text-gray-900">{assignmentProgress[status] ?? 0}</div>
                                <div>{status}</div>
                              </div>
                            ))}
                          </div>
                          <div className="mt-3 max-h-48 overflow-auto rounded-md border border-gray-200">
                            {assignments.map((assignment) => (
                              <button
                                key={assignment.id}
                                type="button"
                                onClick={() => setSelectedAssignmentId(assignment.id)}
                                className={`block w-full border-b border-gray-100 px-3 py-2 text-left text-sm last:border-b-0 hover:bg-gray-50 ${assignment.id === selectedAssignmentId ? "bg-blue-50" : ""}`}
                              >
                                <div className="font-medium text-gray-900">
                                  {reviewerLabel(
                                    reviewerById.get(assignment.assigned_to_user_id),
                                    assignment.assigned_to_user_id
                                  )}
                                </div>
                                <div className="text-xs text-gray-500">
                                  {assignment.status} · result {assignment.run_result_id.slice(0, 8)}
                                </div>
                              </button>
                            ))}
                            {assignments.length === 0 && (
                              <div className="px-3 py-4 text-sm text-gray-500">
                                No review assignments for this run.
                              </div>
                            )}
                          </div>
                        </div>
                        <div>
                          <h3 className="text-sm font-semibold text-gray-800">Review scoring</h3>
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
                                  value={reviewScores[key as keyof typeof reviewScores]}
                                  onChange={(event) =>
                                    setReviewScores((current) => ({
                                      ...current,
                                      [key]: event.target.value,
                                    }))
                                  }
                                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                                />
                              </label>
                            ))}
                          </div>
                          <div className="mt-3 grid gap-2 md:grid-cols-2">
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
                                  checked={reviewFlags[key as keyof typeof reviewFlags]}
                                  onChange={(event) =>
                                    setReviewFlags((current) => ({
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
                            value={reviewFailureCategory}
                            onChange={(event) => setReviewFailureCategory(event.target.value)}
                            placeholder="Recommended failure category"
                            className="mt-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                          />
                          <textarea
                            aria-label="Review feedback"
                            value={reviewFeedback}
                            onChange={(event) => setReviewFeedback(event.target.value)}
                            placeholder="Review feedback"
                            rows={3}
                            className="mt-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                          />
                          <textarea
                            aria-label="Suggested answer"
                            value={suggestedAnswer}
                            onChange={(event) => setSuggestedAnswer(event.target.value)}
                            placeholder="Suggested answer or correction"
                            rows={3}
                            className="mt-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                          />
                          <div className="mt-3 flex gap-2">
                            <button
                              type="button"
                              onClick={() => handleSaveReview(false)}
                              disabled={!selectedAssignmentId || submitting}
                              className="rounded-md border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              Save draft
                            </button>
                            <button
                              type="button"
                              onClick={() => handleSaveReview(true)}
                              disabled={!selectedAssignmentId || submitting}
                              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              Submit review
                            </button>
                          </div>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="px-4 py-8 text-sm text-gray-500">Select or import a run.</div>
                  )}
                </div>
              </section>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
