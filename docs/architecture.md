# Architecture Overview

This document describes the implemented architectural layers of RLALab AI Research Assistant and how data moves across them.

## System shape

The application is a three-tier internal RAG system:

1. A Next.js frontend renders the authenticated user interface and proxies browser requests.
2. A FastAPI backend owns authentication, retrieval, generation, persistence, and analytics.
3. A PostgreSQL 16 database with pgvector stores users, corpus metadata, chat history, and embeddings.

Offline ingestion and evaluation live beside the runtime application but write into, or read from, the same backend contracts and database schema.

## Layered model

### 1. Presentation layer

The presentation layer lives in `frontend/src/app` and `frontend/src/components`.

- `login` provides credential entry.
- `chat` and `chat/[sessionId]` provide the main conversation workspace.
- `analytics` renders corpus-level metrics and charts.
- Next.js route handlers under `frontend/src/app/api` form the browser-facing auth and backend proxy surface.

This layer does not implement retrieval, generation, or direct bearer-token handling. It delegates those concerns to backend APIs and same-origin proxy routes.

### 2. Application/API layer

The backend API layer lives in `backend/app/api/routes`.

- `auth.py` authenticates users and returns JWTs.
- `chat.py` manages sessions and streams answers via SSE.
- `search.py` exposes retrieval without generation.
- `analytics.py` exposes corpus aggregates.
- `feedback.py` stores message ratings.

This layer is intentionally thin. It validates requests, enforces ownership and auth, and delegates core work to CRUD, retrieval, and provider abstractions.

### 3. Domain/service layer

The backend service logic is split across several abstractions:

- `backend/app/rag/pipeline.py` orchestrates retrieve → prompt → stream.
- `backend/app/rag/retrieval.py` performs hybrid retrieval against pgvector and Postgres full-text search.
- `backend/app/rag/citations.py` shapes evidence and source metadata.
- `backend/app/providers` abstracts LLM providers.
- `backend/app/embeddings` abstracts embedding providers.
- `backend/app/core` contains config, logging, resilience, and security.

This is the decision-making layer of the live system.

### 4. Persistence layer

Persistence is handled by:

- `backend/app/db/models.py` for ORM entities
- `backend/app/db/crud.py` for data access operations
- `backend/app/db/session.py` for async session lifecycle
- `backend/alembic` for schema migration history

The database is the single source of truth for:

- user accounts and roles
- ingestion manifests
- documents and chunks
- embeddings
- chat sessions and messages
- feedback

### 5. Offline pipeline layer

The ingestion and indexing pipeline lives in `pipelines/`.

- `ingestion/` fetches source material from PubMed, PMC, and PDFs.
- `processing/` normalizes, deduplicates, and chunks content.
- `indexing/build_index.py` embeds content and writes to Postgres.

This layer is intentionally decoupled from the request path. It prepares the corpus used by the runtime retrieval layer.

### 6. Evaluation layer

The evaluation harness in `evaluation/` exercises the retrieval path and the live SSE chat endpoint to generate benchmark reports.

## Primary request flows

### Login flow

1. The browser posts credentials to `frontend/src/app/api/auth/login/route.ts`.
2. The route handler forwards credentials to `POST /api/v1/auth/login`.
3. FastAPI validates the user and password, then returns a JWT.
4. The Next.js route stores the JWT in an `httpOnly` cookie.
5. Subsequent browser requests stay same-origin and never handle the bearer token directly.

### Authenticated API flow

1. Browser code calls `/api/backend/*` via `frontend/src/lib/api.ts`.
2. The proxy route reads the auth cookie server-side.
3. The proxy forwards the request to FastAPI with `Authorization: Bearer <token>`.
4. FastAPI resolves the current user in `backend/app/api/deps.py`.

### Chat flow

1. The frontend creates or loads a chat session.
2. A user message is posted to `POST /api/v1/chat/sessions/{session_id}/messages`.
3. The backend saves the user message.
4. `run_rag_stream()` retrieves chunks, assembles prompt context, and streams model output.
5. SSE tokens stream back through the frontend proxy to the browser.
6. The backend persists the completed assistant message, sources, retrieved chunk IDs, and latency.

### Analytics flow

1. The frontend analytics page requests corpus stats and chart datasets through the proxy.
2. FastAPI aggregates against `documents`, `document_chunks`, and `ingestion_manifests`.
3. The frontend renders summary cards and charts, including an empty-corpus state.

### Ingestion flow

1. `pipelines/indexing/build_index.py` loads corpus config.
2. An ingester fetches raw source records.
3. Normalization and deduplication produce canonical documents.
4. Chunking produces retrieval units.
5. The active embedding model generates vectors.
6. The pipeline upserts documents and replaces chunk rows idempotently for the active embedding model.
7. A manifest records provenance for the run.

## Architectural boundaries that matter

- The frontend is not allowed to store backend bearer tokens in `localStorage`.
- The backend route layer should not absorb heavy business logic.
- Embedding and LLM dependencies are abstracted so tests can override them cheaply.
- Incremental ingestion is preserved as a first-class workflow, not a one-off script path.
- Persistent indexing currently assumes 768-dimensional PubMedBERT vectors; multi-dimension support remains a future schema change.

## Verified runtime state

The current implementation has been verified locally for:

- PostgreSQL 16 schema bootstrap with pgvector enabled
- login through the Next.js auth proxy
- chat session creation
- chat session reload through `/chat/[sessionId]`
- analytics page rendering against an empty corpus
- logout back to the login page

The remaining runtime quality depends on external corpus ingestion and valid Anthropic credentials for answer generation.