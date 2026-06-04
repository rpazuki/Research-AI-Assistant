"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  createIngestionConfig,
  getIngestionConfig,
  listIngestionConfigs,
  logout,
  updateIngestionConfig,
} from "@/lib/api";
import type {
  IngestionConfigContent,
  IngestionConfigSummary,
  TomlValue,
} from "@/types";

type SourceName =
  | "pubmed_abstract"
  | "pmc_fulltext"
  | "pdf"
  | "lab_protocols"
  | "eln_lims"
  | "inventories"
  | "omics_summaries";

type FieldType = "text" | "textarea" | "number" | "checkbox" | "list" | "select";

interface FieldDefinition {
  section: string;
  key: string;
  label: string;
  type: FieldType;
  description: string;
  required?: boolean;
  options?: { value: string; label: string }[];
  step?: string;
  wide?: boolean;
}

const SOURCE_OPTIONS: { value: SourceName; label: string }[] = [
  { value: "pubmed_abstract", label: "PubMed abstracts" },
  { value: "pmc_fulltext", label: "PMC full text" },
  { value: "pdf", label: "Local PDFs" },
  { value: "lab_protocols", label: "Lab protocols" },
  { value: "eln_lims", label: "ELN / LIMS summaries" },
  { value: "inventories", label: "Inventories" },
  { value: "omics_summaries", label: "Omics summaries" },
];

const COMMON_FIELDS: FieldDefinition[] = [
  {
    section: "corpus",
    key: "name",
    label: "Corpus name",
    type: "text",
    required: true,
    description: "Names this corpus build and is stored in ingestion manifests and cache metadata.",
  },
  {
    section: "corpus",
    key: "source",
    label: "Source type",
    type: "select",
    required: true,
    description: "Selects which ingestion adapter and source-specific TOML section the pipeline will use.",
    options: SOURCE_OPTIONS,
  },
  {
    section: "corpus",
    key: "embedding_model",
    label: "Embedding model",
    type: "select",
    required: true,
    description: "Controls the model used to embed chunks before writing vectors into Postgres/pgvector.",
    options: [
      { value: "pubmedbert", label: "PubMedBERT" },
      { value: "minilm", label: "MiniLM" },
    ],
  },
];

