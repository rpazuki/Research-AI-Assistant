"use client";

/**
 * Analytics page — Literature Landscape.
 * Shows corpus statistics, temporal publication trends, and top journals.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  getCorpusStats,
  getJournals,
  getMeshTerms,
  getTemporalData,
  getTopics,
} from "@/lib/api";
import type { CorpusStats, TemporalDataPoint, JournalDataPoint } from "@/types";

export default function AnalyticsPage() {
  const router = useRouter();
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [temporal, setTemporal] = useState<TemporalDataPoint[]>([]);
  const [journals, setJournals] = useState<JournalDataPoint[]>([]);
  const [meshTerms, setMeshTerms] = useState<Array<{ term: string; count: number }>>([]);
  const [topics, setTopics] = useState<Array<{ topic: string; count: number }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [s, t, j, mesh, topicData] = await Promise.all([
          getCorpusStats(),
          getTemporalData(),
          getJournals(15),
          getMeshTerms(12),
          getTopics(12),
        ]);
        setStats(s);
        setTemporal(t);
        setJournals(j);
        setMeshTerms(mesh);
        setTopics(topicData);
      } catch (err) {
        if (err instanceof Error && err.message === "Unauthorized") {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load analytics");
      }
    }

    load();
  }, [router]);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Literature Landscape</h1>
          <p className="text-xs text-gray-500">RLA Lab corpus analytics</p>
        </div>
        <a
          href="/chat"
          className="text-sm text-blue-600 hover:underline"
        >
          ← Back to Chat
        </a>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-8">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {/* Stats cards */}
        {stats && (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <StatCard label="Documents" value={stats.document_count.toLocaleString()} />
            <StatCard label="Chunks" value={stats.chunk_count.toLocaleString()} />
            <StatCard
              label="Year range"
              value={
                stats.year_min && stats.year_max
                  ? `${stats.year_min}–${stats.year_max}`
                  : "—"
              }
            />
            <StatCard label="Corpus" value={stats.last_corpus_name ?? "—"} small />
            <StatCard
              label="Last ingestion"
              value={
                stats.last_ingestion
                  ? new Date(stats.last_ingestion).toLocaleDateString()
                  : "—"
              }
            />
          </div>
        )}

        {/* Temporal chart */}
        {temporal.length > 0 && (
          <section className="bg-white rounded-xl border p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">
              Publications per Year
            </h2>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={temporal} margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="year"
                  tick={{ fontSize: 11 }}
                  interval="preserveStartEnd"
                />
                <YAxis tick={{ fontSize: 11 }} width={40} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  formatter={(v: number) => [v.toLocaleString(), "Articles"]}
                />
                <Bar dataKey="count" fill="#3b82f6" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </section>
        )}

        {/* Top journals */}
        {journals.length > 0 && (
          <section className="bg-white rounded-xl border p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">
              Top Journals
            </h2>
            <div className="space-y-2">
              {journals.map((j) => {
                const maxCount = journals[0].count;
                const pct = Math.round((j.count / maxCount) * 100);
                return (
                  <div key={j.journal} className="flex items-center gap-3">
                    <span className="text-xs text-gray-600 w-56 truncate flex-shrink-0">
                      {j.journal}
                    </span>
                    <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                      <div
                        className="h-full bg-blue-400 rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500 w-10 text-right flex-shrink-0">
                      {j.count.toLocaleString()}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {(meshTerms.length > 0 || topics.length > 0) && (
          <section className="grid gap-6 lg:grid-cols-2">
            <div className="bg-white rounded-xl border p-6">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Top MeSH Terms</h2>
              <div className="flex flex-wrap gap-2">
                {meshTerms.map((term) => (
                  <span
                    key={term.term}
                    className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-700"
                  >
                    {term.term} ({term.count})
                  </span>
                ))}
              </div>
            </div>
            <div className="bg-white rounded-xl border p-6">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Topic Distribution</h2>
              <div className="space-y-2">
                {topics.map((topic) => (
                  <div key={topic.topic} className="flex items-center justify-between gap-4 text-sm">
                    <span className="text-gray-700 truncate">{topic.topic}</span>
                    <span className="text-gray-500">{topic.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {!stats && !error && (
          <div className="text-center text-gray-400 py-16 text-sm">Loading…</div>
        )}
      </main>
    </div>
  );
}

function StatCard({
  label,
  value,
  small,
}: {
  label: string;
  value: string;
  small?: boolean;
}) {
  return (
    <div className="bg-white rounded-xl border p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`font-semibold text-gray-900 ${small ? "text-sm" : "text-xl"} truncate`}>
        {value}
      </p>
    </div>
  );
}
