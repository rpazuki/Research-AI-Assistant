#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  scripts/collect-logs.sh — one redacted, self-contained support bundle.
#
#  A lab member reports "the chat stopped answering". Run this on the VM; it
#  produces a single .tar.gz holding every log line from every container over
#  the window, merged into one chronological file, plus the state needed to
#  interpret them (deployed commit, container states, restart counts, DB
#  counters, resources). Attach that file to the report.
#
#  Secrets are removed on the way out (scripts/lib/redact.sh) and the finished
#  bundle is grepped for the literal values in .env before it is handed over —
#  if any survived, the bundle is deleted rather than written.
#
#  Usage:
#      scripts/collect-logs.sh                       # last 48h, all services
#      scripts/collect-logs.sh --since 30m
#      scripts/collect-logs.sh --since 2026-08-07T09:00:00
#      scripts/collect-logs.sh --note "chat 500s for user X around 09:40 UTC"
#      scripts/collect-logs.sh -s backend -s frontend --tail 5000
#
#  Options:
#      --since SPEC     docker --since: 30m, 6h, 48h, or an RFC3339 timestamp
#                       (default 48h)
#      --tail N         max lines per service (default 20000)
#      -s, --service X  restrict to a service; repeatable
#      --note TEXT      what the user reported — goes in REPORT.md, do use it
#      --out DIR        where to write the archive (default ops/)
#      --no-db          skip the database snapshot (counts only; never content)
#      --keep-emails    do not pseudonymise email addresses
#      --no-redact      DANGEROUS. Raw logs, secrets included. Never share the
#                       result; local debugging only.
#      -h, --help       this text
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$_here/lib/common.sh"
# shellcheck source=lib/redact.sh
. "$_here/lib/redact.sh"

SINCE=48h
TAIL=20000
TARGETS=""
NOTE=""
OUT_DIR="$OPS_DIR"
DO_DB=1
DO_REDACT=1
EMAIL_FLAG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --since)       SINCE="${2:?--since needs a value}"; shift 2 ;;
        --tail)        TAIL="${2:?--tail needs a value}"; shift 2 ;;
        -s|--service)  TARGETS="$TARGETS ${2:?--service needs a value}"; shift 2 ;;
        --note)        NOTE="${2:?--note needs a value}"; shift 2 ;;
        --out)         OUT_DIR="${2:?--out needs a value}"; shift 2 ;;
        --no-db)       DO_DB=0; shift ;;
        --keep-emails) EMAIL_FLAG="--keep-emails"; shift ;;
        --no-redact)   DO_REDACT=0; shift ;;
        -h|--help)     sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             die "unknown option: $1 (try --help)" ;;
    esac
done

[ -n "$TARGETS" ] || TARGETS="$(configured_services | tr '\n' ' ')"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
HOST="$(hostname -s 2>/dev/null || echo unknown)"
NAME="rlalab-support-${HOST}-${STAMP}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/${NAME}.XXXXXX")"
BUNDLE="$WORK/$NAME"
mkdir -p "$BUNDLE/logs" "$BUNDLE/meta" "$BUNDLE/db"
trap 'rm -rf "$WORK"' EXIT

info "collecting since $SINCE (max $TAIL lines/service)"

# ── Metadata ─────────────────────────────────────────────────────────────────
{
    echo "collected_at_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "host:             $HOST"
    echo "uname:            $(uname -a 2>/dev/null)"
    echo "repo_root:        $ROOT"
    echo "compose_file:     $COMPOSE_FILE"
    echo "rlalab_env:       server (fixed by docker-compose.prod.yml)"
    echo "git_branch:       $(git_branch)"
    echo "git_commit:       $(git_sha)"
    echo "git_committed:    $(git log -1 --pretty='%cI' 2>/dev/null || echo '?')"
    echo "git_subject:      $(git log -1 --pretty='%s' 2>/dev/null || echo '?')"
    echo "git_dirty:        $( [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ] && echo yes || echo no )"
    echo "docker:           $(docker --version 2>/dev/null)"
    echo "compose:          $($DOCKER_COMPOSE_BIN version --short 2>/dev/null)"
    echo "window_since:     $SINCE"
    echo "tail_per_service: $TAIL"
} > "$BUNDLE/meta/versions.txt"

