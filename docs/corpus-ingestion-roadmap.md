# Corpus Ingestion Persistence And Full-Text Roadmap

## Purpose

This document defines the roadmap for making RLALab AI Research Assistant's
offline ingestion pipeline reproducible, transferable, and extensible. The
current pipeline can ingest PubMed abstracts and local PDFs, then store
documents, chunks, and embeddings in Postgres/pgvector. The next step is to
make the corpus itself a durable artifact that can be resumed, audited, copied
between machines, and re-indexed without repeating every upstream download.

The target state is:

- Raw source material is stored locally before parsing or indexing.
- Normalized documents and chunks are cached in explicit machine-readable files.
- The vector database is rebuildable from local corpus cache artifacts.
- Full-text discovery is separated from full-text indexing.
- Licensed full-text access stays legal, credential-safe, and auditable.
- Lab-specific data beyond papers can be represented with clear provenance.

This is a local pipeline and data-contract plan, not a public runtime API.

## Current State

### PubMed abstracts

The PubMed abstract ingester currently stores only PMID checkpoint lists
locally. By default these live under:

```text
data/checkpoints/
```

Checkpoint files are JSON arrays of PMID strings, for example:

```text
data/checkpoints/pmids_2025.json
data/checkpoints/pmids_2025_2025-01-01.json
```

After PMID collection, the pipeline fetches PubMed XML with Entrez `efetch`,
parses each article into an in-memory `NormalizedDocument`, chunks the document,
embeds the chunks, and writes results to Postgres. The fetched XML, parsed
PubMed records, normalized documents, chunks, and embeddings are not currently
cached to local durable files before database ingestion.

This means the PMID discovery step can be resumed, but a failed or migrated run
still needs fresh PubMed `efetch` calls unless the database already contains the
records.

### Local PDFs

The PDF ingester reads PDFs from a configured directory, currently defaulting to:

```text
data/pdfs/
```

It extracts text with `pypdf`, creates a stable document id from the PDF file
hash, and writes the extracted full text directly into Postgres. The original
PDF is the only durable local source. Extracted text, page-level metadata,
parser version, OCR status, and chunk records are not cached as independent
files.

### PMC full text

`pipelines/ingestion/pmc_fulltext.py` exists and can fetch PMC open-access XML
for provided PMC IDs. It parses core metadata and article body text into
`NormalizedDocument` objects.

The main index builder does not yet wire `source = "pmc_fulltext"` into its
source selection, and there is no current first-class path that starts from
PubMed records, collects PMCID values, fetches PMC full text, caches the XML,
and indexes later from local files.

### Database state

The database currently stores:

- `ingestion_manifests`: run metadata and counts.
- `documents`: source metadata plus abstract/full text.
- `document_chunks`: chunk text and 768-dimensional PubMedBERT embeddings.

The database is necessary for search, but it should not be treated as the only
recoverable corpus artifact. A transferable corpus cache should be able to
rebuild these tables in an empty database.

## Reproducible Corpus Cache

Add a run-based cache layout under `data/corpora/`. `data/` remains gitignored;
the cache is transferred by archive, rsync, external object storage, or lab
storage, not by committing source material to Git.

Recommended layout:

```text
data/corpora/<corpus_name>/<run_id>/
  manifest.json
  config/
    corpus.toml
    ingestion.toml
  raw/
    pubmed/
      esearch/
        pmids_2000.json
        pmids_2001.json
      efetch/
        batch_000001.xml
        batch_000002.xml
    pmc/
      xml/
        PMC1234567.xml
      pdf/
        PMC1234567.pdf
    doi/
      discovery/
        doi_10.1000_example.json
    pdf/
      originals/
        <sha256>.pdf
  normalized/
    documents.jsonl
    documents.errors.jsonl
  chunks/
    chunks.jsonl
    chunks.errors.jsonl
  assets/
    asset_manifest.jsonl
  reports/
    acquisition_summary.json
    indexing_summary.json
```

### Manifest responsibilities

`manifest.json` should make each cache self-describing:

