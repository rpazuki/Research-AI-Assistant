# Organism/Bioproduct Datasheet Feature — implementation plan

**Status:** plan, awaiting approval. Derived from `docs/INGESTION_PLAN.md`,
`docs/investigation_summary.md`, `docs/investigation_access_routes.md`, and an audit of the
current codebase (2026-07-29).

**Goal.** An admin starts a search from an **organism** and/or a **bioproduct**. One job runs
discovery → acquisition → ingestion → field extraction and emits a **CSV shaped like
`docs/Yarrowia lipolytica Datasheet(2016-2026).xlsx`**, with the column set editable by admins.

**Delivery is split into two rounds** (owner decision, 2026-07-29). See §8 for the split and §8.0
for what each round does and does not deliver.

| | Scope | API cost | Gated on |
|---|---|---|---|
| **Round 1** | S0–S4 — corpus building: discovery, acquisition, ingestion, manifest CSV, extraction spike | **~$1** | nothing — starts now |
| **Round 2** | S5–S8 — extraction, datasheet CSV, numeric sidecar, gold scoring | ~$19/full run | the three open items in §9 |

Round 2 is deliberately deferred pending internal discussion. Deferring is **cost-neutral**: the
`assets/` cache and the content-hash result cache make the work order-independent, so nothing is
re-fetched or double-extracted later (§7.4).

---

## 0. Decisions on record

| # | Decision | Source |
|---|---|---|
| D1 | One job does discover → acquire → ingest → extract → CSV. Unfetchable papers still get a row, flagged. | owner, 2026-07-29 |
| D2 | CSV = the 17 datasheet columns first, in order, then a provenance block. **Column set is extensible** — admins can add columns. | owner, 2026-07-29 |
| D3 | Bioproduct terms resolve via PubChem/ChEBI synonyms; `Standard Product Class` (17 values) is the class vocabulary. | owner, 2026-07-29 |
| D4 | Admin-only, on its own page (not a tab under `/admin/ingestion`). | owner, 2026-07-29 |
| D5 | Acquisition: build OA routes now (no publisher TDM keys); OpenAthens/EZproxy/LibKey **is** available. | owner, 2026-07-29 |
| D6 | Extraction = one structured pass per paper over selected sections. | owner, 2026-07-29 |
| D7 | Import the 723-row Excel as a gold set; score extraction per column in the DB. | owner, 2026-07-29 |
| D8 | Shared corpus, tagged by organism/product + manifest. | owner, 2026-07-29 |
| D9 | Papers that only *mention* the organism are excluded. | `INGESTION_PLAN.md` §7.1 |
| D10 | Full text stays on local embeddings; only chunks sent to the external LLM. | `INGESTION_PLAN.md` §7.2 |
| D11 | Superlative/comparative questions must work → normalised numeric sidecar required. | `INGESTION_PLAN.md` §7.3 |
| D12 | Reviews included, flagged as reviews. | `INGESTION_PLAN.md` §7.4 |
| D13 | **Never merge on weak evidence.** Candidate identity is DOI/PMID/PMCID only — never title. A preprint and its published version ingested as two rows is acceptable; merging two distinct works is not. Downstream correctness comes from each row citing itself, so a duplicate is harmless as long as some paper backs the value. Title similarity is recorded as `possible_duplicate_of` for a human. | owner, 2026-07-30 |

---

## 1. Corrections to `INGESTION_PLAN.md` before we build to it

Two numbers in that document overstate what Phase 1 delivers. They come from Unpaywall's claim;
the same project's own reachability probe contradicts them.

| Claim in `INGESTION_PLAN.md` | What `investigation_access_routes.md` measured |
|---|---|
| "~146 free full texts left on the table" | 156 OA-but-unfetched, of which **~30 are served to a script**; 126 return HTTP 403 (Cloudflare), including **all 48 MDPI CC-BY papers** |
| "Step 4 alone moves full-text coverage from 32% → ~54%" | Realistic no-credentials gain is **32.3% → 36.5%** |
| "Publisher TDM APIs … up to 438" | Unauthenticated Crossref TDM links returned **0 articles out of 12 probed** (Elsevier serves a ~2 KB stub) |
| "Europe PMC full text — catches some PMC misses" | Europe PMC knows 60/156 of the queue, has full text for **12**; `fullTextXML` 404s even when `inEPMC=Y` |

**Consequence for sequencing.** Phase 0 (institutional access) is not a parallel nice-to-have — it
is the critical path for ~126 of the *free* papers as well as all 324 paywalled ones. With D5 (no
TDM keys, OpenAthens available) the ladder becomes: automated OA routes for the ~30 reachable, then
**assisted institutional acquisition** for everything else.

**On OpenAthens/EZproxy: no scripted login.** Driving an SSO login with stored credentials, then
bulk-pulling PDFs through the proxy, is the route most likely to trip publisher abuse detection and
get Imperial's whole IP range blocked. It is also credential handling we should not automate. The
plan therefore implements step 6 as **assisted acquisition**: the app generates a per-paper resolver
URL (LibKey/EZproxy/DOI), the admin opens it and downloads the PDF in their own browser, then drops
the files into an upload batch. That reuses `register_manual_assets_from_manifest()`, which already
exists. Ladder steps 1–4 stay fully automated.

---

## 2. What already exists (and what the plan reuses)

Verified in the tree, not assumed:

| Capability | Where | Reuse |
|---|---|---|
| Run-scoped corpus cache (`raw/ normalized/ chunks/ assets/ reports/ manifest.json`) | `pipelines/corpus_cache.py` (705 lines) | Datasheet runs get their own cache dir, same layout |
| DB-backed job queue + worker (`FOR UPDATE SKIP LOCKED`, heartbeat, `progress_callback`) | `backend/app/ingestion/worker.py`, `admin_service.py` | Copy the pattern for `datasheet_jobs`; one worker process serving both queues |
| Acquisition review queue → JSONL → CSV export, manual asset registration | `pipelines/acquisition/fulltext.py` (507 lines), `AdminAcquisitionQueueClient.tsx` | Assisted-acquisition step 6/7 |
| Config model: per-source TOML merged over `pipeline.defaults.yaml`, env last | `pipelines/config.py` | New `datasheet.rlalab.toml` + new default sections |
| Admin config editor UI | `frontend/src/app/admin/ingestion/config/page.tsx` | Template editor follows the same shape |
| Evaluation question sets / runs / results / reviews | `backend/app/db/models.py`, `app/evaluation/*` | Optional bridge: emit eval questions from gold cells |
| PubMed + PMC + PDF ingesters, chunker, deduper, embedder | `pipelines/ingestion/*`, `processing/*`, `indexing/build_index.py` | Unchanged; discovery feeds them a DOI/PMID list |

**Gaps that must be built (confirmed absent):**

1. No organism or taxid concept anywhere — PubMed query is a static TOML string.
2. `full_text_candidates()` emits only `pmcid` and `doi` routes. No Unpaywall, Crossref, OpenAlex,
   Europe PMC, or bioRxiv client exists in the tree.
3. **No LLM tool-calling / structured output at all.** `rag/pipeline.py` is retrieve → generate →
   cite; `LLMProvider` (`app/providers/base.py`) exposes only `complete()` and `stream()`. The
   INGESTION_PLAN premise "an LLM tool extracts the fields at query time" is unbuilt.
4. No per-document extracted-field storage, no numeric sidecar, no datasheet CSV writer.