git status --porcelain --untracked-files=no > "$BUNDLE/meta/git-dirty-files.txt" 2>/dev/null || true
git log --oneline -20 > "$BUNDLE/meta/git-recent-commits.txt" 2>/dev/null || true

compose_ro ps > "$BUNDLE/meta/compose-ps.txt" 2>&1 || true
docker stats --no-stream > "$BUNDLE/meta/docker-stats.txt" 2>&1 || true
df -h > "$BUNDLE/meta/disk.txt" 2>&1 || true
(free -m 2>/dev/null || vm_stat 2>/dev/null) > "$BUNDLE/meta/memory.txt" 2>&1 || true
docker system df > "$BUNDLE/meta/docker-disk.txt" 2>&1 || true
[ -f "$OPS_DIR/deploy.log" ] && tail -n 30 "$OPS_DIR/deploy.log" > "$BUNDLE/meta/deploy-history.txt"

# Per-container facts that explain most incidents on their own: an OOM kill, a
# non-zero exit, a climbing restart count, an image older than the last deploy.
{
    printf '%-20s %-11s %-31s %-9s %-5s %-6s %s\n' \
        SERVICE STATE STARTED RESTARTS EXIT OOM IMAGE
    for svc in $TARGETS; do
        id="$(container_id "$svc")"
        if [ -z "$id" ]; then
            printf '%-20s %-11s\n' "$svc" "absent"
            continue
        fi
        # `docker inspect -f` already terminates the line; adding an echo here
        # double-spaces the table.
        docker inspect -f \
          "{{printf \"%-20s\" \"$svc\"}} {{printf \"%-11s\" .State.Status}} {{printf \"%-31s\" .State.StartedAt}} {{printf \"%-9d\" .RestartCount}} {{printf \"%-5d\" .State.ExitCode}} {{printf \"%-6v\" .State.OOMKilled}} {{.Config.Image}}" \
          "$id" 2>/dev/null || printf '%-20s %s\n' "$svc" "(inspect failed)"
    done
} > "$BUNDLE/meta/containers.txt"

# Environment: names and whether set, values only for the ones that are safe and
# that actually change behaviour. Never the secrets themselves.
{
    echo "# Non-secret settings that affect behaviour. Secrets show length only."
    for k in RLALAB_ENV LLM_PROVIDER LLM_MODEL EMBEDDING_MODEL EMBEDDING_BATCH_SIZE \
             RETRIEVAL_VECTOR_TOP_K RETRIEVAL_LEXICAL_TOP_K RETRIEVAL_FINAL_TOP_K \
             RERANKER_ENABLED RERANKER_MODEL LOG_LEVEL ACCESS_TOKEN_EXPIRE_MINUTES \
             POSTGRES_DB POSTGRES_USER FRONTEND_HOST_PORT FRONTEND_AUTH_COOKIE_SECURE \
             NCBI_EMAIL CORS_ORIGINS APP_PUBLIC_URL; do
        v="$(env_get "$k" 2>/dev/null || true)"
        [ -z "$v" ] && v="$(env_get "$k" "$ROOT/.env.server" 2>/dev/null || true)"
        printf '%-32s %s\n' "$k" "${v:-<unset>}"
    done
    echo
    echo "# Secrets — presence and length only"
    for k in $REDACT_KEYS; do
        v="$(env_get "$k" 2>/dev/null || true)"
        if [ -n "$v" ]; then printf '%-32s <set: %s chars>\n' "$k" "${#v}"
        else printf '%-32s <unset>\n' "$k"; fi
    done
} > "$BUNDLE/meta/env-redacted.txt"

