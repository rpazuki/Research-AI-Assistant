"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getAdminStats, getIngestionDocumentErrors, logout } from "@/lib/api";
import type { AdminStats, AdminStatsRecentJob, IngestionDocumentErrorReport } from "@/types";
import { formatBytes, formatCount, formatLastActive, formatLatency } from "./usage";

function formatPercent(value: number, total: number) {
  if (total <= 0) return "0%";
  return `${Math.round((value / total) * 100)}%`;
}

function formatYearRange(min: number | null, max: number | null) {
  if (!min && !max) return "Not available";
  if (min === max) return String(min);
  return `${min ?? "?"}-${max ?? "?"}`;
}

function formatDuration(job: AdminStatsRecentJob) {
  if (!job.started_at || !job.finished_at) return "Not available";
  const started = new Date(job.started_at).getTime();
  const finished = new Date(job.finished_at).getTime();
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) {
    return "Not available";
  }
  const seconds = Math.round((finished - started) / 1000);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes > 0 ? `${minutes}m ${remainder}s` : `${remainder}s`;
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

function BreakdownRow({
  label,
  count,
  total,
}: {
  label: string;
  count: number;
  total: number;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-gray-700">{label}</span>
        <span className="tabular-nums text-gray-600">
          {formatCount(count)} - {formatPercent(count, total)}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-blue-600"
          style={{ width: formatPercent(count, total) }}
        />
      </div>
    </div>
  );
}

function statusClass(status: string) {
  if (status === "succeeded") return "bg-green-50 text-green-700";
  if (status === "failed" || status === "cancelled") return "bg-red-50 text-red-700";
  if (status === "running") return "bg-blue-50 text-blue-700";
  if (status === "queued" || status === "cancel_requested") return "bg-yellow-50 text-yellow-700";
  return "bg-gray-100 text-gray-600";
}

