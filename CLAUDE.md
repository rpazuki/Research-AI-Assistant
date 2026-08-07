# CLAUDE.md — RLALab AI Research Assistant

**Last updated:** 2026-05-16  
**Project owner:** Roozbeh Pazuki (roozbeh.pazuki@imperial.ac.uk)  
**Lab:** Rodrigo Ledesma-Amaro Lab (RLA Lab), Department of Bioengineering, Imperial College London  
**Bezos Centre for Sustainable Protein**

---

## 1. Project Overview

RLALab AI Research Assistant is an internal RAG (Retrieval-Augmented Generation) application for the RLA Lab. It allows lab members (researchers, PhD students, postdocs) to query the scientific literature relevant to the lab's research domain — synthetic biology, metabolic engineering, yeast biology (especially *Y. lipolytica*), microbial communities, bioproduction, and sustainable food systems.

The system ingests documents from PubMed (abstracts and/or full text via PubMed Central), indexes them with domain-tuned embeddings, and answers researcher queries grounded exclusively in retrieved literature with citations.

**Target users:** 50–100 internal lab members (researchers and students at Imperial College London / Bezos Centre).  
**Access control:** Simple token/password authentication in iteration 1; OIDC/SSO ready for future.  
**No public-facing query interface** is included in any iteration.

---

## 2. Architecture Decision Record

All decisions recorded below were made explicitly by the project owner and must not be reversed without discussion.

| # | Decision | Detail |
|---|----------|--------|
| 1 | Internal use only | No public access. Simple auth (bearer token or username/password) for iteration 1. |
| 2 | No public query | The chatbot is for lab members only. No anonymous public endpoint. |
| 3 | Flexible ingestion | Ingestion pipeline must support abstract-only AND full-text. Pluggable sources (PubMed, PMC, DOI, local PDF). |
| 4 | Architecture: B+C hybrid | Modular Python code structure (Option B) WITH FastAPI backend + Next.js frontend (Option C). |
| 5 | Backend: FastAPI | REST API backend. All RAG logic lives in the backend. Frontend only calls API. |
| 6 | Database: Postgres + pgvector | Single database for metadata, users, sessions, and vector embeddings. No separate vector service. |
| 7 | Primary embedding: PubMedBERT | `microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext` as primary. Secondary embeddings available (see §7). |
| 8 | Evaluation harness | Formal evaluation phase with benchmark questions, retrieval metrics, and answer quality scoring. See §10. |
| 9 | LLM provider: Claude | `claude-sonnet-4-6` as primary. Provider abstraction layer allows switching. No Groq/Llama in production. |
| 10 | Resilience | All external calls (LLM API, embedding, PubMed API) implement retries, exponential backoff, timeouts, and rate-limit handling. |
| 11 | Frontend: Next.js | React-based SSR frontend with TypeScript. Tailwind CSS for styling. |
| 12 | Completeness gate | This plan must be complete enough for a second agent to begin implementation without design ambiguity. |

---

## 3. Repository Structure