```json
{
  "schema_version": "1.0",
  "corpus_name": "rlalab-pubmed-v1",
  "run_id": "2026-05-21T120000Z",
  "created_at": "2026-05-21T12:00:00Z",
  "source": "pubmed_abstract",
  "query": "...",
  "date_from": "2000-01-01",
  "date_to": "2026-12-31",
  "embedding_model": "pubmedbert",
  "chunk_size": 512,
  "chunk_overlap": 64,
  "parser_versions": {
    "pubmed": "1",
    "pmc_jats": "1",
    "pdf": "1"
  },
  "counts": {
    "pmids": 0,
    "raw_records": 0,
    "normalized_documents": 0,
    "chunks": 0,
    "errors": 0
  }
}
```

### Transfer rule

To transfer a corpus between machines, copy:

- `data/corpora/<corpus_name>/<run_id>/`
- the project repository
- the relevant `.env` values for database and model configuration
- the embedding model cache if offline indexing is required

Then run a local-only indexing command that reads `normalized/documents.jsonl`
and `chunks/chunks.jsonl` instead of calling PubMed, PMC, DOI, or publisher
services.

## Data Contracts

### Normalized document JSONL

Each line in `normalized/documents.jsonl` should be one JSON object based on the
existing `NormalizedDocument` fields, extended with cache metadata:

```json
{
  "cache_id": "sha256:<hash>",
  "source_run_id": "2026-05-21T120000Z",
  "document_id": "pmid:12345678",
  "source": "pubmed",
  "title": "Article title",
  "abstract": "Abstract text",
  "full_text": null,
  "authors": [
    {
      "last_name": "Smith",
      "fore_name": "Jane",
      "initials": "J",
      "orcid": null
    }
  ],
  "journal": "Journal name",
  "publication_date": null,
  "year": 2026,
  "doi": "10.1000/example",
  "pmid": "12345678",
  "pmc_id": "PMC1234567",
  "mesh_terms": ["Metabolic Engineering"],
  "keywords": [],
  "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
  "license": "metadata-only",
  "ingested_at": "2026-05-21T12:00:00Z",
  "metadata": {},
  "raw_asset_path": "raw/pubmed/efetch/batch_000001.xml",
  "sha256": "<sha256-of-normalized-record-or-raw-asset>",
  "access_status": "metadata-only",
  "retrieved_at": "2026-05-21T12:00:00Z",
  "parser_version": "pubmed-v1"
}
```

Recommended `access_status` values:

- `metadata-only`
- `open-access`
- `licensed-access`
- `internal`
- `restricted`
- `unavailable`
- `failed`

### Chunk JSONL

Each line in `chunks/chunks.jsonl` should be one retrieval chunk:

```json
{
  "source_run_id": "2026-05-21T120000Z",
  "document_id": "pmid:12345678",
  "chunk_index": 0,
  "chunk_type": "abstract",
  "content": "Chunk content",
  "token_count": 184,
  "embedding_model": "pubmedbert",
  "embedding_status": "pending"
}
```

Embeddings may remain database-only initially. If embedding caches are added
later, store them in a separate file or table keyed by `document_id`,
`chunk_index`, and `embedding_model`, because embedding dimensions vary by
model.

### Asset manifest JSONL

Each file acquired or generated by the pipeline should have an asset record:

```json
{
  "asset_id": "sha256:<hash>",
  "document_id": "pmid:12345678",
  "asset_type": "pubmed_xml",
  "relative_path": "raw/pubmed/efetch/batch_000001.xml",
  "source_url": "https://eutils.ncbi.nlm.nih.gov/...",
  "sha256": "<hash>",
  "bytes": 12345,
  "retrieved_at": "2026-05-21T12:00:00Z",
  "access_status": "metadata-only",
  "license": "metadata-only",
  "terms_note": "NCBI PubMed metadata",
  "parser_version": null
}
```

## PubMed Abstract Pipeline

Add durable caching to the PubMed abstract flow in stages:

1. Preserve existing PMID checkpoints for resumable search.
2. Save every `efetch` response as raw XML before parsing.
3. Parse raw XML into normalized document JSONL.
4. Chunk normalized documents and write chunk JSONL.
5. Index from cached normalized/chunk JSONL into Postgres.

The pipeline should support these modes:

- `fetch`: network access allowed; populate raw and normalized cache.
- `normalize`: parse raw assets into `documents.jsonl` without network access.
- `chunk`: create `chunks.jsonl` from normalized documents.
- `index`: write cached documents and chunks to Postgres and generate embeddings.
- `all`: run the full pipeline.

This separation allows a networked machine to prepare the corpus and another
machine to perform indexing later.

## PDF Pipeline

For local PDFs, keep original PDFs content-addressed and cache extraction
outputs:

```text
raw/pdf/originals/<sha256>.pdf
normalized/documents.jsonl
assets/asset_manifest.jsonl
```

PDF extraction metadata should include:

- original filename
- content hash
- page count
- extraction library and version
- parser version
- text extraction status
- OCR status: `not-needed`, `needed`, `complete`, `failed`
- page-level text path if page text is stored separately
- detected title and PDF metadata

Scanned PDFs should not silently disappear from the corpus. If `pypdf` extracts
no text, write an error or pending-OCR record so the corpus report shows which
files require OCR.

## PMC And Open-Access Full Text

PMC full text is the cleanest full-paper path when a PubMed record has a PMCID
or when PubMed/NCBI linking can discover one.

Implement the open-access full-text path as:

1. Read PubMed-derived `documents.jsonl`.
2. Select records with `pmc_id`.
3. Fetch PMC OA XML and, when available, associated PDF assets.
4. Store raw JATS/XML under `raw/pmc/xml/`.
5. Parse JATS sections into `NormalizedDocument.full_text`.
6. Mark access as `open-access`.
7. Index full text from local cache.

The main index builder should accept `source = "pmc_fulltext"` or a local cache
source so this path becomes first-class rather than a standalone component.

Recommended JATS handling:

- Preserve section headings in text.
- Keep method/results/discussion labels where possible.
- Store article metadata separately from body text.
- Capture license text and license URL when present.
- Record parser failures in `normalized/documents.errors.jsonl`.

## DOI And Open-Access Discovery

PubMed records often contain DOI values even when no PMCID is present. Add a
discovery stage that uses DOI, PMCID, and PubMed identifiers to find legal
full-text sources.

Candidate discovery sources:

- PMCID from PubMed `ArticleIdList`.
- NCBI ELink or LinkOut metadata for related PMC records and publisher links.
- DOI landing pages for canonical publisher URLs.
- Open-access metadata services such as Unpaywall for OA locations and direct
  PDF links.
- Publisher-provided text and data mining APIs where available.

Discovery should not immediately download everything. It should create an
acquisition queue:

```json
{
  "document_id": "pmid:12345678",
  "pmid": "12345678",
  "pmc_id": null,
  "doi": "10.1000/example",
  "candidate_url": "https://publisher.example/article",
  "candidate_pdf_url": null,
  "route": "doi",
  "access_status": "candidate",
  "priority": "normal",
  "notes": "Publisher landing page found"
}
```

The acquisition queue lets the project separate discovery, access review, and
download policy.

## Licensed Full-Text Workflow

Many full papers will require institutional access. This project should support
legal, auditable, user-mediated acquisition through Imperial College London
library routes such as VPN, Shibboleth authentication, publisher institutional
login, and library helper tools.

Rules:

- Do not store Imperial, Shibboleth, publisher, or personal credentials.
- Do not bypass paywalls, DRM, CAPTCHAs, publisher controls, or terms of use.
- Do not use illicit sources.
- Do not automate bulk downloading unless the library or publisher terms allow
  it for text and data mining.
- Keep acquired full text local to authorized project storage.
- Record access method and provenance for each asset.

Recommended workflow:

1. Generate an acquisition queue from DOI/PMCID/PubMed metadata.
2. Let an authorized lab member authenticate in a normal browser session using
   VPN, Shibboleth, library proxy, or approved library tooling.
3. Download PDFs or XML only through permitted routes.
4. Store files under content-addressed paths in the corpus cache.
5. Record `access_status = "licensed-access"` and `access_method`.
6. Extract text locally and index only for authorized internal users.

For larger corpora, prefer formal text-and-data-mining routes through the
library or publishers instead of browser-driven downloads.

## Broader Lab Data Sources

The assistant should become useful for more than papers. A synthetic biology
and metabolic engineering lab can benefit from retrieval over operational,
experimental, and analytical records.