const SOURCE_FIELDS: Record<SourceName, FieldDefinition[]> = {
  pubmed_abstract: [
    {
      section: "pubmed",
      key: "query",
      label: "PubMed query",
      type: "textarea",
      required: true,
      wide: true,
      description: "NCBI Entrez search expression used to collect candidate PubMed records.",
    },
    {
      section: "pubmed",
      key: "year_from",
      label: "Year from",
      type: "number",
      required: true,
      description: "Earliest publication year included in the PubMed search window.",
    },
    {
      section: "pubmed",
      key: "year_to",
      label: "Year to",
      type: "number",
      required: true,
      description: "Latest publication year included in the PubMed search window.",
    },
    {
      section: "pubmed",
      key: "batch_size",
      label: "Batch size",
      type: "number",
      required: true,
      description: "Number of PubMed records fetched per metadata request batch.",
    },
    {
      section: "pubmed",
      key: "sleep_between_batches_s",
      label: "Sleep between batches",
      type: "number",
      required: true,
      step: "0.01",
      description: "Delay between PubMed requests, used to respect NCBI rate limits.",
    },
  ],
  pmc_fulltext: [
    {
      section: "pmc",
      key: "ids",
      label: "PMC IDs",
      type: "list",
      description: "Optional explicit identifiers, one per line. PMCIDs, PMIDs, and DOIs are accepted by the pipeline.",
    },
    {
      section: "pmc",
      key: "pmc_id_file",
      label: "PMCID file",
      type: "text",
      wide: true,
      description: "Path to a local text file containing one PMCID per line for full-text ingestion.",
    },
    {
      section: "pmc",
      key: "from_cached_pubmed_documents",
      label: "Use cached PubMed PMCIDs",
      type: "checkbox",
      description: "Reads PMCIDs from an existing PubMed cache when the job is run with a cache path.",
    },
    {
      section: "pmc",
      key: "sleep_between_batches_s",
      label: "Sleep between batches",
      type: "number",
      required: true,
      step: "0.01",
      description: "Delay between PMC full-text fetches to keep upstream requests gentle.",
    },
  ],
  pdf: [
    {
      section: "pdf",
      key: "dir",
      label: "PDF directory",
      type: "text",
      required: true,
      description: "Local folder containing already acquired PDFs to extract and index.",
    },
  ],
  lab_protocols: [
    { section: "lab_protocols", key: "dir", label: "Directory", type: "text", required: true, description: "Local folder of Markdown or text protocol files to index." },
    { section: "lab_protocols", key: "access_status", label: "Access status", type: "text", description: "Access classification recorded on cached assets, such as internal or restricted." },
    { section: "lab_protocols", key: "sensitivity", label: "Sensitivity", type: "text", description: "Sensitivity label stored with local lab-source provenance metadata." },
    { section: "lab_protocols", key: "owner", label: "Owner", type: "text", description: "Team or person responsible for the local source material." },
    { section: "lab_protocols", key: "retention_policy", label: "Retention policy", type: "text", description: "Internal storage or retention rule recorded in asset metadata." },
  ],
  eln_lims: [
    { section: "eln_lims", key: "dir", label: "Directory", type: "text", required: true, description: "Local folder of CSV or TSV ELN/LIMS summary exports to index." },
    { section: "eln_lims", key: "access_status", label: "Access status", type: "text", description: "Access classification recorded on cached assets, such as internal or restricted." },
    { section: "eln_lims", key: "sensitivity", label: "Sensitivity", type: "text", description: "Sensitivity label stored with local lab-source provenance metadata." },
    { section: "eln_lims", key: "owner", label: "Owner", type: "text", description: "Team or person responsible for the local source material." },
    { section: "eln_lims", key: "retention_policy", label: "Retention policy", type: "text", description: "Internal storage or retention rule recorded in asset metadata." },
    { section: "eln_lims", key: "max_rows", label: "Max rows", type: "number", description: "Maximum rows from each table included in generated retrieval text." },
  ],
  inventories: [
    { section: "inventories", key: "dir", label: "Directory", type: "text", required: true, description: "Local folder of CSV or TSV inventory exports to index." },
    { section: "inventories", key: "access_status", label: "Access status", type: "text", description: "Access classification recorded on cached assets, such as internal or restricted." },
    { section: "inventories", key: "sensitivity", label: "Sensitivity", type: "text", description: "Sensitivity label stored with local lab-source provenance metadata." },
    { section: "inventories", key: "owner", label: "Owner", type: "text", description: "Team or person responsible for the local source material." },
    { section: "inventories", key: "retention_policy", label: "Retention policy", type: "text", description: "Internal storage or retention rule recorded in asset metadata." },
    { section: "inventories", key: "max_rows", label: "Max rows", type: "number", description: "Maximum rows from each table included in generated retrieval text." },
  ],
  omics_summaries: [
    { section: "omics_summaries", key: "dir", label: "Directory", type: "text", required: true, description: "Local folder of CSV or TSV omics summary exports to index." },
    { section: "omics_summaries", key: "access_status", label: "Access status", type: "text", description: "Access classification recorded on cached assets, such as internal or restricted." },
    { section: "omics_summaries", key: "sensitivity", label: "Sensitivity", type: "text", description: "Sensitivity label stored with local lab-source provenance metadata." },
    { section: "omics_summaries", key: "owner", label: "Owner", type: "text", description: "Team or person responsible for the local source material." },
    { section: "omics_summaries", key: "retention_policy", label: "Retention policy", type: "text", description: "Internal storage or retention rule recorded in asset metadata." },
    { section: "omics_summaries", key: "max_rows", label: "Max rows", type: "number", description: "Maximum rows from each table included in generated retrieval text." },
  ],
};

