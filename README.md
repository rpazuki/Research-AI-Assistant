# RLALab AI Research Assistant

Internal RAG-based scientific literature assistant for the Rodrigo Ledesma-Amaro Lab, Department of Bioengineering, Imperial College London / Bezos Centre for Sustainable Protein.

**Access is restricted to lab members.** No public endpoint.

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

### Or: use Docker (preferred)

```bash
# Start only the database container
docker-compose up db -d
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
docker-compose up db
```

API docs available at: `http://localhost:8000/api/docs`

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

### After first full ingestion — create the vector index

The IVFFlat index must be built after data exists. Run this once:

```bash
psql $DATABASE_URL -c "
CREATE INDEX ix_chunks_embedding ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
"
```

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
