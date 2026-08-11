"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  cancelDatasheetRun,
  downloadDatasheetAssistedLinks,
  downloadDatasheetCsv,
  downloadDatasheetRunManifest,
  estimateDatasheetExtraction,
  getDatasheetRun,
  listDatasheetRunCandidates,
  listDatasheetRunRows,
  reextractDatasheetRun,
} from "@/lib/api";
import type {
  DatasheetCandidate,
  DatasheetExtractionEstimate,
  DatasheetRow,
  DatasheetRunDetail,
} from "@/types";
import AdminHeader from "./AdminHeader";

/**
 * One discovery run: what it searched, what it found, and why each candidate was
 * kept or dropped.
 *
 * The relevance reason is shown on every row on purpose. This corpus's original
 * failure was silent omission — 28% of the curated literature was missing and
 * nothing said so — and a filter whose decisions are invisible reproduces exactly
 * that. Excluded candidates stay in the table, marked `skipped`, and the manifest
 * CSV carries the same reasons for offline review.
 */

const POLL_INTERVAL_MS = 5000;
// `awaiting_batch` counts as active: the run is parked on an extraction batch, not
// finished. Leaving it out would stop polling on a run that is still going to
// change, and hide the Cancel button on the one state where cancelling saves money.
const ACTIVE_STATUSES = new Set(["queued", "running", "awaiting_batch", "cancel_requested"]);

const RELEVANCE_STYLES: Record<string, string> = {
  studies: "bg-green-50 text-green-700",
  mentions: "bg-yellow-50 text-yellow-800",
  off_topic: "bg-gray-100 text-gray-600",
  unknown: "bg-blue-50 text-blue-700",
};

// Per-paper extraction outcome. A paper that refused or failed has no datasheet
// row, so this column is the only place it appears at all.
const EXTRACTION_STYLES: Record<string, string> = {
  extracted: "bg-green-50 text-green-700",
  cached: "bg-green-50 text-green-700",
  refused: "bg-red-50 text-red-700",
  failed: "bg-red-50 text-red-700",
  no_text: "bg-gray-100 text-gray-600",
  over_cap: "bg-yellow-50 text-yellow-800",
};

const RELEVANCE_FILTERS = ["", "studies", "mentions", "unknown", "off_topic"];

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <p className="text-xs font-semibold uppercase text-gray-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-gray-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