**Dependency direction to preserve.** `pipelines/` imports nothing from `backend/app` (verified).
Backend imports pipelines. So: pure functions (template→schema, section selection, unit parsing, CSV
writing) go in `pipelines/`; anything needing the LLM provider or the DB session goes in
`backend/app/datasheet/`, mirroring `app/ingestion/` and `app/evaluation/`.

---

## 3. Architecture

```
  organism (NCBI taxid)  ─┐
                          ├─→  SEED RESOLUTION  → synonym set + product synonym set + class filter
  bioproduct (PubChem/ChEBI CID) ─┘
                          │
                          ▼
   ┌─ Phase A: DISCOVERY ─────────────────────────────────────────────┐
   │ PubMed · Europe PMC · Crossref · OpenAlex · bioRxiv              │
   │ → canonicalise (DOI normalise, preprint→VoR) → dedupe            │
   │ → relevance filter (studies vs mentions) → doc-type + review flag│
   │ → retraction check                                               │
   └──────────────────────────────────────────────────────────────────┘
                          │ datasheet_candidates rows
                          ▼
   ┌─ Phase B: ACQUISITION ladder (stop at first success) ────────────┐
   │ 1 PMC OA JATS · 2 Europe PMC · 3 bioRxiv JATS · 4 Unpaywall      │
   │ 5 publisher TDM (stub; needs key)                                │
   │ 6 ASSISTED: resolver URL → admin downloads → upload batch        │
   │ 7 manual / ILL                                                   │
   └──────────────────────────────────────────────────────────────────┘
                          │ JATS XML or PDF, cached under assets/
                          ▼
   ┌─ Phase C: INGESTION (existing build_index path) ─────────────────┐
   │ normalise → chunk (section-labelled) → embed locally → pgvector  │
   │ + sidecar columns on documents/document_chunks                   │
   └──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
   ┌─ Phase D: EXTRACTION ────────────────────────────────────────────┐
   │ template → JSON schema; one structured LLM pass per paper over   │
   │ title+abstract+Methods+Results(+SI tables); Batch API + caching  │
   │ → datasheet_rows.cells (value, confidence, evidence, tier)       │
   │ → numeric parse → datasheet_numeric_claims                      │
   └──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
   ┌─ Phase E: EXPORT + SCORE ────────────────────────────────────────┐
   │ datasheet.csv (17 cols + provenance + admin-added cols)          │
   │ gold-set diff → per-column accuracy                             │
   └──────────────────────────────────────────────────────────────────┘
```

Phases are **checkpointed per run**: a job records `phase` and per-phase counts, and can resume or
be re-run from any phase without repeating upstream network work (the corpus cache already
guarantees this for raw assets).

---

## 4. Database changes

### 4.1 New tables

**Round split.** Round 1's migration creates `datasheet_templates`, `datasheet_template_columns`,
`datasheet_runs`, `datasheet_candidates`. Round 2's migration adds `datasheet_rows`,
`datasheet_numeric_claims`, `datasheet_gold_rows`, `datasheet_gold_scores` — no point shipping four
unused tables. The S4 spike writes its findings to a report file under the run's cache
(`reports/extraction_spike.json`), not to the DB.

```sql
-- Column set is data, not code (D2).
CREATE TABLE datasheet_templates (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL UNIQUE,          -- 'rlalab-datasheet-v1'
    version       INTEGER NOT NULL DEFAULT 1,
    description   TEXT,
    is_default    BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata      JSONB
);

CREATE TABLE datasheet_template_columns (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id   UUID NOT NULL REFERENCES datasheet_templates(id) ON DELETE CASCADE,
    order_index   INTEGER NOT NULL,
    key           TEXT NOT NULL,                 -- stable snake_case id, e.g. 'carbon_source'
    label         TEXT NOT NULL,                 -- exact Excel header, e.g. 'carbon source'
    kind          TEXT NOT NULL,                 -- 'bibliographic'|'free_text'|'controlled'|'numeric'|'derived'
    vocabulary    JSONB,                         -- 17 Standard Product Class values, etc.
    extraction_hint TEXT,                        -- goes into the JSON-schema field description
    source_hint   TEXT NOT NULL DEFAULT 'any',   -- 'metadata'|'abstract'|'fulltext'|'any'
    required      BOOLEAN NOT NULL DEFAULT FALSE,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (template_id, key),
    UNIQUE (template_id, order_index)
);

CREATE TABLE datasheet_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    requested_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'queued',   -- queued|running|cancel_requested|cancelled|failed|succeeded
    phase         TEXT,                             -- discovery|acquisition|ingestion|extraction|export
    stop_after_phase TEXT NOT NULL DEFAULT 'export',
                                                    -- round 1 sets 'ingestion' so a run without
                                                    -- extraction completes as 'succeeded'
    seed_kind     TEXT NOT NULL,                    -- 'organism'|'bioproduct'|'organism_and_product'
    organism_name TEXT,
    organism_taxid INTEGER,
    organism_synonyms JSONB,
    product_term  TEXT,
    product_ids   JSONB,                            -- {pubchem_cid, chebi_id, inchikey}
    product_synonyms JSONB,
    product_classes TEXT[],                         -- filter against the 17-value vocab
    year_from     INTEGER,
    year_to       INTEGER,
    template_id   UUID REFERENCES datasheet_templates(id) ON DELETE SET NULL,
    template_snapshot JSONB NOT NULL,               -- frozen columns for reproducibility
    config_snapshot JSONB,
    cache_path    TEXT,
    manifest_id   UUID REFERENCES ingestion_manifests(id) ON DELETE SET NULL,
    csv_path      TEXT,
    candidate_count INTEGER, acquired_count INTEGER,
    ingested_count INTEGER, extracted_count INTEGER,
    prompt_tokens INTEGER, completion_tokens INTEGER, cached_tokens INTEGER,
    progress_message TEXT, log_tail TEXT, error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE datasheet_candidates (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL REFERENCES datasheet_runs(id) ON DELETE CASCADE,
    doi           TEXT, pmid TEXT, pmc_id TEXT,
    title         TEXT, journal TEXT, publisher TEXT, year INTEGER,
    found_in      TEXT[],                       -- ['pubmed','crossref','openalex']
    oa_status     TEXT, license TEXT,
    is_preprint   BOOLEAN NOT NULL DEFAULT FALSE,
    version_of_record_doi TEXT,
    doc_type      TEXT,                         -- 'primary'|'review'|'other'
    is_review     BOOLEAN NOT NULL DEFAULT FALSE,
    is_retracted  BOOLEAN NOT NULL DEFAULT FALSE,
    retraction_checked_at TIMESTAMPTZ,
    relevance     TEXT NOT NULL DEFAULT 'unknown',  -- 'studies'|'mentions'|'off_topic'|'unknown'
    relevance_reason TEXT,
    acquisition_route TEXT,                      -- 'pmc_oa'|'europepmc'|'biorxiv'|'unpaywall'|'publisher_tdm'|'assisted'|'manual'
    acquisition_status TEXT NOT NULL DEFAULT 'pending',
                                                 -- pending|fetched|blocked|paywalled|assisted_pending|failed|skipped
    resolver_url  TEXT,                          -- for assisted acquisition
    asset_path    TEXT,
    document_id   UUID REFERENCES documents(id) ON DELETE SET NULL,
    dedupe_group  TEXT,
    notes         TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_ds_candidates_run_doi ON datasheet_candidates(run_id, doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_ds_candidates_status ON datasheet_candidates(run_id, acquisition_status);

-- One row per paper (verified: the Excel is one row per paper; its 10 duplicate links
-- are accidental re-curations, not per-compound splits).
CREATE TABLE datasheet_rows (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL REFERENCES datasheet_runs(id) ON DELETE CASCADE,
    candidate_id  UUID NOT NULL REFERENCES datasheet_candidates(id) ON DELETE CASCADE,
    document_id   UUID REFERENCES documents(id) ON DELETE SET NULL,
    cells         JSONB NOT NULL,   -- {column_key: {value, confidence, evidence_quote,
                                    --  evidence_section, source_tier, chunk_ids}}
    source_tier   TEXT NOT NULL,    -- best tier available: 'fulltext'|'abstract'|'metadata'|'none'
    extraction_model TEXT, template_version INTEGER,
    prompt_tokens INTEGER, completion_tokens INTEGER,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',  -- unreviewed|accepted|corrected
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, candidate_id)
);

-- D11: vector search cannot rank numbers.
CREATE TABLE datasheet_numeric_claims (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    row_id        UUID NOT NULL REFERENCES datasheet_rows(id) ON DELETE CASCADE,
    compound      TEXT,
    compound_normalized TEXT,
    value_min     DOUBLE PRECISION,
    value_max     DOUBLE PRECISION,
    unit_raw      TEXT,
    unit_canonical TEXT,          -- 'g/L' | 'mg/g' | '%_dcw' | 'mL/gVS' | 'g/L/h' ...
    basis         TEXT,           -- 'per_volume'|'per_biomass'|'per_substrate'|'percent'|'rate'|'absolute'
    value_si      DOUBLE PRECISION,   -- NULL when bases are not comparable — do not fake it
    comparable    BOOLEAN NOT NULL DEFAULT FALSE,
    qualifier     TEXT,           -- 'max'|'titre'|'yield'|'productivity'
    cultivation_mode TEXT, scale TEXT,
    evidence_quote TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ds_numeric_compound ON datasheet_numeric_claims(compound_normalized);

-- D7: gold set from the existing Excel.
CREATE TABLE datasheet_gold_rows (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id   UUID REFERENCES datasheet_templates(id) ON DELETE SET NULL,
    source        TEXT NOT NULL,          -- 'excel:Yarrowia lipolytica Datasheet(2016-2026).xlsx'
    doi           TEXT, pmid TEXT, link TEXT,
    cells         JSONB NOT NULL,         -- {column_key: raw curated string}
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, link)
);

CREATE TABLE datasheet_gold_scores (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL REFERENCES datasheet_runs(id) ON DELETE CASCADE,
    column_key    TEXT NOT NULL,
    matched       INTEGER NOT NULL DEFAULT 0,
    partial       INTEGER NOT NULL DEFAULT 0,
    missed        INTEGER NOT NULL DEFAULT 0,
    not_in_gold   INTEGER NOT NULL DEFAULT 0,
    score         DOUBLE PRECISION,
    method        TEXT NOT NULL,          -- 'token_recall'|'llm_judge'
    detail        JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, column_key, method)
);
```