# ── Logs ─────────────────────────────────────────────────────────────────────
# `docker logs` on the container id rather than `compose logs`: no "service |"
# prefix to strip, and it still works for a container that has exited.
COLLECTED=""
for svc in $TARGETS; do
    id="$(container_id "$svc")"
    if [ -z "$id" ]; then
        echo "(no container for service '$svc' — never started, or removed)" \
            > "$BUNDLE/logs/${svc}.log"
        printf '      %-22s %s\n' "$svc" "absent"
        continue
    fi
    docker logs --timestamps --since "$SINCE" --tail "$TAIL" "$id" \
        > "$BUNDLE/logs/${svc}.log" 2>&1 || \
        echo "(docker logs failed for $svc)" >> "$BUNDLE/logs/${svc}.log"
    COLLECTED="$COLLECTED $svc"
    printf '      %-22s %s lines\n' "$svc" "$(wc -l < "$BUNDLE/logs/${svc}.log" | tr -d ' ')"
done

# The merged view — this is the file to read first. Docker stamps every line
# with an RFC3339 timestamp, so a stable sort on column 1 interleaves the
# services correctly. Stable, so lines sharing a timestamp (a multi-line Python
# traceback) keep their original order; per-service files remain authoritative
# if a traceback ever does get split.
# Only services with a real container take part — a placeholder file has no
# timestamp in column 1 and would sort to a meaningless position.
for svc in $COLLECTED; do
    f="$BUNDLE/logs/${svc}.log"
    [ -f "$f" ] || continue
    awk -v s="$svc" '
        /^[0-9]{4}-[0-9]{2}-[0-9]{2}T/ { ts=$1; $1=""; sub(/^ /,"");
                                         printf "%s %-18s %s\n", ts, "["s"]", $0; next }
        # A line docker did not stamp (rare) inherits the previous timestamp so
        # it stays attached to the entry it belongs to.
        { printf "%s %-18s %s\n", (ts?ts:"0000-00-00T00:00:00.000000000Z"), "["s"]", $0 }
    ' "$f"
done | sort -s -k1,1 > "$BUNDLE/logs/all.log"

# ── Database snapshot ────────────────────────────────────────────────────────
# Counters and schema state only. No document text, no chat content, no PII.
if [ "$DO_DB" = "1" ]; then
    PGUSER_V="$(env_get POSTGRES_USER || echo postgres)"
    PGDB_V="$(env_get POSTGRES_DB || echo rlalab_ai)"
    {
        echo "== pg_isready =="
        compose exec -T db pg_isready -U "$PGUSER_V" -d "$PGDB_V" 2>&1 || true
        echo
        echo "== version / extensions / migration =="
        compose exec -T db psql -U "$PGUSER_V" -d "$PGDB_V" -At -c \
            "select version();
             select extname||' '||extversion from pg_extension;
             select 'alembic_version='||version_num from alembic_version;
             select 'db_size='||pg_size_pretty(pg_database_size(current_database()));" 2>&1 || true
        echo
        echo "== row counts =="
        compose exec -T db psql -U "$PGUSER_V" -d "$PGDB_V" -At -c \
            "select 'users='||count(*) from users;
             select 'documents='||count(*) from documents;
             select 'document_chunks='||count(*) from document_chunks;
             select 'chat_sessions='||count(*) from chat_sessions;
             select 'chat_messages='||count(*) from chat_messages;
             select 'last_ingested_at='||coalesce(max(ingested_at)::text,'none') from documents;" 2>&1 || true
        echo
        echo "== indexes on document_chunks (is the IVFFlat index built?) =="
        compose exec -T db psql -U "$PGUSER_V" -d "$PGDB_V" -At -c \
            "select indexname from pg_indexes where tablename='document_chunks';" 2>&1 || true
        echo
        echo "== connections =="
        compose exec -T db psql -U "$PGUSER_V" -d "$PGDB_V" -At -c \
            "select state||' '||count(*) from pg_stat_activity
             where datname=current_database() group by state;" 2>&1 || true
    } > "$BUNDLE/db/snapshot.txt"
