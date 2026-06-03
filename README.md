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

## Prerequisites

- Python 3.12
- Node.js 20+
- PostgreSQL 16 with pgvector extension  
- An Anthropic API key  
- An NCBI API key (free, for PubMed ingestion)

### Install PostgreSQL + pgvector (if not using Docker)

```bash
brew install postgresql@16
brew install pgvector

# Start service
brew services start postgresql@16

# Create database
createdb rlalab_ai

# Enable pgvector extension
psql rlalab_ai -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

If `brew install pgvector` completes but PostgreSQL 16 still cannot see the `vector` extension, build it directly against the PostgreSQL 16 `pg_config`:

```bash
brew unpack pgvector --destdir /tmp/pgvector-src
cd /tmp/pgvector-src/pgvector-*
make PG_CONFIG="$(brew --prefix postgresql@16)/bin/pg_config"
make install PG_CONFIG="$(brew --prefix postgresql@16)/bin/pg_config"
psql rlalab_ai -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Or: use Docker (preferred)

```bash
# Start only the database container
docker compose up db -d
```

If your machine still exposes the legacy standalone binary, `docker-compose up db -d` is equivalent.


Use the follwoing command to make sure the postgres accept connection, and the db is running.
```bash
docker exec -it rlalab_db pg_isready -U postgres -d rlalab_ai
```
and next
```bash
docker exec -it rlalab_db psql -U postgres -d rlalab_ai
```
inside psql, run
```
SELECT current_database(), current_user, version();
\l
\dt
```
---

## Configuration — API Keys

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env` and set these required values:

```bash
# Your Anthropic API key — get one at https://console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...

# NCBI API key — free registration at https://www.ncbi.nlm.nih.gov/account/
# Without this, PubMed rate limit is 3 req/s instead of 10 req/s
NCBI_EMAIL=your.email@imperial.ac.uk
NCBI_API_KEY=your_ncbi_key_here

# Generate a strong secret key for JWT signing
# Run: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=replace_with_32_byte_hex_string
```

All other values in `.env` have working defaults for local development.

---

## Bootstrap — First Run

### 1. Backend setup

```bash
cd backend

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run database migrations
alembic upgrade head
```

If you already installed backend dependencies before 2026-05-12, refresh them once so the local model stack matches the pinned runtime-compatible versions:

```bash
pip install -e ".[dev]" --upgrade
```

The backend also pins `bcrypt<4.1` because newer releases break Passlib-backed password hashing in this project.

### 2. Create the first user

```bash
# From backend/ with venv active
python scripts/create_user.py \
  --email your.email@imperial.ac.uk \
  --password yourpassword \
  --role admin
```

To add more users (researcher role by default):

```bash
python scripts/create_user.py \
  --email colleague@imperial.ac.uk \
  --password theirpassword \
  --full-name "Jane Smith"
```

### 3. Frontend setup

```bash
cd frontend
npm install
```

The frontend proxies authenticated API calls through Next.js route handlers under `/api/auth/*` and `/api/backend/*`. For local development, `NEXT_PUBLIC_API_URL` must point to the FastAPI backend, which defaults to `http://localhost:8000`.

---

## Running in Development

Open three terminals:

**Terminal 1 — Backend**
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Frontend**
```bash
cd frontend
npm run dev
# → http://localhost:3000
```

**Terminal 3 — Database** (if using Docker)
```bash
docker compose up -d --build db
```

API docs available at: `http://localhost:8000/api/docs`


**Terminal 4 — dev on Docker and frontend on local** (if using Docker)
```bash
docker compose up -d db backend ingestion-worker
cd frontend
npm run dev -- --hostname 0.0.0.0
```

Notes:

- The first backend startup downloads the PubMedBERT checkpoint (~440 MB) into `backend/model_cache` unless it is already cached.
- Backend startup currently preloads the embedding model. The verified local-compatible stack is `torch 2.2.x` plus `transformers 4.51.x`; if startup fails with a `torch.load` safety error, rerun `pip install -e ".[dev]" --upgrade` from `backend/`.
- The frontend expects the backend at `http://localhost:8000` unless `NEXT_PUBLIC_API_URL` is overridden.
- To watch the ingestion worker, run
```bash
docker compose logs -f ingestion-worker
```

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
psql $DATABASE_URL -c "
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

---

## Production Deployment

```bash
# Copy and fill in production env (strong SECRET_KEY, real DB credentials)
cp .env.example .env
# edit .env ...

# Build and start all services
docker-compose -f docker-compose.prod.yml up -d

# Check logs
docker-compose -f docker-compose.prod.yml logs -f backend
```

Production compose includes: PostgreSQL, FastAPI backend (2 workers), Next.js frontend, nginx reverse proxy.

You must supply `nginx/nginx.conf` and SSL certificates at `nginx/ssl/` before using the production compose.

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
