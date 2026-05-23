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
  normalized/documents.jsonl
  normalized/documents.errors.jsonl
  chunks/chunks.jsonl
  assets/asset_manifest.jsonl
  reports/acquisition_queue.jsonl
```

`data/` is gitignored. Transfer cache directories through lab storage, archive,
or `rsync`, not by committing source material.

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

The queue is written to:

```text
reports/acquisition_queue.jsonl
```

Each record separates discovery from acquisition policy. PMCID candidates are
marked as open-access candidates; DOI candidates require access classification
before any download workflow.

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

## Operational Notes

- Keep `data/corpora/` backed up if the corpus needs to be reproducible.
- Do not commit raw XML, PDFs, extracted text, or generated cache files.
- Local-only mode should be used for transfer and redo checks.
- Licensed full-text acquisition is not implemented yet. Do not automate
  paywalled downloads or store institutional credentials in this project.
