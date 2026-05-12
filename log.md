# Implementation Log

## Session: 2026-05-11

### Status at session start
Scaffold code already existed for all backend modules and two frontend pages. Missing: frontend config, analytics page, production compose, deduplicator, user bootstrap script.

---

### What was done

#### Backend
- **Fixed `pyproject.toml`**
  - Added `[tool.hatch.build.targets.wheel] packages = ["app"]` — hatchling requires explicit package paths
  - Added `pydantic[email]` — `EmailStr` requires `email-validator` at runtime
  - Pinned `sentence-transformers>=3.0.0,<4.0`, `transformers>=4.40.0,<5.0`, `numpy<2.0`
    — sentence-transformers 4+ and transformers 5+ both require torch≥2.4, which is unavailable on Intel macOS (PyPI ceiling is 2.2.2). numpy 2.x also breaks torch 2.2.x at import.
- **Created `backend/scripts/create_user.py`** — async CLI to provision the first admin/researcher user; required because there is no self-registration endpoint
- **Created `.venv`** with Python 3.12 and installed all deps; verified `from app.main import app` imports cleanly

#### Frontend
- **Created `frontend/next.config.ts`** — standalone output mode; proxy rewrite for `/api/v1/*` to backend
- **Created `frontend/tsconfig.json`** — strict mode, `@/*` path alias to `./src/*`
- **Created `frontend/tailwind.config.ts`** — content paths for App Router
- **Created `frontend/postcss.config.mjs`** — `@tailwindcss/postcss` plugin
- **Created `frontend/src/app/globals.css`** — Tailwind base import, thin scrollbar, blink keyframe
- **Created `frontend/src/app/page.tsx`** — root redirect to `/chat`
- **Created `frontend/src/app/analytics/page.tsx`** — Literature Landscape page: corpus stats cards, temporal bar chart (Recharts), top-journals horizontal bar list
- **Created `frontend/Dockerfile`** — multi-stage build (deps → builder → runner), non-root user, standalone Next.js output

#### Pipelines
- **Created `pipelines/processing/deduplicator.py`** — PMID-based exact dedup + normalized-title fuzzy dedup; `load_existing_pmids()` for incremental runs

#### Infrastructure
- **Created `docker-compose.prod.yml`** — adds nginx service, no exposed DB port, runs `alembic upgrade head` before uvicorn, 2 uvicorn workers
- **Created `.env`** from `.env.example` — placeholder values; user must fill in API keys before starting

---

### Files created this session
```
backend/pyproject.toml                  (modified)
backend/scripts/create_user.py          (new)
frontend/next.config.ts                 (new)
frontend/tsconfig.json                  (new)
frontend/tailwind.config.ts             (new)
frontend/postcss.config.mjs             (new)
frontend/src/app/globals.css            (new)
frontend/src/app/page.tsx               (new)
frontend/src/app/analytics/page.tsx     (new)
frontend/Dockerfile                     (new)
pipelines/processing/deduplicator.py    (new)
docker-compose.prod.yml                 (new)
.env                                    (new, from .env.example)
```

### Outstanding items
- PostgreSQL + pgvector not yet running locally (Docker not installed; Homebrew Postgres suggested as alternative)
- `ANTHROPIC_API_KEY` and `NCBI_API_KEY` in `.env` are placeholders — must be filled before first run
- IVFFlat index on `document_chunks.embedding` must be created manually after first ingestion (see CLAUDE.md §17)
- `pipelines/ingestion/pmc_fulltext.py` full JATS XML parsing is a stub — raw XML returned as `full_text`; section extraction not yet implemented
- Frontend `npm install` not yet run (no Node on path at session time was not checked — run manually)

---

## Session continuation: 2026-05-11

### What was done

#### Frontend
- Replaced browser `localStorage` token storage with a Next.js auth proxy:
  - Added `/api/auth/login` route handler to exchange credentials for a backend JWT and store it in an `httpOnly` cookie
  - Added `/api/auth/logout` route handler to clear the cookie
  - Added `/api/backend/[...path]` proxy route so authenticated frontend requests are forwarded to FastAPI with the bearer token injected server-side
