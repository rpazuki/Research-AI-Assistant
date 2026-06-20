# Ingestion Guide

This guide describes how to run the implemented corpus ingestion and indexing
pipeline. For design rationale and future phases, see
`docs/corpus-ingestion-roadmap.md`.

The pipeline can now write a durable corpus cache under `data/corpora/`, then
rebuild the Postgres/pgvector index from local cache artifacts without repeating
upstream downloads.

## Prerequisites

Run commands from the repository root:

```bash
cd /Users/roozbeh/Research/Bezos_Centre/codes/RLALab-AI-Assistant
```

Use the backend virtual environment:

```bash
source backend/.venv/bin/activate
```

Required environment variables live in `.env`. At minimum:

- `DATABASE_URL`
- `NCBI_EMAIL`
- `NCBI_API_KEY` for PubMed network fetches

Local-only indexing does not call PubMed, PMC, DOI, or publisher services, but
it still needs `DATABASE_URL` and the configured embedding model.

## Main Config

The default corpus config is:

```text
pipelines/configs/corpus.rlalab.toml
```

The key field is:

```toml
[corpus]
source = "pubmed_abstract"
```

Supported implemented values are:

- `pubmed_abstract`
- `pmc_fulltext`
- `pdf`
- `lab_protocols`
- `eln_lims`
- `inventories`
- `omics_summaries`

## Cache Layout

Networked or extraction runs create a cache like:

```text
data/corpora/<corpus_name>/<run_id>/
  manifest.json
  config/corpus.toml
  raw/pubmed/efetch/*.xml
  raw/pmc/xml/*.xml
  raw/pdf/originals/*.pdf
  raw/pdf/extracted/*.txt
  raw/licensed/originals/*
  raw/lab/originals/*
  raw/lab/extracted/*.txt
  normalized/documents.jsonl
  normalized/documents.errors.jsonl
  chunks/chunks.jsonl
  assets/asset_manifest.jsonl
  acquisition/registered_assets.jsonl
  reports/acquisition_queue.jsonl
```

`data/` is gitignored. Transfer cache directories through lab storage, archive,
or `rsync`, not by committing source material.

## Cumulative vs per-run, auditabile runs

The default behaviour of build_index, creates a `data/corpora/rlalab-pubmed-v1/<run_id>/` folder, where `<run_id>` is a fresh timestamped. Therefore, cached data is separated per-run and usful for auditability. 

To make the runs cumulative, use `--cache <latest-incremental-folder>`, and then the cached data will be added into the same folder.

## PubMed Abstract Ingestion

This fetches PubMed PMIDs and raw XML, caches the XML, writes normalized
documents and chunks, embeds chunks, and indexes into Postgres:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml
```

To limit a test run to one year:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --year 2024
```

To run an incremental PubMed update:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --from-date 2026-05-01
```

The run writes:

- raw PubMed XML batches to `raw/pubmed/efetch/`
- normalized records to `normalized/documents.jsonl`
- chunks to `chunks/chunks.jsonl`
- source asset records to `assets/asset_manifest.jsonl`

## Local-Only Re-Indexing

Use this when a cache has already been created or copied from another machine.
This mode refuses to run without `--cache` and does not make network calls.

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --cache data/corpora/<corpus_name>/<run_id> \
  --local-only
```

The indexer reads `normalized/documents.jsonl` if present. If normalized records
are missing, it can rebuild them from local raw assets for the configured source:

- `raw/pubmed/efetch/*.xml` for `pubmed_abstract`
- `raw/pmc/xml/*.xml` for `pmc_fulltext`
- `raw/pdf/extracted/*.txt` for `pdf`

## Disabling Cache Writes

For a legacy-style run that indexes directly without writing cache artifacts:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --no-cache
```

Prefer cache-enabled runs for reproducibility.

## PDF Ingestion

Set the source and PDF directory in the config:

```toml
[corpus]
source = "pdf"

[pdf]
dir = "./data/pdfs"
```

Then run:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml
```

PDF ingestion now stores:

- content-addressed originals under `raw/pdf/originals/`
- extracted full text under `raw/pdf/extracted/`
- page-level extracted text JSON
- extraction metadata in the normalized document record
- OCR-needed errors in `normalized/documents.errors.jsonl`

Scanned PDFs with no extractable text are not indexed until OCR is added, but
they are recorded as `ocr_status = "needed"` so they can be reviewed.

## PMC Full-Text Ingestion

Set:

```toml
[corpus]
source = "pmc_fulltext"

[pmc]
ids = ["PMC1234567"]
sleep_between_batches_s = 0.5
```

Then run:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml
```

The PMC ingester caches raw JATS/XML under `raw/pmc/xml/`, parses article
metadata and body sections into normalized documents, and indexes full text.

You can also provide one PMCID per line:

```toml
[pmc]
pmc_id_file = "data/pmc_ids.txt"
```

If a cache already contains PubMed normalized records with `pmc_id` values, use:

```toml
[pmc]
from_cached_pubmed_documents = true
```

Then run with `--cache` so the PMCID list can be read from that cache.

## DOI/PMCID Acquisition Queue

To produce candidate full-text acquisition records from indexed documents:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --write-acquisition-queue
```

With an existing cache:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --cache data/corpora/<corpus_name>/<run_id> \
  --local-only \
  --write-acquisition-queue
