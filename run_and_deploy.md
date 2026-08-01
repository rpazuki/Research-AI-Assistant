# Running and deploying RLALab AI Assistant

The system is five processes: Postgres, the FastAPI backend, an ingestion worker, an
evaluation worker, and the Next.js frontend. **Docker Compose runs all of them, in every
scenario.** Postgres is always a container — there is no native-Postgres install path.

| | Scenario | What it is | Command |
|---|---|---|---|
| 1 | **`compose`** | everything in containers on your machine | [§3](#3-run-it-locally) |
| 2 | **`local`** | dev inner loop: containerised Postgres, backend and frontend on the host with reload | [§4](#4-dev-inner-loop) |
| 3 | **`server`** | everything in containers on the deployment VM, behind nginx | [§5](#5-deploy-to-the-server) |

---

## 1. Configuration model

**One variable names the scenario. Everything else is derived from it.**

```
RLALAB_ENV = local | compose | server
```

Every component reads that same variable — the backend (`app/core/config.py`), the frontend
(`configs/frontend.yaml`), the pipelines (`configs/pipeline.defaults.yaml`) and the
evaluation runner (`configs/evaluation.yaml`). You never set it by hand: Compose sets it,
and its absence means `local`.

### Three files, one job each

| File | Contains | Loaded by | In git |
|---|---|---|---|
| `.env` | **secrets and behaviour** — API keys, `SECRET_KEY`, `top_k`, model names, log level. **No hostnames, no ports, no URLs.** | every scenario | no |
| `.env.compose` | addresses for containers on a dev machine | `docker-compose.yml` only | yes |
| `.env.server` | addresses for the deployment VM | `docker-compose.prod.yml` only | yes |

Because `.env` contains no addresses, **`source .env` is safe in any shell** — that is the
whole point of the split. The address files are only ever read by Compose, never sourced.

### Two rules behind it

1. **Defaults serve `local`.** Compose is an injection mechanism that always works, so it
   never needs a default. A bare shell has no injection mechanism, so it is the case the
   defaults must cover. Hence `Settings.database_url` defaults to `localhost:5433` — the
   Compose database on its published port — not to `db:5432`.
2. **Each address has exactly one owner.** The database address is owned by
   `Settings` (+ `.env.compose`/`.env.server` for containers); the backend URL as seen by
   the frontend is owned by `frontend/configs/frontend.yaml`; the API URL used by the
   evaluation runner is owned by `evaluation/configs/evaluation.yaml`. Nothing restates
   another component's address.

### The address map

The right address depends on **where the caller runs**, not where the target runs. Compose
service names (`db`, `backend`) resolve only inside the Compose network.

| Caller | Postgres | Backend |
|---|---|---|
| Host process (`npm run dev`, `alembic`, `psql`, `curl`) | `localhost:5433` | `localhost:8000` |
| Container | `db:5432` | `backend:8000` |

---

## 2. Prerequisites

| Need | Required for | macOS | Ubuntu / Debian | RHEL / Rocky / Fedora |
|---|---|---|---|---|
| Docker + Compose v2 | all scenarios | Docker Desktop | `sudo apt install -y docker.io docker-compose-v2` | `sudo dnf install -y docker docker-compose-plugin` |
| Python 3.12 — **not 3.13** (the `torch 2.2.x` pin has no 3.13 wheel) | inner loop only | `brew install python@3.12` | `sudo apt install -y python3.12 python3.12-venv` | `sudo dnf install -y python3.12` |
| Node 20+ | inner loop only | `brew install node@20` | NodeSource `setup_20.x` | NodeSource `setup_20.x` |

Nothing else. No Postgres, no pgvector, no build toolchain — the `pgvector/pgvector:pg16`
image handles all of it.

First-time setup:

```bash
cp .env.example .env      # then fill in the secrets
```

`.env` needs at minimum: `SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`),
`ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, and `NCBI_EMAIL` / `NCBI_API_KEY` for ingestion.

---

## 3. Run it locally

```bash
docker compose up -d --build
docker compose ps
```

| Service | Reachable from the host |
|---|---|
| frontend | http://localhost:3000 |
| backend | http://localhost:8000 (`/api/docs` for the OpenAPI UI) |
| db | `localhost:5433` |
| ingestion-worker, evaluation-worker | no port — they poll the database |

Migrations run automatically: the backend container's command is
`alembic upgrade head && uvicorn …`.

Create the first admin:

```bash
docker compose exec backend python scripts/create_user.py \
  --email you@imperial.ac.uk --password '<choose-one>' --role admin
```

Then sign in at http://localhost:3000/login.

`docker-compose.override.yml` is applied automatically. It bind-mounts `backend/app`,
`backend/alembic` and `pipelines`, and adds `--reload`, so **Python changes are live**. The
frontend service runs the production image, so a frontend change needs
`docker compose up -d --build frontend` — or use the inner loop below.

---

## 4. Dev inner loop

Postgres in a container; backend and frontend on the host with reload and a debugger.

```bash
docker compose up -d db                  # publishes localhost:5433
```

**Backend** — one-time venv, then run:

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

```bash
set -a; source .env; set +a              # secrets only — no addresses, safe in any shell
cd backend
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

No `DATABASE_URL` needed: `RLALAB_ENV` is unset, so the `local` default already points at
`localhost:5433`.

**Frontend** — needs no environment at all:

```bash
cd frontend
npm install
npm run dev                              # http://localhost:3000
```

**Workers**, if you are ingesting or evaluating — each in its own terminal, same
`source .env`:

```bash
cd backend && .venv/bin/python -m app.ingestion.worker
cd backend && .venv/bin/python -m app.evaluation.worker
```

First start downloads PubMedBERT (~440 MB) into `backend/model_cache`.

Verify:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/v1/auth/me   # 401 = alive
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/login            # 200
```

A `401` from `/auth/me` is success — the endpoint is up and requires a token.

---

## 5. Deploy to the server

Single VM, Docker Compose, nginx terminating TLS. Assumes the repo at `/opt/rlalab`.

### 5.1 Secrets and addresses

```bash
cp .env.example .env && chmod 600 .env
```

In `.env` — production values:

| Variable | Value |
|---|---|
| `SECRET_KEY` | freshly generated; **never** the development value |
| `POSTGRES_PASSWORD` | a real password |
| `ANTHROPIC_API_KEY`, `NCBI_*`, `SENDGRID_*` | real credentials |

In `.env.server` — replace the placeholder hostname in `CORS_ORIGINS` and `APP_PUBLIC_URL`
with the real one. There is no `DATABASE_URL` to set: `docker-compose.prod.yml` assembles it
from `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`, so the password has exactly one
owner. If the password contains `@ : / # ?`, percent-encode it — asyncpg parses the URL and a
raw `@` truncates the host.

**Rotating `POSTGRES_PASSWORD` later takes two steps, not one.** The Postgres image reads that
variable only when it initialises an empty data directory; once `pgdata` exists, editing `.env`
changes what the backend sends and nothing about what the server expects. See §7.

You do **not** set `RLALAB_ENV` — `docker-compose.prod.yml` sets it to `server`.

### 5.2 How the app is served

Two topologies. Pick one; they contend for host port 80.

**Plain HTTP (the default).** `frontend` publishes host `80` → container `3000` and serves the
app directly. nginx does not start. This is complete on its own: the browser only ever talks to
the frontend origin, which proxies to the backend server-side under `/api/backend/*`, so no
second hop is needed. Two settings must match it:

| Where | Setting | Why |
|---|---|---|
| `.env` | `FRONTEND_AUTH_COOKIE_SECURE=false` | `frontend.yaml` marks the auth cookie `Secure` for `server`; a browser silently discards a `Secure` cookie over HTTP, so login succeeds and immediately bounces back to `/login` |
| `.env.server` | `APP_PUBLIC_URL=http://<host>` | invitation emails link here |

Credentials then cross the network in clear text. On a wired campus subnet that may be an
acceptable trade for a first deployment; it is not acceptable once the tool holds real accounts.

```bash
docker compose -f docker-compose.prod.yml up -d
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' http://localhost/login      # 200
```

**TLS via nginx.** Started only by its profile, because it needs files that are not in the repo
and would otherwise fight the frontend for port 80:

```bash
docker compose -f docker-compose.prod.yml --profile tls up -d
```

Set `FRONTEND_HOST_PORT=3000` in `.env` first to free port 80, restore
`FRONTEND_AUTH_COOKIE_SECURE=true` (or unset it — that is the default), and put
`APP_PUBLIC_URL` back to `https://`.

`docker-compose.prod.yml` mounts `./nginx/nginx.conf` and `./nginx/ssl`. **Neither exists in
the repo — create them or the nginx container will not start.**

```bash
mkdir -p nginx/ssl
# place fullchain.pem and privkey.pem in nginx/ssl/
```

`nginx/nginx.conf` — a complete config (it replaces `/etc/nginx/nginx.conf`, not a site
snippet), using service names because nginx runs inside the network:

```nginx
events {}
http {
  # Docker's embedded DNS. An `upstream { server frontend:3000; }` block resolves
  # once, while the configuration is being read, so nginx exits with
  #   [emerg] host not found in upstream "frontend:3000"
  # whenever it starts before the frontend — and it never picks up the new address
  # after a container is recreated. Resolving per request avoids both.
  resolver 127.0.0.11 valid=10s ipv6=off;

  map $http_upgrade $connection_upgrade { default upgrade; '' close; }

  server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
  }

  server {
    listen 443 ssl;
    http2 on;                     # nginx < 1.25.1: use `listen 443 ssl http2;`
    server_name _;

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    # Everything the browser touches, INCLUDING /api/auth/* and /api/backend/*,
    # which are Next.js route handlers on this origin — not the FastAPI backend.
    # Sending /api/ to the backend would break login.
    location / {
      set $frontend_upstream frontend:3000;
      proxy_pass http://$frontend_upstream$request_uri;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_buffering off;        # the chat stream reaches the browser from here
      proxy_read_timeout 300s;
    }

    # FastAPI's own prefix. Not needed by the browser — the frontend proxies
    # server-side — but useful for curl and the OpenAPI docs.
    location /api/v1/ {
      set $backend_upstream backend:8000;
      proxy_pass http://$backend_upstream$request_uri;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_buffering off;        # required: chat streams tokens over SSE
      proxy_read_timeout 300s;
    }
  }
}
```

`proxy_buffering off` is required, not cosmetic — with it on, chat replies arrive in one
lump at the end.

### 5.3 Deploy

```bash
cd /opt/rlalab
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

Differences from local: `restart: unless-stopped`, Postgres **not** published, backend and
frontend `expose`d to the network only, `uvicorn --workers 2`, and the nginx service.

First admin:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python scripts/create_user.py --email admin@… --password '…' --role admin
```

**Pass `-f docker-compose.prod.yml` on every command.** Omit it and Docker loads
`docker-compose.yml` + `docker-compose.override.yml` — the dev stack, with `--reload`, a
published database port and no nginx.

### 5.4 Update

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Compose recreates only changed services. Migrations apply on backend start.

---

## 6. Operations

**Logs**

```bash
docker compose logs -f backend                    # add -f <file> on the server
docker compose logs --tail 200 ingestion-worker
```

**Database shell**

```bash
docker compose exec db psql -U postgres -d rlalab_ai
```

**Backup / restore.** State lives in three named volumes: `pgdata` (the corpus and users —
back this up), `model_cache` (440 MB of weights, rebuildable), `corpus_data` (ingestion
caches and uploads).

```bash
docker compose exec -T db pg_dump -U postgres rlalab_ai | gzip > backup-$(date +%F).sql.gz
gunzip -c backup-2026-07-29.sql.gz | docker compose exec -T db psql -U postgres -d rlalab_ai
```

**Stop**

```bash
docker compose down          # stop, keep volumes
docker compose down -v       # ⚠ also deletes pgdata, model_cache, corpus_data
```

**IVFFlat index.** It cannot live in a migration — pgvector needs rows before the index can
be built (CLAUDE.md §17.1). Once, after the first substantial ingestion:

```sql
CREATE INDEX ix_chunks_embedding ON document_chunks
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

`pipelines/indexing/build_index.py` prints this reminder when a first load completes.

**Tests** — the gate before any deploy (CLAUDE.md §15):

```bash
cd backend && .venv/bin/python -m pytest tests/ -v --tb=short
cd ../frontend && npm test -- --run && npm run type-check
```

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `getaddrinfo ENOTFOUND backend` / `ENOTFOUND db` | a host process was given a Compose service name — something exported an address into your shell | `.env` must contain no addresses; check `env | grep -E 'DATABASE_URL|NEXT_PUBLIC_API_URL'` is empty, then restart the process |
| `ValidationError: rlalab_env` at startup | typo in `RLALAB_ENV` | must be exactly `local`, `compose` or `server` |
| Frontend still uses an old backend URL | `next.config.ts` is read once at boot | restart `next dev`; for the image, rebuild |
| Login works, then admin pages 500 | Next server-side proxy cannot reach the backend | `curl localhost:8000/api/v1/auth/me` → expect `401` |
| Chat replies arrive all at once | nginx buffering | `proxy_buffering off` on `/api/` |
| `ModuleNotFoundError: pytest`, or a torch wheel error | wrong interpreter — `.venv-1` is Python 3.13 | always `backend/.venv/bin/python` |
| Frontend change invisible under Compose | that service runs the production image | `docker compose up -d --build frontend`, or use §4 |
| `database preflight failed: database password mismatch`, or a raw `InvalidPasswordError` in a restart loop | `POSTGRES_PASSWORD` was changed after the volume was initialised; the image reads it only at first init | rotate it on the running server — recipe below |
| Retrieval slow after a big ingestion | IVFFlat index missing | §6 |
| `Cache path must live under data/corpora` on the stats or acquisition page, though the folder exists | a *mixed* topology — e.g. a containerised ingestion worker (repo root `/app`) writing job rows read by a host backend (repo root the checkout) | cache paths are stored repo-relative (`data/corpora/<name>`) and re-rooted on read, so this now only means the cache is genuinely absent locally; note that with the default named volume the container's `data/` and your `./data/` are **separate copies** — run one topology, or sync them |

### 7.1 Rotating the database password

`POSTGRES_PASSWORD` is an *initdb* variable. The Postgres image reads it exactly once, when it
initialises an empty data directory. From then on the role's password lives in `pgdata`, and
editing `.env` changes only what the backend presents — so the two drift apart, every container
that talks to the database exits, and `restart: unless-stopped` turns that into a loop. While a
container is restarting, `docker compose exec` refuses to attach, which is why `create_user.py`
reports *"is restarting, wait until the container is running"*.

Every service now runs `python -m app.db.preflight` before its real command, so the log says
`database password mismatch` and names the fix instead of printing an asyncpg traceback.

Rotate in two steps. `exec db psql` connects over the unix socket, which the image configures as
`trust`, so this works even when nothing can authenticate over TCP:

```bash
docker compose -f docker-compose.prod.yml stop backend ingestion-worker evaluation-worker
docker compose -f docker-compose.prod.yml exec db psql -U postgres
```

At the prompt — interactive, so the secret stays out of shell history and the statement log:

```
\password postgres
\q
```

Then set the same value as `POSTGRES_PASSWORD` in `.env` and bring the stack back:

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f backend
```

`docker compose down -v` also works, by discarding `pgdata` and re-running initdb. It **destroys
every user, document, chunk and embedding**; it is only reasonable on a deployment with nothing
in it yet.

To run a one-off command while the backend is still crash-looping, use `run` rather than `exec` —
it starts a fresh container and ignores the failing `command`:

```bash
docker compose -f docker-compose.prod.yml run --rm backend python scripts/create_user.py
```

---

## 8. Reference

```bash
# compose  — everything in containers (§3)
docker compose up -d --build
docker compose logs -f backend
docker compose down

# local    — inner loop (§4)
docker compose up -d db
set -a; source .env; set +a; cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# server   — deployment VM (§5)
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f backend
```

| | `local` | `compose` | `server` |
|---|---|---|---|
| Postgres | `localhost:5433` | `db:5432` | `db:5432` (not published) |
| Backend | `localhost:8000` | `backend:8000` | `backend:8000` (via nginx) |
| Frontend | `localhost:3000` | `localhost:3000` | `:443` via nginx |
| Addresses from | code defaults | `.env.compose` | `.env.server` |
| Secrets from | `.env` | `.env` | `.env` |
| Set by | nobody (the default) | `docker-compose.yml` | `docker-compose.prod.yml` |
