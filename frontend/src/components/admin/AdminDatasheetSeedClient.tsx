"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { createDatasheetRun, listDatasheetRuns, lookupOrganism, lookupProduct } from "@/lib/api";
import type { DatasheetRunSummary, OrganismSeed, ProductSeed } from "@/types";
import AdminHeader from "./AdminHeader";

/**
 * S1 of the datasheet feature: resolve a run's seed before there is a run to
 * create.
 *
 * A datasheet starts from an organism or a bioproduct, and what discovery needs
 * is not the typed name but the set of names the literature uses for it —
 * searching for `Yarrowia lipolytica` alone misses every paper published under
 * `Candida lipolytica`. This page is where a curator confirms that set, and the
 * search terms shown here are exactly what S2 will query each source with.
 */

const DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 3;
const DEFAULT_YEAR_FROM = 2016;
const DEFAULT_YEAR_TO = 2026;

const STATUS_STYLES: Record<string, string> = {
  succeeded: "bg-green-50 text-green-700",
  running: "bg-blue-50 text-blue-700",
  queued: "bg-gray-100 text-gray-700",
  failed: "bg-red-50 text-red-700",
  cancelled: "bg-amber-50 text-amber-800",
  cancel_requested: "bg-amber-50 text-amber-800",
};

function Chips({ values, tone = "gray" }: { values: string[]; tone?: "gray" | "blue" }) {
  const className =
    tone === "blue"
      ? "rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-800"
      : "rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-700";
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) => (
        <span key={value} className={className}>
          {value}
        </span>
      ))}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase text-gray-500">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-gray-900">{value ?? "Not reported"}</dd>
    </div>
  );
}