fi

# ── Redact ───────────────────────────────────────────────────────────────────
if [ "$DO_REDACT" = "1" ]; then
    info "redacting"
    SED_SCRIPT="$WORK/redact.sed"
    build_redaction_script "$SED_SCRIPT" $EMAIL_FLAG
    find "$BUNDLE" -type f -print | while IFS= read -r f; do
        redact_file "$SED_SCRIPT" "$f"
    done
else
    warn "--no-redact: this bundle contains secrets in clear text. Do not share it."
fi

# ── Report ───────────────────────────────────────────────────────────────────
cat > "$BUNDLE/REPORT.md" <<EOF
# RLALab support bundle

|                |                                              |
|----------------|----------------------------------------------|
| collected      | $(date -u +%Y-%m-%dT%H:%M:%SZ) (UTC)         |
| host           | $HOST                                         |
| commit         | $(git_short) on $(git_branch)                 |
| window         | last \`$SINCE\`, max $TAIL lines per service  |
| redacted       | $( [ "$DO_REDACT" = "1" ] && echo "yes — secrets removed, emails pseudonymised unless --keep-emails" || echo "**NO — contains secrets, do not share**" ) |

## Reported problem

${NOTE:-_(none given — rerun with --note "what the user saw and roughly when, in UTC")_}

## Where to look

| Path | What it holds |
|------|---------------|
| \`logs/all.log\` | **start here** — every service merged in timestamp order, each line tagged \`[service]\` |
| \`logs/<service>.log\` | one service, exact original order (authoritative if a traceback looks interleaved in all.log) |
| \`meta/containers.txt\` | state, restart count, exit code, OOM kill, image per container |
| \`meta/versions.txt\` | deployed commit, docker versions, collection window |
| \`meta/compose-ps.txt\`, \`meta/docker-stats.txt\`, \`meta/disk.txt\`, \`meta/memory.txt\` | resources |
| \`meta/deploy-history.txt\` | recent deploys — does the problem start at one of them? |
| \`meta/env-redacted.txt\` | behaviour-affecting settings; secrets as length only |
| \`db/snapshot.txt\` | counters, migration revision, indexes. No document or chat content |

## Reading the backend log

The backend emits one JSON object per line (structlog, \`app/core/logging.py\`):

\`\`\`bash
grep '\[backend\]' logs/all.log | sed 's/^[^ ]* *\[backend\] *//' | jq -c 'select(.level=="error")'
\`\`\`

Uvicorn and library output is plain text on the same stream, so \`jq\` will
reject those lines — filter with \`grep '^{'\` first if that is noisy.

## What is deliberately absent

Chat messages, document text, embeddings, \`.env\` values, JWTs and cookies.
If a specific chat session has to be inspected, ask for its session id and
query the database directly on the VM — do not put content in a bundle.
EOF

# ── Verify, then archive ─────────────────────────────────────────────────────
if [ "$DO_REDACT" = "1" ]; then
    if ! verify_no_secrets "$BUNDLE"; then
        die "a secret survived redaction — bundle discarded, nothing written.
      Add the offending key to REDACT_KEYS in scripts/lib/redact.sh and rerun."
    fi
    ok "no .env secret literal survives in the bundle"
fi

mkdir -p "$OUT_DIR"
ARCHIVE="$OUT_DIR/${NAME}.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK" "$NAME"

SIZE="$(du -h "$ARCHIVE" | cut -f1 | tr -d ' ')"
SHA="$( (sha256sum "$ARCHIVE" 2>/dev/null || shasum -a 256 "$ARCHIVE") | cut -d' ' -f1 )"

ok "bundle written"
dim "      file    $ARCHIVE"
dim "      size    $SIZE"
dim "      sha256  $SHA"
echo
dim "      copy it off the VM with:"
dim "        scp $(whoami)@$HOST:$ARCHIVE ."