export default function AdminDatasheetRunClient({ runId }: { runId: string }) {
  const router = useRouter();
  const [run, setRun] = useState<DatasheetRunDetail | null>(null);
  const [candidates, setCandidates] = useState<DatasheetCandidate[]>([]);
  const [relevanceFilter, setRelevanceFilter] = useState("");
  const [onlyIncluded, setOnlyIncluded] = useState(false);
  const [rows, setRows] = useState<DatasheetRow[]>([]);
  const [estimate, setEstimate] = useState<DatasheetExtractionEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [reextracting, setReextracting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleError(err: unknown, fallback: string) {
    if (err instanceof Error && err.message === "Unauthorized") {
      router.push("/login");
      return;
    }
    setError(err instanceof Error ? err.message : fallback);
  }

  useEffect(() => {
    void load();
  }, [runId, relevanceFilter, onlyIncluded]);

  useEffect(() => {
    if (!run || !ACTIVE_STATUSES.has(run.status)) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [run?.status, runId, relevanceFilter, onlyIncluded]);

  async function load() {
    try {
      const [detail, rows] = await Promise.all([
        getDatasheetRun(runId),
        listDatasheetRunCandidates(runId, {
          relevance: relevanceFilter || undefined,
          acquisition_status: onlyIncluded ? "pending" : undefined,
          limit: 300,
        }),
      ]);
      setRun(detail);
      setCandidates(rows);
      setError(null);
      if (detail.row_count > 0) {
        setRows(await listDatasheetRunRows(runId, { limit: 300 }));
      }
    } catch (err) {
      handleError(err, "Failed to load run");
    } finally {
      setLoading(false);
    }
  }

  async function handleEstimate() {
    try {
      setEstimating(true);
      setEstimate(await estimateDatasheetExtraction(runId));
    } catch (err) {
      handleError(err, "Failed to estimate extraction cost");
    } finally {
      setEstimating(false);
    }
  }

  async function handleDatasheetDownload() {
    try {
      setDownloading(true);
      const { blob, filename } = await downloadDatasheetCsv(runId);
      await saveBlob(blob, filename);
    } catch (err) {
      handleError(err, "Failed to download the datasheet");
    } finally {
      setDownloading(false);
    }
  }

  async function handleCancel() {
    try {
      setRun(await cancelDatasheetRun(runId));
    } catch (err) {
      handleError(err, "Failed to cancel run");
    }
  }

  async function handleReextract() {
    try {
      setReextracting(true);
      const detail = await reextractDatasheetRun(runId);
      setRun(detail);
      // The previous pass's rows are gone server-side; keeping them on screen would
      // show a datasheet that no longer exists.
      setRows([]);
      setEstimate(null);
    } catch (err) {
      handleError(err, "Failed to queue a re-extraction");
    } finally {
      setReextracting(false);
    }
  }

  async function saveBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function handleAssistedDownload() {
    try {
      setDownloading(true);
      const { blob, filename } = await downloadDatasheetAssistedLinks(runId);
      await saveBlob(blob, filename);
    } catch (err) {
      handleError(err, "Failed to download the assisted-acquisition list");
    } finally {
      setDownloading(false);
    }
  }

  async function handleDownload() {
    try {
      setDownloading(true);
      const { blob, filename } = await downloadDatasheetRunManifest(runId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      handleError(err, "Failed to download manifest");
    } finally {
      setDownloading(false);
    }
  }

  const counts = run?.candidate_counts ?? {};
  const summary = (run?.discovery_summary ?? {}) as Record<string, unknown>;
  const acquisition = (run?.acquisition_summary ?? null) as Record<string, unknown> | null;
  const acquisitionHosts = ((acquisition?.host_tallies ?? []) as Record<string, unknown>[]).filter(
    (host) => Number(host.requests ?? 0) > 0
  );
  const assistedCount = Number(acquisition?.assisted_pending ?? 0);
  const extraction = (run?.extraction_summary ?? null) as Record<string, unknown> | null;
  const extractionPlan = (extraction?.plan ?? null) as Record<string, unknown> | null;
  // Papers whose result the cache already holds. They produce rows without a call
  // and are excluded from the projected cost, so saying so is what makes a cheap
  // projection legible rather than suspicious.
  const cachedPapers = estimate?.cached ?? Number(extractionPlan?.cached ?? 0);
  // Column order comes from the rows themselves, which carry the run's frozen
  // template — not from the live template, which may have moved on since.
  const rowColumns = useMemo(() => Object.keys(rows[0]?.cells ?? {}), [rows]);
  const sourceCounts = (summary.source_record_counts ?? {}) as Record<string, number>;
  const sourceErrors = (summary.source_errors ?? {}) as Record<string, string>;

  const sourceRows = useMemo(
    () =>
      Object.entries(sourceCounts).map(([source, records]) => ({
        source,
        records,
        error: sourceErrors[source] ?? null,
      })),
    [sourceCounts, sourceErrors]
  );

  return (
    <main className="min-h-screen bg-gray-50">
      <AdminHeader subtitle={run ? `Run: ${run.name}` : "Datasheet run"} />

      <section className="mx-auto grid max-w-6xl gap-6 px-6 py-6">
        {error && (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading && !run ? (
          <p className="rounded-lg border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
            Loading run...
          </p>
        ) : !run ? null : (
          <>
            <div className="rounded-lg border border-gray-200 bg-white p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">{run.name}</h2>
                  <p className="mt-1 text-sm text-gray-600">
                    {run.organism_name ?? run.product_term} · {run.year_from}-{run.year_to} ·{" "}
                    {run.organism_synonyms.length + run.product_synonyms.length} search terms ·
                    template {run.template_name} v{run.template_version}
                  </p>
                  <p className="mt-1 text-sm text-gray-700">
                    <span className="font-medium">{run.status}</span>
                    {run.phase ? ` · ${run.phase}` : ""} — {run.error ?? run.progress_message}
                  </p>
                  {run.status === "awaiting_batch" && (
                    <p className="mt-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
                      Parked on extraction batch{" "}
                      <code className="font-mono">{run.extraction_batch_id}</code>. The worker is
                      free to run other jobs meanwhile and collects this batch when it ends —
                      a batch can take up to 24 hours. Cancelling stops the requests that have
                      not started; anything already in flight still completes and is billed.
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void handleDownload()}
                    disabled={downloading || !run.candidate_count}
                    className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {downloading ? "Preparing..." : "Manifest CSV"}
                  </button>
                  {assistedCount > 0 && (
                    <button
                      type="button"
                      onClick={() => void handleAssistedDownload()}
                      disabled={downloading}
                      className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Assisted list ({assistedCount})
                    </button>
                  )}
                  {run.row_count > 0 && (
                    <button
                      type="button"
                      onClick={() => void handleDatasheetDownload()}
                      disabled={downloading}
                      className="rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm font-medium text-green-800 hover:bg-green-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Datasheet CSV ({run.row_count})
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleEstimate()}
                    disabled={estimating}
                    className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {estimating ? "Counting..." : "Estimate extraction"}
                  </button>
                  {!ACTIVE_STATUSES.has(run.status) && (
                    <button
                      type="button"
                      onClick={() => void handleReextract()}
                      disabled={reextracting}
                      title="Re-run extraction only. Discovery and acquisition are kept, and papers whose prompt has not changed come from the result cache."
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {reextracting ? "Queueing..." : "Re-extract"}
                    </button>
                  )}
                  {ACTIVE_STATUSES.has(run.status) && (
                    <button
                      type="button"
                      onClick={() => void handleCancel()}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
                    >
                      Cancel run
                    </button>
                  )}
                </div>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Candidates" value={counts.total ?? run.candidate_count ?? 0} />
              <Stat
                label="Studies the seed"
                value={counts.relevance_studies ?? 0}
                hint="Seed in title, or repeated in the abstract"
              />
              <Stat
                label="Needs adjudication"
                value={counts.relevance_unknown ?? 0}
                hint="No abstract and no title match"
              />
              <Stat
                label="Flagged"
                value={`${counts.reviews ?? 0} reviews · ${counts.retracted ?? 0} retracted`}
                hint="Kept in the manifest, excluded from acquisition"
              />
              {typeof summary.possible_duplicates_flagged === "number" &&
                (summary.possible_duplicates_flagged as number) > 0 && (
                  <Stat
                    label="Possible duplicates"
                    value={summary.possible_duplicates_flagged as number}
                    hint="Same title, kept as separate rows — merging is a human decision"
                  />
                )}
            </div>

            {(estimate || extraction) && (
              <div className="rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-200 px-4 py-3">
                  <h3 className="text-sm font-semibold text-gray-800">Extraction</h3>
                  <p className="mt-0.5 text-xs text-gray-500">
                    Extraction is the only phase that sends paper text to the model and the
                    only one that costs money, so a run reports what it would cost and stops
                    unless extraction has been explicitly enabled.
                  </p>
                </div>
                {estimate && !estimate.extraction_enabled && (
                  <p className="mx-4 mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    Extraction is disabled. This is a projection only — nothing was sent. Set
                    DATASHEET_EXTRACTION_ENABLED in the backend environment to run it.
                  </p>
                )}
                <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Stat
                    label="Papers ready"
                    value={estimate?.papers ?? Number(extractionPlan?.papers ?? 0)}
                    hint={`${cachedPapers} already extracted · ${estimate?.skipped_no_text ?? extractionPlan?.skipped_no_text ?? 0} have no fetched text`}
                  />
                  <Stat
                    label="Projected cost"
                    value={`$${(estimate?.projected_cost_usd ?? Number(extractionPlan?.projected_cost_usd ?? 0)).toFixed(2)}`}
                    hint={
                      cachedPapers > 0
                        ? `${estimate?.model ?? extractionPlan?.model ?? ""}, batch rates — ${cachedPapers} cached papers cost nothing`
                        : `${estimate?.model ?? extractionPlan?.model ?? ""}, batch rates`
                    }
                  />
                  <Stat
                    label="Input tokens"
                    value={(estimate?.input_tokens ?? Number(extractionPlan?.input_tokens ?? 0)).toLocaleString()}
                    hint={
                      (estimate?.token_method ?? extractionPlan?.token_method) === "provider"
                        ? "Counted by the model's own tokeniser"
                        : "Character estimate — no API key available"
                    }
                  />
                  <Stat
                    label="Rows extracted"
                    value={run.row_count}
                    hint={
                      run.prompt_tokens
                        ? `${run.prompt_tokens.toLocaleString()} prompt · ${(run.cached_tokens ?? 0).toLocaleString()} cached`
                        : "No extraction run yet"
                    }
                  />
                </div>
              </div>
            )}

            {rows.length > 0 && (
              <div className="rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-200 px-4 py-3">
                  <h3 className="text-sm font-semibold text-gray-800">
                    Extracted rows ({rows.length})
                  </h3>
                  <p className="mt-0.5 text-xs text-gray-500">
                    Hover a value to see the quote it came from. A cell reading &quot;Not
                    reported&quot; is a fact about the paper, not a gap in the extraction.
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
                      <tr>
                        <th className="px-4 py-2">Paper</th>
                        <th className="px-4 py-2">Tier</th>
                        {rowColumns.map((key) => (
                          <th key={key} className="px-4 py-2">
                            {key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {rows.map((row) => (
                        <tr key={row.id} className="align-top">
                          <td className="max-w-xs px-4 py-2">
                            <span className="block truncate text-gray-900" title={row.title ?? ""}>
                              {row.title ?? row.doi ?? "Untitled"}
                            </span>
                            <span className="text-xs text-gray-500">
                              {row.journal} {row.year ? `· ${row.year}` : ""}
                            </span>
                          </td>
                          <td className="px-4 py-2">
                            <span
                              className={`rounded px-2 py-0.5 text-xs ${
                                row.source_tier === "fulltext"
                                  ? "bg-green-50 text-green-700"
                                  : "bg-yellow-50 text-yellow-800"
                              }`}
                            >
                              {row.source_tier}
                            </span>
                          </td>
                          {rowColumns.map((key) => {
                            const cell = row.cells[key];
                            return (
                              <td key={key} className="px-4 py-2 text-gray-700">
                                <span title={cell?.evidence_quote || undefined}>
                                  {cell?.value ?? "Not reported"}
                                </span>
                                {cell && cell.confidence < 0.6 && (
                                  <span className="ml-1 text-xs text-amber-700">
                                    ({cell.confidence.toFixed(2)})
                                  </span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {sourceRows.length > 0 && (
              <div className="rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-200 px-4 py-3">
                  <h3 className="text-sm font-semibold text-gray-800">Per-source records</h3>
                  <p className="mt-0.5 text-xs text-gray-500">
                    A source that failed is reported here rather than silently reducing coverage.
                  </p>
                </div>
                <div className="flex flex-wrap gap-3 px-4 py-3 text-sm">
                  {sourceRows.map((row) => (
                    <span
                      key={row.source}
                      className={`rounded-md border px-3 py-1.5 ${
                        row.error
                          ? "border-red-200 bg-red-50 text-red-700"
                          : "border-gray-200 bg-gray-50 text-gray-700"
                      }`}
                      title={row.error ?? undefined}
                    >
                      {row.source}: {row.records}
                      {row.error ? " (failed)" : ""}
                    </span>
                  ))}
                  {typeof summary.duplicates_collapsed === "number" && (
                    <span className="rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-gray-700">
                      duplicates collapsed: {summary.duplicates_collapsed as number}
                    </span>
                  )}
                  {typeof summary.preprints_collapsed === "number" && (
                    <span className="rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-gray-700">
                      preprints merged into their VoR: {summary.preprints_collapsed as number}
                    </span>
                  )}
                </div>
              </div>
            )}

            {acquisition && (
              <div className="rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-200 px-4 py-3">
                  <h3 className="text-sm font-semibold text-gray-800">Acquisition</h3>
                  <p className="mt-0.5 text-xs text-gray-500">
                    Papers with no automated open-access route are queued for a human, not
                    recorded as failures. A host that blocked us is named below.
                  </p>
                </div>
                <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Stat
                    label="Full texts"
                    value={Number(acquisition.fetched ?? 0)}
                    hint={`${Number(acquisition.from_cache ?? 0)} already cached`}
                  />
                  <Stat
                    label="Assisted"
                    value={assistedCount}
                    hint="Downloadable by hand via the resolver link"
                  />
                  <Stat label="Failed" value={Number(acquisition.failed ?? 0)} />
                  <Stat
                    label="Fidelity warnings"
                    value={Number(acquisition.fidelity_warnings ?? 0)}
                    hint="Greek characters may not have survived extraction"
                  />
                </div>
                {acquisitionHosts.length > 0 && (
                  <div className="flex flex-wrap gap-2 border-t border-gray-200 px-4 py-3 text-sm">
                    {acquisitionHosts.map((host) => (
                      <span
                        key={String(host.host)}
                        title={
                          host.circuit_open
                            ? "Circuit opened: three consecutive blocks, so this host was left alone for the rest of the run"
                            : undefined
                        }
                        className={`rounded-md border px-3 py-1.5 ${
                          host.circuit_open
                            ? "border-red-200 bg-red-50 text-red-700"
                            : Number(host.blocked ?? 0) > 0
                              ? "border-amber-200 bg-amber-50 text-amber-800"
                              : "border-gray-200 bg-gray-50 text-gray-700"
                        }`}
                      >
                        {String(host.host)}: {Number(host.successes ?? 0)}/{Number(host.requests ?? 0)}
                        {Number(host.blocked ?? 0) > 0 ? ` · ${Number(host.blocked)} blocked` : ""}
                        {host.circuit_open ? " · circuit open" : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-4 py-3">
                <h3 className="text-sm font-semibold text-gray-800">Candidates</h3>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <label className="flex items-center gap-2">
                    Relevance
                    <select
                      aria-label="Relevance filter"
                      value={relevanceFilter}
                      onChange={(event) => setRelevanceFilter(event.target.value)}
                      className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm"
                    >
                      {RELEVANCE_FILTERS.map((value) => (
                        <option key={value || "all"} value={value}>
                          {value || "all"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={onlyIncluded}
                      onChange={(event) => setOnlyIncluded(event.target.checked)}
                    />
                    Only those to acquire
                  </label>
                  <span className="text-xs text-gray-500">{candidates.length} shown</span>
                </div>
              </div>

              {candidates.length === 0 ? (
                <p className="px-4 py-6 text-sm text-gray-500">
                  {run.status === "queued" || run.status === "running"
                    ? "Discovery is still running."
                    : "No candidates match this filter."}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
                      <tr>
                        <th className="px-4 py-2">Title</th>
                        <th className="px-4 py-2">Year</th>
                        <th className="px-4 py-2">Found in</th>
                        <th className="px-4 py-2">Relevance</th>
                        <th className="px-4 py-2">Why</th>
                        <th className="px-4 py-2">Flags</th>
                        <th className="px-4 py-2">Status</th>
                        <th className="px-4 py-2">Extraction</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {candidates.map((candidate) => (
                        <tr key={candidate.id} className="hover:bg-gray-50">
                          <td className="max-w-md px-4 py-2">
                            <p className="truncate text-gray-900" title={candidate.title ?? ""}>
                              {candidate.title ?? "Not reported"}
                            </p>
                            <p className="truncate text-xs text-gray-500">
                              {candidate.doi ? (
                                <a
                                  href={`https://doi.org/${candidate.doi}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-blue-700 hover:underline"
                                >
                                  {candidate.doi}
                                </a>
                              ) : (
                                "no DOI"
                              )}
                              {candidate.journal ? ` · ${candidate.journal}` : ""}
                            </p>
                          </td>
                          <td className="px-4 py-2 text-gray-700">{candidate.year ?? "-"}</td>
                          <td className="px-4 py-2 text-xs text-gray-600">
                            {candidate.found_in.join(", ")}
                          </td>
                          <td className="px-4 py-2">
                            <span
                              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                                RELEVANCE_STYLES[candidate.relevance] ?? "bg-gray-100 text-gray-700"
                              }`}
                            >
                              {candidate.relevance}
                            </span>
                          </td>
                          <td className="max-w-xs px-4 py-2 text-xs text-gray-600">
                            {candidate.relevance_reason ?? "-"}
                          </td>
                          <td className="px-4 py-2 text-xs">
                            <span className="flex flex-wrap gap-1">
                              {candidate.is_review && (
                                <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-800">
                                  review
                                </span>
                              )}
                              {candidate.is_retracted && (
                                <span className="rounded bg-red-50 px-1.5 py-0.5 text-red-700">
                                  retracted
                                </span>
                              )}
                              {candidate.is_preprint && (
                                <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">
                                  preprint
                                </span>
                              )}
                              {candidate.preprint_doi && !candidate.is_preprint && (
                                <span
                                  className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700"
                                  title={`Preprint: ${candidate.preprint_doi}`}
                                >
                                  has preprint
                                </span>
                              )}
                              {candidate.possible_duplicate_of.length > 0 && (
                                <span
                                  className="rounded bg-purple-50 px-1.5 py-0.5 text-purple-700"
                                  title={
                                    candidate.duplicate_evidence ??
                                    candidate.possible_duplicate_of.join(", ")
                                  }
                                >
                                  possible duplicate
                                </span>
                              )}
                            </span>
                          </td>
                          <td className="px-4 py-2 text-xs text-gray-700">
                            {candidate.acquisition_status}
                          </td>
                          <td className="px-4 py-2 text-xs">
                            {candidate.extraction_status ? (
                              <span
                                className={`rounded px-1.5 py-0.5 ${
                                  EXTRACTION_STYLES[candidate.extraction_status] ??
                                  "bg-gray-100 text-gray-700"
                                }`}
                                // The reason travels with the outcome: "3 failed" with
                                // no way to learn which three, or why, is not a report.
                                title={candidate.extraction_error ?? undefined}
                              >
                                {candidate.extraction_status}
                              </span>
                            ) : (
                              <span className="text-gray-400">-</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {run.log_tail && (
              <div className="rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-200 px-4 py-3">
                  <h3 className="text-sm font-semibold text-gray-800">Run log</h3>
                </div>
                <pre className="overflow-x-auto px-4 py-3 text-xs leading-relaxed text-gray-700">
                  {run.log_tail}
                </pre>
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}
