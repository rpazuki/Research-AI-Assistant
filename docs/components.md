# Components Inventory

This document lists the real implemented components in the repository: concrete files, routes, services, data stores, and entry points.

## Runtime services

### Frontend web app

- Location: `frontend/`
- Framework: Next.js 15 App Router
- Responsibility: render UI, hold auth cookie boundary, proxy authenticated API calls, consume SSE streams

Key runtime files:

- `frontend/src/app/layout.tsx`
- `frontend/src/app/page.tsx`
- `frontend/src/app/login/page.tsx`
- `frontend/src/app/chat/page.tsx`
- `frontend/src/app/chat/[sessionId]/page.tsx`
- `frontend/src/app/analytics/page.tsx`
- `frontend/src/components/chat/ChatClient.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.ts`

### Backend API service

- Location: `backend/`
- Framework: FastAPI
- Responsibility: auth, sessions, retrieval, generation orchestration, analytics, feedback, persistence

Key runtime files:

- `backend/app/main.py`
- `backend/app/api/deps.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/routes/chat.py`
- `backend/app/api/routes/search.py`
- `backend/app/api/routes/analytics.py`
- `backend/app/api/routes/feedback.py`

### Database

- Engine: PostgreSQL 16
- Extension: pgvector
- Responsibility: store application state and retrieval corpus

Primary tables:

- `users`
- `ingestion_manifests`
- `documents`
- `document_chunks`
- `chat_sessions`
- `chat_messages`
- `feedback`

Schema sources:

- `backend/app/db/models.py`
- `backend/alembic/versions/0001_initial_schema.py`

## Frontend components

### Auth boundary

- `frontend/src/app/api/auth/login/route.ts`
- `frontend/src/app/api/auth/logout/route.ts`
- `frontend/src/lib/auth.ts`

Purpose:

- exchange credentials with FastAPI
- set and clear the `httpOnly` auth cookie
- keep browser code away from direct token storage

### Backend proxy

- `frontend/src/app/api/backend/[...path]/route.ts`

Purpose:

- forward authenticated same-origin requests to FastAPI
- inject the bearer token from the cookie
- normalize browser-to-backend traffic through one proxy layer

### Chat UI

- `frontend/src/components/chat/ChatClient.tsx`

Responsibilities:

- load and list sessions
- create new sessions
- restore an existing session
- stream SSE answer tokens into UI state
- show retrieved sources
- handle logout and navigation

### Analytics UI

Concrete files:

- `frontend/src/app/analytics/page.tsx`

Responsibilities:

- fetch summary metrics and chart datasets
- render empty-corpus and populated states

## Backend components

### Configuration and cross-cutting concerns

- `backend/app/core/config.py` loads all env-based settings
- `backend/app/core/security.py` hashes passwords and handles JWT encode/decode
- `backend/app/core/logging.py` sets structured logging
- `backend/app/core/resilience.py` provides retry/backoff policies

### Dependency injection surface

- `backend/app/api/deps.py`

Responsibilities:

- provide DB sessions
- resolve authenticated users
- resolve provider and embedding singletons
- provide admin-only access checks

### Data access layer

- `backend/app/db/crud.py`

Responsibilities:

- query and mutate users, sessions, messages, and corpus metadata
- provide reusable DB operations to route and pipeline code

### Embedding providers

- `backend/app/embeddings/base.py`
- `backend/app/embeddings/pubmedbert.py`
- `backend/app/embeddings/minilm.py`
- `backend/app/embeddings/registry.py`

Responsibilities:

- embed queries and document batches
- expose a swappable provider interface

### LLM provider layer

- `backend/app/providers/base.py`
- `backend/app/providers/anthropic_provider.py`
- `backend/app/providers/registry.py`

Responsibilities:

- abstract the generation provider
- provide normal completion and streaming interfaces

### RAG pipeline

- `backend/app/rag/pipeline.py`
- `backend/app/rag/retrieval.py`
- `backend/app/rag/prompts.py`
- `backend/app/rag/citations.py`

Responsibilities:

- retrieve evidence
- build the grounded prompt
- stream answer tokens
- attach source metadata

## Offline pipeline components

### Ingestion sources

- `pipelines/ingestion/pubmed_abstract.py`
- `pipelines/ingestion/pmc_fulltext.py`
- `pipelines/ingestion/pdf_local.py`

Notes:

- PubMed ingestion supports full, incremental, and exact-year modes.
- PMC ingestion now parses metadata and article text instead of returning raw XML.

### Processing

- `pipelines/processing/normalizer.py`
- `pipelines/processing/deduplicator.py`
- `pipelines/processing/chunker.py`

Responsibilities:

- normalize upstream records into the internal schema
- remove duplicates
- generate retrieval chunks

### Index build entry point

- `pipelines/indexing/build_index.py`

Responsibilities:

- coordinate fetch, normalize, chunk, embed, and write stages
- skip already indexed PMIDs in incremental mode
- replace existing chunk rows for repeated re-indexing of the same document/model

### Pipeline configuration

- `pipelines/configs/corpus.rlalab.toml`

Purpose:

- define corpus scope, source type, years, and query terms

## Evaluation components

- `evaluation/run_eval.py`
- `evaluation/benchmark/questions.jsonl`
- `evaluation/reports/`

Responsibilities:

- run retrieval-only and live RAG evaluations
- consume SSE output from the chat endpoint
- emit structured benchmark reports

## Operations and setup components

- `backend/scripts/create_user.py` provisions local users
- `docker-compose.yml` defines local orchestration
- `docker-compose.prod.yml` defines production-oriented compose services
- `README.md` is the developer setup guide
- `CLAUDE.md` is the coding-agent implementation guide
- `docs/architecture.md` describes abstract layers and flow
- `docs/components.md` describes concrete implementation components
- `log.md` records major implementation sessions and verification milestones

## Automated tests

### Backend tests

- `backend/tests/test_api_integration.py`
- `backend/tests/test_build_index.py`
- `backend/tests/test_eval_runner.py`
- `backend/tests/test_pmc_fulltext.py`
- `backend/tests/test_pubmed_ingester.py`

### Frontend tests

- `frontend/src/app/login/page.test.tsx`
- `frontend/vitest.config.ts`

These tests cover auth, analytics, session APIs, SSE chat streaming, ingestion behavior, PMC parsing, evaluation parsing, and frontend login behavior.