# RLALab AI Research Assistant

Internal RAG-based scientific literature assistant for the Rodrigo Ledesma-Amaro Lab, Department of Bioengineering, Imperial College London / Bezos Centre for Sustainable Protein.

**Access is restricted to lab members.** No public endpoint.

This README is for developers working on local setup, testing, ingestion, and deployment.

The frontend authenticates against the backend through same-origin Next.js route handlers and stores the backend bearer token in an `httpOnly` cookie. The browser does not need direct access to the token.

For architectural context, see `docs/architecture.md`. For a concrete implementation inventory, see `docs/components.md`.

---

## Architecture

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, Tailwind CSS 4, TypeScript |
| Backend | FastAPI, Python 3.12, SQLAlchemy 2 (async) |
| Database | PostgreSQL 16 + pgvector 0.7 |
| Embeddings | PubMedBERT (`microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext`) |
| LLM | Claude (`claude-sonnet-4-6`) via Anthropic API |
| Ingestion | Biopython Entrez (PubMed), PMC OA API, local PDF |

---

## Running it

**See [`run_and_deploy.md`](run_and_deploy.md)** — the single authoritative guide for running
and deploying this project. It covers the three scenarios (`local`, `compose`, `server`),
the configuration model, operations and troubleshooting.

The short version:

```bash
cp .env.example .env        # fill in SECRET_KEY, ANTHROPIC_API_KEY, POSTGRES_PASSWORD, NCBI_*
docker compose up -d --build
docker compose exec backend python scripts/create_user.py \
  --email you@imperial.ac.uk --password '<choose-one>' --role admin
# → http://localhost:3000
```

Postgres always runs as a container — there is nothing to install beyond Docker. For the dev
inner loop (backend and frontend on the host with reload), see `run_and_deploy.md` §4.

### Configuration in one paragraph

One variable names the scenario: `RLALAB_ENV = local | compose | server`, read by all four
components. `.env` holds **secrets and behaviour only — never a hostname, port or URL**, which
is what makes `source .env` safe in any shell. Addresses live in `.env.compose` / `.env.server`
and are read only by Compose. Defaults serve `local`, because Compose always injects values
explicitly and a bare shell cannot. Details: `run_and_deploy.md` §1 and CLAUDE.md §14.

## Tests

The repository now has both backend and frontend automated tests.

```bash
# Backend unit + integration tests
cd backend
python -m pytest tests

# Frontend unit tests
cd ../frontend
npm run test

# Frontend type-check
npm run type-check
```

Current coverage includes:

- Backend unit tests for indexing safeguards, incremental PubMed ingestion, SSE evaluation parsing, and PMC full-text parsing.
- Backend integration tests for auth, search, analytics, chat session loading, and chat streaming using FastAPI dependency overrides.
- Frontend unit tests for the login flow with Vitest, jsdom, and Testing Library.

---

## Ingesting Literature

After the backend is running and the database is ready:

```bash
cd backend
source .venv/bin/activate

# Full ingestion (all years configured in corpus.rlalab.toml)
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml

# Test run — 2024 only (~few hundred articles, fast)
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --year 2024

# Incremental update — only articles since a date
python -m pipelines.indexing.build_index \
  --config pipelines/configs/corpus.rlalab.toml \
  --from-date 2025-01-01
```

Notes:

- `--from-date` now performs date-bounded PubMed queries and skips PMIDs that are already present in the database, so incremental runs avoid re-embedding previously indexed articles.
- `--year YYYY` constrains the PubMed ingestion window to that exact publication year.
- PMC full-text ingestion now parses article metadata and body sections into normalized documents instead of storing raw XML payloads.
- Re-running indexing for an existing document replaces that document's chunk rows for the active embedding model instead of silently duplicating them.
- Persistent indexing currently requires the default PubMedBERT embedding because the database schema stores `vector(768)`. MiniLM remains available for experimentation, but not for writing a persistent index until a multi-dimension embedding table is added.

### After first full ingestion — create the vector index

The IVFFlat index must be built after data exists. Run this once:

