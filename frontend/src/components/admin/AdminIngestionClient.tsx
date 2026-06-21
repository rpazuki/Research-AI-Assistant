"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  cancelIngestionJob,
  createIngestionJob,
  getIngestionDefaults,
  getIngestionWorkerStatus,
  listIngestionConfigs,
  listIngestionJobs,
  listIngestionUploads,
  logout,
  uploadIngestionPdfFolder,
} from "@/lib/api";
import type {
  IngestionConfigSummary,
  IngestionDefaults,
  IngestionJob,
  IngestionJobMode,
  IngestionUploadBatch,
  IngestionWorkerStatus,
} from "@/types";

function formatDate(value: string | null) {
  if (!value) return "Not yet";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDuration(startedAt: string | null, finishedAt: string | null) {
  if (!startedAt || !finishedAt) return "Not available";
  const started = new Date(startedAt).getTime();
  const finished = new Date(finishedAt).getTime();
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) {
    return "Not available";
  }
  const totalSeconds = Math.round((finished - started) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function statusClass(status: IngestionJob["status"]) {
  if (status === "succeeded") return "bg-green-50 text-green-700";
  if (status === "failed" || status === "cancelled") return "bg-red-50 text-red-700";
  if (status === "running") return "bg-blue-50 text-blue-700";
  return "bg-gray-100 text-gray-700";
}

function formatHeartbeatAge(seconds: number | null) {
  if (seconds === null) return "unknown";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function jobModeDetail(job: IngestionJob) {
  if (job.mode === "test_year") return job.year ? `Year ${job.year}` : "Year not set";
  if (job.mode === "incremental") return job.from_date ? `From ${job.from_date}` : "From date not set";
  if (job.mode === "local_only") return "Cache only";
  if (job.mode === "queue_only") return "Queue from cache";
  return "Complete configured range";
}

function formatOptionValue(value: unknown) {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value === null || value === undefined) return "not set";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function DetailItem({
  label,
  value,
  className = "",
}: {
  label: string;
  value: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="text-xs font-semibold uppercase text-gray-500">{label}</div>
      <div className="mt-1 break-words text-sm text-gray-800">{value || "-"}</div>
    </div>
  );
}

function LabelWithTooltip({
  label,
  description,
}: {
  label: string;
  description: string;
}) {
  return (
    <span className="flex items-center gap-1 font-medium text-gray-700">
      <span>{label}</span>
      <span aria-hidden="true" className="group relative inline-flex">
        <span
          className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-gray-300 bg-white text-[10px] font-semibold leading-none text-gray-500"
        >
          ?
        </span>
        <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-64 -translate-x-1/2 rounded-md border border-gray-200 bg-gray-950 px-3 py-2 text-xs font-normal leading-relaxed text-white shadow-lg group-hover:block group-focus-within:block">
          {description}
        </span>
      </span>
    </span>
  );
}

export default function AdminIngestionClient() {
  const router = useRouter();
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const [configs, setConfigs] = useState<IngestionConfigSummary[]>([]);
  const [uploads, setUploads] = useState<IngestionUploadBatch[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [workerStatus, setWorkerStatus] = useState<IngestionWorkerStatus | null>(null);
  const [configName, setConfigName] = useState("");
  const [mode, setMode] = useState<IngestionJobMode>("full");
  const [fromDate, setFromDate] = useState("");
  const [year, setYear] = useState("");
  const [cachePath, setCachePath] = useState("");
  const [selectedUploadId, setSelectedUploadId] = useState("");
  const [writeQueue, setWriteQueue] = useState(false);
  const [includeCachedFulltext, setIncludeCachedFulltext] = useState(false);
  const [uploadName, setUploadName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedJobIds, setExpandedJobIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "");
    folderInputRef.current?.setAttribute("directory", "");
    void loadAll();
    const timer = window.setInterval(() => void refreshJobs(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const selectedConfig = useMemo(
    () => configs.find((config) => config.name === configName) ?? null,
    [configs, configName]
  );

  async function loadAll() {
    try {
      setLoading(true);
      const [configData, defaultsData, uploadData, jobData, workerData] = await Promise.all([
        listIngestionConfigs(),
        getIngestionDefaults(),
        listIngestionUploads(),
        listIngestionJobs(),
        getIngestionWorkerStatus(),
      ]);
      setConfigs(configData);
      setUploads(uploadData);
      setJobs(jobData);
      setWorkerStatus(workerData);
      applyDefaults(defaultsData, configData);
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load ingestion controls");
    } finally {
      setLoading(false);
    }
  }

  function applyDefaults(
    defaults: IngestionDefaults,
    availableConfigs: IngestionConfigSummary[]
  ) {
    const defaultConfigExists = availableConfigs.some(
      (config) => config.name === defaults.config_name
    );
    setConfigName((current) =>
      current || (defaultConfigExists ? defaults.config_name : availableConfigs[0]?.name || "")
    );
    setMode(defaults.mode || "full");
    setCachePath((current) => current || defaults.cache_path || "");
    setWriteQueue(defaults.write_acquisition_queue);
    setIncludeCachedFulltext(defaults.include_cached_fulltext);
  }

  async function refreshJobs() {
    try {
      const [jobData, workerData] = await Promise.all([
        listIngestionJobs(),
        getIngestionWorkerStatus(),
      ]);
      setJobs(jobData);
      setWorkerStatus(workerData);
    } catch {
      // Keep the current table during transient polling failures.
    }
  }

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  async function handleUpload() {
    const files = Array.from(folderInputRef.current?.files ?? []);
    if (files.length === 0) {
      setError("Choose a folder or one or more PDF files first");
      return;
    }
    try {
      setUploading(true);
      const upload = await uploadIngestionPdfFolder(files, uploadName || undefined);
      setUploads((current) => [upload, ...current]);
      setSelectedUploadId(upload.id);
      setUploadName("");
      if (folderInputRef.current) folderInputRef.current.value = "";
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload PDFs");
    } finally {
      setUploading(false);
    }
  }

  async function handleCreateJob() {
    if (!configName) return;
    try {
      setSubmitting(true);
      const job = await createIngestionJob({
        config_name: configName,
        mode,
        from_date: mode === "incremental" ? fromDate || null : null,
        year: mode === "test_year" && year ? Number(year) : null,
        cache_path: cachePath || null,
        pdf_upload_batch_id: selectedConfig?.supports_pdf_upload && selectedUploadId
          ? selectedUploadId
          : null,
        write_acquisition_queue: writeQueue,
        include_cached_fulltext: includeCachedFulltext,
      });
      setJobs((current) => [job, ...current]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create ingestion job");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel(jobId: string) {
    try {
      const updated = await cancelIngestionJob(jobId);
      setJobs((current) => current.map((job) => (job.id === jobId ? updated : job)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel job");
    }
  }

  function toggleJobDetails(jobId: string) {
    setExpandedJobIds((current) => {
      const next = new Set(current);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else {
        next.add(jobId);
      }
      return next;
    });
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Admin</h1>
            <p className="text-sm text-gray-500">Ingestion operations</p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/admin/ingestion/config" className="rounded-md border border-blue-200 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50">
              Config
            </Link>
            <Link href="/admin/ingestion/acquisition" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Acquisition
            </Link>
            <Link href="/admin" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Users
            </Link>
            <Link href="/admin/stats" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Stats
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

      <section className="mx-auto grid max-w-6xl gap-6 px-6 py-6">
        {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        {workerStatus?.active && (
          <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
            Ingestion worker active: {workerStatus.state}
          </div>
        )}

        {workerStatus && !workerStatus.active && workerStatus.state === "running" && (
          <div className="rounded-md border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
            Ingestion worker was running, but its heartbeat is stale
            {workerStatus.seconds_since_heartbeat !== null
              ? ` (${formatHeartbeatAge(workerStatus.seconds_since_heartbeat)} ago)`
              : ""}
            . The worker may be busy in a long indexing step; check the running job progress and Docker
            CPU usage before restarting it.
          </div>
        )}

        {workerStatus && !workerStatus.active && workerStatus.state !== "running" && (
          <div className="rounded-md border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
            Ingestion worker is not active. Queued jobs will not start until
            `python -m app.ingestion.worker` or the `ingestion-worker` Docker service is running.
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
          <div className="rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-gray-800">Queue ingestion job</h2>
            </div>
            <div className="grid gap-4 px-4 py-4 text-sm">
              <label className="grid gap-1">
                <LabelWithTooltip
                  label="Approved config"
                  description="TOML config from pipelines/configs that will be snapshotted and used for this ingestion job."
                />
                <select aria-label="Approved config" value={configName} onChange={(event) => setConfigName(event.target.value)} className="rounded-md border border-gray-300 px-3 py-2">
                  {configs.map((config) => (
                    <option key={config.name} value={config.name}>
                      {config.name} · {config.source}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1">
                <LabelWithTooltip
                  label="Mode"
                  description="Chooses whether the job runs the full configured corpus, a PubMed update, a one-year test, or cache-only workflows."
                />
                <select aria-label="Mode" value={mode} onChange={(event) => setMode(event.target.value as IngestionJobMode)} className="rounded-md border border-gray-300 px-3 py-2">
                  <option value="full">Full run</option>
                  <option value="incremental">Incremental PubMed update</option>
                  <option value="test_year">Single-year test</option>
                  <option value="local_only">Local-only re-index</option>
                  <option value="queue_only">Acquisition queue from cache</option>
                </select>
              </label>
              {mode === "incremental" && (
                <label className="grid gap-1">
                  <LabelWithTooltip
                    label="From date"
                    description="Publication date lower bound for incremental PubMed abstract ingestion."
                  />
                  <input aria-label="From date" type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} className="rounded-md border border-gray-300 px-3 py-2" />
                </label>
              )}
              {mode === "test_year" && (
                <label className="grid gap-1">
                  <LabelWithTooltip
                    label="Year"
                    description="Single publication year used to limit a PubMed test ingestion run."
                  />
                  <input aria-label="Year" type="number" min="1900" max="2100" value={year} onChange={(event) => setYear(event.target.value)} className="rounded-md border border-gray-300 px-3 py-2" />
                </label>
              )}
              <label className="grid gap-1">
                <LabelWithTooltip
                  label="Cache path"
                  description="Optional data/corpora path to append to, re-index from, or use when generating acquisition queues."
                />
                <input aria-label="Cache path" value={cachePath} onChange={(event) => setCachePath(event.target.value)} placeholder="data/corpora/rlalab-pubmed-v1/cumulative" className="rounded-md border border-gray-300 px-3 py-2" />
              </label>
              {selectedConfig?.supports_pdf_upload && (
                <label className="grid gap-1">
                  <LabelWithTooltip
                    label="PDF upload batch"
                    description="Previously staged PDFs that can override the selected PDF config folder for this job."
                  />
                  <select aria-label="PDF upload batch" value={selectedUploadId} onChange={(event) => setSelectedUploadId(event.target.value)} className="rounded-md border border-gray-300 px-3 py-2">
                    <option value="">Use config folder</option>
                    {uploads.map((upload) => (
                      <option key={upload.id} value={upload.id}>
                        {upload.name} · {upload.file_count} PDFs
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="flex items-center gap-2 text-gray-700">
                <input type="checkbox" checked={writeQueue} onChange={(event) => setWriteQueue(event.target.checked)} />
                <LabelWithTooltip
                  label="Write acquisition queue"
                  description="Writes DOI/PMCID full-text acquisition candidates into the selected cache reports folder."
                />
              </label>
              <label className="flex items-center gap-2 text-gray-700">
                <input type="checkbox" checked={includeCachedFulltext} onChange={(event) => setIncludeCachedFulltext(event.target.checked)} />
                <LabelWithTooltip
                  label="Include cached full text in queue"
                  description="Includes records that already have PMC full text cached, useful for refresh or audit review."
                />
              </label>
              <button type="button" disabled={loading || submitting || !configName} onClick={handleCreateJob} className="rounded-md bg-blue-600 px-3 py-2 font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300">
                {submitting ? "Queueing..." : "Queue job"}
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-gray-800">Stage PDF folder</h2>
            </div>
            <div className="grid gap-4 px-4 py-4 text-sm">
              <label className="grid gap-1">
                <LabelWithTooltip
                  label="Batch name"
                  description="Optional display name for this staged PDF upload set."
                />
                <input aria-label="Batch name" value={uploadName} onChange={(event) => setUploadName(event.target.value)} placeholder="Batch name" className="rounded-md border border-gray-300 px-3 py-2" />
              </label>
              <label className="grid gap-1">
                <LabelWithTooltip
                  label="PDF files"
                  description="Folder or individual PDFs to stage for local PDF ingestion; files are not acquired from publishers here."
                />
                <input aria-label="PDF files" ref={folderInputRef} type="file" multiple accept="application/pdf,.pdf" className="rounded-md border border-gray-300 px-3 py-2" />
              </label>
              <button type="button" disabled={uploading} onClick={handleUpload} className="rounded-md border border-blue-200 px-3 py-2 font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:text-gray-400">
                {uploading ? "Uploading..." : "Upload PDFs"}
              </button>
              <div className="text-xs text-gray-500">
                Uploads are staged for local PDF ingestion only; acquisition and access decisions remain separate.
              </div>
              <div className="max-h-40 overflow-auto rounded-md border border-gray-100">
                {uploads.map((upload) => (
                  <div key={upload.id} className="flex items-center justify-between border-b border-gray-100 px-3 py-2 last:border-b-0">
                    <span className="truncate font-medium text-gray-700">{upload.name}</span>
                    <span className="shrink-0 text-xs text-gray-500">{upload.file_count} · {formatBytes(upload.total_bytes)}</span>
                  </div>
                ))}
                {uploads.length === 0 && <div className="px-3 py-4 text-gray-500">No upload batches yet.</div>}
              </div>
            </div>
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-800">Jobs</h2>
            <span className="text-xs text-gray-500">{jobs.length} recent</span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-semibold uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">Details</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Mode</th>
                  <th className="px-4 py-3 text-right">Docs</th>
                  <th className="px-4 py-3 text-right">Chunks</th>
                  <th className="px-4 py-3">Progress</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {jobs.map((job) => {
                  const isExpanded = expandedJobIds.has(job.id);
                  const options = job.options ? Object.entries(job.options) : [];
                  return (
                    <Fragment key={job.id}>
                      <tr className="align-top hover:bg-gray-50">
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            aria-expanded={isExpanded}
                            aria-controls={`job-details-${job.id}`}
                            onClick={() => toggleJobDetails(job.id)}
                            className="flex h-7 w-7 items-center justify-center rounded-md border border-gray-300 text-sm font-semibold text-gray-700 hover:bg-gray-100"
                          >
                            <span aria-hidden="true">{isExpanded ? "^" : ">"}</span>
                            <span className="sr-only">{isExpanded ? "Collapse job details" : "Expand job details"}</span>
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${statusClass(job.status)}`}>{job.status}</span>
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          <div>{job.mode}</div>
                          <div className="mt-1 text-xs text-gray-500">{jobModeDetail(job)}</div>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-600">{job.document_count ?? "-"}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-600">{job.chunk_count ?? "-"}</td>
                        <td className="max-w-sm px-4 py-3 text-gray-600">
                          <div>{job.progress_message ?? "-"}</div>
                          {job.error && <div className="mt-1 text-xs text-red-600">{job.error}</div>}
                        </td>
                        <td className="px-4 py-3 text-gray-600">{formatDate(job.started_at)}</td>
                        <td className="px-4 py-3 text-right">
                          {(job.status === "queued" || job.status === "running") && (
                            <button type="button" onClick={() => void handleCancel(job.id)} className="text-sm font-medium text-red-600 hover:underline">
                              Cancel
                            </button>
                          )}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${job.id}-details`} id={`job-details-${job.id}`} className="bg-gray-50">
                          <td colSpan={8} className="px-4 py-4">
                            <div className="grid gap-4 rounded-md border border-gray-200 bg-white p-4 md:grid-cols-2 xl:grid-cols-4">
                              <DetailItem label="Config" value={job.config_name} />
                              <DetailItem label="Duration" value={formatDuration(job.started_at, job.finished_at)} />
                              <DetailItem label="Created" value={formatDate(job.created_at)} />
                              <DetailItem label="Updated" value={formatDate(job.updated_at)} />
                              <DetailItem label="Finished" value={formatDate(job.finished_at)} />
                              <DetailItem label="Requested range" value={jobModeDetail(job)} />
                              <DetailItem label="Source" value={job.source} />
                              <DetailItem label="Manifest" value={job.manifest_id ?? "Not created yet"} />
                              <DetailItem label="PDF upload batch" value={job.pdf_upload_batch_id ?? "None"} />
                              <DetailItem label="Cache path" value={job.cache_path ?? "Not set"} className="md:col-span-2 xl:col-span-4" />
                              <DetailItem label="Config path" value={job.config_path} className="md:col-span-2 xl:col-span-4" />
                              {options.length > 0 && (
                                <div className="md:col-span-2 xl:col-span-4">
                                  <div className="text-xs font-semibold uppercase text-gray-500">Options</div>
                                  <dl className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                                    {options.map(([key, value]) => (
                                      <div key={key} className="rounded-md bg-gray-50 px-3 py-2">
                                        <dt className="text-xs font-medium text-gray-500">{key}</dt>
                                        <dd className="mt-1 text-sm text-gray-800">{formatOptionValue(value)}</dd>
                                      </div>
                                    ))}
                                  </dl>
                                </div>
                              )}
                              {job.error && (
                                <DetailItem label="Error" value={job.error} className="md:col-span-2 xl:col-span-4" />
                              )}
                              {job.log_tail && (
                                <div className="md:col-span-2 xl:col-span-4">
                                  <div className="text-xs font-semibold uppercase text-gray-500">Recent log</div>
                                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-gray-950 p-3 text-xs text-gray-100">{job.log_tail}</pre>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
                {jobs.length === 0 && (
                  <tr>
                    <td className="px-4 py-8 text-sm text-gray-500" colSpan={8}>
                      No ingestion jobs yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>
  );
}
