# Unified logging and support bundles

**Audience:** whoever operates the deployment VM, and any agent asked to
diagnose a production problem from evidence rather than from the running system.

---

## 1. The problem

A user reports "the chat stopped answering". The evidence for that one request
is spread over up to five containers:

| Container | What only it knows |
|---|---|
| `frontend` | the browser request, the Next.js route handler, the server-side call to `/api/backend/*`, cookie/auth outcome |
| `backend` | retrieval, the Anthropic call, the SSE stream, the traceback |
| `db` | slow queries, connection exhaustion, checkpoints |
| `ingestion-worker` / `evaluation-worker` | background jobs competing for the same database and model cache |
| `nginx` (TLS profile) | TLS, buffering, upstream timeouts |

Three things were missing:

1. **Retention.** Docker's default `json-file` driver does not rotate. Logs
   either grow until the disk fills — which takes Postgres down with it — or, if
   a container is recreated, vanish entirely.
2. **A single timeline.** `docker compose logs backend` and
   `docker compose logs frontend` are two files a human has to interleave by
   eye.
3. **A way to hand it over.** Copy-pasting terminal scrollback loses ordering,
   loses everything outside the paste, and risks pasting an API key.

---

## 2. What is in place now

Everything below is implemented; nothing new runs on the VM.

### 2.1 stdout stays the log

Every service already writes structured output to stdout: the backend emits one
JSON object per line via structlog (`backend/app/core/logging.py`), Next.js and
Postgres write plain text. Docker captures all of it. No service writes a log
file, and none should — a file inside a container is invisible to
`docker logs` and dies with the container.

SQLAlchemy statement echo is bound to the scenario
(`echo=not settings.is_production`, `backend/app/db/session.py:15`), so the
per-statement SQL flood exists on a laptop and not on the VM. Keep it that way:
with echo on, one busy day exceeds the whole log budget below.

### 2.2 Rotation, so history survives

`docker-compose.prod.yml` sets one `x-logging` anchor on every service:

```yaml
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "20m"
    max-file: "5"
```

100 MB per service, ~600 MB for the stack, bounded. `docker logs` reads the
rotated files as well as the live one, so nothing is hidden by rotation — it
only decides how far back the window reaches. At INFO with echo off, the backend
produces on the order of a few MB a day for this user population, so 100 MB is
weeks of history, not hours.

**This takes effect only when a container is recreated.** After pulling this
change: `scripts/deploy.sh --all --force`, or
`docker compose -f docker-compose.prod.yml up -d --force-recreate`.

### 2.3 One command produces one file

```bash
scripts/collect-logs.sh --since 6h --note "chat 500s for <user>, ~09:40 UTC"
```

Writes `ops/rlalab-support-<host>-<UTC>.tar.gz`:

```
REPORT.md                 what was collected, where to look, what was reported
logs/all.log              ← every service, merged, timestamp-ordered, [service]-tagged
logs/<service>.log        one service, exact original order
meta/versions.txt         deployed commit, docker versions, collection window
meta/containers.txt       state, restart count, exit code, OOM kill, image
meta/compose-ps.txt       docker compose ps
meta/docker-stats.txt     CPU and memory per container
meta/disk.txt  memory.txt  docker-disk.txt
meta/deploy-history.txt   recent deploys — did the problem start at one?
meta/env-redacted.txt     behaviour-affecting settings; secrets as length only
meta/git-*.txt            recent commits, uncommitted files
db/snapshot.txt           counters, alembic revision, indexes, connections
```

`logs/all.log` is the point of the exercise. Docker stamps every line with an
RFC3339 timestamp, so a stable sort on that column interleaves the services
correctly and each line carries its `[service]` tag:

```
2026-08-07T09:40:03.221Z [frontend]        POST /api/backend/chat/sessions/… 502
2026-08-07T09:40:03.219Z [backend]         {"event":"llm call failed","level":"error",…}
2026-08-07T09:40:02.104Z [db]              LOG: duration: 4210.221 ms  execute …
```

The per-service files stay authoritative if a multi-line traceback ever looks
interleaved.

### 2.4 Redaction is verified, not assumed

`scripts/lib/redact.sh` runs two layers over everything in the bundle:

- **Literal** — the actual values of `POSTGRES_PASSWORD`, `SECRET_KEY`,
  `ANTHROPIC_API_KEY`, `NCBI_API_KEY`, `SENDGRID_API_KEY` and friends, read out
  of `.env` and replaced verbatim. This is the layer that catches a secret
  printed in a shape no pattern anticipated.