const ADVANCED_FIELDS: FieldDefinition[] = [
  { section: "chunking", key: "chunk_size", label: "Chunk size", type: "number", description: "Approximate token or word target for each retrieval chunk." },
  { section: "chunking", key: "chunk_overlap", label: "Chunk overlap", type: "number", description: "Amount of overlap retained between adjacent chunks to preserve context." },
  { section: "indexing", key: "embedding_batch_size", label: "Embedding batch size", type: "number", description: "Number of chunks embedded per model batch during indexing." },
];

function defaultConfig(source: SourceName, corpusName = "rlalab-pubmed-v1"): IngestionConfigContent {
  const common = {
    corpus: {
      name: corpusName,
      source,
      embedding_model: "pubmedbert",
    },
    chunking: {
      chunk_size: source === "pubmed_abstract" ? 512 : 1024,
      chunk_overlap: source === "pubmed_abstract" ? 64 : 128,
    },
  };

  if (source === "pubmed_abstract") {
    return {
      ...common,
      pubmed: {
        query: "(\"synthetic biology\"[Title/Abstract] OR \"metabolic engineering\"[Title/Abstract]) AND english[lang]",
        year_from: 2000,
        year_to: new Date().getFullYear(),
        batch_size: 20,
        sleep_between_batches_s: 0.15,
      },
    };
  }
  if (source === "pmc_fulltext") {
    return {
      ...common,
      pmc: {
        ids: [],
        pmc_id_file: "",
        from_cached_pubmed_documents: true,
        sleep_between_batches_s: 1,
      },
      indexing: { embedding_batch_size: 1 },
    };
  }
  if (source === "pdf") {
    return { ...common, pdf: { dir: "./data/pdfs" } };
  }
  const section = source;
  return {
    ...common,
    [section]: {
      dir: `./data/${source}`,
      access_status: "internal",
      sensitivity: "internal",
      owner: "RLA Lab",
      retention_policy: "internal-project-storage",
      ...(source === "lab_protocols" ? {} : { max_rows: 500 }),
    },
  };
}

function sourceFromContent(content: IngestionConfigContent): SourceName {
  const raw = content.corpus?.source;
  if (typeof raw === "string" && SOURCE_OPTIONS.some((source) => source.value === raw)) {
    return raw as SourceName;
  }
  return "pubmed_abstract";
}

function stemToCorpusName(filename: string) {
  return filename.replace(/\.toml$/, "") || "rlalab-pubmed-v1";
}

function normalizeContent(raw: IngestionConfigContent, filename: string): IngestionConfigContent {
  const source = sourceFromContent(raw);
  const corpusName =
    typeof raw.corpus?.name === "string" && raw.corpus.name
      ? raw.corpus.name
      : stemToCorpusName(filename);
  const base = defaultConfig(source, corpusName);
  return {
    ...base,
    ...raw,
    corpus: {
      ...base.corpus,
      ...raw.corpus,
      name: corpusName,
      source,
      embedding_model:
        typeof raw.corpus?.embedding_model === "string" && raw.corpus.embedding_model
          ? raw.corpus.embedding_model
          : "pubmedbert",
    },
  };
}

function valueToInput(value: TomlValue | undefined, field: FieldDefinition) {
  if (field.type === "list") return Array.isArray(value) ? value.join("\n") : "";
  if (field.type === "checkbox") return Boolean(value);
  if (value === null || value === undefined) return "";
  return String(value);
}

