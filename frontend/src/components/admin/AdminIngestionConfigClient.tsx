"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  createIngestionConfig,
  getIngestionConfig,
  listDatasheetRuns,
  listIngestionConfigs,
  updateIngestionConfig,
} from "@/lib/api";
import type {
  DatasheetRunSummary,
  IngestionConfigContent,
  IngestionConfigSummary,
  TomlValue,
} from "@/types";
import AdminHeader from "./AdminHeader";

type SourceName =
  | "pubmed_abstract"
  | "pmc_fulltext"
  | "discovery_search"
  | "datasheet_manifest"
  | "datasheet_fulltext"
  | "datasheet_rows"
  | "pdf"
  | "lab_protocols"
  | "eln_lims"
  | "inventories"
  | "omics_summaries";

const DATASHEET_SOURCES: SourceName[] = [
  "datasheet_manifest",
  "datasheet_fulltext",
  "datasheet_rows",
];

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
  // Options filled at render time from live data rather than a fixed list.
  optionsSource?: "datasheet_runs";
}

const SOURCE_OPTIONS: { value: SourceName; label: string }[] = [
  { value: "pubmed_abstract", label: "PubMed abstracts" },
  { value: "pmc_fulltext", label: "PMC full text" },
  { value: "discovery_search", label: "Multi-source discovery search" },
  { value: "datasheet_manifest", label: "Datasheet run — manifest worklist" },
  { value: "datasheet_fulltext", label: "Datasheet run — fetched full text" },
  { value: "datasheet_rows", label: "Datasheet rows (CSV)" },
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
  discovery_search: [
    {
      section: "discovery",
      key: "organism_terms",
      label: "Organism terms",
      type: "list",
      required: true,
      wide: true,
      description:
        "One term per line. A candidate must match an organism term to be considered relevant at all.",
    },
    {
      section: "discovery",
      key: "product_terms",
      label: "Product terms",
      type: "list",
      wide: true,
      description:
        "One term per line. Product terms only promote an already relevant paper; they never rescue an off-topic one.",
    },
    {
      section: "discovery",
      key: "sources",
      label: "Sources",
      type: "list",
      description:
        "One per line: pubmed, europepmc, crossref, openalex. A source that fails is reported, not treated as zero results.",
    },
    {
      section: "discovery",
      key: "year_from",
      label: "Year from",
      type: "number",
      description: "Earliest publication year included in the search window.",
    },
    {
      section: "discovery",
      key: "year_to",
      label: "Year to",
      type: "number",
      description: "Latest publication year included in the search window.",
    },
    {
      section: "discovery",
      key: "max_records_per_source",
      label: "Max records per source",
      type: "number",
      description: "Upper bound on records fetched from each source before merging and deduplication.",
    },
    {
      section: "discovery",
      key: "include_mentions",
      label: "Include peripheral mentions",
      type: "checkbox",
      description: "Also index papers where a seed term appears outside the title and abstract focus.",
    },
    {
      section: "discovery",
      key: "include_reviews",
      label: "Include reviews",
      type: "checkbox",
      description: "Index review articles as well as primary research. Excluded by default.",
    },
    {
      section: "discovery",
      key: "check_retraction_notices",
      label: "Check retraction notices",
      type: "checkbox",
      description:
        "Run one extra PubMed search per included DOI to catch retractions not flagged in source metadata.",
    },
  ],
  datasheet_manifest: [
    {
      section: "datasheet",
      key: "run_dir",
      label: "Datasheet run",
      type: "select",
      required: true,
      wide: true,
      optionsSource: "datasheet_runs",
      description:
        "The finished datasheet run whose manifest drives this build. Its discovery manifest lists which papers were judged relevant.",
    },
    {
      section: "datasheet",
      key: "fetch_fulltext",
      label: "Fetch full text where available",
      type: "checkbox",
      description:
        "Fetch PMC full text for rows with a PMCID, falling back to the abstract when the full text is not retrievable.",
    },
    {
      section: "datasheet",
      key: "skip_metadata_only",
      label: "Skip rows without PMID or PMCID",
      type: "checkbox",
      description:
        "Manifest rows with neither identifier have a title and no abstract. Skipped by default; the count is logged.",
    },
    {
      section: "datasheet",
      key: "min_relevance",
      label: "Minimum relevance",
      type: "select",
      options: [
        { value: "studies", label: "studies (subject of the paper)" },
        { value: "mentions", label: "mentions (peripheral)" },
      ],
      description: "The weakest relevance verdict a manifest row may carry and still be indexed.",
    },
    {
      section: "datasheet",
      key: "include_reviews",
      label: "Include reviews",
      type: "checkbox",
      description: "Index review articles from the manifest as well as primary research.",
    },
  ],
  datasheet_fulltext: [
    {
      section: "datasheet",
      key: "run_dir",
      label: "Datasheet run",
      type: "select",
      required: true,
      wide: true,
      optionsSource: "datasheet_runs",
      description:
        "The run whose already fetched full text is indexed. No network calls are made: the text is read from the run's cache.",
    },
    {
      section: "datasheet",
      key: "min_relevance",
      label: "Minimum relevance",
      type: "select",
      options: [
        { value: "studies", label: "studies (subject of the paper)" },
        { value: "mentions", label: "mentions (peripheral)" },
      ],
      description: "The weakest relevance verdict a manifest row may carry and still be indexed.",
    },
    {
      section: "datasheet",
      key: "include_reviews",
      label: "Include reviews",
      type: "checkbox",
      description: "Index review articles from the run as well as primary research.",
    },
  ],
  datasheet_rows: [
    {
      section: "datasheet",
      key: "rows_csv",
      label: "Datasheet CSV",
      type: "text",
      required: true,
      wide: true,
      description:
        "CSV or TSV whose header matches the datasheet template. Each row becomes its own document so answers cite that row's paper.",
    },
    {
      section: "datasheet",
      key: "template_name",
      label: "Template name",
      type: "text",
      description: "Recorded on each row and used to keep row identities stable across rebuilds.",
    },
    {
      section: "datasheet",
      key: "access_status",
      label: "Access status",
      type: "text",
      description: "Access classification recorded on cached assets, such as internal or restricted.",
    },
    {
      section: "datasheet",
      key: "sensitivity",
      label: "Sensitivity",
      type: "text",
      description: "Sensitivity label stored with the curated rows' provenance metadata.",
    },
    {
      section: "datasheet",
      key: "owner",
      label: "Owner",
      type: "text",
      description: "Team or person responsible for the curated datasheet.",
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

// Sources that index a title and abstract rather than a body. Their chunks are
// smaller because the whole document usually fits in one.
const ABSTRACT_SOURCES: SourceName[] = [
  "pubmed_abstract",
  "discovery_search",
  "datasheet_manifest",
  "datasheet_rows",
];

function defaultConfig(source: SourceName, corpusName = "rlalab-pubmed-v1"): IngestionConfigContent {
  const isAbstractSource = ABSTRACT_SOURCES.includes(source);
  const common = {
    corpus: {
      name: corpusName,
      source,
      embedding_model: "pubmedbert",
    },
    chunking: {
      chunk_size: isAbstractSource ? 512 : 1024,
      chunk_overlap: isAbstractSource ? 64 : 128,
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
  if (source === "discovery_search") {
    return {
      ...common,
      discovery: {
        organism_terms: ["Yarrowia lipolytica"],
        product_terms: [],
        sources: ["pubmed", "europepmc", "crossref", "openalex"],
        year_from: 2016,
        year_to: new Date().getFullYear(),
        max_records_per_source: 5000,
        include_mentions: false,
        include_reviews: false,
        check_retraction_notices: false,
      },
    };
  }
  if (source === "datasheet_manifest") {
    return {
      ...common,
      datasheet: {
        run_dir: "",
        fetch_fulltext: true,
        skip_metadata_only: true,
        min_relevance: "studies",
        include_reviews: false,
      },
    };
  }
  if (source === "datasheet_fulltext") {
    return {
      ...common,
      datasheet: {
        run_dir: "",
        min_relevance: "studies",
        include_reviews: false,
      },
      indexing: { embedding_batch_size: 1 },
    };
  }
  if (source === "datasheet_rows") {
    return {
      ...common,
      datasheet: {
        rows_csv: "./data/datasheets/rows.csv",
        template_name: "default",
        access_status: "internal",
        sensitivity: "internal",
        owner: "RLA Lab",
      },
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
    <span className="flex min-w-0 items-center gap-1 font-medium text-gray-700">
      <span className="min-w-0 break-words">
        {label}
        {required ? <span className="text-red-600"> *</span> : null}
      </span>
      <span aria-hidden="true" className="group relative inline-flex flex-shrink-0">
        <span
          className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-gray-300 bg-white text-[10px] font-semibold leading-none text-gray-500"
        >
          ?
        </span>
        <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-64 max-w-[80vw] -translate-x-1/2 rounded-md border border-gray-200 bg-gray-950 px-3 py-2 text-xs font-normal leading-relaxed text-white shadow-lg group-hover:block group-focus-within:block">
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
  dynamicOptions,
}: {
  field: FieldDefinition;
  value: TomlValue | undefined;
  onChange: (value: TomlValue) => void;
  dynamicOptions?: { value: string; label: string }[];
}) {
  const label = (
    <LabelWithTooltip
      label={field.label}
      required={field.required}
      description={field.description}
    />
  );
  const fieldClassName = field.wide ? "min-w-0 md:col-span-2" : "min-w-0";

  // A select whose options come from live data falls back to a text input when
  // there is nothing to choose from. Rendering an empty dropdown would make a
  // required field unfillable — and a path typed by hand is still valid.
  const options = field.optionsSource ? dynamicOptions ?? [] : field.options;
  const isEmptyDynamicSelect =
    field.type === "select" && field.optionsSource !== undefined && options?.length === 0;

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
          className="w-full min-w-0 rounded-md border border-gray-300 px-3 py-2 font-mono text-sm"
        />
      </label>
    );
  }

  if (field.type === "select" && !isEmptyDynamicSelect) {
    return (
      <label className={`grid gap-1 text-sm ${fieldClassName}`}>
        {label}
        <select
          value={valueToInput(value, field) as string}
          onChange={(event) => onChange(parseInputValue(field, event.target.value))}
          className="w-full min-w-0 rounded-md border border-gray-300 px-3 py-2"
        >
          {field.optionsSource ? <option value="">Select a datasheet run…</option> : null}
          {options?.map((option) => (
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
        type={field.type === "select" ? "text" : field.type}
        step={field.step}
        value={valueToInput(value, field) as string}
        onChange={(event) => onChange(parseInputValue(field, event.target.value))}
        className="w-full min-w-0 rounded-md border border-gray-300 px-3 py-2"
        placeholder={isEmptyDynamicSelect ? "data/corpora/datasheets/<run>" : undefined}
      />
    </label>
  );
}

const MIN_LIST_WIDTH = 220;
const MAX_LIST_WIDTH = 560;
const DEFAULT_LIST_WIDTH = 320;

export default function AdminIngestionConfigClient() {
  // Draggable split between the config list and the editor, same interaction as
  // the chat sidebars. Config names and TOML lines are both long, so a fixed
  // 320px column forced truncation on one side or the other.
  const [listWidth, setListWidth] = useState(DEFAULT_LIST_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const splitRef = useRef<HTMLDivElement>(null);

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

  const [datasheetRuns, setDatasheetRuns] = useState<DatasheetRunSummary[]>([]);

  const source = sourceFromContent(content);
  const sourceFields = useMemo(() => SOURCE_FIELDS[source], [source]);

  const datasheetRunOptions = useMemo(
    () =>
      datasheetRuns
        .filter((run) => run.cache_path)
        .map((run) => ({
          value: run.cache_path as string,
          label: `${run.name} — ${run.candidate_count ?? 0} candidates (${run.status})`,
        })),
    [datasheetRuns]
  );

  useEffect(() => {
    void loadConfigs();
  }, []);

  useEffect(() => {
    // Only when a datasheet source is selected: an admin editing a PubMed config
    // has no reason to trigger a run listing.
    if (!DATASHEET_SOURCES.includes(source)) return;
    let cancelled = false;
    listDatasheetRuns()
      .then((runs) => {
        if (!cancelled) setDatasheetRuns(runs);
      })
      .catch(() => {
        // A failed listing is not an editing error: the run-dir field falls back
        // to a plain text input, which still accepts a valid path.
        if (!cancelled) setDatasheetRuns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [source]);


  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (event: MouseEvent) => {
      if (!splitRef.current) return;
      const bounds = splitRef.current.getBoundingClientRect();
      setListWidth(
        Math.max(MIN_LIST_WIDTH, Math.min(MAX_LIST_WIDTH, event.clientX - bounds.left))
      );
    };
    const handleMouseUp = () => setIsDragging(false);

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging]);

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

  return (
    <main className="min-h-screen bg-gray-50">
      <AdminHeader subtitle="Ingestion config" />

      <section className="mx-auto grid max-w-6xl gap-6 px-6 py-6">
        {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        {message && <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">{message}</div>}

        <div ref={splitRef} className="flex flex-col gap-6 lg:flex-row lg:gap-0">
          <aside
            // The dragged width belongs to the split layout only. Below `lg` the
            // panels stack and the splitter is hidden, so an inline pixel width
            // would leave a narrow orphan column above a full-width editor —
            // which is what put the dropdown in its own skinny box. Passing it as
            // a custom property lets the `lg:` variant apply it and nothing else.
            style={{ "--config-list-width": `${listWidth}px` } as CSSProperties}
            className="w-full min-w-0 max-w-full flex-shrink-0 overflow-hidden rounded-lg border border-gray-200 bg-white lg:w-[var(--config-list-width)]"
          >
            <div className="border-b border-gray-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-gray-800">Config file</h2>
            </div>
            <div className="grid min-w-0 gap-4 px-4 py-4 text-sm">
              <label className="grid min-w-0 gap-1">
                <LabelWithTooltip
                  label="Existing config"
                  description="Approved TOML file from pipelines/configs to load into the editor."
                />
                <select
                  value={selectedName}
                  disabled={loading || isCreating}
                  onChange={(event) => void loadConfig(event.target.value)}
                  className="w-full min-w-0 max-w-full truncate rounded-md border border-gray-300 px-3 py-2"
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
                <label className="grid min-w-0 gap-1">
                  <LabelWithTooltip
                    label="New filename"
                    description="Plain, non-conflicting .toml filename to create under pipelines/configs."
                  />
                  <input
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    className="w-full min-w-0 rounded-md border border-gray-300 px-3 py-2"
                  />
                </label>
              )}
              <div className="min-w-0 rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-600">
                <div className="font-semibold text-gray-700">Current path</div>
                <div
                  title={loadedPath || undefined}
                  className="mt-1 overflow-x-auto whitespace-nowrap pb-1 font-mono"
                >
                  {loadedPath || "New file under pipelines/configs"}
                </div>
              </div>
            </div>
          </aside>

          {/* Splitter. Hidden on narrow screens, where the panels stack. */}
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize config list"
            title="Drag to resize the config list"
            onMouseDown={() => setIsDragging(true)}
            onDoubleClick={() => setListWidth(DEFAULT_LIST_WIDTH)}
            className={`hidden w-1.5 flex-shrink-0 cursor-col-resize rounded transition-colors lg:mx-3 lg:block ${
              isDragging ? "bg-blue-400" : "bg-gray-200 hover:bg-blue-400"
            }`}
          />

          {/* min-w-0 so the editor can shrink: a flex child defaults to its content
              width, which would push the splitter off-screen on long TOML lines. */}
          <div className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white">
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
                      dynamicOptions={
                        field.optionsSource === "datasheet_runs" ? datasheetRunOptions : undefined
                      }
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