export default function AdminStatsClient() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [documentErrorReports, setDocumentErrorReports] = useState<IngestionDocumentErrorReport[]>([]);
  const [selectedCachePath, setSelectedCachePath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadStats();
  }, []);

  async function loadStats() {
    try {
      setLoading(true);
      const [data, errorReports] = await Promise.all([
        getAdminStats(),
        getIngestionDocumentErrors(),
      ]);
      setStats(data);
      setDocumentErrorReports(errorReports);
      setSelectedCachePath((current) => {
        if (current && errorReports.some((report) => report.cache_path === current)) {
          return current;
        }
        return errorReports[0]?.cache_path ?? "";
      });
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load admin statistics");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  const overview = stats?.overview;
  const content = stats?.content;
  const totalDocuments = overview?.document_count ?? 0;
  const selectedErrorReport =
    documentErrorReports.find((report) => report.cache_path === selectedCachePath) ??
    documentErrorReports[0] ??
    null;

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Admin</h1>
            <p className="text-sm text-gray-500">Statistics</p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/admin" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Users
            </Link>
            <Link href="/admin/ingestion" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Ingestion
            </Link>
            <Link href="/admin/evaluation" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Evaluation
            </Link>
            <Link href="/chat" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Chat
            </Link>
            <button type="button" onClick={handleLogout} className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-6">
        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="rounded-lg border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
            Loading statistics...
          </div>
        ) : stats && overview && content ? (
          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Corpus documents"
                value={formatCount(overview.document_count)}
                hint={`${formatCount(overview.chunk_count)} chunks`}
              />
              <MetricCard
                label="Indexed tokens"
                value={formatCount(overview.indexed_token_count)}
                hint={`Years ${formatYearRange(overview.year_min, overview.year_max)}`}
              />
              <MetricCard
                label="Lab chat tokens"
                value={formatCount(overview.total_chat_token_count)}
                hint={`${formatCount(overview.question_count)} questions`}
              />
              <MetricCard
                label="Active users"
                value={formatCount(overview.active_user_count)}
                hint={`${formatCount(overview.user_count)} total users`}
              />
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <section className="rounded-lg border border-gray-200 bg-white p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-sm font-semibold text-gray-800">Corpus composition</h2>
                    <p className="mt-1 text-sm text-gray-500">
                      Ingested content grouped by what the database can identify.
                    </p>
                  </div>
                  <Link href="/admin/ingestion" className="text-sm font-medium text-blue-600 hover:underline">
                    Manage ingestion
                  </Link>
                </div>
                <div className="mt-5 space-y-4">
                  <BreakdownRow label="Abstract-only articles" count={content.abstract_only_documents} total={totalDocuments} />
                  <BreakdownRow label="Full-text articles" count={content.full_text_documents} total={totalDocuments} />
                  <BreakdownRow label="PDFs" count={content.pdf_documents} total={totalDocuments} />
                  <BreakdownRow label="Electronic lab notebooks" count={content.electronic_lab_notebook_documents} total={totalDocuments} />
                  <BreakdownRow label="Other documents" count={content.other_documents} total={totalDocuments} />
                </div>
              </section>

              <section className="rounded-lg border border-gray-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-gray-800">Usage and freshness</h2>
                <dl className="mt-5 grid gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-semibold uppercase text-gray-500">Prompt tokens</dt>
                    <dd className="mt-1 text-lg font-semibold text-gray-900">{formatCount(overview.prompt_token_count)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-gray-500">Completion tokens</dt>
                    <dd className="mt-1 text-lg font-semibold text-gray-900">{formatCount(overview.completion_token_count)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-gray-500">Assistant responses</dt>
                    <dd className="mt-1 text-lg font-semibold text-gray-900">{formatCount(overview.assistant_message_count)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-gray-500">Avg latency</dt>
                    <dd className="mt-1 text-lg font-semibold text-gray-900">{formatLatency(overview.avg_latency_ms)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-gray-500">Uploaded PDF folders</dt>
                    <dd className="mt-1 text-lg font-semibold text-gray-900">{formatCount(overview.upload_batch_count)}</dd>
                    <dd className="text-sm text-gray-500">{formatCount(overview.uploaded_pdf_file_count)} files - {formatBytes(overview.uploaded_pdf_bytes)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-gray-500">Last ingestion</dt>
                    <dd className="mt-1 text-lg font-semibold text-gray-900">{formatLastActive(overview.last_ingestion_at)}</dd>
                    <dd className="text-sm text-gray-500">{overview.last_corpus_name ?? "No manifest yet"}</dd>
                  </div>
                </dl>
              </section>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-200 px-4 py-3">
                  <h2 className="text-sm font-semibold text-gray-800">Sources</h2>
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50 text-left text-xs font-semibold uppercase text-gray-500">
                      <tr>
                        <th className="px-4 py-3">Source</th>
                        <th className="px-4 py-3 text-right">Documents</th>
                        <th className="px-4 py-3 text-right">Chunks</th>
                        <th className="px-4 py-3 text-right">Tokens</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {stats.sources.map((source) => (
                        <tr key={source.source}>
                          <td className="px-4 py-3 font-medium text-gray-900">{source.source}</td>
                          <td className="px-4 py-3 text-right tabular-nums text-gray-600">{formatCount(source.document_count)}</td>
                          <td className="px-4 py-3 text-right tabular-nums text-gray-600">{formatCount(source.chunk_count)}</td>
                          <td className="px-4 py-3 text-right tabular-nums text-gray-600">{formatCount(source.indexed_token_count)}</td>
                        </tr>
                      ))}
                      {stats.sources.length === 0 && (
                        <tr>
                          <td className="px-4 py-8 text-sm text-gray-500" colSpan={4}>No source data yet.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-200 px-4 py-3">
                  <h2 className="text-sm font-semibold text-gray-800">Ingestion jobs</h2>
                </div>
                <div className="grid gap-3 border-b border-gray-100 px-4 py-4 sm:grid-cols-3">
                  {stats.job_statuses.map((item) => (
                    <div key={item.status} className="rounded-md bg-gray-50 px-3 py-2">
                      <div className="text-xs font-medium uppercase text-gray-500">{item.status}</div>
                      <div className="mt-1 text-lg font-semibold text-gray-900">{formatCount(item.count)}</div>
                    </div>
                  ))}
                  {stats.job_statuses.length === 0 && (
                    <div className="text-sm text-gray-500">No ingestion jobs yet.</div>
                  )}
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50 text-left text-xs font-semibold uppercase text-gray-500">
                      <tr>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Mode</th>
                        <th className="px-4 py-3 text-right">Docs</th>
                        <th className="px-4 py-3">Duration</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {stats.recent_jobs.map((job) => (
                        <tr key={job.id}>
                          <td className="px-4 py-3">
                            <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${statusClass(job.status)}`}>{job.status}</span>
                          </td>
                          <td className="px-4 py-3 text-gray-600">
                            <div>{job.mode}</div>
                            <div className="text-xs text-gray-500">{job.source}</div>
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums text-gray-600">{job.document_count ?? "-"}</td>
                          <td className="px-4 py-3 text-gray-600">
                            <div>{formatDuration(job)}</div>
                            {job.error && <div className="mt-1 text-xs text-red-600">{job.error}</div>}
                          </td>
                        </tr>
                      ))}
                      {stats.recent_jobs.length === 0 && (
                        <tr>
                          <td className="px-4 py-8 text-sm text-gray-500" colSpan={4}>No recent jobs yet.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>

            <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
              <div className="flex flex-col gap-3 border-b border-gray-200 px-4 py-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-gray-800">Normalized document errors</h2>
                  <p className="mt-1 text-sm text-gray-500">
                    Contents of normalized/documents.errors.jsonl from ingestion cache folders.
                  </p>
                </div>
                {documentErrorReports.length > 1 && (
                  <label className="grid gap-1 text-sm md:min-w-80">
                    <span className="font-medium text-gray-700">Cache path</span>
                    <select
                      value={selectedErrorReport?.cache_path ?? ""}
                      onChange={(event) => setSelectedCachePath(event.target.value)}
                      className="rounded-md border border-gray-300 px-3 py-2"
                    >
                      {documentErrorReports.map((report) => (
                        <option key={report.cache_path} value={report.cache_path}>
                          {report.cache_path}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>

              {selectedErrorReport ? (
                <div className="grid gap-4 px-4 py-4">
                  <div className="grid gap-3 text-sm md:grid-cols-3">
                    <div className="rounded-md bg-gray-50 px-3 py-2">
                      <div className="text-xs font-semibold uppercase text-gray-500">Cache path</div>
                      <div className="mt-1 break-words text-gray-800">{selectedErrorReport.cache_path}</div>
                    </div>
                    <div className="rounded-md bg-gray-50 px-3 py-2">
                      <div className="text-xs font-semibold uppercase text-gray-500">Error file</div>
                      <div className="mt-1 break-words text-gray-800">{selectedErrorReport.error_file_path}</div>
                    </div>
                    <div className="rounded-md bg-gray-50 px-3 py-2">
                      <div className="text-xs font-semibold uppercase text-gray-500">Records</div>
                      <div className="mt-1 text-gray-800">
                        {selectedErrorReport.exists ? formatCount(selectedErrorReport.record_count) : "File not found"}
                      </div>
                    </div>
                  </div>

                  {selectedErrorReport.parse_errors.length > 0 && (
                    <div className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
                      {selectedErrorReport.parse_errors.join("; ")}
                    </div>
                  )}

                  {selectedErrorReport.records.length > 0 ? (
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-gray-950 p-3 text-xs leading-relaxed text-gray-100">
                      {selectedErrorReport.records
                        .map((record) => JSON.stringify(record, null, 2))
                        .join("\n\n")}
                    </pre>
                  ) : (
                    <div className="rounded-md border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">
                      {selectedErrorReport.exists
                        ? "No normalized document errors recorded in this cache."
                        : "No normalized document error file was found for this cache path."}
                    </div>
                  )}
                </div>
              ) : (
                <div className="px-4 py-8 text-sm text-gray-500">
                  No ingestion jobs with cache paths have been recorded yet.
                </div>
              )}
            </section>
          </div>
        ) : null}
      </section>
    </main>
  );
}