function parseInputValue(field: FieldDefinition, value: string | boolean): TomlValue {
  if (field.type === "checkbox") return Boolean(value);
  if (field.type === "number") {
    if (value === "") return null;
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : null;
  }
  if (field.type === "list") {
    return String(value)
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return String(value);
}

function LabelWithTooltip({
  label,
  required = false,
  description,
}: {
  label: string;
  required?: boolean;
  description: string;
}) {
  return (
    <span className="flex items-center gap-1 font-medium text-gray-700">
      <span>
        {label}
        {required ? <span className="text-red-600"> *</span> : null}
      </span>
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

function FieldControl({
  field,
  value,
  onChange,
}: {
  field: FieldDefinition;
  value: TomlValue | undefined;
  onChange: (value: TomlValue) => void;
}) {
  const label = (
    <LabelWithTooltip
      label={field.label}
      required={field.required}
      description={field.description}
    />
  );
  const fieldClassName = field.wide ? "md:col-span-2" : "";

  if (field.type === "checkbox") {
    return (
      <label className={`flex items-center gap-2 rounded-md border border-gray-200 px-3 py-2 text-sm text-gray-700 ${fieldClassName}`}>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(parseInputValue(field, event.target.checked))}
        />
        {label}
      </label>
    );
  }

  if (field.type === "textarea" || field.type === "list") {
    return (
      <label className={`grid gap-1 text-sm ${fieldClassName}`}>
        {label}
        <textarea
          value={valueToInput(value, field) as string}
          onChange={(event) => onChange(parseInputValue(field, event.target.value))}
          rows={field.type === "textarea" ? 8 : 5}
          className="rounded-md border border-gray-300 px-3 py-2 font-mono text-sm"
        />
      </label>
    );
  }

  if (field.type === "select") {
    return (
      <label className={`grid gap-1 text-sm ${fieldClassName}`}>
        {label}
        <select
          value={valueToInput(value, field) as string}
          onChange={(event) => onChange(parseInputValue(field, event.target.value))}
          className="rounded-md border border-gray-300 px-3 py-2"
        >
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    );
  }

  return (
    <label className={`grid gap-1 text-sm ${fieldClassName}`}>
      {label}
      <input
        type={field.type}
        step={field.step}
        value={valueToInput(value, field) as string}
        onChange={(event) => onChange(parseInputValue(field, event.target.value))}
        className="rounded-md border border-gray-300 px-3 py-2"
      />
    </label>
  );
}

export default function AdminIngestionConfigClient() {
  const router = useRouter();
  const [configs, setConfigs] = useState<IngestionConfigSummary[]>([]);
  const [selectedName, setSelectedName] = useState("");
  const [newName, setNewName] = useState("new.ingestion.rlalab.toml");
  const [isCreating, setIsCreating] = useState(false);
  const [content, setContent] = useState<IngestionConfigContent>(defaultConfig("pubmed_abstract"));
  const [loadedPath, setLoadedPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const source = sourceFromContent(content);
  const sourceFields = useMemo(() => SOURCE_FIELDS[source], [source]);

  useEffect(() => {
    void loadConfigs();
  }, []);

  async function loadConfigs(nextSelectedName?: string) {
    try {
      setLoading(true);
      const configData = await listIngestionConfigs();
      setConfigs(configData);
      const name = nextSelectedName || selectedName || configData[0]?.name || "";
      if (name) {
        await loadConfig(name);
      }
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load ingestion configs");
    } finally {
      setLoading(false);
    }
  }

  async function loadConfig(name: string) {
    const detail = await getIngestionConfig(name);
    setSelectedName(detail.name);
    setLoadedPath(detail.path);
    setContent(normalizeContent(detail.content, detail.name));
    setIsCreating(false);
    setMessage(null);
  }

  function startNewConfig() {
    setIsCreating(true);
    setSelectedName("");
    setLoadedPath("");
    setContent(defaultConfig("pubmed_abstract"));
    setNewName("new.ingestion.rlalab.toml");
    setMessage(null);
    setError(null);
  }

  function updateField(field: FieldDefinition, value: TomlValue) {
    if (field.section === "corpus" && field.key === "source" && typeof value === "string") {
      const currentName = typeof content.corpus?.name === "string" ? content.corpus.name : "rlalab-pubmed-v1";
      const next = defaultConfig(value as SourceName, currentName);
      next.corpus.embedding_model =
        typeof content.corpus?.embedding_model === "string"
          ? content.corpus.embedding_model
          : "pubmedbert";
      setContent(next);
      return;
    }

    setContent((current) => ({
      ...current,
      [field.section]: {
        ...(current[field.section] || {}),
        [field.key]: value,
      },
    }));
  }

  async function handleSave() {
    try {
      setSaving(true);
      const detail = isCreating
        ? await createIngestionConfig(newName, content)
        : await updateIngestionConfig(selectedName, content);
      setContent(normalizeContent(detail.content, detail.name));
      setSelectedName(detail.name);
      setLoadedPath(detail.path);
      setIsCreating(false);
      setMessage(`Saved ${detail.name}`);
      await loadConfigs(detail.name);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save ingestion config");
    } finally {
      setSaving(false);
    }
  }

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Admin</h1>
            <p className="text-sm text-gray-500">Ingestion config</p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/admin/ingestion" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Ingestion
            </Link>
            <Link href="/admin" className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Users
            </Link>
            <button type="button" onClick={handleLogout} className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl gap-6 px-6 py-6">
        {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        {message && <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">{message}</div>}

        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <aside className="rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-gray-800">Config file</h2>
            </div>
            <div className="grid gap-4 px-4 py-4 text-sm">
              <label className="grid gap-1">
                <LabelWithTooltip
                  label="Existing config"
                  description="Approved TOML file from pipelines/configs to load into the editor."
                />
                <select
                  value={selectedName}
                  disabled={loading || isCreating}
                  onChange={(event) => void loadConfig(event.target.value)}
                  className="rounded-md border border-gray-300 px-3 py-2"
                >
                  {configs.map((config) => (
                    <option key={config.name} value={config.name}>
                      {config.name}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" onClick={startNewConfig} className="rounded-md border border-blue-200 px-3 py-2 font-semibold text-blue-700 hover:bg-blue-50">
                New config
              </button>
              {isCreating && (
                <label className="grid gap-1">
                  <LabelWithTooltip
                    label="New filename"
                    description="Plain, non-conflicting .toml filename to create under pipelines/configs."
                  />
                  <input
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    className="rounded-md border border-gray-300 px-3 py-2"
                  />
                </label>
              )}
              <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-600">
                <div className="font-semibold text-gray-700">Current path</div>
                <div className="mt-1 break-words">{loadedPath || "New file under pipelines/configs"}</div>
              </div>
            </div>
          </aside>

          <div className="rounded-lg border border-gray-200 bg-white">
            <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-gray-800">{isCreating ? "Create TOML config" : "Edit TOML config"}</h2>
              <button
                type="button"
                disabled={saving || loading || (!isCreating && !selectedName)}
                onClick={() => void handleSave()}
                className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>

            <div className="grid gap-6 px-4 py-4">
              <section className="grid gap-4">
                <h3 className="text-sm font-semibold text-gray-800">Corpus</h3>
                <div className="grid gap-4 md:grid-cols-3">
                  {COMMON_FIELDS.map((field) => (
                    <FieldControl
                      key={`${field.section}.${field.key}`}
                      field={field}
                      value={content[field.section]?.[field.key]}
                      onChange={(value) => updateField(field, value)}
                    />
                  ))}
                </div>
              </section>

              <section className="grid gap-4">
                <h3 className="text-sm font-semibold text-gray-800">Source</h3>
                <div className="grid gap-4 md:grid-cols-2">
                  {sourceFields.map((field) => (
                    <FieldControl
                      key={`${field.section}.${field.key}`}
                      field={field}
                      value={content[field.section]?.[field.key]}
                      onChange={(value) => updateField(field, value)}
                    />
                  ))}
                </div>
              </section>

              <section className="grid gap-4">
                <h3 className="text-sm font-semibold text-gray-800">Chunking and indexing</h3>
                <div className="grid gap-4 md:grid-cols-3">
                  {ADVANCED_FIELDS.map((field) => (
                    <FieldControl
                      key={`${field.section}.${field.key}`}
                      field={field}
                      value={content[field.section]?.[field.key]}
                      onChange={(value) => updateField(field, value)}
                    />
                  ))}
                </div>
              </section>

              <details className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
                <summary className="cursor-pointer text-sm font-semibold text-gray-700">Structured preview</summary>
                <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-xs text-gray-700">
                  {JSON.stringify(content, null, 2)}
                </pre>
              </details>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