```
RLALab-AI-Assistant/
├── CLAUDE.md                        ← This file. Architecture reference for agents.
├── README.md                        ← Developer-facing setup, testing, and operations guide
├── docker-compose.yml               ← Local dev orchestration (Postgres, backend, frontend)
├── docker-compose.prod.yml          ← Production compose override
├── .env.example                     ← Template for required environment variables
├── .gitignore
│
├── backend/                         ← FastAPI application
│   ├── pyproject.toml               ← Python deps (uv/pip)
│   ├── Dockerfile
│   ├── alembic.ini                  ← DB migration config
│   ├── alembic/
│   │   └── versions/               ← Migration scripts
│   └── app/
│       ├── main.py                  ← FastAPI app factory
│       ├── api/
│       │   ├── deps.py              ← Shared FastAPI dependencies (auth, db session)
│       │   └── routes/
│       │       ├── auth.py          ← Login, token endpoints
│       │       ├── chat.py          ← Chat session and message endpoints
│       │       ├── search.py        ← Direct semantic search endpoint
│       │       └── analytics.py     ← Corpus analytics endpoints
│       ├── core/
│       │   ├── config.py            ← Settings (loaded from env vars via pydantic-settings)
│       │   ├── security.py          ← Password hashing, JWT creation/validation
│       │   ├── logging.py           ← Structured logging setup (structlog)
│       │   └── resilience.py        ← Retry/backoff/timeout decorators and utilities
│       ├── db/
│       │   ├── session.py           ← SQLAlchemy async session factory
│       │   ├── models.py            ← ORM models (User, Document, Chunk, Session, Message, Feedback, Manifest)
│       │   └── crud.py              ← Data access layer
│       ├── schemas/
│       │   ├── auth.py              ← Pydantic models for auth request/response
│       │   ├── chat.py              ← Chat request/response schemas
│       │   ├── document.py          ← Document and chunk schemas
│       │   └── analytics.py         ← Analytics response schemas
│       ├── rag/
│       │   ├── pipeline.py          ← Main RAG orchestrator (query → retrieve → generate → cite)
│       │   ├── retrieval.py         ← Vector + hybrid search logic
│       │   ├── generation.py        ← LLM call wrapper with streaming
│       │   ├── prompts.py           ← System prompt templates for researcher modes
│       │   ├── citations.py         ← Source extraction and citation formatting
│       │   └── reranker.py          ← Optional cross-encoder reranking
│       ├── providers/               ← LLM provider abstraction
│       │   ├── base.py              ← Abstract LLMProvider interface
│       │   ├── anthropic_provider.py← Claude (Anthropic SDK) implementation
│       │   └── registry.py          ← Provider factory and registry
│       └── embeddings/              ← Embedding model abstraction
│           ├── base.py              ← Abstract EmbeddingModel interface
│           ├── pubmedbert.py        ← PubMedBERT embedding implementation
│           ├── minilm.py            ← MiniLM-L6-v2 (fast baseline) implementation
│           └── registry.py          ← Embedding factory and registry
│
├── frontend/                        ← Next.js 15 application
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── Dockerfile
│   └── src/
│       ├── app/                     ← Next.js App Router
│       │   ├── layout.tsx
│       │   ├── page.tsx             ← Redirect to /chat or /login
│       │   ├── login/
│       │   │   └── page.tsx
│       │   ├── chat/
│       │   │   ├── page.tsx         ← Main chat interface
│       │   │   └── [sessionId]/
│       │   │       └── page.tsx     ← Existing session view
│       │   └── analytics/
│       │       └── page.tsx         ← Literature landscape analytics
│       ├── components/
│       │   ├── chat/
│       │   │   ├── ChatWindow.tsx
│       │   │   ├── MessageBubble.tsx
│       │   │   ├── CitationChip.tsx
│       │   │   └── SourcePanel.tsx
│       │   ├── analytics/
│       │   │   ├── TemporalChart.tsx
│       │   │   ├── JournalChart.tsx
│       │   │   └── TopicHeatmap.tsx
│       │   └── ui/                  ← Shared UI primitives
│       │       ├── Button.tsx
│       │       ├── Input.tsx
│       │       └── Spinner.tsx
│       ├── lib/
│       │   ├── api.ts               ← API client (typed fetch wrapper)
│       │   └── auth.ts              ← Auth token management
│       └── types/
│           └── index.ts             ← Shared TypeScript types
│
├── pipelines/                       ← Offline data ingestion and indexing
│   ├── pyproject.toml               ← Pipeline-specific deps (can share backend venv)
│   ├── configs/
│   │   ├── corpus.rlalab.toml       ← Search query, date range, source, filters
│   │   └── ingestion.toml           ← Batch sizes, rate limits, retry settings
│   ├── ingestion/
│   │   ├── base.py                  ← Abstract Ingester interface
│   │   ├── pubmed_abstract.py       ← PubMed abstract fetcher (extends GutFeeling approach)
│   │   ├── pmc_fulltext.py          ← PubMed Central full-text fetcher (OA subset)
│   │   ├── discovery_search.py      ← Multi-source search via pipelines/discovery (pubmed+epmc+crossref+openalex)
│   │   ├── datasheet_manifest.py    ← A datasheet run's manifest CSV as an ingestion worklist
│   │   ├── datasheet_fulltext.py    ← Full text a datasheet run already fetched (section-labelled, no network)
│   │   ├── datasheet_rows.py        ← Curated datasheet rows, one document per row
│   │   └── pdf_local.py             ← Local PDF ingester (for lab preprints / reports)
│   ├── processing/
│   │   ├── normalizer.py            ← Unified document schema normalization
│   │   ├── chunker.py               ← Configurable chunking (sentence, fixed-size, semantic)
│   │   └── deduplicator.py          ← PMID-based dedup + fuzzy title dedup
│   ├── indexing/
│   │   ├── embedder.py              ← Batch embedding with progress tracking
│   │   └── build_index.py           ← Main indexing entry point (writes to pgvector)
│   └── manifest.py                  ← Corpus manifest tracking (query, date, counts, model)
│
├── evaluation/                      ← Evaluation harness (see §10)
│   ├── README.md                    ← Evaluation methodology documentation
│   ├── benchmark/
│   │   ├── questions.jsonl          ← Gold benchmark questions
│   │   └── labels.jsonl             ← Relevant PMID labels per question
│   ├── metrics.py                   ← recall@k, MRR, answer faithfulness, latency
│   ├── run_eval.py                  ← Evaluation runner (queries backend API)
│   └── reports/                     ← Evaluation run outputs (gitignored large files)
│
├── scripts/                         ← Production operations (deployment VM)
│   ├── README.md                    ← Flag reference and recipes
│   ├── deploy.sh                    ← Pull from GitHub, rebuild only changed services, verify, roll back
│   ├── restart.sh                   ← Bounce/recreate services without touching git
│   ├── status.sh                    ← Deployed commit, container states, health, resources
│   ├── logs.sh                      ← Live unified log view across containers
│   ├── collect-logs.sh              ← Redacted support bundle (.tar.gz) for a bug report
│   └── lib/
│       ├── common.sh                ← compose wrapper, .env reader, health checks, path→service map
│       └── redact.sh                ← Secret removal + pre-handover verification
│
└── docs/
    ├── architecture.md              ← Abstract system layers, flows, and runtime boundaries
    ├── components.md                ← Concrete component inventory: files, routes, pages, services
    ├── evaluation-guidelines.md     ← Full evaluation methodology (auto-generated, see §10)
    ├── ingestion-guide.md           ← How to run and update corpus
    ├── operations-logging.md        ← Unified logging design, support bundles, redaction rules
    └── api-reference.md             ← FastAPI auto-docs supplement
```

---

## 4. Technology Stack