export default function AdminDatasheetSeedClient() {
  const router = useRouter();

  const [organismQuery, setOrganismQuery] = useState("");
  const [organismOptions, setOrganismOptions] = useState<
    { taxid: number; label: string; rank: string | null }[]
  >([]);
  const [organismSeed, setOrganismSeed] = useState<OrganismSeed | null>(null);
  const [organismBusy, setOrganismBusy] = useState(false);

  const [productQuery, setProductQuery] = useState("");
  const [productOptions, setProductOptions] = useState<string[]>([]);
  const [productSeed, setProductSeed] = useState<ProductSeed | null>(null);
  const [productClasses, setProductClasses] = useState<string[]>([]);
  const [manualClass, setManualClass] = useState("");
  const [productBusy, setProductBusy] = useState(false);

  const [runs, setRuns] = useState<DatasheetRunSummary[]>([]);
  const [runName, setRunName] = useState("");
  const [yearFrom, setYearFrom] = useState(String(DEFAULT_YEAR_FROM));
  const [yearTo, setYearTo] = useState(String(DEFAULT_YEAR_TO));
  const [includeMentions, setIncludeMentions] = useState(false);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  // Guards against a slow earlier keystroke overwriting a newer result.
  const organismRequestRef = useRef(0);
  const productRequestRef = useRef(0);

  function handleError(err: unknown, fallback: string) {
    if (err instanceof Error && err.message === "Unauthorized") {
      router.push("/login");
      return;
    }
    setError(err instanceof Error ? err.message : fallback);
  }

  useEffect(() => {
    void loadRuns();
  }, []);

  async function loadRuns() {
    try {
      setRuns(await listDatasheetRuns());
    } catch (err) {
      handleError(err, "Failed to load runs");
    }
  }

  useEffect(() => {
    const trimmed = organismQuery.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setOrganismOptions([]);
      return;
    }

    const timer = window.setTimeout(() => {
      const requestId = ++organismRequestRef.current;
      void (async () => {
        try {
          const result = await lookupOrganism({ q: trimmed, limit: 10 });
          if (requestId !== organismRequestRef.current) return;
          setOrganismOptions(
            result.suggestions.map((item) => ({
              taxid: item.taxid,
              label: item.scientific_name,
              rank: item.rank,
            }))
          );
          setError(null);
        } catch (err) {
          if (requestId !== organismRequestRef.current) return;
          handleError(err, "Organism lookup failed");
        }
      })();
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [organismQuery]);

  useEffect(() => {
    const trimmed = productQuery.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setProductOptions([]);
      return;
    }

    const timer = window.setTimeout(() => {
      const requestId = ++productRequestRef.current;
      void (async () => {
        try {
          const result = await lookupProduct({ q: trimmed, limit: 10 });
          if (requestId !== productRequestRef.current) return;
          setProductOptions(result.suggestions.map((item) => item.name));
          setProductClasses(result.product_classes);
          setError(null);
        } catch (err) {
          if (requestId !== productRequestRef.current) return;
          handleError(err, "Product lookup failed");
        }
      })();
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [productQuery]);

  async function resolveOrganism(params: { q?: string; taxid?: number }) {
    try {
      setOrganismBusy(true);
      const result = await lookupOrganism({ ...params, resolve: true });
      setOrganismSeed(result.seed);
      setError(result.seed ? null : "No organism matched that name in NCBI Taxonomy");
    } catch (err) {
      handleError(err, "Organism lookup failed");
    } finally {
      setOrganismBusy(false);
    }
  }

  async function resolveProduct(params: { q?: string; cid?: number }) {
    try {
      setProductBusy(true);
      const result = await lookupProduct({ ...params, resolve: true });
      setProductSeed(result.seed);
      setProductClasses(result.product_classes);
      setManualClass(result.seed?.product_class ?? "");
      setError(result.seed ? null : "No compound matched that name in PubChem");
    } catch (err) {
      handleError(err, "Product lookup failed");
    } finally {
      setProductBusy(false);
    }
  }

  const seedKind =
    organismSeed && productSeed
      ? "organism_and_product"
      : productSeed
        ? "bioproduct"
        : "organism";
  const canCreate = Boolean(organismSeed || productSeed) && runName.trim().length > 0;

  async function handleCreateRun() {
    if (!canCreate) return;
    try {
      setCreating(true);
      const run = await createDatasheetRun({
        name: runName.trim(),
        seed_kind: seedKind,
        organism_name: organismSeed?.scientific_name ?? null,
        organism_taxid: organismSeed?.taxid ?? null,
        // The reviewed term list is sent verbatim rather than re-resolved, so what
        // the curator approved is exactly what gets searched.
        organism_synonyms: organismSeed?.search_terms ?? [],
        product_term: productSeed?.preferred_name ?? null,
        product_ids: productSeed
          ? { pubchem_cid: productSeed.cid, chebi_id: productSeed.chebi_id, inchikey: productSeed.inchikey }
          : null,
        product_synonyms: productSeed?.search_terms ?? [],
        product_classes: productSeed?.product_class ? [productSeed.product_class] : null,
        year_from: Number(yearFrom) || null,
        year_to: Number(yearTo) || null,
        include_mentions: includeMentions,
      });
      setNotice(`Run "${run.name}" queued. The worker picks it up within seconds.`);
      setRunName("");
      setError(null);
      await loadRuns();
    } catch (err) {
      handleError(err, "Failed to create run");
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <AdminHeader subtitle="Datasheet runs" />

      <section className="mx-auto grid max-w-6xl gap-6 px-6 py-6">
        {error && (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {notice && (
          <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
            {notice}
          </div>
        )}

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-base font-semibold text-gray-900">Seed resolution</h2>
          <p className="mt-1 text-sm text-gray-600">
            A datasheet run starts from an organism, a bioproduct, or both. Resolving a seed
            expands it to every name the literature uses, which is what discovery searches with.
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* ── Organism ─────────────────────────────────────────────────── */}
          <div className="rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-4 py-3">
              <h3 className="text-sm font-semibold text-gray-800">Organism</h3>
              <p className="mt-0.5 text-xs text-gray-500">NCBI Taxonomy</p>
            </div>
            <div className="grid gap-3 px-4 py-4">
              <label className="grid gap-1 text-sm font-medium text-gray-700">
                Name, synonym or taxid
                <input
                  value={organismQuery}
                  onChange={(event) => setOrganismQuery(event.target.value)}
                  list="organism-options"
                  placeholder="Yarrowia lipolytica"
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm font-normal text-gray-900"
                />
              </label>
              <datalist id="organism-options">
                {organismOptions.map((option) => (
                  <option key={option.taxid} value={option.label}>
                    {option.rank ? `taxid ${option.taxid} · ${option.rank}` : `taxid ${option.taxid}`}
                  </option>
                ))}
              </datalist>

              {organismOptions.length > 0 && (
                <ul className="grid gap-1">
                  {organismOptions.map((option) => (
                    <li key={option.taxid}>
                      <button
                        type="button"
                        onClick={() => {
                          setOrganismQuery(option.label);
                          void resolveOrganism({ taxid: option.taxid });
                        }}
                        className="w-full rounded-md border border-gray-200 px-3 py-2 text-left text-sm text-gray-800 hover:bg-gray-50"
                      >
                        <span className="font-medium">{option.label}</span>
                        <span className="ml-2 text-xs text-gray-500">
                          taxid {option.taxid}
                          {option.rank ? ` · ${option.rank}` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <button
                type="button"
                onClick={() => void resolveOrganism({ q: organismQuery })}
                disabled={organismBusy || organismQuery.trim().length === 0}
                className="justify-self-start rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {organismBusy ? "Resolving..." : "Resolve organism"}
              </button>

              {organismSeed && (
                <div className="grid gap-3 rounded-md border border-gray-200 bg-gray-50 p-3">
                  <dl className="grid grid-cols-2 gap-3">
                    <Field label="Taxid" value={organismSeed.taxid} />
                    <Field label="Rank" value={organismSeed.rank} />
                    <div className="col-span-2">
                      <Field label="Accepted name" value={organismSeed.scientific_name} />
                    </div>
                  </dl>
                  <div>
                    <p className="text-xs font-semibold uppercase text-gray-500">
                      Synonyms ({organismSeed.synonyms.length})
                    </p>
                    <div className="mt-1">
                      {organismSeed.synonyms.length > 0 ? (
                        <Chips values={organismSeed.synonyms} />
                      ) : (
                        <p className="text-sm text-gray-600">None recorded in NCBI Taxonomy</p>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-gray-500">
                      Search terms ({organismSeed.search_terms.length})
                    </p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      What every discovery source will be queried with.
                    </p>
                    <div className="mt-1">
                      <Chips values={organismSeed.search_terms} tone="blue" />
                    </div>
                  </div>
                  {organismSeed.lineage.length > 0 && (
                    <p className="text-xs text-gray-500">{organismSeed.lineage.join(" › ")}</p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ── Bioproduct ───────────────────────────────────────────────── */}
          <div className="rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-4 py-3">
              <h3 className="text-sm font-semibold text-gray-800">Bioproduct</h3>
              <p className="mt-0.5 text-xs text-gray-500">PubChem, with ChEBI enrichment</p>
            </div>
            <div className="grid gap-3 px-4 py-4">
              <label className="grid gap-1 text-sm font-medium text-gray-700">
                Compound name, synonym or CID
                <input
                  value={productQuery}
                  onChange={(event) => setProductQuery(event.target.value)}
                  list="product-options"
                  placeholder="hesperetin"
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm font-normal text-gray-900"
                />
              </label>
              <datalist id="product-options">
                {productOptions.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>

              {productOptions.length > 0 && (
                <ul className="grid gap-1">
                  {productOptions.map((option) => (
                    <li key={option}>
                      <button
                        type="button"
                        onClick={() => {
                          setProductQuery(option);
                          void resolveProduct({ q: option });
                        }}
                        className="w-full rounded-md border border-gray-200 px-3 py-2 text-left text-sm text-gray-800 hover:bg-gray-50"
                      >
                        {option}
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <button
                type="button"
                onClick={() => void resolveProduct({ q: productQuery })}
                disabled={productBusy || productQuery.trim().length === 0}
                className="justify-self-start rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {productBusy ? "Resolving..." : "Resolve bioproduct"}
              </button>

              {productSeed && (
                <div className="grid gap-3 rounded-md border border-gray-200 bg-gray-50 p-3">
                  <dl className="grid grid-cols-2 gap-3">
                    <Field label="PubChem CID" value={productSeed.cid} />
                    <Field label="ChEBI" value={productSeed.chebi_id} />
                    <Field label="Formula" value={productSeed.molecular_formula} />
                    <Field label="Mol. weight" value={productSeed.molecular_weight} />
                    <div className="col-span-2">
                      <Field label="Preferred name" value={productSeed.preferred_name} />
                    </div>
                  </dl>

                  <div>
                    <p className="text-xs font-semibold uppercase text-gray-500">
                      Standard product class
                    </p>
                    {productSeed.product_class ? (
                      <p className="mt-0.5 text-sm text-gray-900">
                        {productSeed.product_class}
                        {productSeed.product_class_evidence && (
                          <span className="ml-2 text-xs text-gray-500">
                            matched on &ldquo;{productSeed.product_class_evidence}&rdquo;
                          </span>
                        )}
                      </p>
                    ) : (
                      <div className="mt-1 grid gap-1">
                        <p className="text-sm text-amber-700">
                          No rule matched — pick the class rather than letting the run guess.
                        </p>
                        <select
                          aria-label="Standard product class"
                          value={manualClass}
                          onChange={(event) => setManualClass(event.target.value)}
                          className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900"
                        >
                          <option value="">Select a class</option>
                          {productClasses.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>

                  <div>
                    <p className="text-xs font-semibold uppercase text-gray-500">
                      Search terms ({productSeed.search_terms.length})
                    </p>
                    <div className="mt-1">
                      <Chips values={productSeed.search_terms.slice(0, 12)} tone="blue" />
                    </div>
                    {productSeed.search_terms.length > 12 && (
                      <p className="mt-1 text-xs text-gray-500">
                        + {productSeed.search_terms.length - 12} more
                      </p>
                    )}
                  </div>

                  {productSeed.chebi_definition && (
                    <p className="text-xs text-gray-600">{productSeed.chebi_definition}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Create a run ─────────────────────────────────────────────── */}
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-4 py-3">
            <h3 className="text-sm font-semibold text-gray-800">New discovery run</h3>
            <p className="mt-0.5 text-xs text-gray-500">
              Searches PubMed, Europe PMC, Crossref and OpenAlex with every resolved term, then
              reconciles, deduplicates and judges the results.
            </p>
          </div>
          <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="grid gap-1 text-sm font-medium text-gray-700">
              Run name
              <input
                value={runName}
                onChange={(event) => setRunName(event.target.value)}
                placeholder="yarrowia-2016-2026"
                className="rounded-md border border-gray-300 px-3 py-2 text-sm font-normal text-gray-900"
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-gray-700">
              Year from
              <input
                type="number"
                value={yearFrom}
                onChange={(event) => setYearFrom(event.target.value)}
                className="rounded-md border border-gray-300 px-3 py-2 text-sm font-normal text-gray-900"
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-gray-700">
              Year to
              <input
                type="number"
                value={yearTo}
                onChange={(event) => setYearTo(event.target.value)}
                className="rounded-md border border-gray-300 px-3 py-2 text-sm font-normal text-gray-900"
              />
            </label>
            <label className="flex items-end gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={includeMentions}
                onChange={(event) => setIncludeMentions(event.target.checked)}
                className="mb-2.5"
              />
              <span className="mb-2">Include peripheral mentions</span>
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-gray-200 px-4 py-3">
            <button
              type="button"
              onClick={() => void handleCreateRun()}
              disabled={!canCreate || creating}
              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {creating ? "Queueing..." : "Queue discovery run"}
            </button>
            <span className="text-xs text-gray-500">
              {canCreate
                ? `Seed: ${seedKind.replace(/_/g, " ")} — ${
                    (organismSeed?.search_terms.length ?? 0) + (productSeed?.search_terms.length ?? 0)
                  } search terms`
                : "Resolve a seed and name the run first"}
            </span>
          </div>
        </div>

        {/* ── Existing runs ────────────────────────────────────────────── */}
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
            <h3 className="text-sm font-semibold text-gray-800">Runs</h3>
            <span className="text-xs text-gray-500">{runs.length} total</span>
          </div>
          {runs.length === 0 ? (
            <p className="px-4 py-6 text-sm text-gray-500">No runs yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
                  <tr>
                    <th className="px-4 py-2">Name</th>
                    <th className="px-4 py-2">Seed</th>
                    <th className="px-4 py-2">Years</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2">Candidates</th>
                    <th className="px-4 py-2">Progress</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {runs.map((run) => (
                    <tr key={run.id} className="hover:bg-gray-50">
                      <td className="px-4 py-2">
                        <Link
                          href={`/admin/datasheets/${run.id}`}
                          className="font-medium text-blue-700 hover:underline"
                        >
                          {run.name}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-gray-700">
                        {run.organism_name ?? run.product_term ?? "-"}
                        {run.organism_taxid ? (
                          <span className="ml-1 text-xs text-gray-500">taxid {run.organism_taxid}</span>
                        ) : null}
                      </td>
                      <td className="px-4 py-2 text-gray-600">
                        {run.year_from ?? "-"}-{run.year_to ?? "-"}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            STATUS_STYLES[run.status] ?? "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {run.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-gray-700">{run.candidate_count ?? "-"}</td>
                      <td className="max-w-sm truncate px-4 py-2 text-gray-600">
                        {run.error ?? run.progress_message ?? "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
