# Ingestion Overview

This document gives a compact view of the corpus ingestion workflow. For
commands and operational details, see `docs/ingestion-guide.md`.

## Workflow Diagram

```text
+--------------------------------------------------------------+
| 1. Configuration                                             |
| pipelines/configs/*.toml + .env                              |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
| 2. Source ingestion                                           |
+----------------+----------------+----------------+------------+
| PubMed         | PMC full text  | Local PDFs     | Lab exports |
| abstracts      | JATS/XML       | PDF -> text    | text/tables |
+-------+--------+-------+--------+-------+--------+-----+------+
        |                |                |              |
        v                v                v              v
 raw/pubmed/       raw/pmc/xml/     raw/pdf/        raw/lab/
 efetch/*.xml      *.xml            originals/      originals/
                                    extracted/      extracted/
        \                |                |              /
         \               |                |             /
          v              v                v            v
+--------------------------------------------------------------+
| 3. Normalization                                             |
| normalized/documents.jsonl                                   |
| normalized/documents.errors.jsonl                            |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
| 4. Chunking                                                  |
| chunks/chunks.jsonl                                          |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
| 5. Embedding and database indexing                           |
| Postgres + pgvector                                          |
| documents, document_chunks, ingestion_manifests              |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
| 6. RAG-ready corpus                                          |
| Search, chat, analytics, and evaluation use the DB index      |
+--------------------------------------------------------------+

Side workflow A: DOI/PMCID acquisition queue

 normalized/documents.jsonl
        |
        v
+--------------------------------------------------------------+
| DOI/PMCID acquisition queue                                  |
| Skips raw/pmc/xml/<PMCID>.xml by default                     |
+------------------------------+-------------------------------+
                               |
                               v
 reports/acquisition_queue.jsonl
                               |
                               v
 acquisition/review_queue.csv

Side workflow B: licensed/manual full-text registration

 Authorized manual download
        |
        +-----------------------+------------------------------+
        |                       |                              |
        v                       v                              |
 register-asset          register-batch                        |
 single file             CSV/JSONL/NDJSON manifest             |
        |                       |                              |
        +-----------+-----------+                              |
                    v                                          |
 raw/licensed/originals/<sha256>.<ext>                         |
                    |                                          |
                    v                                          |
 assets/asset_manifest.jsonl                                   |
 acquisition/registered_assets.jsonl                           |

Side workflow C: cache validation and local-only re-indexing

 data/corpora/<corpus>/<run-or-cumulative>/
        |
        +--> python -m pipelines.corpus_cache validate
        |
        +--> build_index --cache <cache> --local-only
             rebuilds Postgres/pgvector without network calls
```

## Workflow Parts