### 4.2 Additions to existing tables (the "metadata sidecar", `INGESTION_PLAN.md` §3)

```sql
ALTER TABLE documents
    ADD COLUMN taxids            INTEGER[],
    ADD COLUMN product_classes   TEXT[],
    ADD COLUMN publisher         TEXT,
    ADD COLUMN oa_status         TEXT,
    ADD COLUMN doc_type          TEXT,
    ADD COLUMN is_review         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN is_retracted      BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN retraction_checked_at TIMESTAMPTZ,
    ADD COLUMN preprint_of_doi   TEXT,
    ADD COLUMN full_text_source  TEXT,     -- pmc_jats|publisher_xml|pdf_grobid|pdf_text|abstract_only
    ADD COLUMN access_route      TEXT,
    ADD COLUMN chat_visible      BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE document_chunks
    ADD COLUMN section_label TEXT;         -- Introduction|Methods|Results|Discussion|SI|Abstract|Title

CREATE INDEX idx_documents_taxids ON documents USING gin(taxids);
CREATE INDEX idx_chunks_section  ON document_chunks(section_label);
```

`chat_visible` is the D8 safety valve: an off-domain datasheet run (say *E. coli* + succinate) still
lands in the shared corpus but is excluded from chat retrieval until an admin promotes it. Retracted
documents are excluded from chat retrieval unconditionally.

Migrations are hand-written (`mistakes.md`: alembic autogenerate misses vector/array changes; no
IVFFlat creation in a migration).

### 4.3 Retrieval changes

`backend/app/rag/retrieval.py::_apply_filters` gains `taxid`, `product_class`, `doc_type`,
`exclude_reviews`, `section_label` and hard-codes `is_retracted = FALSE AND chat_visible = TRUE`
for chat. `SearchResult` carries `section_label` and `is_review` so `citations.py` can cite to
section level.

---

## 5. Configuration

New `pipelines/configs/datasheet.rlalab.toml`:

```toml
[datasheet]
name = "rlalab-datasheet-v1"
template = "rlalab-datasheet-v1"
embedding_model = "pubmedbert"

[discovery]
sources = ["pubmed", "europepmc", "crossref", "openalex", "biorxiv"]
year_from = 2016
year_to = 2026
expand_organism_synonyms = true
max_candidates = 2000
relevance_mode = "rule_then_llm"      # rule filter first, LLM adjudicates the ambiguous tail
relevance_min_confidence = 0.6

[acquisition]
ladder = ["pmc_oa", "europepmc", "biorxiv", "unpaywall", "publisher_tdm", "assisted"]
prefer_xml = true
fetch_supplementary = true
per_host_delay_s = 2.0
per_host_max_attempts = 2
respect_robots = true
resolver_url_template = ""             # LibKey/EZproxy pattern; empty → plain doi.org link

[extraction]
model = "claude-sonnet-5"
escalation_model = "claude-opus-5"     # low-confidence / Not-reported cells only
use_batch_api = true
max_section_tokens = 24000
sections = ["title", "abstract", "methods", "results", "si_tables"]
cache_system_prompt = true

[numeric]
enabled = true
```

Additions to `pipelines/configs/pipeline.defaults.yaml`: `discovery:`, `acquisition.ladder:`,
`extraction:`, `numeric:` blocks with the same keys (per the established defaults-plus-override
pattern; no root `/configs` folder).

New env vars (`.env.example` + `core/config.py` + `pipelines/config.py`):

```
UNPAYWALL_EMAIL=
CROSSREF_MAILTO=
OPENALEX_MAILTO=
LIBKEY_RESOLVER_TEMPLATE=       # e.g. https://libkey.io/libraries/<id>/{doi}
EZPROXY_URL_TEMPLATE=           # assisted-acquisition link only; never used for scripted login
ELSEVIER_TDM_KEY=               # stub until Phase 0 lands
DATASHEET_EXTRACTION_MODEL=claude-sonnet-5
DATASHEET_ESCALATION_MODEL=claude-opus-5
DATASHEET_USE_BATCH_API=true
```

No secrets in the TOML. All access via `Settings` / `pipeline config`, never `os.getenv()` in
business logic.

---

## 6. New code