### Backend
| Component | Choice | Rationale |
|-----------|--------|-----------|
| Python version | 3.12 | LTS, full async support, type-hint improvements |
| Web framework | FastAPI 0.115+ | Async-native, OpenAPI auto-docs, pydantic v2 |
| ORM | SQLAlchemy 2.x (async) | Async sessions, alembic migrations |
| DB | PostgreSQL 16 + pgvector 0.7+ | Vector search co-located with metadata; no separate service |
| Auth | python-jose + passlib (bcrypt) | JWT bearer tokens for iteration 1 |
| Settings | pydantic-settings | Env-var validation and type coercion |
| LLM SDK | anthropic>=0.40 | Official Anthropic Python SDK; streaming supported |
| Embeddings | sentence-transformers, transformers, torch | Local model inference |
| HTTP retries | tenacity | Configurable retry/backoff for all external calls |
| Logging | structlog | Structured JSON logs; compatible with any log aggregator |
| Testing | pytest + pytest-asyncio + httpx | Async-aware API test suite |

### Frontend
| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | Next.js 15 (App Router) | SSR, TypeScript, route handlers for same-origin proxying |
| Styling | Tailwind CSS 4 | Utility-first, low-friction iteration |
| State | Local React state + route state | Current UI does not use a separate global state library |
| Data fetching | Typed fetch wrapper in `src/lib/api.ts` | Keeps browser calls on same-origin `/api/*` routes |
| Auth | Next.js route handlers + `httpOnly` cookie | Browser never handles backend bearer token directly |
| Charts | Recharts | React-native charting; good for analytics tab |
| Streaming | native EventSource / fetch ReadableStream | SSE for LLM token streaming |

### Infrastructure
| Component | Choice |
|-----------|--------|
| Container | Docker + docker-compose |
| DB hosting | Managed Postgres (e.g. Neon, Supabase, or self-hosted) |
| Secrets | Environment variables; never committed to git |
| CI | GitHub Actions (lint, test, build) |

---

## 5. Database Schema

All tables live in a single Postgres 16 database. pgvector extension must be enabled.

```sql
-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Users ──────────────────────────────────────────────────────────────────
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    full_name     TEXT,
    role          TEXT NOT NULL DEFAULT 'researcher',  -- 'researcher' | 'admin'
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Ingestion Manifests ────────────────────────────────────────────────────
-- One row per corpus build. Tracks provenance of every index version.
CREATE TABLE ingestion_manifests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,               -- e.g. 'rlalab-pubmed-v1'
    source          TEXT NOT NULL,               -- 'pubmed_abstract' | 'pmc_fulltext' | 'pdf'
    query           TEXT,                        -- PubMed query string (if applicable)
    date_from       DATE,
    date_to         DATE,
    embedding_model TEXT NOT NULL,               -- e.g. 'microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext'
    chunk_size      INTEGER,
    chunk_overlap   INTEGER,
    document_count  INTEGER,
    chunk_count     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB                        -- arbitrary extra info
);

-- ── Documents ──────────────────────────────────────────────────────────────
-- One row per source article / PDF.
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manifest_id     UUID REFERENCES ingestion_manifests(id) ON DELETE SET NULL,
    document_id     TEXT NOT NULL UNIQUE,        -- 'pmid:12345678' | 'doi:10.1234/...' | 'pdf:filename'
    source          TEXT NOT NULL,               -- 'pubmed' | 'pmc' | 'pdf'
    title           TEXT,
    abstract        TEXT,
    full_text       TEXT,                        -- NULL if abstract-only ingestion
    authors         JSONB,                       -- [{last_name, fore_name, initials, orcid?}]
    journal         TEXT,
    publication_date DATE,
    year            INTEGER,
    doi             TEXT,
    pmid            TEXT,
    pmc_id          TEXT,
    mesh_terms      TEXT[],
    keywords        TEXT[],
    url             TEXT,
    license         TEXT,                        -- 'open-access' | 'metadata-only' | etc.
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB                        -- source-specific extra fields
);

CREATE INDEX idx_documents_pmid ON documents(pmid) WHERE pmid IS NOT NULL;
CREATE INDEX idx_documents_doi  ON documents(doi)  WHERE doi  IS NOT NULL;
CREATE INDEX idx_documents_year ON documents(year);
CREATE INDEX idx_documents_source ON documents(source);

-- ── Document Chunks ────────────────────────────────────────────────────────
-- One row per chunk. embedding dimension = 768 for PubMedBERT.
-- Change 768 if using a different model (MiniLM = 384, text-embedding-3-large = 3072).
CREATE TABLE document_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    manifest_id     UUID REFERENCES ingestion_manifests(id) ON DELETE SET NULL,
    chunk_index     INTEGER NOT NULL,            -- 0-based position within document
    chunk_type      TEXT NOT NULL DEFAULT 'abstract',  -- 'abstract' | 'fulltext' | 'title_abstract'
    content         TEXT NOT NULL,
    token_count     INTEGER,
    embedding_model TEXT NOT NULL,
    embedding       vector(768),                 -- PubMedBERT dimensionality
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- IVFFlat index for approximate nearest-neighbour search.
-- lists=100 is appropriate for ~100k–1M vectors.
-- Rebuild with more lists if corpus grows to millions.
CREATE INDEX idx_chunks_embedding ON document_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Full-text search index for BM25-style lexical retrieval (hybrid search).
CREATE INDEX idx_chunks_content_fts ON document_chunks
    USING gin(to_tsvector('english', content));

-- ── Chat Sessions ──────────────────────────────────────────────────────────
CREATE TABLE chat_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           TEXT,                        -- Auto-generated from first message
    mode            TEXT NOT NULL DEFAULT 'researcher',  -- 'researcher' | 'lab_manager'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Chat Messages ──────────────────────────────────────────────────────────
CREATE TABLE chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,               -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    retrieved_chunks UUID[],                     -- chunk IDs used for this response
    sources         JSONB,                       -- [{pmid, doi, title, journal, year, url}]
    llm_model       TEXT,                        -- model string used
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON chat_messages(session_id);

-- ── Feedback ───────────────────────────────────────────────────────────────
CREATE TABLE feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    comment         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Notes for implementer:**
- Alembic migrations generate the actual DDL from SQLAlchemy models. The SQL above is the reference schema.
- `embedding vector(768)` is for PubMedBERT. If you add MiniLM (384-dim) or other embeddings, add a separate column or table rather than mixing dimensions in one column.
- For multi-embedding support: consider a `chunk_embeddings` table with `(chunk_id, model_name, embedding vector)` and a polymorphic index per model.
- The IVFFlat index requires a corpus before it can be created. Create it after initial data load, not before.

---

## 6. API Design

Base URL: `/api/v1`

### Authentication
```
POST /api/v1/auth/login           → { access_token, token_type, expires_in }
POST /api/v1/auth/logout          → 204
GET  /api/v1/auth/me              → UserResponse
```

### Chat
```
POST /api/v1/chat/sessions                      → ChatSession (create new session)
GET  /api/v1/chat/sessions                      → List[ChatSession]
GET  /api/v1/chat/sessions/{session_id}         → ChatSession + messages
DELETE /api/v1/chat/sessions/{session_id}       → 204

