# shellcheck shell=bash
# ─────────────────────────────────────────────────────────────────────────────
#  scripts/lib/common.sh — shared helpers for the production ops scripts.
#
#  Sourced, never executed. Anything that sources this file gets:
#    * the repository root as the working directory
#    * compose()      — docker compose already bound to the right compose file
#    * env_get()      — read one key out of .env without sourcing it
#    * health/state helpers and the changed-path → service map
#
#  COMPOSE_FILE defaults to docker-compose.prod.yml because these scripts exist
#  for the deployment VM. Set COMPOSE_FILE=docker-compose.yml to rehearse any of
#  them against the dev stack on a laptop.
#
#  Portability: written for bash 3.2 (macOS) as well as bash 5 (the VM), so no
#  associative arrays, no mapfile, no ${var^^}.
# ─────────────────────────────────────────────────────────────────────────────

if [ -n "${_RLALAB_COMMON_SOURCED:-}" ]; then return 0; fi
_RLALAB_COMMON_SOURCED=1

# ── Repository root ──────────────────────────────────────────────────────────
# Path-derived rather than `git rev-parse`, so collect-logs.sh still works on a
# deployment that was unpacked from a tarball rather than cloned.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
OPS_DIR="${OPS_DIR:-$ROOT/ops}"

# ── Output ───────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
    C_BLU=$'\033[34m'; C_DIM=$'\033[2m';  C_OFF=$'\033[0m'
else
    C_RED=''; C_GRN=''; C_YEL=''; C_BLU=''; C_DIM=''; C_OFF=''
fi

info() { printf '%s==>%s %s\n' "$C_BLU" "$C_OFF" "$*"; }
ok()   { printf '%s ok %s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
dim()  { printf '%s%s%s\n' "$C_DIM" "$*" "$C_OFF"; }
die()  { printf '%serror%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }

confirm() {  # confirm "question" — honours ASSUME_YES and non-interactive stdin
    [ "${ASSUME_YES:-0}" = "1" ] && return 0
    [ -t 0 ] || die "not a terminal and --yes was not given: refusing to $1"
    printf '%s [y/N] ' "$1"
    local reply; read -r reply
    case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ── docker compose ───────────────────────────────────────────────────────────
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_BIN="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_BIN="docker-compose"
else
    die "neither 'docker compose' nor 'docker-compose' is available"
fi

[ -f "$COMPOSE_FILE" ] || die "$COMPOSE_FILE not found (cwd: $ROOT)"

# Word splitting on $DOCKER_COMPOSE_BIN is deliberate — it is "docker compose".
# shellcheck disable=SC2086
compose() { $DOCKER_COMPOSE_BIN -f "$COMPOSE_FILE" "$@"; }

# Read-only variant that also sees the `tls` profile, so `ps`/`logs` include
# nginx when it is running. Never use this for `up`: it would start nginx.
# shellcheck disable=SC2086
compose_ro() { $DOCKER_COMPOSE_BIN -f "$COMPOSE_FILE" --profile tls "$@"; }

# ── .env access ──────────────────────────────────────────────────────────────
# Reads a single key. Deliberately does NOT source the file: .env holds secrets
# and, per CLAUDE.md §14, must never leak into a child process by accident.
env_get() {  # env_get KEY [FILE]
    local key="$1" file="${2:-$ROOT/.env}"
    [ -f "$file" ] || return 1
    sed -n "s/^[[:space:]]*${key}=//p" "$file" \
        | tail -n 1 \
        | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# ── Services ─────────────────────────────────────────────────────────────────
# `compose config --services` is the single source of truth; the tls profile is
# added so nginx is listed when it exists.
configured_services() { compose_ro config --services 2>/dev/null | tr -d '\r' | sort; }

container_id() { compose_ro ps -q "$1" 2>/dev/null | head -n 1; }

container_state() {  # running | exited | restarting | absent
    local id; id="$(container_id "$1")"
    [ -n "$id" ] || { echo absent; return 0; }
    docker inspect -f '{{.State.Status}}' "$id" 2>/dev/null || echo absent
}

container_restarts() {
    local id; id="$(container_id "$1")"
    [ -n "$id" ] || { echo 0; return 0; }
    docker inspect -f '{{.RestartCount}}' "$id" 2>/dev/null || echo 0
}

# Which services must be rebuilt for a given changed path. "ALL" means the whole
# stack — a compose or address-file change alters every container's definition.
# pipelines/ is copied into the backend image (backend/Dockerfile), so it moves
# the backend and both workers.
services_for_change() {
    case "$1" in
        backend/*|pipelines/*)              echo "backend ingestion-worker evaluation-worker" ;;
        frontend/*)                         echo "frontend" ;;
        docker-compose.prod.yml|.env.server|nginx/*) echo "ALL" ;;
        *)                                  echo "" ;;
    esac
}

# ── Health ───────────────────────────────────────────────────────────────────
health_db() {
    local u d; u="$(env_get POSTGRES_USER)"; d="$(env_get POSTGRES_DB)"
    compose exec -T db pg_isready -U "${u:-postgres}" -d "${d:-rlalab_ai}" >/dev/null 2>&1
}

health_backend() {
    compose exec -T backend curl -fsS -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1
}

health_frontend() {
    compose exec -T frontend node -e \
      "fetch('http://127.0.0.1:3000/login',{redirect:'manual'}).then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))" \
      >/dev/null 2>&1
}

# Workers expose no endpoint; "healthy" for them means up and not restart-looping.
health_worker() {
    [ "$(container_state "$1")" = "running" ]
}

health_of() {  # health_of SERVICE → 0 healthy, 1 unhealthy
    case "$1" in
        db)       health_db ;;
        backend)  health_backend ;;
        frontend) health_frontend ;;
        nginx)    [ "$(container_state nginx)" = "running" ] ;;
        *)        health_worker "$1" ;;
    esac
}

wait_healthy() {  # wait_healthy SERVICE [TIMEOUT_S]
    local svc="$1" timeout="${2:-180}" waited=0
    while [ "$waited" -lt "$timeout" ]; do
        if health_of "$svc"; then return 0; fi
        # A restart loop will never become healthy — fail fast instead of waiting.
        if [ "$(container_state "$svc")" = "exited" ]; then
            warn "$svc exited while waiting for health"
            return 1
        fi
        sleep 3; waited=$((waited + 3))
        printf '%s.%s' "$C_DIM" "$C_OFF"
    done
    printf '\n'
    return 1
}

git_sha()    { git rev-parse HEAD 2>/dev/null || echo unknown; }
git_short()  { git rev-parse --short=12 HEAD 2>/dev/null || echo unknown; }
git_branch() { git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown; }