```

By default the queue skips documents whose PMC full-text XML is already cached
under `raw/pmc/xml/<PMCID>.xml`. This avoids re-queuing records that the PMC
full-text ingestion workflow has already acquired. To intentionally include
already-cached PMC full text, for audit or refresh review, add:

```bash
--include-cached-fulltext
```

The queue is written to:

```text
reports/acquisition_queue.jsonl
```

Each record separates discovery from acquisition policy. PMCID candidates are
marked as open-access candidates; DOI candidates require access classification
before any download workflow.

## Licensed Full-Text Acquisition

Licensed or library-mediated full text is handled by a separate workflow from
ingestion and indexing. The pipeline does not log in, store credentials, bypass
access controls, or download paywalled full text. An authorized lab member must
obtain files through approved Imperial/library routes first, then register the
local file into the cache.

Export a spreadsheet-friendly queue for manual access review:

```bash
python -m pipelines.acquisition.fulltext export-review \
  --cache data/corpora/<corpus_name>/<run_id>
```

The export also filters already-cached PMC XML by default, even if an older
`reports/acquisition_queue.jsonl` still contains stale records. Use
`--include-cached-fulltext` to override that filter, and `--refresh-queue` to
regenerate the JSONL queue before exporting.

This writes:

```text
acquisition/review_queue.csv
```

After an authorized user has legally acquired a file, register the local asset:

```bash
python -m pipelines.acquisition.fulltext register-asset \
  --cache data/corpora/<corpus_name>/<run_id> \
  --file /path/to/downloaded/article.pdf \
  --document-id pmid:12345678 \
  --access-method imperial-library \
  --access-status licensed-access \
  --source-url https://doi.org/10.1000/example \
  --license licensed-access \
  --terms-note "Imperial library access for internal project use" \
  --acquired-by "authorized lab member"
```

For multiple already-downloaded PDFs, first create a CSV template:

```bash
python -m pipelines.acquisition.fulltext batch-template \
  --output acquisition_batch.csv
```

Fill one row per file. Required columns are `file`, `document_id`, and either
row-level `access_method` or a CLI default. Relative file paths are resolved
from the manifest directory unless `--base-dir` is supplied. Supported manifest
formats are `.csv`, `.jsonl`, and `.ndjson`.

Dry-run validation:

```bash
python -m pipelines.acquisition.fulltext register-batch \
  --cache data/corpora/<corpus_name>/<run_id> \
  --manifest acquisition_batch.csv \
  --default-access-method imperial-library \
  --dry-run
```

Register the batch:

```bash
python -m pipelines.acquisition.fulltext register-batch \
  --cache data/corpora/<corpus_name>/<run_id> \
  --manifest acquisition_batch.csv \
  --default-access-method imperial-library
```

Allowed access methods are:

- `imperial-library`
- `imperial-vpn`
- `shibboleth`
- `publisher-tdm`
- `author-provided`
- `manual-upload`

Registered assets are copied to:

```text
raw/licensed/originals/<sha256>.<ext>
```

and recorded in:

```text
assets/asset_manifest.jsonl
acquisition/registered_assets.jsonl
```

Indexing those files is a later local-ingestion step. Keep acquisition review,
manual download, and indexing as separate operations.

## Provenance And Access Tracking

Cache asset records include:

- checksum: `sha256`
- byte size
- source URL or local source path
- access status
- license or terms note
- source system
- access method
- sensitivity
- retention policy
- owner or steward

Normalized document records also carry cache metadata such as `cache_id`,
`raw_asset_path`, `access_status`, `parser_version`, `source_system`, and
`sensitivity`.

Validate a cache before transfer or local-only re-indexing:

```bash
python -m pipelines.corpus_cache validate \
  --cache data/corpora/<corpus_name>/<run_id>
```

The validator checks manifest presence, asset file existence, checksums, and
known access/sensitivity values.

## Local Lab Data Adapters

The lab-data adapters ingest local exports only. They do not connect to ELN (Electronic Lab Notebook),
LIMS (Laboratory Information Management System), inventory systems, cloud storage, or remote services.

### Protocols And SOPs

For Markdown/text protocol files:

```toml
[corpus]
source = "lab_protocols"

[lab_protocols]
dir = "./data/lab_protocols"
access_status = "internal"
sensitivity = "internal"
owner = "RLA Lab"
```

Then run:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml
```

Supported text extensions are `.md`, `.markdown`, and `.txt`.

### ELN/LIMS, Inventories, And Omics Summaries

For local CSV/TSV exports:

```toml
[corpus]
source = "inventories"  # or "eln_lims" / "omics_summaries"

[inventories]
dir = "./data/inventories"
access_status = "internal"
sensitivity = "confidential"
max_rows = 500
```

Then run the same index command. The adapter preserves the original table under
`raw/lab/originals/`, writes text summaries under `raw/lab/extracted/`, and
stores normalized document records with access-control metadata.

Use these adapters for exported summaries, not raw large binary data. For omics
and sequencing work, ingest QC summaries, result tables, annotations, and
pathway summaries rather than FASTQ, BAM, or other large raw files.

## Validation

Run the ingestion-related tests:

```bash
backend/.venv/bin/python -m pytest \
  backend/tests/test_corpus_cache.py \
  backend/tests/test_build_index.py \
  backend/tests/test_pubmed_ingester.py \
  backend/tests/test_pmc_fulltext.py
```

Run the full backend suite:

```bash
backend/.venv/bin/python -m pytest backend/tests
```

Run lint for the pipeline modules:

```bash
backend/.venv/bin/ruff check pipelines
```

Validate transfer/redo behavior:

```bash
python -m pipelines.corpus_cache validate \
  --cache data/corpora/<corpus_name>/<run_id>

python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --cache data/corpora/<corpus_name>/<run_id> \
  --local-only
```

## Operational Notes

- Keep `data/corpora/` backed up if the corpus needs to be reproducible.
- Do not commit raw XML, PDFs, extracted text, or generated cache files.
- Local-only mode should be used for transfer and redo checks.
- Keep licensed full-text acquisition separate from ingestion and indexing.
- Do not automate paywalled downloads or store institutional credentials in this project.