POST /api/v1/chat/sessions/{session_id}/messages → stream of SSE events
     Body: { query: str, mode: str, top_k?: int }
     Stream: text/event-stream
     Events: { type: "token"|"sources"|"done"|"error", data: ... }
```

### Search (direct retrieval without generation)
```
POST /api/v1/search
     Body: { query: str, top_k?: int, filters?: { year_from, year_to, source } }
     Response: List[SearchResult]  # chunks with metadata and scores
```

### Analytics
```
GET /api/v1/analytics/temporal        → publication counts by year
GET /api/v1/analytics/journals        → top journals by count
GET /api/v1/analytics/mesh_terms      → top MeSH terms
GET /api/v1/analytics/topics          → topic distribution
GET /api/v1/analytics/corpus_stats    → total docs, chunks, date range, last updated
```

### Feedback
```
POST /api/v1/feedback
     Body: { message_id: UUID, rating: int, comment?: str }
```

**Streaming design:** The chat endpoint streams via Server-Sent Events (SSE). The frontend uses the Fetch API ReadableStream to consume tokens as they arrive. Final event carries `sources` (citation list). This requires the backend to use `anthropic` SDK streaming (`client.messages.stream()`).

---

## 7. Embedding Models

### Primary: PubMedBERT
- **Model:** `microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext`
- **Dimensions:** 768
- **Why:** Pre-trained on PubMed abstracts and PMC full text. Superior biomedical vocabulary alignment versus general-purpose models. Essential for RLA Lab's highly specialized domain (synthetic biology, metabolic pathways, yeast engineering).
- **Inference:** Local via `sentence-transformers`. Requires ~440 MB model weights.
- **GPU:** Strongly recommended for indexing (CUDA). CPU is acceptable for online query embedding (single vector per query).

### Secondary: MiniLM-L6-v2
- **Model:** `sentence-transformers/all-MiniLM-L6-v2`
- **Dimensions:** 384
- **Why:** Fast CPU inference. Use as baseline comparison in evaluation. Can serve as a fallback or for quick prototype runs.

### Optional / Future: E5-large-v2
- **Model:** `intfloat/e5-large-v2`
- **Dimensions:** 1024
- **Why:** Strong general retrieval performance. Add as a third comparison point in evaluation phase.

### Embedding abstraction pattern

```python
# app/embeddings/base.py
from abc import ABC, abstractmethod

class EmbeddingModel(ABC):
    model_name: str
    dimensions: int

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
```

All embedding classes implement this interface. The registry maps `model_name` strings to class instances. The active model is set via `EMBEDDING_MODEL` env var (default: `pubmedbert`).

---

## 8. LLM Provider Abstraction

### Primary: Claude (Anthropic)
- **Model:** `claude-sonnet-4-6` (default). Configurable via `LLM_MODEL` env var.
- **Why:** Strong instruction following, long context (200K tokens), good at scientific synthesis and citation grounding.
- **SDK:** `anthropic` Python SDK with streaming.

### Provider interface

```python
# app/providers/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator

class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str: ...

    @abstractmethod
    async def stream(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]: ...
```

### Provider registry

```python
# app/providers/registry.py
from app.core.config import settings
from app.providers.anthropic_provider import AnthropicProvider

PROVIDER_MAP = {
    "anthropic": AnthropicProvider,
    # "openai": OpenAIProvider,   # add when needed
}

def get_provider() -> LLMProvider:
    return PROVIDER_MAP[settings.LLM_PROVIDER](
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
    )
```

Set `LLM_PROVIDER=anthropic` and `LLM_MODEL=claude-sonnet-4-6` in `.env`.

---

## 9. Resilience: Retries, Timeouts, Rate Limits

**Rule:** Every external call (LLM API, PubMed Entrez, embedding if remote) must go through the resilience layer.

### Retry policy (tenacity)

```python
# app/core/resilience.py
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)
import logging

logger = logging.getLogger(__name__)

llm_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError, Timeout)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)