Recommended adapters:

### Scientific documents

- Lab publications, preprints, theses, reports, and supplementary files.
- Protocols and SOPs for cloning, transformation, fermentation, HPLC/GC-MS,
  microscopy, flow cytometry, plate readers, and sample preparation.
- Grant applications, project summaries, milestones, deliverables, and review
  documents where internal access is appropriate.

### ELN and LIMS records

- Experiment notes exported from ELN systems.
- Sample sheets and assay records.
- Experiment metadata: organism, strain, plasmid, media, conditions, timepoints,
  operator, project, and outcome.
- Links back to authoritative ELN/LIMS records rather than replacing them.

### Strains, plasmids, primers, and inventory

- Strain collections with genotype, phenotype, freezer location, project, and
  lineage.
- Plasmid maps, construct descriptions, resistance markers, promoters, genes,
  and sequence file references.
- Primer inventories and validation notes.
- Glycerol stocks and sample storage locations.

### Omics and sequencing

Do not embed raw FASTQ, BAM, or large binary files directly. Instead ingest:

- QC summaries such as FastQC/MultiQC outputs.
- Alignment and variant summaries.
- Differential expression tables.
- Pathway enrichment results.
- Metabolomics, lipidomics, and proteomics result tables.
- Genome annotations, gene lists, and feature summaries.
- Checksums and file paths to raw data stored elsewhere.

### Fermentation and analytical data

- Bioreactor run summaries: organism, media, feed, pH, dissolved oxygen,
  temperature, aeration, agitation, sampling times, yields, titers, rates.
- Plate reader outputs and growth curve summaries.
- HPLC, GC-MS, LC-MS, and lipid profiling tables.
- Calculated KPIs and figure-ready tables from notebooks.

### Operations and safety

- Stock orders, supplier information, lot numbers, and reagent inventories.
- SDS/COSHH documents and risk assessments.
- Instrument manuals, booking notes, maintenance records, calibration reports,
  and troubleshooting logs.
- Training material and onboarding guides.

### Models and code

- Genome-scale metabolic models, SBML files, COBRA outputs, and model summaries.
- Analysis notebooks with rendered markdown summaries.
- GitHub repository READMEs, release notes, and selected source docs.
- Data dictionaries and schema descriptions.

Each adapter should preserve original files, extract text/metadata, and attach
access-control metadata. Sensitive operational data should be flagged before it
is exposed through retrieval.

## Governance And Access Control

The corpus cache should preserve these distinctions:

- Raw asset: original XML, PDF, CSV, DOCX, XLSX, or exported file.
- Extracted text: parser or OCR output used for chunking.
- Normalized document: canonical metadata and text fields.
- Chunk: retrieval unit.
- Embedding: model-specific vector representation.

Every record should track:

- source system
- source URL or file path
- retrieval timestamp
- parser version
- checksum
- access status
- license or terms note
- sensitivity flag
- retention policy
- owner or steward when applicable

Recommended sensitivity values:

- `public`
- `internal`
- `licensed`
- `confidential`
- `personal-data`
- `restricted`

The RAG runtime should filter retrieval based on user role and source access
class before showing content. This is especially important for internal lab
records, project documents, personnel-linked records, and licensed full text.

## Implementation Phases

### Phase 1: Corpus cache foundation

Deliver:

- `data/corpora/<corpus_name>/<run_id>/` layout.
- `manifest.json`.
- `asset_manifest.jsonl`.
- normalized document JSONL writer and reader.
- chunk JSONL writer and reader.

Acceptance criteria:

- A PubMed test run writes raw or normalized cache artifacts.
- A local-only indexing command can read `documents.jsonl`.
- The cache can be copied to another path and still be readable.

### Phase 2: PubMed abstract reproducibility

Deliver:

- Raw PubMed `efetch` XML batch caching.
- Parser that can rebuild normalized documents from cached XML.
- Resume behavior that skips already cached batches.
- Error JSONL for failed records.

Acceptance criteria:

- Interrupting after raw XML cache can resume without repeating completed
  `efetch` batches.
- Running from cache produces the same document count as the networked run.

### Phase 3: PDF extraction persistence

Deliver:

- Content-addressed PDF storage.
- Extracted text cache.
- OCR-needed records for scanned PDFs.
- PDF extraction reports.

Acceptance criteria:

- Re-indexing PDFs does not require re-reading originals if extracted text
  cache is present.
- Scanned PDFs are reported as pending OCR rather than silently skipped.

### Phase 4: PMC open-access full text

Deliver:

- Main builder support for PMC full text.
- PMCID extraction from cached PubMed records.
- PMC XML cache and parser.
- Full-text chunking mode from local cache.

Acceptance criteria:

- A PMCID list can fetch and cache PMC XML.
- A local-only run can parse cached PMC XML and index full text.

### Phase 5: DOI and OA discovery

Deliver:

- DOI/PMCID discovery module.
- Acquisition queue JSONL.
- OA candidate classification.
- Download policy flags.

Acceptance criteria:

- PubMed records with DOI values produce acquisition candidates.
- Open-access candidates are separated from licensed or unknown candidates.

### Phase 6: Licensed full-text workflow

Deliver:

- User-mediated acquisition queue workflow.
- Credential-free browser/manual download guidance.
- Asset tracking for licensed PDFs.
- Terms and access-status metadata.

Acceptance criteria:

- Licensed PDFs can be added to the cache without storing credentials.
- Each licensed asset records access method, source, checksum, and status.

### Phase 7: Lab data adapters

Deliver:

- Adapter interfaces for structured local files and exported systems.
- Initial adapters for protocols, ELN/LIMS exports, inventories, and omics
  summaries.
- Access class filtering metadata.

Acceptance criteria:

- At least one protocol/SOP and one tabular lab-data source can be normalized,
  chunked, and indexed.
- Sensitive data can be flagged before retrieval exposure.

### Phase 8: Evaluation and operations

Deliver:

- Transfer/redo acceptance tests.
- Cache validation command.
- Corpus summary report.
- Documentation for backup, transfer, and re-indexing.

Acceptance criteria:

- Copying a cache directory to another machine can reproduce document and chunk
  counts.
- Tests cover PubMed cache resume, cached indexing, PMC XML parsing, and PDF
  extraction metadata.

## Future CLI Shape

The exact CLI can be decided during implementation, but the pipeline should move
toward explicit stages:

```bash
python -m pipelines.corpus_cache run \
  --config pipelines/configs/corpus.rlalab.toml \
  --stage fetch

python -m pipelines.corpus_cache run \
  --cache data/corpora/rlalab-pubmed-v1/2026-05-21T120000Z \
  --stage normalize

python -m pipelines.corpus_cache run \
  --cache data/corpora/rlalab-pubmed-v1/2026-05-21T120000Z \
  --stage index \
  --local-only
```

The important design constraint is that `--local-only` must never make network
calls. It should fail clearly if required local artifacts are missing.

## Risks And Mitigations

- Large local storage: use content-addressed files, compression for XML/JSONL,
  and retention policies by corpus run.
- Licensing ambiguity: record access status and terms; keep licensed assets
  internal; prefer library-approved TDM routes for large-scale full text.
- Parser drift: record parser versions and support re-normalization from raw
  assets.
- Mixed embedding dimensions: keep embeddings separate from document and chunk
  cache contracts.
- Sensitive lab records: add access-class metadata before exposing new source
  types through runtime retrieval.
- Operational complexity: implement in phases, starting with PubMed raw and
  normalized caching because that gives the biggest reproducibility win.

## Test Plan

Near-term documentation checks:

- Confirm this roadmap exists at `docs/corpus-ingestion-roadmap.md`.
- Confirm it covers current state, cache architecture, full text, licensed
  access, governance, implementation phases, and lab-data sources.
- Confirm `todo.md` contains feature items 9 through 18 as unchecked tasks.

Implementation tests to add later:

- PubMed ingestion can be interrupted after local caching and resumed without
  additional NCBI downloads for completed batches.
- Cached normalized JSONL can rebuild `documents` and `document_chunks` into an
  empty database.
- PMC full-text ingestion works from PMCID and can parse cached XML.
- PDF extraction cache records original files, extracted text, OCR-needed state,
  and checksums.
- A copied cache directory can reproduce document and chunk counts in local-only
  mode.