- Refactored `frontend/src/lib/api.ts` to call the proxy layer instead of reading a token in the browser
- Replaced the old chat page implementation with a shared `ChatClient` component and added `/chat/[sessionId]` so historical sessions now restore correctly
- Added sign-out handling in the chat UI and updated the root page to redirect based on cookie presence instead of blindly redirecting to `/chat`
- Expanded the analytics page to show chunk counts, MeSH terms, and topic distribution in addition to the existing temporal and journal views
- Removed the stale `next-auth` dependency entry from `frontend/package.json` because the app no longer uses it and the pinned version did not resolve from npm

#### Backend
- Added `POST /api/v1/auth/logout` as a 204 no-op endpoint so the API surface matches the frontend logout flow
- Expanded analytics with:
  - `chunk_count` in `/analytics/corpus_stats`
  - `/analytics/topics` endpoint using keywords with MeSH fallback
- Added request-level validation for feedback ratings (`1..5`)
- Aligned the embedding abstraction with actual usage by adding async wrapper methods to the base embedding interface
- Tightened retry behavior so the resilience layer retries transient API/network faults instead of retrying arbitrary exceptions
- Decorated Anthropic streaming calls with the retry policy
- Persisted more assistant-message metadata from the chat pipeline: retrieved chunk IDs, model name, sources, and latency

#### Pipelines and evaluation
- Completed incremental PubMed ingestion support:
  - incremental runs now build date-bounded year queries
  - incremental checkpoints are scoped by date
  - incremental builds preload existing PMIDs from the database and skip them
- Added exact-year support for `--year`
- Made indexing idempotent for repeated document updates by replacing existing chunk rows for the active embedding model before re-inserting
- Added an explicit index-model guard so non-768 embedding models are rejected for persistent indexing until the schema supports multiple vector dimensions
- Replaced the placeholder RAG evaluation path with actual SSE consumption, storing streamed responses, sources, and latencies in the report output

#### Validation
- Installed backend dependencies with `pip install -e '.[dev]'`
- Installed frontend dependencies with `npm install`
- Ran backend tests: `6 passed`
- Ran frontend type check: `npm run type-check` passed

### Remaining notable limitations
- `pipelines/ingestion/pmc_fulltext.py` full JATS XML parsing is still incomplete
- Persistent multi-embedding indexing is still not implemented; the code now fails fast instead of pretending otherwise

---

## Session continuation: 2026-05-12

### What was done

#### Automated verification and local runtime
- Installed and initialized a local PostgreSQL 16 cluster under Homebrew
- Created the `rlalab_ai` database and matching `postgres` role for the local `.env` configuration
- Built and installed `pgvector` manually against PostgreSQL 16 after the default Homebrew formula path only exposed extension artifacts for PostgreSQL 17/18 on this machine
- Enabled `CREATE EXTENSION vector` and ran `alembic upgrade head` successfully
- Created a local verification user with `backend/scripts/create_user.py`
- Verified the real browser flow against the live stack:
  - login through the Next.js auth route and backend JWT exchange
  - analytics page rendering against an empty corpus
  - chat session creation and session restore route
  - logout back to `/login`

#### Backend fixes completed during runtime verification
- **Pinned `bcrypt<4.1` in `backend/pyproject.toml`** to restore Passlib-compatible password hashing for user creation and login
- **Fixed async chat session serialization** in `backend/app/api/routes/chat.py` by constructing `ChatSessionWithMessages` explicitly instead of letting Pydantic trigger lazy ORM access on `messages`
- **Updated `backend/app/schemas/chat.py`** to use `Field(default_factory=list)` for `messages`
- **Extended backend integration coverage** with a regression test for `GET /api/v1/chat/sessions/{session_id}`

#### Documentation
- Added `docs/architecture.md` for the abstract layer and flow overview
- Added `docs/components.md` for the concrete component inventory
- Updated `README.md` with:
  - links to the new architecture docs
  - a manual pgvector build fallback for PostgreSQL 16
  - the verified `bcrypt` compatibility note
- Updated `CLAUDE.md` with agent-facing runtime notes about pgvector, bcrypt compatibility, and async ORM serialization hazards

### Validation
- Backend focused integration tests: `5 passed`
- Full backend suite: previously verified at `12 passed`
- Frontend tests: previously verified at `2 passed`
- Frontend type-check: previously verified clean
- Live backend auth endpoint: verified 200 response
- Live UI flows: verified login, analytics, session create/restore, logout

### Remaining notable limitations
- Chat answer generation still depends on external Anthropic credentials and a populated corpus; the empty local database only validates the shell and session flow, not scientific answer quality
- Persistent multi-embedding indexing is still intentionally blocked by the fixed `vector(768)` schema
