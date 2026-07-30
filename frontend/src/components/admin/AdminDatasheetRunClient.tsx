"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  cancelDatasheetRun,
  downloadDatasheetAssistedLinks,
  downloadDatasheetRunManifest,
  getDatasheetRun,
  listDatasheetRunCandidates,
} from "@/lib/api";
import type { DatasheetCandidate, DatasheetRunDetail } from "@/types";
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
const ACTIVE_STATUSES = new Set(["queued", "running", "cancel_requested"]);

const RELEVANCE_STYLES: Record<string, string> = {
  studies: "bg-green-50 text-green-700",
  mentions: "bg-yellow-50 text-yellow-800",
  off_topic: "bg-gray-100 text-gray-600",
  unknown: "bg-blue-50 text-blue-700",
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
    } catch (err) {
      handleError(err, "Failed to load run");
    } finally {
      setLoading(false);
    }
  }

  async function handleCancel() {
    try {
      setRun(await cancelDatasheetRun(runId));
    } catch (err) {
      handleError(err, "Failed to cancel run");
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