- **Pattern** — JWTs, `Authorization: Bearer …`, session cookies, `sk-ant-…`,
  passwords inside connection strings, `password`/`secret`/`api_key`/`token`
  key-value pairs.

Then `verify_no_secrets()` greps the finished bundle for those literal values.
**If one survived, the bundle is deleted and the script fails** — a redactor
without that check is a guess.

Two deliberate exceptions:

- A secret whose value is a dictionary word (`postgres`, `changeme`, …) is *not*
  removed literally: it would blank out `postgresql://`, `/var/run/postgresql`
  and every `postgres[27] LOG:` line, i.e. shred the log to hide a non-secret.
  The script says so — and a production password in that list is itself a
  finding worth acting on.
- Email addresses are pseudonymised to `ro***@imperial.ac.uk` rather than
  removed, so one person stays traceable across lines. `--keep-emails` if you
  genuinely need the address.

Never included at all: chat messages, document text, embeddings, `.env` values.
If a specific session must be inspected, query the database on the VM with the
session id — do not put user content into a bundle.

---

## 3. How to use it

**Someone reports a problem.** Ask for two things: roughly when (with a
timezone) and what they did. Then:

```bash
ssh <vm>
cd /opt/rlalab
scripts/collect-logs.sh --since 6h --note "<what they reported, when, which user>"
scp <vm>:/opt/rlalab/ops/rlalab-support-*.tar.gz .
```

Attach the tarball. The `--note` is what makes it diagnosable rather than
archaeological — an untimed bundle is a haystack.

**Something is failing right now.** Watch it instead:

```bash
scripts/logs.sh -f --errors        # errors, tracebacks and HTTP 5xx, all services
scripts/status.sh                  # states, restart counts, health, disk
```

**Reading the backend log in a bundle:**

```bash
grep '\[backend\]' logs/all.log | sed 's/^[^ ]* *\[backend\] *//' \
  | grep '^{' | jq -c 'select(.level=="error")'
```

Uvicorn and library output is plain text on the same stream, hence the
`grep '^{'` before `jq`.

---

## 4. What this does not solve, and what would

### 4.1 Request correlation — the recommended next step

Today, joining a frontend line to the backend line it caused means matching
timestamps by eye. Under concurrent users that is guesswork.

The fix is small and self-contained:

1. An ASGI middleware in `backend/app/main.py` that reads `X-Request-ID` or
   mints one, binds it with `structlog.contextvars.bind_contextvars` (the
   `merge_contextvars` processor is already first in the chain, so every
   subsequent log line inherits it for free), and echoes it back on the
   response.
2. The Next.js proxy (`frontend/src/app/api/backend/[...path]/route.ts`)
   generates the id per browser request, forwards it, and logs it.
3. The chat error path surfaces it in the SSE `error` event so the UI can show
   "reference `7f3a91c2`" — and a user reports *that* instead of "around
   half nine".

Then one grep over `all.log` returns the complete story of one request across
frontend, backend and database. This touches application code and needs the
test gate (CLAUDE.md §15), so it is proposed rather than done.

### 4.2 Live browsing without SSH — Dozzle

One extra container, no storage, no agents:

```yaml
  dozzle:
    image: amir20/dozzle:latest
    container_name: rlalab_dozzle
    restart: unless-stopped
    profiles: ["ops"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "127.0.0.1:8888:8080"    # localhost only — reach it over an SSH tunnel
```

`ssh -L 8888:127.0.0.1:8888 <vm>` then browse `localhost:8888`. Live search and
filtering across all containers.

**It mounts the Docker socket read-only, which is still effectively root on the
VM.** Never publish that port on `0.0.0.0`, and never put it behind the app's
own auth — it must stay behind the SSH boundary.

### 4.3 Search over weeks — Loki

Only worth it if the questions become "how often has this happened since
April?" or "show me every 5xx this month". Grafana Loki + Promtail + Grafana is
three more containers, a retention volume, and real maintenance. It is the right
answer for a fleet; for one VM with 50–100 internal users, rotation plus bundles
answers the same questions with nothing to operate. Revisit if the corpus of
questions outgrows a 48-hour window.

### 4.4 Alerting

Nothing here notices a problem — a human still has to look. The cheapest useful
addition is a cron entry running `scripts/status.sh --no-health` (or a
`/health` probe) and emailing on failure, using the SMTP credentials the app
already holds for invitations.

---

## 5. Adding a new secret

If a new secret goes into `.env`, add its key to `REDACT_KEYS` in
`scripts/lib/redact.sh`. Otherwise it is covered only by the pattern layer,
which is best-effort, and it will not be caught by the pre-handover check.