pubmed_retry = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((IncompleteRead, RemoteDisconnected, Exception)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
```

### Timeout policy
- LLM streaming: 120 seconds total; first token timeout 10 seconds.
- PubMed fetch: 30 seconds per batch request.
- Embedding (local): no network timeout; but add a thread executor timeout of 60 seconds for safety.

### Rate limit handling
- **Anthropic:** Respect `x-ratelimit-*` response headers. The SDK handles basic retry on 429. Add exponential backoff via tenacity on top.
- **NCBI/PubMed:** 10 req/sec with API key. Enforce `asyncio.sleep(0.1)` between requests in ingestion pipeline. Use configurable `NCBI_SLEEP_BETWEEN_BATCHES` env var.
- **Local embeddings:** Batch size controlled by `EMBEDDING_BATCH_SIZE` env var (default 32). No external rate limit.

### Circuit breaker (future)
For iteration 2, add a circuit breaker (e.g. `pybreaker`) around LLM calls to fail fast when the API is degraded, rather than queuing retries.

---

## 10. Ingestion Pipeline

### Source types and content strategy

| Source | Content | When to use |
|--------|---------|-------------|
| `pubmed_abstract` | Title + abstract + MeSH | Default. Broad coverage. Low storage. |
| `pmc_fulltext` | Full text via PMC OA API | Deep dives. Methods/results sections. Requires OA license check. |
| `pdf_local` | Lab preprints, reports, theses | Ad-hoc internal documents. |

### Ingestion flow

```
Config file (corpus.rlalab.toml)
    ↓
Ingester (PubMed / PMC / PDF)
    ↓ raw records
Normalizer (→ unified document schema)
    ↓ normalized documents
Deduplicator (PMID-based + fuzzy title)
    ↓ unique documents
Chunker (sentence-aware, configurable size/overlap)
    ↓ chunks
Embedder (batch, GPU if available)
    ↓ embedded chunks
Postgres / pgvector (upsert)
    ↓
Manifest record (provenance saved)
```

### Corpus config (`pipelines/configs/corpus.rlalab.toml`)

```toml
[corpus]
name = "rlalab-pubmed-v1"
source = "pubmed_abstract"
embedding_model = "pubmedbert"

[pubmed]
query = """
(
  "synthetic biology"[Title/Abstract] OR
  "metabolic engineering"[Title/Abstract] OR
  "Yarrowia lipolytica"[Title/Abstract] OR
  "lipid production"[Title/Abstract] OR
  "microbial cell factory"[Title/Abstract] OR
  "bioproduction"[Title/Abstract] OR
  "oleaginous yeast"[Title/Abstract] OR
  "microbial community"[Title/Abstract] OR
  "sustainable protein"[Title/Abstract]
) AND english[lang]
"""
year_from = 2000
year_to   = 2026
batch_size = 20
sleep_between_batches_s = 0.15
```

### Document schema (normalized)

```python
class NormalizedDocument(BaseModel):
    document_id: str           # 'pmid:XXXXXXXX' | 'doi:...' | 'pdf:filename'
    source: str
    title: str | None
    abstract: str | None
    full_text: str | None      # None for abstract-only
    authors: list[dict]
    journal: str | None
    publication_date: date | None
    year: int | None
    doi: str | None
    pmid: str | None
    pmc_id: str | None
    mesh_terms: list[str]
    keywords: list[str]
    url: str | None
    license: str | None
    ingested_at: datetime
    metadata: dict
```

### Chunking strategy

Default (abstract mode):
- **Chunk size:** 512 tokens
- **Overlap:** 64 tokens
- **Splitter:** sentence-aware (no mid-sentence breaks)

Full-text mode:
- **Chunk size:** 1024 tokens
- **Overlap:** 128 tokens
- **Strategy:** Section-aware — keep Introduction, Methods, Results, Discussion as labelled chunk_type metadata.

### Incremental updates

The pipeline supports `--mode incremental --from-date YYYY-MM-DD` to fetch only new articles since the last manifest. PMIDs are deduped against the existing manifest before re-embedding.

---

## 11. RAG Pipeline Design

### Query flow

```
User query (string)
    ↓
Query embedding (PubMedBERT, same model as index)
    ↓
Vector search (pgvector cosine similarity, top_k=10)
    ↓
Lexical search (Postgres FTS, BM25 approximation, top_k=10)
    ↓
Reciprocal Rank Fusion (combine scores, top_k=5 final)
    ↓ [optional]
Cross-encoder reranker (if RERANKER_ENABLED=true)
    ↓
Context assembly (inject chunks + metadata into prompt)
    ↓
LLM generation (Claude, streaming)
    ↓
Citation extraction (from source_nodes metadata)
    ↓
Response + citations streamed to frontend
```

### Retrieval parameters (configurable via env vars)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RETRIEVAL_VECTOR_TOP_K` | 10 | Candidates from vector search |
| `RETRIEVAL_LEXICAL_TOP_K` | 10 | Candidates from FTS |
| `RETRIEVAL_FINAL_TOP_K` | 5 | After fusion/reranking |
| `RERANKER_ENABLED` | false | Enable cross-encoder reranking |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model |

### System prompts

Two modes for internal users:

**Researcher mode** (default):
```
You are a rigorous biomedical research assistant serving scientists at the Rodrigo Ledesma-Amaro Lab (Imperial College London), 
which focuses on synthetic biology, metabolic engineering, and sustainable bioproduction, primarily using Yarrowia lipolytica 
and related organisms.

Your role is to help researchers navigate the scientific literature. Answer ONLY based on the retrieved context provided.
Use precise scientific terminology. Reference methodologies, study designs, and findings accurately.
Structure answers to clarify what has been studied, how, and what gaps remain.
If the context partially answers the question, summarize what is found and identify the gaps.
Never fabricate citations, statistics, or conclusions not present in the retrieved context.
Always cite sources using their PMID or DOI when available.
```

**Lab Manager mode** (future):
```
[Broader scientific context, suitable for administrative or cross-domain queries]
```

---

## 12. Authentication

### Iteration 1: JWT Bearer Tokens

- Users are pre-provisioned by an admin (no self-registration).
- Login: `POST /api/v1/auth/login` with `{ email, password }` → `{ access_token }`.
- Tokens: HS256 JWT, 8-hour expiry, signed with `SECRET_KEY` env var.
- All protected endpoints require `Authorization: Bearer <token>`.
- Frontend exchanges credentials through `POST /api/auth/login`, stores the backend JWT in an `httpOnly` cookie, and forwards authenticated backend calls through `/api/backend/*`.
- User roles: `researcher` (default), `admin` (can manage users and trigger re-ingestion).

### Iteration 2 (future): OIDC/SSO
- Imperial College London provides OIDC via Azure AD.
- Add `python-social-auth` or `authlib` integration.
- The user table already has `email` as the natural key for SSO linkage.

---

## 13. Frontend Architecture

### Pages
- `/login` — credential form that calls the Next.js login route, which writes the backend JWT into an `httpOnly` cookie.
- `/chat` — main interface. Left sidebar: session history. Main panel: chat window. Right panel (collapsible): source documents.
- `/chat/[sessionId]` — restore a previous session.
- `/analytics` — literature landscape: temporal chart, journal ranking, topic heatmap (data from analytics API).

### Chat streaming
Use `fetch` with `ReadableStream` to consume SSE from the Next.js backend proxy, not directly from the browser to FastAPI:
```typescript
const response = await fetch('/api/backend/chat/sessions/{id}/messages', {
  method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ query, mode }),
});
const reader = response.body.getReader();
// decode and append tokens to UI state
```

### Agent constraints for auth work
- Do not reintroduce browser-managed bearer tokens or `localStorage` token storage.
- Keep auth mutations in Next.js route handlers under `frontend/src/app/api/auth/*`.
- Keep authenticated browser-to-backend traffic on the same-origin proxy under `frontend/src/app/api/backend/[...path]/route.ts`.

### Source panel
After the `done` SSE event, display retrieved sources in a collapsible right panel:
- PMID / DOI link
- Title and first author
- Journal, year
- Retrieved snippet (the chunk text used for that source)

This provides claim-level context, unlike the original GutFeeling chip-only display.

---

## 14. Environment Variables

**One variable names the scenario; everything else derives from it.** Full detail in
`run_and_deploy.md` §1.

```
RLALAB_ENV = local | compose | server
```

| Scenario | Meaning | Set by |
|---|---|---|
| `local` | host processes; Postgres reached on its published port | nobody — it is the default |
| `compose` | containers on a dev machine | `docker-compose.yml` |
| `server` | containers on the deployment VM, production behaviour | `docker-compose.prod.yml` |

All four components read this same variable: `backend/app/core/config.py`,
`frontend/configs/frontend.yaml`, `pipelines/configs/pipeline.defaults.yaml`,
`evaluation/configs/evaluation.yaml`.

### Three config files, one job each

| File | Contains | Loaded by | In git |
|---|---|---|---|
| `.env` | secrets + behaviour. **No hostnames, no ports, no URLs.** | every scenario | no |
| `.env.compose` | addresses for containers on a dev machine | `docker-compose.yml` | yes |
| `.env.server` | addresses for the deployment VM | `docker-compose.prod.yml` | yes |

Because `.env` holds no addresses, `source .env` is safe in any shell. **Never add a hostname,
port or service URL to `.env`** — that reintroduces the class of bug where a host process is
handed a Compose service name (`getaddrinfo ENOTFOUND backend`).

```bash
# .env — secrets and behaviour only
RLALAB_ENV=local
POSTGRES_DB=rlalab_ai
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<password>
SECRET_KEY=<random 32-byte hex>
ACCESS_TOKEN_EXPIRE_MINUTES=480
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=<your key>
EMBEDDING_MODEL=pubmedbert
EMBEDDING_BATCH_SIZE=32
NCBI_EMAIL=<your email>
NCBI_API_KEY=<your key>
RETRIEVAL_VECTOR_TOP_K=10
RETRIEVAL_LEXICAL_TOP_K=10
RETRIEVAL_FINAL_TOP_K=5
RERANKER_ENABLED=false
LOG_LEVEL=INFO

# .env.compose — addresses only (committed). No DATABASE_URL: the compose file
# assembles it from POSTGRES_* so the password has exactly one owner.
CORS_ORIGINS=["http://localhost:3000"]
APP_PUBLIC_URL=http://localhost:3000
```

### Rules for agents

- **Defaults serve `local`.** Compose always injects addresses explicitly, so it never needs a
  default; a bare shell has no injection mechanism, so the defaults must cover it. Hence
  `Settings.database_url` defaults to `localhost:5433`, never `db:5432`.
- **Each address has exactly one owner.** Database → `Settings` (+ the `DATABASE_URL` that
  each compose file builds under `environment:`). Backend URL for the frontend →
  `frontend/configs/frontend.yaml`. Evaluation API URL → `evaluation/configs/evaluation.yaml`.
  Do not restate another component's address.
- **Never write a password into `DATABASE_URL` in an address file.** The compose files build the
  URL from `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` under `environment:`, which
  outranks `env_file:`. A second copy drifts the moment anyone rotates the password, and the
  whole stack then sits in a restart loop. Note also that `POSTGRES_PASSWORD` is an *initdb*
  variable: changing it never changes an existing database — see run_and_deploy.md §7.1.
- **The backend has no YAML config file** and must not gain one; it is env-var-only by design
  (`backend/app/core/config.py` docstring).
- Ask `settings.is_production` / `settings.is_containerised` rather than comparing
  `rlalab_env` to a string.
- `${VAR}` interpolation in a compose file reads the shell and the project `.env` **only** —
  a service-level `env_file:` does not feed it. Anything used for interpolation must stay in
  `.env` (or be hardcoded in the compose file, as the published db port is).

---

## 15. Development Setup

**`run_and_deploy.md` is the authoritative guide.** Summary of the dev inner loop
(`RLALAB_ENV` unset → `local`):

```bash
# 1. Postgres — always a container; nothing to install
docker compose up -d db                  # published on localhost:5433

# 2. Secrets into this shell. Safe: .env holds no addresses (see §14)
set -a; source .env; set +a

# 3. Backend — no DATABASE_URL needed, the `local` default already points at :5433
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 4. Frontend — needs no environment at all
cd frontend && npm install && npm run dev      # → http://localhost:3000

# 5. Everything in containers instead of steps 2-4
docker compose up -d --build

# 6. Run ALL tests — backend unit + E2E + frontend unit (MANDATORY before any PR or merge)
cd backend && .venv/bin/python -m pytest tests/ -v --tb=short
cd ../frontend && npm test -- --run && npm run type-check
```

**Test gate rule:** After implementing any feature, fix, or refactor — run the full test suite above. No flaky test results are acceptable: every test must pass deterministically. If a test flickers, fix the test root cause before proceeding.

Implementation notes for agents:

- Always use `backend/.venv/bin/python` (Python 3.12) — not any other virtualenv. Python 3.13 (.venv-1) is incompatible with the torch/transformers pin.
- First backend startup downloads PubMedBERT weights into `backend/model_cache` if they are missing.
- The supported local runtime currently relies on `torch 2.2.x` plus `transformers 4.51.x`; if a machine has a newer `transformers` installed already, reinstall backend deps with `pip install -e ".[dev]" --upgrade` before debugging unrelated startup failures.
- The supported password-hashing stack currently relies on `passlib[bcrypt]` with `bcrypt<4.1`; do not widen that constraint without revalidating user creation and login flows.
- Integration tests must override `deps.get_embedding_model` and `deps.get_llm_provider`; otherwise tests will try to instantiate the real embedding model and external provider client.
- The full automated test suite lives in `backend/tests/` (89 tests) and `frontend/src/` (28 tests). See §20 for test file inventory.
- If Homebrew installs `pgvector` without exposing `vector.control` to PostgreSQL 16, build it manually with `make PG_CONFIG=$(brew --prefix postgresql@16)/bin/pg_config && make install ...` before troubleshooting Alembic or app startup.
- Before writing any new test or async code, read `mistakes.md` in the repo root for known pitfalls.

---

## 16. Deployment

**Operating the VM goes through `scripts/`** — `deploy.sh` (fast-forward from
GitHub, rebuild only the services whose paths changed, verify health, roll back
on failure), `restart.sh`, `status.sh`, `logs.sh`, `collect-logs.sh`. Details in
`scripts/README.md`; deployment context in `run_and_deploy.md` §5–6; logging and
support-bundle design in `docs/operations-logging.md`.

Container logs are rotated by the `x-logging` anchor in `docker-compose.prod.yml`
(20 MB × 5 per service). Do not remove it: Docker's default `json-file` driver
never rotates, and an unbounded backend log fills the VM disk and takes Postgres
with it.

### Docker Compose (production)

```yaml
# docker-compose.prod.yml
services:
  db:
    image: pgvector/pgvector:pg16
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: rlalab_ai
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}

  backend:
    build: ./backend
    env_file: .env
    depends_on: [db]
    ports:
      - "8000:8000"

  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_API_URL: http://backend:8000
    ports:
      - "3000:3000"
```

**Recommended hosting for Imperial/Bezos Centre:**
- Containerized deployment on Imperial's HPC or cloud (Azure, AWS).
- Managed Postgres with pgvector extension support (e.g. Azure Database for PostgreSQL Flexible Server supports pgvector).
- Reverse proxy (nginx or Caddy) in front of both services.
- SSL termination at the proxy level.
- Model weights cached in a persistent volume (not rebuilt on restart).

---

## 17. Key Implementation Warnings

1. **IVFFlat index creation:** The pgvector IVFFlat index requires data to exist before it can be built. Run `CREATE INDEX` after the first ingestion, not in the initial migration.
2. **PubMedBERT model weights:** ~440 MB. Cache in a persistent volume. Do not bundle into the Docker image.
3. **Streaming and nginx:** If using nginx as a reverse proxy, set `proxy_buffering off` for the streaming chat endpoint.
4. **CORS:** Lock `CORS_ORIGINS` to the frontend domain in production. The dev default `http://localhost:3000` must not reach production.
5. **JWT secret:** Generate a strong `SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`). Never use the dev default in production.
6. **MeSH terms:** Available only for PubMed-indexed articles (not always present for very recent papers). Handle missing MeSH gracefully throughout.
7. **Rate limits:** Anthropic Claude rate limits vary by tier. Monitor `x-ratelimit-requests-remaining` and `x-ratelimit-tokens-remaining` response headers. Log these to structlog for visibility.
8. **Chunk embedding dimensions:** If you add an embedding model with different dimensions, you must either add a new vector column or a separate table. Mixing 768-dim and 384-dim vectors in the same column is not valid.
9. **alembic autogenerate:** Will not detect vector column type changes automatically. Write those migrations by hand using `op.execute()`.
10. **Full-text ingestion licensing:** PMC full text is only available for open-access articles. Always check `license` field and respect restrictions.
11. **Async ORM serialization:** When returning ORM-backed response models in async routes, avoid response construction paths that trigger lazy relationship loading during Pydantic validation. Build nested response objects explicitly when necessary.