| Part | Aim | Inputs | Outputs |
|---|---|---|---|
| Corpus config | Select the source, corpus name, embedding model, chunking, and source-specific settings. | TOML files in `pipelines/configs/*.toml`; environment variables such as `DATABASE_URL`, `NCBI_EMAIL`, and `NCBI_API_KEY`. | Runtime settings copied to `config/corpus.toml` inside the cache. |
| Cache layout | Preserve a portable, auditable copy of the run or cumulative corpus artifacts. | A new timestamped run, or an existing cache passed with `--cache`. | `data/corpora/<corpus_name>/<run_id-or-cumulative>/`, including `manifest.json`. |
| PubMed abstract ingestion | Build broad literature coverage from PubMed metadata and abstracts. | PubMed query, date range, optional `--from-date` or `--year`. | Raw XML in `raw/pubmed/efetch/*.xml`; normalized JSONL in `normalized/documents.jsonl`; asset provenance in `assets/asset_manifest.jsonl`. |
| PMC full-text ingestion | Fetch reusable full-text JATS/XML for articles available in PubMed Central. | PMCID list, PMCID file, or `from_cached_pubmed_documents = true` using cached PubMed records. | Raw JATS/XML in `raw/pmc/xml/*.xml`; normalized full-text records in `normalized/documents.jsonl`; errors such as unavailable OAI XML in `normalized/documents.errors.jsonl`. |
| Local PDF ingestion | Register and extract locally available PDFs for indexing. | A configured PDF directory. | Originals in `raw/pdf/originals/*.pdf`; extracted text in `raw/pdf/extracted/*.txt`; normalized records and extraction metadata in `normalized/documents.jsonl`. |
| Local lab data adapters | Ingest internal exports such as protocols, inventories, ELN/LIMS summaries, and omics summaries. | Local `.md`, `.txt`, `.csv`, or `.tsv` exports depending on source config. | Raw copies in `raw/lab/originals/*`; extracted text in `raw/lab/extracted/*.txt`; normalized records in `normalized/documents.jsonl`. |
| Normalization | Convert every source into a shared document schema. | Parsed PubMed, PMC, PDF, or lab records. | JSONL records in `normalized/documents.jsonl`; failures in `normalized/documents.errors.jsonl`. |
| Chunking | Split indexable text into retrieval units. | Normalized documents and chunk settings. | JSONL records in `chunks/chunks.jsonl` with document ID, chunk index, type, content, token count, and embedding status. |
| Embedding and indexing | Embed chunks and store searchable metadata plus vectors. | `chunks/chunks.jsonl`, embedding model, database connection. | Postgres rows in `documents`, `document_chunks`, and `ingestion_manifests`; pgvector embeddings in `document_chunks.embedding`. |
| Local-only re-indexing | Rebuild the database from cache without network calls. | Existing cache passed with `--cache` and `--local-only`. | Fresh Postgres/pgvector rows from cached normalized records or raw local assets. |
| DOI/PMCID acquisition queue | Identify full-text acquisition candidates from normalized documents. | Cached documents, optionally generated during `build_index --write-acquisition-queue`. | `reports/acquisition_queue.jsonl`. Records with cached `raw/pmc/xml/<PMCID>.xml` are skipped unless `--include-cached-fulltext` is set. |
| Manual review export | Produce a spreadsheet-friendly review queue for access decisions. | `reports/acquisition_queue.jsonl`; optional `--refresh-queue` and `--include-cached-fulltext`. | CSV file at `acquisition/review_queue.csv` by default. |
| Licensed full-text registration | Record files already acquired through approved library or manual routes. | One downloaded file via `register-asset`, or a CSV/JSONL manifest via `register-batch`. | Copied files in `raw/licensed/originals/<sha256>.<ext>`; provenance in `assets/asset_manifest.jsonl` and `acquisition/registered_assets.jsonl`. |
| Batch licensed registration | Register many already-downloaded PDFs or other supported full-text files at once. | `acquisition_batch.csv`, `.jsonl`, or `.ndjson` with `file`, `document_id`, and access metadata; optional `--dry-run`. | Same outputs as single-file registration, plus a JSON command summary of registered and failed rows. |
| Cache validation | Check that a cache can be transferred or re-indexed safely. | Existing cache directory. | JSON validation report from `python -m pipelines.corpus_cache validate`, including errors, warnings, and artifact counts. |

## Key File Formats

- `manifest.json`: JSON metadata for the cache run, including source, model,
  parser versions, chunking settings, and counts.
- `normalized/documents.jsonl`: one normalized document per line.
- `normalized/documents.errors.jsonl`: one failed or unavailable document event
  per line.
- `chunks/chunks.jsonl`: one chunk per line, pending embedding until indexed.
- `assets/asset_manifest.jsonl`: one raw or licensed asset provenance record per
  line, including checksum, byte size, access status, license, and sensitivity.
- `reports/acquisition_queue.jsonl`: candidate DOI/PMCID acquisition records.
- `acquisition/review_queue.csv`: spreadsheet-friendly manual review file.
- `acquisition/registered_assets.jsonl`: records linking manually registered
  full-text assets to document IDs.

## Cumulative Cache Rule

By default, `build_index` creates a timestamped cache folder for each run. To
append into a cumulative cache, pass the existing folder explicitly:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --cache data/corpora/<corpus_name>/cumulative
```

Use `--local-only` with `--cache` when the goal is to rebuild or generate
reports from existing cache artifacts without downloading anything.


## UI Run Modes

**Full run** is the same as the original script default:

```bash
python -m pipelines.indexing.build_index --config pipelines/configs/...
```

It reads the selected approved config, fetches/loads the configured source, creates a new cache if needed, chunks, embeds, indexes, and records a manifest.

**Incremental PubMed** update maps to the original --from-date option:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/pubmed_abstract.rlalab.toml \
  --from-date 2026-05-01
```

It is only allowed for pubmed_abstract configs. The pipeline loads existing PMIDs from the DB and skips duplicates.

**Single-year test** maps to the original --year option:

```bash
python -m pipelines.indexing.build_index \
  --config pipelines/configs/pubmed_abstract.rlalab.toml \
  --year 2024
```

It is also only allowed for pubmed_abstract configs. It overrides the configured year range just for that job.