### `pipelines/discovery/` (pure, no DB, no LLM)
| File | Contents |
|---|---|
| `taxonomy.py` | taxid ↔ name via NCBI Taxonomy; synonym expansion (4952 → *Candida/Saccharomycopsis/Endomycopsis lipolytica*) |
| `product.py` | PubChem PUG-REST + ChEBI synonym/CID lookup; map to a `Standard Product Class` |
| `query_builder.py` | per-source query strings from the resolved synonym sets |
| `sources/{pubmed,europepmc,crossref,openalex,biorxiv}.py` | one thin client each, all through `resilience.pubmed_retry`-style decorators |
| `canonicalize.py` | DOI normalisation, preprint→VoR collapse, cross-source dedupe |
| `relevance.py` | rule pass (title/abstract term positions, MeSH); returns `studies`/`mentions`/`off_topic` + reason; ambiguous rows deferred to the LLM adjudicator in the backend |
| `doctype.py` | review detection (Crossref types 702/704 as plain `journal-article`, so infer) |
| `retraction.py` | PubMed `Retracted Publication` + Retraction Watch |

### `pipelines/acquisition/`
| File | Contents |
|---|---|
| `ladder.py` | ordered route resolution, per-route enable flags, stop-at-first-success, cache-once |
| `clients/{unpaywall,europepmc,biorxiv,pmc}.py` | fetchers; polite UA, per-host rate limit, robots check |
| `clients/publisher_tdm.py` | Elsevier/Wiley/Springer TDM — implemented but inert without a key; logs `blocked_needs_entitlement` |
| `assisted.py` | resolver-URL generation + review-queue row; **no scripted login, no proxy scraping** |
| `supplementary.py` | SI file discovery and download (the residual ~9% lives here) |
| `extract_text.py` | JATS-preferred text; GROBID-or-`pdf_local` for PDFs, with a Greek-character fidelity check (`Po1g-Δku70`, `ΔEYD`) |