---

## 18. File Naming and Code Conventions

- Python: PEP 8, type hints everywhere, docstrings for all public functions.
- TypeScript: strict mode, interfaces over types for data shapes.
- All async Python functions use `async def`. No blocking calls in async context (use `asyncio.to_thread` for CPU-bound work like embedding).
- Environment variables: UPPER_SNAKE_CASE. All accessed through `app/core/config.py` `Settings` class only — never `os.getenv()` directly in business logic.
- Route files: one file per resource group. No business logic in route files; delegate to service/rag layer.
- Pydantic models: suffix `Request` for inputs, `Response` for outputs, `Schema` for internal data.

---

## 19. For the Implementing Agent

If you are an AI agent beginning implementation of this project:

1. **Start with the database layer:** `backend/app/db/models.py` → `alembic` migration → verify schema in psql.
2. **Then auth:** `backend/app/core/security.py` + `backend/app/api/routes/auth.py` — get login working with a test user.
3. **Then the embedding pipeline:** `pipelines/ingestion/pubmed_abstract.py` → `pipelines/processing/normalizer.py` → `pipelines/indexing/build_index.py`. Run a small test ingestion (year 2024 only, ~100 articles).
4. **Then retrieval:** `backend/app/rag/retrieval.py` — test vector search via psql and then via a standalone script before wiring to the API.
5. **Then generation:** `backend/app/providers/anthropic_provider.py` + `backend/app/rag/generation.py` — test with a fixed query and fixed context.
6. **Then the full RAG pipeline:** `backend/app/rag/pipeline.py` — wire retrieval + generation.
7. **Then API routes:** `backend/app/api/routes/chat.py` — expose the pipeline via FastAPI with SSE streaming.
8. **Then frontend:** Start with login page, then chat page with streaming, then analytics.
9. **Run evaluation** after the pipeline is working (see `evaluation/` and `docs/evaluation-guidelines.md`).

