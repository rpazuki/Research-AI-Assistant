"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  downloadIngestionAcquisitionReviewCsv,
  getIngestionAcquisitionQueue,
  logout,
} from "@/lib/api";
import type { IngestionAcquisitionQueueReport } from "@/types";

const PREFERRED_COLUMNS = [
  "doi",
  "route",
  "candidate_url",
  "candidate_pdf_url",
  "access_status",
  "priority",
  "review_decision",
  "access_method",
  "reviewer",
  "notes",
];

const HIDDEN_COLUMNS = new Set(["document_id", "pmid", "pmc_id"]);

function columnLabel(column: string) {
  return column.replaceAll("_", " ");
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function toHttpUrl(value: unknown) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  try {
    const url = new URL(trimmed);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function CellValue({ column, value }: { column: string; value: unknown }) {
  const url = toHttpUrl(value);
  if (url) {
    return (
      <div className="grid gap-1">
        <span className="max-w-sm truncate text-xs text-gray-500" title={url}>
          {url}
        </span>
        <span className="flex gap-3">
          <a href={url} target="_blank" rel="noreferrer" className="font-medium text-blue-700 hover:underline">
            Open
          </a>
          <a href={url} download className="font-medium text-blue-700 hover:underline">
            Download
          </a>
        </span>
      </div>
    );
  }

  const text = formatValue(value);
  return (
    <span className={column === "notes" ? "whitespace-pre-wrap" : "whitespace-nowrap"} title={text}>
      {text}
    </span>
  );
}

function buildColumns(records: Record<string, unknown>[]) {
  const seen = new Set<string>();
  for (const record of records) {
    for (const key of Object.keys(record)) {
      if (!HIDDEN_COLUMNS.has(key)) {
        seen.add(key);
      }
    }
  }

  const preferred = PREFERRED_COLUMNS.filter((column) => seen.has(column));
  const rest = [...seen]
    .filter((column) => !PREFERRED_COLUMNS.includes(column))
    .sort((a, b) => a.localeCompare(b));
  return [...preferred, ...rest];
}

function priorityRank(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return 0;

  const normalized = value.trim().toLowerCase();
  const parsed = Number(normalized);
  if (Number.isFinite(parsed)) return parsed;
  if (normalized === "high") return 3;
  if (normalized === "medium") return 2;
  if (normalized === "low") return 1;
  return 0;
}

function sortRecordsByPriority(records: Record<string, unknown>[]) {
  return records
    .map((record, index) => ({ record, index }))
    .sort((left, right) => {
      const priorityDelta = priorityRank(right.record.priority) - priorityRank(left.record.priority);
      return priorityDelta || left.index - right.index;
    })
    .map(({ record }) => record);
}

export default function AdminAcquisitionQueueClient() {
  const router = useRouter();
  const [reports, setReports] = useState<IngestionAcquisitionQueueReport[]>([]);
  const [selectedCachePath, setSelectedCachePath] = useState("");
  const [loading, setLoading] = useState(true);
  const [downloadingCsv, setDownloadingCsv] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadReports();
  }, []);

  async function loadReports() {
    try {
      setLoading(true);
      const data = await getIngestionAcquisitionQueue();
      setReports(data);
      setSelectedCachePath((current) => {
        if (current && data.some((report) => report.cache_path === current)) {
          return current;
        }
        return data[0]?.cache_path ?? "";
      });
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load acquisition queue");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  async function handleCsvDownload() {
    if (!selectedReport) return;
    try {
      setDownloadingCsv(true);
      const { blob, filename } = await downloadIngestionAcquisitionReviewCsv(selectedReport.cache_path);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download review CSV");
    } finally {
      setDownloadingCsv(false);
    }
  }

  const selectedReport = reports.find((report) => report.cache_path === selectedCachePath) ?? reports[0];
  const sortedRecords = useMemo(
    () => sortRecordsByPriority(selectedReport?.records ?? []),
    [selectedReport]
  );
  const columns = useMemo(
    () => buildColumns(sortedRecords),
    [sortedRecords]
  );

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Admin</h1>
            <p className="text-sm text-gray-500">Acquisition queue</p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/admin/ingestion" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Ingestion
            </Link>
            <Link href="/admin/ingestion/config" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Config
            </Link>
            <Link href="/admin/stats" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Stats
            </Link>
            <button type="button" onClick={handleLogout} className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl gap-6 px-6 py-6">
        {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">reports/acquisition_queue.jsonl</h2>
              <p className="mt-1 text-sm text-gray-500">
                Review queued full-text acquisition candidates for each ingestion cache.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              {reports.length > 1 && (
                <label className="grid gap-1 text-sm font-medium text-gray-700">
                  Cache path
                  <select
                    value={selectedCachePath}
                    onChange={(event) => setSelectedCachePath(event.target.value)}
                    className="min-w-72 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-normal text-gray-900"
                  >
                    {reports.map((report) => (
                      <option key={report.cache_path} value={report.cache_path}>
                        {report.cache_path}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                type="button"
                onClick={handleCsvDownload}
                disabled={loading || !selectedReport || downloadingCsv}
                className="rounded-md border border-blue-200 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {downloadingCsv ? "Preparing..." : "To CSV"}
              </button>
            </div>
          </div>

          {loading && <div className="mt-6 text-sm text-gray-500">Loading acquisition queue...</div>}

          {!loading && !selectedReport && (
            <div className="mt-6 rounded-md border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
              No cache paths have been recorded for ingestion jobs yet.
            </div>
          )}

          {!loading && selectedReport && (
            <div className="mt-6 grid gap-4">
              <div className="grid gap-1 text-sm text-gray-600">
                <div>
                  <span className="font-medium text-gray-800">Cache:</span> {selectedReport.cache_path}
                </div>
                <div>
                  <span className="font-medium text-gray-800">File:</span> {selectedReport.queue_file_path}
                </div>
                <div>
                  <span className="font-medium text-gray-800">Records:</span> {selectedReport.record_count}
                </div>
              </div>

              {!selectedReport.exists && (
                <div className="rounded-md border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
                  This cache does not have a reports/acquisition_queue.jsonl file.
                </div>
              )}

              {selectedReport.parse_errors.length > 0 && (
                <div className="rounded-md border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
                  <div className="font-medium">Some lines could not be parsed.</div>
                  <ul className="mt-2 list-disc pl-5">
                    {selectedReport.parse_errors.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {selectedReport.exists && selectedReport.records.length === 0 && (
                <div className="rounded-md border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
                  The acquisition queue file is present but empty.
                </div>
              )}

              {sortedRecords.length > 0 && (
                <div className="overflow-x-auto rounded-md border border-gray-200">
                  <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        {columns.map((column) => (
                          <th key={column} scope="col" className="whitespace-nowrap px-3 py-2 font-semibold capitalize text-gray-700">
                            {columnLabel(column)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                      {sortedRecords.map((record, index) => (
                        <tr key={`${selectedReport.cache_path}-${index}`} className="align-top">
                          {columns.map((column) => (
                            <td key={column} className="px-3 py-2 text-gray-700">
                              <CellValue column={column} value={record[column]} />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
