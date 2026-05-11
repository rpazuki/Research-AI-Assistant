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