Read `docs/evaluation-guidelines.md` before starting frontend polish — evaluation results may change retrieval parameters.

---

## 20. Test Suite Inventory

**Backend** (run with `backend/.venv/bin/python -m pytest tests/ -v`):

| File | What it covers |
| ------ | --------------- |
| `tests/test_security.py` | `hash_password`, `verify_password`, `create_access_token`, `decode_access_token` |
| `tests/test_citations.py` | `build_sources`: deduplication, snippet truncation, URL construction |
| `tests/test_prompts.py` | `get_system_prompt`, `build_context_block` |
| `tests/test_pipeline.py` | `_format_exception_message`, `_chunk_to_dict`, `run_rag_stream` events |
| `tests/test_retrieval.py` | `_reciprocal_rank_fusion`, `_apply_filters` |
| `tests/test_resilience.py` | `_is_llm_retryable`, `pubmed_retry`, `llm_retry` |
| `tests/test_e2e.py` | Auth (login/logout/me/inactive), session CRUD, feedback, search, admin gate |
| `tests/test_api_integration.py` | Full SSE streaming, auto-title, analytics, search |
| `tests/test_build_index.py` | Embedding dimension validation, chunk-mode map, cache replay per source |
| `tests/test_discovery_search_ingester.py` | Candidate → document mapping, audit artifacts, `from_config` |
| `tests/test_datasheet_ingesters.py` | Manifest parsing/selection, PMC→abstract fallback, section-labelled full text, row documents |
| `tests/test_chunker.py` | Chunk splitting, overlap, section labels |
| `tests/test_eval_runner.py` | SSE stream parser |
| `tests/test_pmc_fulltext.py` | PMC XML metadata/text extraction |
| `tests/test_pubmed_ingester.py` | PubMed query builder, incremental checkpoint |

**Frontend** (run with `npm test -- --run` in `frontend/`):

| File | What it covers |
| ------ | --------------- |
| `src/lib/api.test.ts` | All API client functions: login, logout, sessions CRUD, streaming, analytics, feedback |
| `src/app/login/page.test.tsx` | Login form: success redirect, error display |
| `src/components/chat/ChatClient.test.tsx` | Markdown rendering, rename, delete from context menu |

---

## 21. Mistakes Reference

`mistakes.md` in the repository root tracks recurring implementation mistakes with root cause and prevention rules.

**Mandatory:** AI agents must read `mistakes.md` before writing:

- Any test involving `async def` or fixtures that yield.
- Any monkeypatch of a function that is `await`-ed in production code.
- Any code that touches the vector index, embedding dimensions, or ORM relationships.

**Update rule:** After every 5 user requests in a session (or after discovering a new recurring pattern), the agent must review the session's work, identify patterns that could have been prevented with prior knowledge, and append them to `mistakes.md`.