### `pipelines/extraction/` (pure)
| File | Contents |
|---|---|
| `template.py` | load template → JSON schema (`additionalProperties: false`, per-column `description` from `extraction_hint`, `enum` for controlled columns) |
| `sections.py` | pick and budget title/abstract/Methods/Results/SI within `max_section_tokens` |
| `numeric.py` | unit parser/normaliser: `488.7 mg/L`, `13.4 mg/g WCO`, `400 mL CH₄ gVS⁻¹`, `36.7% lipid`, `6,370.39 mg/L (21.11 mg/g glucose)` → `(value, unit_canonical, basis, comparable)` |
| `csv_writer.py` | 17 labels first in Excel order, then provenance, then admin-added columns; `Not reported` for empty cells (matches the curators' convention) |
| `gold_import.py` | xlsx/csv → `datasheet_gold_rows`; handles the 4 broken date serials and the 10 duplicate links |
| `scoring.py` | per-column token-recall scorer (same method as `yarrowia_report.py`, so numbers stay comparable) + optional LLM judge |

### `backend/app/datasheet/`
| File | Contents |
|---|---|
| `admin_service.py` | run CRUD, template CRUD, candidate/row listing, CSV streaming, lookup endpoints |
| `worker.py` | claims `datasheet_jobs`, drives phases A–E, heartbeats, cancellable |
| `extractor.py` | one structured call per paper via the provider; batch submit/poll; escalation pass |
| `relevance_judge.py` | LLM adjudication of the ambiguous relevance tail (D9) |

### `backend/app/providers/base.py` — interface extension

Currently only `complete()` / `stream()`. Add:

```python
async def extract_structured(self, *, system: str, content: str, schema: dict,
                             max_tokens: int = 8192) -> tuple[dict, CompletionUsage]: ...
async def submit_batch(self, requests: list[BatchRequest]) -> str: ...
async def poll_batch(self, batch_id: str) -> BatchStatus: ...
async def fetch_batch_results(self, batch_id: str) -> AsyncIterator[BatchResult]: ...
```

`AnthropicProvider` implements these with `messages.parse()` / `output_config.format` and
`messages.batches.*`. Providers that cannot do structured output raise `NotImplementedError` — the
registry stays the single switch point.

**Round split.** Round 1 adds `extract_structured()` only — the relevance judge and the 20-document
S4 spike both call it synchronously, and 20 documents do not need batching. The three `*_batch`
methods land in round 2 with the full extraction pass.

### Frontend
| Path | Contents |
|---|---|
| `app/admin/datasheets/page.tsx` | R1 — run list + "New datasheet" wizard (organism autocomplete → taxid, product autocomplete → CID, year range, template, ladder toggles, max candidates) |
| `app/admin/datasheets/[runId]/page.tsx` | R1 — phase progress, counts, candidate table (filter by acquisition status), per-host request tallies, manifest CSV download, assisted-acquisition link list. **R2** adds the row table and datasheet CSV |
| `app/admin/datasheets/templates/page.tsx` | R1 — column editor: reorder, add, disable, edit label/kind/vocab/hint |
| `components/admin/AdminDatasheet*Client.tsx` | as above; typed `lib/api.ts` additions; all traffic via the `/api/backend/*` proxy, `httpOnly` cookie auth (no `localStorage` tokens) |

### API (`/api/v1/admin/datasheets`)

Round 1:
```
GET    /templates                     POST  /templates
GET    /templates/{name}              PUT   /templates/{name}
GET    /lookup/organism?q=            GET   /lookup/product?q=
GET    /runs                          POST  /runs
GET    /runs/{id}                     POST  /runs/{id}/cancel
GET    /runs/{id}/candidates          GET   /runs/{id}/manifest.csv
GET    /runs/{id}/acquisition-links.csv
```
Round 2 (✅ = built; `/runs/{id}/csv` shipped as `/runs/{id}/datasheet.csv`):
```
GET    /runs/{id}/rows            ✅   GET   /runs/{id}/datasheet.csv        ✅
POST   /runs/{id}/reextract       ✅   POST  /runs/{id}/extraction-estimate  ✅
POST   /runs/{id}/score                POST  /gold/import
GET    /gold/scores?run_id=
```

---

## 6.5 Rate limiting and block avoidance

Two distinct problems get conflated here. Only one is a rate limit.

**API quotas** (NCBI, Crossref, Unpaywall, OpenAlex) are documented and honourable — respect them
and we are never blocked.

**Publisher bot protection** (the 126 Cloudflare 403s in `investigation_access_routes.md`) is *not*
a rate limit. It is TLS/header fingerprinting: the probe received 403 on its **first** request to
those hosts. Slowing down does not fix it, and the probe's run-to-run variance (29–31 reachable)
is the tell that pushing harder makes it worse. **Therefore: never retry a 403.** Retrying is the
path from a per-request block to an IP-range block that affects colleagues.

### Already in the tree

`pipeline.defaults.yaml` carries `pubmed.sleep_between_batches_s = 0.15`,
`pmc.sleep_between_batches_s = 0.5`, and `pmc.http.{attempts,timeout_s,retry_backoff_*}`.
`backend/app/core/resilience.py` provides `pubmed_retry`, `llm_retry`, and `http_retry` (429 + 5xx,
exponential). The analysis project's probe already used a `mailto:` User-Agent and a shared lock
enforcing ≥1s per host — this section formalises that.

### To build — `pipelines/acquisition/ratelimit.py`

| Mechanism | Detail |
|---|---|
| Per-host token bucket + `min_interval_s` | Keyed on URL netloc, single asyncio lock |
| **Per-host concurrency = 1** | The single most effective control: one in-flight request per publisher, always |
| Global semaphore | Caps total in-flight fetches across all hosts |
| Honour `Retry-After` | On 429/503. Tenacity's exponential wait ignores the header — wrap it |
| Response classification | `200`+content → success · **`401/402/403` → `blocked`, zero retries, route to assisted** · `429/503` → Retry-After, ≤2 attempts · `5xx` → ≤2 attempts |
| Per-host circuit breaker | After 3 consecutive blocks, stop touching that host for the run and send its papers to assisted — stops 48 MDPI papers producing 48 × 403 |
| Fetch-once cache | Keyed `(doi, route)`; a document already under `assets/` is never re-requested, across runs |
| Honest identification | `RLALab-AI-Assistant/1.0 (+mailto:...)` UA and `mailto=` params for Crossref/Unpaywall/OpenAlex → their polite pools |
| robots.txt check | Before any publisher-direct fetch; cached per host per run |
| Kill switch | `max_requests_per_host_per_run` + an admin flag the running job polls (cancellation plumbing exists) |
| Visibility | Every request logged with host/status/latency; per-host tallies on the run detail page so blocks are visible, not silent |

Defaults (add to `pipeline.defaults.yaml` under `acquisition.rate_limits`):

| Host class | Min interval | Concurrency | On block |
|---|---|---|---|
| NCBI (with API key) | 0.10s | 1 | retry 5xx only |
| NCBI (no key) | 0.35s | 1 | — |
| Crossref (polite pool) | 0.05s | 2 | — |
| Unpaywall | 0.10s | 1 | — |
| OpenAlex (polite pool) | 0.10s | 2 | — |
| bioRxiv | 1.0s | 1 | — |
| Publisher direct | 3.0s | 1 | **circuit-break after 3, no retries** |

**Limits are only enforceable because there is one worker process.** A per-job limiter with two
concurrent jobs doubles real egress. The buckets live at process scope — a further reason the
datasheet queue shares the ingestion worker rather than running its own.

---

## 7. Extraction design (D6, D10)

**One call per paper.** Input: title + abstract + Methods + Results (+ SI tables when fetched),
budgeted to `max_section_tokens`. Output: one JSON object keyed by column, each value
`{value, confidence, evidence_quote, evidence_section}`. Schema is generated from the template, so
an admin adding a column automatically adds a schema field — no code change (D2).

### 7.0 Why sections, and why not retrieval-per-field

Two decisions that a later implementer would plausibly reverse, so the reasoning is recorded here.

**Extraction is document-driven, not query-driven.** The vector index serves the chat feature. The
extraction pass is a batch over documents we already hold, keyed by document ID, and does not touch
retrieval. Retrieval-per-field — embed "carbon source", fetch top-k chunks, extract from those — is
the natural reading of INGESTION_PLAN's "extract at query time", and it is the wrong tool for
*building* the datasheet:

1. **Retrieval can only subtract.** The whole document is already in hand. If the right chunk misses
   top-k the cell is unrecoverable, pushing achieved recall *below* the 90.9% ceiling §1 measures,
   in exchange for nothing.
2. **It breaks cross-field coherence — a correctness bug, not a cost one.** The 17 columns jointly
   describe one experiment. Excel row 2: strain `Po1g-Δku70` → final strain `Y29`, yield
   `488.7 mg/L (13.4 mg/g WCO)`, carbon source `waste cooking oil 6% v/v`. Per-field retrieval
   pairs the shake-flask control's titre with the bioreactor strain and reports it as one result.
3. **The best chunk for a field often lacks the field's vocabulary.** "YP medium … supplemented with
   6% v/v waste cooking oil" is a weak cosine match for "carbon source"; an LLM reading Methods gets
   it immediately. Same class of problem as `DGA1` vs diacylglycerol acyltransferase.
4. **17× the call overhead** — each call re-pays system prompt and schema.

**Section restriction is a precision guard, not a budget trick.** Introduction and Discussion
describe *other groups'* results ("previous work reported 400 mg/L lupeol"); reference lists are
dense with compound names, strain names, and yields. Feeding either risks attributing another
paper's numbers to this one — a fabrication that is invisible in the output, because the number is
real and only the attribution is wrong. Selection is rule-based (JATS `<sec>` labels; heuristic
headings for PDF-only, flagged when detection fails), so it is deterministic and auditable rather
than embedding-dependent.

**The token cap is an outlier backstop.** A typical 8-page article is ~6–9k words ≈ 10–14k tokens of
full text, of which Methods + Results is roughly half — so `max_section_tokens = 24000` does not
engage on the normal path, only on reviews and unusually long papers. This also means the ~20k
input/paper figure in §7.1 is closer to whole-document; with section filtering, expect 8–12k, making
the cost estimate conservative. S4's `count_tokens` measurement settles it.

**The one case where a narrowing step earns its place:** a paper whose Methods + Results alone
overflows the cap. A second pass then covers the remaining sections for **only the still-empty
cells** — the same escalation mechanism used for low-confidence cells, scoped so it never competes
with the primary pass.

**Legal fit with D10.** Full text is stored locally and embedded locally; the extraction call sends
selected *sections* of one paper to Anthropic. That is the same class of transfer as the chat
chunks, at higher volume. Flagging it explicitly because volume is the thing that changed, not the
category — please confirm before Step 4 runs on the real corpus.

**Cost, on today's published pricing.** ~700 papers × ~20k input tokens ≈ 14M input; 17 fields with
evidence ≈ 1.5k output/paper ≈ 1M output.

| Route | Input | Output | Run total |
|---|---|---|---|
| `claude-sonnet-5`, Batch API (50% off, intro rates to 2026-08-31) | $1.00/MTok | $5.00/MTok | **≈ $19** |
| `claude-sonnet-5`, Batch API (standard rates) | $1.50/MTok | $7.50/MTok | ≈ $29 |
| `claude-opus-5`, Batch API | $2.50/MTok | $12.50/MTok | ≈ $48 |

Batch API is the right fit: extraction is not latency-sensitive, batches take under an hour
typically, and results are keyed by `custom_id` (never by position). The shared system prompt +
template schema (~2–3k tokens) gets a `cache_control` breakpoint; per-paper content goes after it.
Cache reads are ~0.1× so this is worth doing even inside a batch. Verify with
`usage.cache_read_input_tokens` — if it stays zero, something upstream is varying the prefix.

Results cached by `(document_content_sha256, template_version, model)` so re-runs and template
tweaks only re-extract what actually changed.

**Escalation.** Cells returned with low confidence or `Not reported` get a second targeted pass on
`claude-opus-5`. Bounded to ≤10% of cells by default (~+$5).

### 7.1 What is and is not certain in that estimate

Discovery and acquisition are free APIs. Embedding is free — local PubMedBERT, per D10. **Only the
extraction pass costs money**, one call per paper.

| Input | Value | Confidence |
|---|---|---|
| Papers | ~700 | Solid (706 unique DOIs) |
| Input tokens/paper | ~20k | **Assumed — the weak number** |
| Output tokens/paper | ~1.5k | Assumed (17 fields × value + confidence + evidence quote) |
| Prices, batch discount, cache multipliers | as tabled above | Solid |

A full-text paper is frequently 40–80k tokens. If the per-paper estimate is 3× low, Sonnet-batch
becomes ~$47 (intro) / ~$68 (standard). **The conclusion holds either way: this is tens of dollars,
not thousands. Cost is not the binding constraint on the feature — acquisition is.** So the goal is
bounded and measured cost, not minimised cost.

### 7.2 Levers, ranked by actual effect

1. **Section budgeting — biggest by far.** Title + abstract + Methods + Results + SI tables instead
   of whole papers cuts input 2–3×, and `max_section_tokens = 24000` is a hard per-paper ceiling
   however long the paper is. It also improves precision — less Discussion prose to wander into.
2. **Batch API — flat 50%, no downside for offline work.** Code against: ≤100k requests/batch,
   256MB, usually <1h (24h max), results retained 29 days, and **results return in arbitrary order —
   key by `custom_id`, never by position.**
3. **Content-hash result cache** — re-runs cost $0 for unchanged papers. Note the coupling: adding a
   column bumps `template_version` and invalidates everything, so batch template edits together
   before re-running.
4. **Prompt caching — real but smaller than it sounds.** The shared system prompt + schema (~2–3k
   tokens) is identical across all 700 calls and reads at 0.1×, but per-paper content dominates the
   prefix, so expect ~10–15% off input, not 90%. The schema block clears the minimum cacheable
   prefix (1024 tokens on Sonnet 5, 512 on Opus 5). Verify via `usage.cache_read_input_tokens`; a
   persistent zero means something varies the prefix — a timestamp in the system prompt is the
   classic cause.
5. **Model tiering** — Sonnet 5 bulk, Opus 5 only on low-confidence/`Not reported` cells.
6. **Hard escalation cap** — so a poorly-performing batch cannot silently 10× the bill.

### 7.3 Guardrails so the estimate cannot hurt us

- **Measure before spending.** S4's 20-document spike runs `count_tokens` against the target model
  for the real per-paper figure. No full run launches off the estimate above.
- **Dry-run mode.** Resolve candidates, count tokens, report projected cost, stop. Admin approves
  before extraction spends anything.
- **`max_papers_per_run`** as a second ceiling.
- **Per-run counters.** `prompt_tokens` / `completion_tokens` / `cached_tokens` already exist on
  `datasheet_runs`; surface them on the run detail page so cost is observed, not inferred.
- **Refresh runs are near-free** — only genuinely new papers reach the model.

### 7.4 Cost of deferring extraction to round 2

Extraction is ~99% of the API spend; every other phase is free APIs plus local embedding.

| Phase | Round-1 API cost |
|---|---|
| Discovery (PubMed, Europe PMC, Crossref, OpenAlex, bioRxiv) | $0 — free APIs |
| Relevance adjudication (D9) | $0 rule-only, **~$0.60** for the LLM tail (~600 candidates × ~500 tok, batch) |
| Acquisition ladder + assisted | $0 |
| Ingestion + embedding | $0 — local PubMedBERT (D10) |
| S4 extraction spike | **~$0.50** (20 documents) |
| **Round 1 total** | **~$1** |

**Deferring is cost-neutral, not a saving deferred.**

| | Round 1 | Round 2 | Total |
|---|---|---|---|
| Extraction in round 1 | ~$19 | refresh only, ~$1 | **~$20** |
| Extraction deferred | ~$1 | ~$19 | **~$20** |

No double-spend, because `assets/` holds the original JATS/PDF bytes (never re-downloaded) and the
content-hash cache extracts each paper exactly once whenever that happens. **So cost is not an input
to the round-1/round-2 decision in either direction** — decide on schedule and risk instead.

**Round 1's real cost is wall-clock and human hours, not dollars.**
`fulltext.pmc.rlalab.toml` sets `embedding_batch_size = 1` because full-text chunks exhaust BERT
attention memory on Apple MPS — embedding ~700 full-text documents at that batch size is hours. Add
the assisted-acquisition downloads. Budget for those.

---

## 8. Sequencing

Each step ends green on the full suite (`backend/.venv/bin/python -m pytest tests/ -v` +
`npm test -- --run` + `npm run type-check`) before the next begins. `mistakes.md` read before every
test-writing step.

### 8.0 What each round delivers

**Round 1 (S0–S4) delivers:**
- Organism/bioproduct seed resolution — taxid and PubChem/ChEBI lookup with synonym expansion.
- Multi-source discovery closing the **27% PubMed blind spot**, canonicalised and deduped, with
  review and retraction flags.
- Acquisition ladder (automated OA routes) plus the assisted queue for the blocked and paywalled
  remainder, with the rate-limiting and circuit-breaking of §6.5.
- Full text ingested into the **shared corpus with the metadata sidecar** — which upgrades the
  *existing chat RAG* immediately: section-level citation, taxid filtering, retracted-work exclusion.
- A **manifest CSV** per run (DOI, PMID, journal, publisher, year, OA status, doc type, review flag,
  acquisition status, resolver URL) — this is the `INGESTION_PLAN.md` §3 deliverable: "emit a
  manifest, not a finished datasheet".
- A recorded XML-vs-PDF extraction decision from the S4 spike.

**Round 1 does NOT deliver:** the datasheet CSV, the 17 extracted columns, the numeric sidecar, or
gold scoring. A round-1 run sets `stop_after_phase = 'ingestion'` and completes as `succeeded` with
zero rows — not as a failure.

**Round 2 (S5–S8) delivers:** the extraction pass, the datasheet CSV, the numeric sidecar for
superlative queries (D11), gold-set scoring against the 90.9% ceiling, and the refresh loop.

### 8.1 Round 1 — corpus + spike (~$1 API)

| Step | Work | Acceptance |
|---|---|---|
| **S0** | Template model + round-1 migration (4 tables + `documents`/`document_chunks` sidecar columns); seed `rlalab-datasheet-v1` with the 17 columns and the 17-value `Standard Product Class` vocabulary (both already extracted from the Excel); template CRUD API + editor page | Admin can add a column and see it appear in the generated JSON schema; `psql` shows the seeded template; retrieval filters honour `is_retracted` / `chat_visible` |
| **S1** ✅ | Seed resolution: `taxonomy.py`, `product.py`, `product_classes.py`, `discovery/http.py`, `backend/app/datasheet/lookup_service.py`, `/lookup/{organism,product}`, seed page at `/admin/datasheets` | **Met, live:** `Yarrowia lipolytica` → taxid 4952 + 3 synonyms → 4 search terms; `hesperetin` → CID 72281 + CHEBI:28230 + 40 synonyms + `Flavonoids & Polyphenols` (matched on `flavanone`) |

**S1 correction to this plan.** The three NCBI synonyms of taxid 4952 are *Candida*,
*Endomycopsis* and **Mycotorula** *lipolytica* — not *Saccharomycopsis lipolytica*, which this
plan guessed. `Saccharomycopsis lipolytica` appears in the literature but resolves to no taxid at
all, so no taxonomy lookup can supply it. `organism_search_terms(seed, extra_synonyms=[...])`
therefore takes curator-supplied names, ordered after the authoritative ones so provenance stays
visible. **S2 must expose that as config** (`[discovery] extra_organism_synonyms`) — the ≥706-DOI
target may depend on names NCBI does not carry.
| **S2** ✅ | Discovery: 4 term-search clients (+ bioRxiv as a lookup client), canonicalise, dedupe, rule relevance, doc-type, retraction; `datasheet_candidates` + run list/detail UI + manifest CSV; runs driven by the shared ingestion worker | **Met, measured** (`pipelines/discovery/measure_recall.py`, 2026-07-30): 3,952 candidates from 8,833 source records; **699/706 gold DOIs = 99.0%**; **193/199 PubMed-missing = 97.0%**; 7,279 duplicates collapsed, 24 preprints merged into their VoR, 2 retracted flagged, 269 reviews flagged |

**S2 measured results and corrections to this plan.**

| Claim in this plan | Measured |
|---|---|
| "199 PubMed misses" | Confirmed exactly: 706 unique DOIs, 199 absent from PubMed (28.2%), 10 duplicate rows |
| bioRxiv as a discovery source | **bioRxiv has no term-search API.** Its endpoints are per-DOI or whole-server date listings. Preprints are discovered through Europe PMC `SRC:PPR` and OpenAlex, both of which index bioRxiv DOIs; `sources/biorxiv.py` is a *lookup* client providing the preprint→VoR link (`pubs/{server}/{doi}`) that `canonicalize.collapse_preprints` needs |
| Crossref for coverage | True, and it needs guards: `query.bibliographic` is fuzzy, so `Candida lipolytica` reports **27,471** results. Fixed with a per-term budget plus an early stop after 3 consecutive pages whose records do not mention the term — same recall, 4,014 records instead of 9,000 |
| LLM relevance tail (`rule_then_llm`) | Deferred within S2: the rule pass leaves **453/3,952 (11%)** as `unknown` (no abstract, no title hit). They are *kept*, not dropped, and flagged for adjudication. The judge is worth building on measured data rather than guessed volume |

**Per-source contribution to the gold set** (records returned): PubMed 1,686 · Europe PMC 1,886 ·
Crossref 4,014 · OpenAlex 3,669. OpenAlex is the single largest contributor of gold DOIs that no
other source returned.

**Known cost to revisit in S3:** the preprint→VoR lookup spends 1 request/second per 10.1101 DOI
(bioRxiv's quota) and tries both servers — measured 58 requests over 33 DOIs, 57 s. Resolve it
lazily at acquisition time instead (the preprint DOI's real use there is as a free full-text route
for a paywalled VoR), where S3's fetch-once cache also absorbs it across runs.

**S2 follow-up applied (D13, 2026-07-30).** An audit of the v4 run found title-based identity
merging **205 candidates that carried two or more distinct DOIs** — four separate peer-review
reports into one row, two book front-matter sections into another, and papers with their
figshare/Zenodo deposits. The last case lost work: the union of `types` made a paper inherit
`dataset`, doc-type then filed the *paper* as `other`, and **4 papers judged `studies` were dropped
from acquisition**; one row's identity became a Zenodo DOI. Now:

| Rule | Where |
|---|---|
| Identity is DOI / PMID / PMCID only — never title | `canonicalize._identity_keys` |
| Preprint→VoR merges only on an authoritative link (bioRxiv `pubs`, Crossref `relation`) | `canonicalize.collapse_preprints` |
| Title similarity recorded as `possible_duplicate_of` + evidence, never acted on | `canonicalize.flag_possible_duplicates`, migration `0009` |
| A dataset or repository DOI can never be a row's citable identity | `canonicalize.doi_class` + merge preference |
| DataCite object types (`dataset`, `collection`, `software`, …) classify as `other` | `doctype._OTHER_TYPES` |
| **S3** ✅ | `ratelimit.py` (token bucket, per-host concurrency 1, circuit breaker, `Retry-After`, kill switch, tallies) → `clients.py` (PMC OA · Europe PMC · bioRxiv · Unpaywall · TDM stub) → `ladder.py` → `assisted` resolver links + CSV → `extract_text.py` (JATS/PDF, section labels, Greek fidelity) → `acquisition_service.py` + worker phase B + run UI panel | **Met.** Live: PMC OA papers fetched as JATS with full section structure; Elsevier/MDPI/Wiley → `assisted_pending` with resolver URLs, **one** request each, never retried; per-host tallies and opened circuits shown in the UI |
| **S4** ✅ | `extraction_spike.py` — 20 real papers (14 JATS from PMC OA, 6 bioRxiv PDFs), fidelity + section structure + `count_tokens`. Writes `reports/extraction_spike.json` | **Met, measured 2026-07-30** — see below |

### S4 results (20 documents, Anthropic `count_tokens`, not an estimate)

| | JATS XML (14) | PDF (6) |
|---|---|---|
| Methods **and** Results recovered | 100% | 100% |
| Documents flagged character-corrupted | 0 | 0 |
| Δ characters preserved | 75 | 226 |
| Median tokens, selected sections | **7,544** | **18,164** |
| Median tokens, whole document | 10,548 | 22,736 |

**The §7.1 estimate is ~3× too high.** Median selected-section cost is **8,350 tokens/paper**
against the plan's 24,000 — a factor of **0.35**. Round 2's ~$19/full-run figure should be
re-derived before it gates anything; on this measurement it is closer to $7.

**Route preference: XML.** Not on fidelity — both formats preserved Δ and μ intact, and pypdf
recovered section headings from every PDF — but on **cost**: the same class of paper costs 2.4×
more tokens as PDF, because headers, footers and reference lists survive extraction. GROBID was
not installed, so the PDF arm is pypdf; on these numbers GROBID's operational cost is not yet
justified.

**Caveat worth carrying into round 2:** the PDF arm is bioRxiv preprints, which are born-digital
with a clean text layer. Publisher PDFs arriving through the assisted queue are a harder case, and
`character_fidelity` runs on every acquisition (`fidelity_warnings` on the run) so a bad batch
announces itself rather than being discovered in the datasheet.

**Order note.** The rate limiter lands *before* the fetchers in S3, not after — retrofitting
throttling onto working fetchers is how an IP block happens.

**S4 before round 2 is the point of including it.** It settles whether we should be asking humans to
fetch publisher XML rather than PDFs, and that answer changes the assisted queue before hundreds of
manual downloads are worked. Recoverability is not the concern — `assets/` keeps the original bytes,
so a bad parse is fixable by re-parsing locally — but route *preference* is awkward to change after
the fact.

### 8.2 Round 2 — extraction + datasheet (~$19/full run)

| Step | Work | Acceptance |
|---|---|---|
| **S5** ✅ | Round-2 migration (4 tables); provider `extract_structured` + `*_batch` + `count_prompt_tokens`; `pipelines/extraction/{sections,csv_writer}.py`; `app/datasheet/{extractor,export_service}.py`; worker phase D; rows/CSV/estimate API + run-page UI | **Met, 2026-08-07.** CSV renders the enabled template columns in spreadsheet order then the provenance block, `Not reported` for empty cells; dry run reports projected cost and stops; token counters recorded per run from actual usage |
| **S5a** ✅ | Batch lifecycle hardening: migration 0011, `cancel_batch`, park-and-re-claim (`awaiting_batch`), result cache, per-candidate outcome, `reextract`, `stop_after_phase` | **Met, 2026-08-11.** A live run can be cancelled without leaking a paid batch, survives a worker restart, leaves the ingestion queue usable while a batch runs, re-runs at near-zero cost for unchanged papers, and reports which papers failed and why. See the S5a table below |

**S5 decisions and corrections to this plan.**

| Claim in this plan | As built |
|---|---|
| `claude-sonnet-5` bulk + `claude-opus-5` escalation (open item (c)) | Confirmed as the default (2026-08-07). Escalation re-asks *only* the flagged columns rather than re-extracting the paper, and is capped by **cell** count (`datasheet_escalation_max_fraction`, default 10%) rather than by paper |
| "confirm before Step 4 runs on the real corpus" (open item (b)) | Enforced in code, not by convention: `DATASHEET_EXTRACTION_ENABLED` defaults to **false**, and a run with it off still reaches phase D to report a projection and stop. A caller cannot override it by passing `dry_run=False` |
| `~$19/full run` | S4 measured 8,350 tokens/paper against the plan's 24,000. On Sonnet 5 batch intro rates the same 700 papers project at **≈$11** (input ≈$5.8 + output ≈$5.3), and the dry run reports the real figure per run |
| Sampling parameters on the extraction call | Removed, and the chat path is now model-gated too. `temperature`/`top_p`/`top_k` are rejected with a 400 by Claude 5 models, so `AnthropicProvider.sampling_params()` drops them for any `-(opus\|sonnet\|haiku\|fable)-5+` model and keeps them for 4-series. Moving `LLM_MODEL` to Claude 5 is a config change, not a code change |
| Phase E ("export") | Built as a real phase, not a status label: `export_service.run_export_phase` writes `<run>/datasheet.csv` and records `csv_path` repo-relative, so a run's deliverable exists on disk beside the assets it came from. The HTTP download still renders from the rows on demand |
| Progress from phase D to completion | Reported line by line onto the run (`progress_message` + `log_tail`): token counting, batch submitted, per-poll `N done / M processing`, escalation, row count, export path. A batch can run for an hour, and a single unchanging message for that long is indistinguishable from a hung worker — which invites a restart mid-batch |
| `stop_after_phase` | New runs are created with `export`. Round-1 rows carry `ingestion` and still finish after acquisition, so an already-completed run does not change meaning when round 2 lands |
| §7.0's "second pass over the remaining sections" for over-cap papers | Not built. `sections.remaining_sections()` returns the input it needs and the cap did not engage on any S4-measured paper; wiring it before it is observed to matter would be speculative |

**S5a — hardening the live path (2026-08-11).** S5 shipped correct for the happy path with
extraction switched off. Four holes only bite once `DATASHEET_EXTRACTION_ENABLED` is on, which is
why they were closed before it is:

| Hole | As fixed |
|---|---|
| A cancelled run leaked a paid batch — nothing called `batches.cancel` | `LLMProvider.cancel_batch`, called from both cancellation paths: `request_cancel` (a parked run is not `running`, so no worker would ever look at it again) and the worker's collect path. Best-effort by contract: requests already in flight finish and are still billed, and the log says so rather than implying a refund. The batch id stays on the row so an uncollectable charge is named |
| A worker restart orphaned a paid batch — `batch_id` was a local variable | `datasheet_runs.extraction_batch_id` (+ `submitted_at`, `polled_at`), migration 0011. A column, not a `config_snapshot` key: the claim query filters on it |
| The 1–24h batch poll blocked the ingestion queue the same process serves (§6.5) | New status `awaiting_batch`. Submitting parks the run and returns; `claim_next_run` also takes parked runs whose `extraction_batch_polled_at` is older than `DATASHEET_BATCH_POLL_INTERVAL_S`, and collection polls **once**. A still-processing batch re-parks and reports "no work" so the loop sleeps instead of spinning. Resume needs no extra state: `plan_extraction` is deterministic over the candidates and cached payloads, and `custom_id` *is* the candidate id, so results match by identifier and never by position |
| §7.2 lever 3 (result cache) was never built | `datasheet_extraction_cache`, keyed `(content_sha256, template_version, model)` where the hash is of the **exact prompt text sent**, not of the document — change section selection or the budget and the cache correctly misses. Hits produce rows without a call and are excluded from the projected cost, so a dry run answers "what will this cost me now". Entries are written *after* escalation, so a re-run inherits the escalated values. Recorded trade-off: the key carries the bulk model only, so changing `DATASHEET_ESCALATION_MODEL` alone does not invalidate an entry; `escalated_cells` is stored so that stays visible |

Two operator gaps closed alongside them:

- **Failure attribution.** `datasheet_candidates.extraction_status` (`extracted | cached | refused |
  failed | no_text | over_cap`) and `extraction_error`. A failed paper has no `datasheet_rows` row
  by design — an empty row would be a fabricated line in the datasheet — so the candidate is the
  only place its reason can live. `3 failed` with no way to learn which three is not a report.
  Shown as a column on the run page, with the reason as its tooltip.
- **`POST /runs/{id}/reextract`** (§6's round-2 API list): clears the run's rows, resets the
  candidates' extraction fields and the batch columns, and re-queues with `phase='extraction'` —
  which is the worker's "start at D" signal, since a normal queued run has `phase = NULL`. With the
  result cache, a corrected extraction hint re-sends only the papers it actually affected. Refused
  with a 409 while the run is still active rather than racing the worker.
- **`stop_after_phase` on run creation** (`discovery | acquisition | export`, default `export`).
  Now that runs default to going the whole way, this is the only way to queue a discovery-only run
  and review the manifest before anything is fetched.
| **S6** | Numeric sidecar + comparative query path | "Highest lupeol titre" answers from `datasheet_numeric_claims`, not vector similarity; non-comparable bases reported as non-comparable rather than coerced to a fake SI value |
| **S7** | Gold import + per-column scoring + optional eval-question bridge | Per-column accuracy against the 90.9% ceiling, by the same token-recall method as `yarrowia_report.py` so numbers stay comparable; scores stored per run |
| **S8** | Refresh loop: re-check prior misses, retraction re-check, preprint→VoR promotion | A second run on the same seed reports new/changed/retracted deltas rather than re-fetching |

---

## 9. Risks and open items

| Risk | Handling |
|---|---|
| 46% of the corpus is paywalled; assisted acquisition is human-paced | R1: every candidate appears in the manifest CSV with its `acquisition_status`. R2: rows still emitted with `source_tier='abstract'` and a visible flag. Coverage is reported per run, never implied |
| PDF extraction mangles `Δ`, `Po1g-Δku70` | S4 gates the choice on measured fidelity; XML preferred wherever the ladder offers it |
| Token-recall scoring is an upper bound, not accuracy | Kept as the primary metric *because* it is comparable to the existing report; LLM judge offered as a second method, stored separately |
| `Family of Compounds` is uncontrolled (581 distinct values / 723 rows) | Left free-text; `Standard Product Class` (17 values) carries the controlled semantics. A normalisation pass is a later option, not S0 |
| Publisher rate limits / IP blocks | Per-host delay + max 2 attempts + robots respect + fetch-once caching. No bot-protection circumvention, no scripted proxy login |
| Extraction cost drift as the corpus grows | Batch API + prompt caching + content-hash result cache; per-run token counters surfaced in the UI |

### Open items, by round

| # | Item | Gates |
|---|---|---|
| a | LibKey/EZproxy resolver URL template for assisted links (`LIBKEY_RESOLVER_TEMPLATE`) | **S3.** Without it, assisted links fall back to plain `doi.org` — workable, just one more click per paper. Not a blocker. |
| b | Confirm that sending Methods/Results sections of ~700 papers to Anthropic sits within the D10 reading (same category as chat chunks; the change is volume) | **Round 2 / S5 only** |
| c | `claude-sonnet-5` bulk + `claude-opus-5` escalation, or Opus throughout? | **Round 2 / S5 only** — though S4 will produce evidence for the choice |

**Nothing in round 1 is blocked.** (b) and (c) are round-2 decisions; (a) has a working fallback.