```bash
psql postgresql://postgres:postgres@localhost:5433/rlalab_ai -c "
CREATE INDEX ix_chunks_embedding ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
"
```

## Evaluation

The retrieval and RAG evaluation harness can be run against a live backend once you have a valid JWT bearer token:

```bash
cd backend
source .venv/bin/activate

# Retrieval-only evaluation
python ../evaluation/run_eval.py --mode retrieval --api-url http://localhost:8000 --token <jwt>

# Full RAG evaluation via SSE consumption
python ../evaluation/run_eval.py --mode rag --api-url http://localhost:8000 --token <jwt>
```

RAG evaluation now consumes the streaming chat endpoint directly and writes full responses, sources, and latencies to `evaluation/reports/`.

Admins can manage the DB-backed evaluation workflow at `/admin/evaluation`.
The evaluation UI supports:

- creating question sets and individual benchmark questions;
- importing/exporting benchmark JSONL files such as `evaluation/benchmark/questions.jsonl`;
- creating queued run records and starting in-app background execution;
- importing JSON reports produced by `evaluation/run_eval.py`;
- inspecting run summaries and per-question retrieval/RAG results;
- assigning results to expert reviewers and recording 1-5 answer quality scores;
- comparing candidate runs against a baseline run;
- checking the default release gate for completed runs.

The CLI runner remains useful for local development and CI, while the admin UI
supports benchmark curation, execution, expert review, comparison, and release
decisions in the application.

Evaluation documentation is split for two audiences:

- `docs/evaluation-rationale-for-biologists.md` explains why the benchmark matters
  and how domain experts should interpret results.
- `docs/evaluation-metrics-and-benchmarking.md` defines retrieval/RAG metrics,
  expert scoring, comparison, and release-gate logic.

---

## Production Deployment

Full procedure in [`run_and_deploy.md`](run_and_deploy.md) §5. In brief:

```bash
cp .env.example .env         # strong SECRET_KEY, real credentials; chmod 600
# edit .env.server: set the real hostname in CORS_ORIGINS and APP_PUBLIC_URL
mkdir -p nginx/ssl           # supply nginx/nginx.conf + fullchain.pem/privkey.pem
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f backend
```

The production stack adds nginx (TLS) and does **not** publish Postgres. `RLALAB_ENV=server`
is set by the compose file — do not set it by hand. Pass `-f docker-compose.prod.yml` on every
command, or Docker will load the dev stack instead.

### Recommended hosting (Imperial/Bezos Centre)

- Azure Container Apps or Azure App Service (container deployment)
- Azure Database for PostgreSQL Flexible Server (supports pgvector natively)
- Reverse proxy: nginx or Azure Application Gateway
- Model weights: mount as a persistent volume, not bundled in the image

---

## Repository Structure

```
├── backend/               FastAPI application
│   ├── app/
│   │   ├── api/routes/    auth, chat, search, analytics, feedback
│   │   ├── core/          config, security, logging, resilience
│   │   ├── db/            models, session, crud
│   │   ├── embeddings/    PubMedBERT, MiniLM
│   │   ├── providers/     Anthropic (LLM)
│   │   └── rag/           pipeline, retrieval, generation, prompts, citations
│   ├── alembic/           database migrations
│   └── scripts/
│       └── create_user.py user provisioning
├── frontend/              Next.js 15 application
│   └── src/app/
│       ├── login/         login page
│       ├── chat/          main chat interface (SSE streaming)
│       └── analytics/     literature landscape charts
├── pipelines/             offline ingestion and indexing
│   ├── ingestion/         PubMed, PMC, local PDF ingesters
│   ├── processing/        normalizer, chunker, deduplicator
│   └── indexing/          build_index.py entry point
├── evaluation/            retrieval and answer quality benchmarks
├── docker-compose.yml     local dev
├── docker-compose.prod.yml production
└── .env.example           required environment variables
```

---

## Contact

**Roozbeh Pazuki** — roozbeh.pazuki@imperial.ac.uk  
RLA Lab, Department of Bioengineering, Imperial College London
