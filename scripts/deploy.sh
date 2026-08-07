#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  scripts/deploy.sh — update the deployed version on the production VM.
#
#      fast-forward from GitHub → rebuild only the services whose code moved
#      → recreate them → verify health → roll back if verification fails.
#
#  Replaces the two-line manual recipe in run_and_deploy.md §5.4. The value it
#  adds over `git pull && docker compose up -d --build` is: refuses to run on a
#  dirty or diverged tree, rebuilds the frontend without touching the backend
#  (and vice versa), proves the stack answers afterwards, and leaves an audit
#  line in ops/deploy.log.
#
#  Usage:
#      scripts/deploy.sh                    # pull, rebuild what changed, verify
#      scripts/deploy.sh -y                 # same, no confirmation prompt (cron)
#      scripts/deploy.sh -s frontend        # rebuild one service, whatever changed
#      scripts/deploy.sh --all --force      # rebuild everything at the current commit
#      scripts/deploy.sh --no-pull -s backend
#      scripts/deploy.sh --dry-run          # show the plan, change nothing
#
#  Options:
#      -b, --branch NAME   branch to fast-forward from    (default: current branch)
#      -s, --service NAME  restrict to this service; repeatable
#          --all           treat every service as changed
#          --no-pull       skip git entirely, rebuild from the working tree
#          --force         rebuild even when the commit did not move
#          --no-cache      docker build --no-cache
#          --no-rollback   leave the new commit in place if health checks fail
#          --allow-dirty   proceed with uncommitted tracked changes
#          --prune         docker image prune -f after a successful deploy
#          --dry-run       print the plan and exit
#      -y, --yes           do not ask for confirmation
#      -h, --help          this text
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

BRANCH=""
EXPLICIT_SERVICES=""
DO_PULL=1
DO_ALL=0
FORCE=0
NO_CACHE=0
ROLLBACK=1
ALLOW_DIRTY=0
PRUNE=0
DRY_RUN=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        -b|--branch)   BRANCH="${2:?--branch needs a value}"; shift 2 ;;
        -s|--service)  EXPLICIT_SERVICES="$EXPLICIT_SERVICES ${2:?--service needs a value}"; shift 2 ;;
        --all)         DO_ALL=1; shift ;;
        --no-pull)     DO_PULL=0; shift ;;
        --force)       FORCE=1; shift ;;
        --no-cache)    NO_CACHE=1; shift ;;
        --no-rollback) ROLLBACK=0; shift ;;
        --allow-dirty) ALLOW_DIRTY=1; shift ;;
        --prune)       PRUNE=1; shift ;;
        --dry-run)     DRY_RUN=1; shift ;;
        -y|--yes)      ASSUME_YES=1; shift ;;
        -h|--help)     sed -n '2,44p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             die "unknown option: $1 (try --help)" ;;
    esac
done

# ── One deploy at a time ─────────────────────────────────────────────────────
mkdir -p "$OPS_DIR"
LOCK="$OPS_DIR/deploy.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    die "a deploy is already running (started $(cat "$LOCK/started_at" 2>/dev/null || echo '?')).
      If that is stale: rmdir $LOCK"
fi
date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK/started_at" 2>/dev/null || true
cleanup() { rm -rf "$LOCK" 2>/dev/null || true; }
trap cleanup EXIT

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BEFORE="$(git_sha)"
AFTER="$BEFORE"

record() {  # record RESULT DETAIL — one audit line per deploy attempt
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$STARTED_AT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" \
        "${BEFORE:0:12}->${AFTER:0:12}" "${SERVICES:-none}" "$2" \
        >> "$OPS_DIR/deploy.log"
}

# ── 1. Preconditions ─────────────────────────────────────────────────────────
[ -f "$ROOT/.env" ] || die ".env is missing — the stack cannot start without it (run_and_deploy.md §5.1)"

if [ "$DO_PULL" = "1" ]; then
    git rev-parse --git-dir >/dev/null 2>&1 || die "not a git checkout — use --no-pull"
    [ -n "$BRANCH" ] || BRANCH="$(git_branch)"
    [ "$BRANCH" != "HEAD" ] || die "detached HEAD — check out a branch or pass --branch"

    if [ "$ALLOW_DIRTY" = "0" ] && [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        git status --short --untracked-files=no >&2
        die "the working tree has uncommitted tracked changes.
      A rollback would discard them, so deploy refuses to start.
      Commit/stash them, or pass --allow-dirty (which disables rollback safety)."
    fi
fi

# ── 2. Fast-forward ──────────────────────────────────────────────────────────
if [ "$DO_PULL" = "1" ]; then
    info "fetching origin/$BRANCH"
    [ "$DRY_RUN" = "1" ] || git fetch --prune origin "$BRANCH"

    REMOTE_SHA="$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")"
    [ -n "$REMOTE_SHA" ] || die "origin/$BRANCH does not exist"

    if [ "$REMOTE_SHA" != "$BEFORE" ]; then
        info "$(git log --oneline "$BEFORE..$REMOTE_SHA" | wc -l | tr -d ' ') new commit(s):"
        git log --oneline --no-decorate "$BEFORE..$REMOTE_SHA" | head -20 | sed 's/^/      /'
        if [ "$DRY_RUN" = "0" ]; then
            # --ff-only, never a merge: a diverged production checkout is an
            # operator problem, not something a deploy script should resolve.
            git merge --ff-only "origin/$BRANCH" \
                || die "cannot fast-forward: the checkout has diverged from origin/$BRANCH.
      Inspect with: git log --oneline --graph HEAD origin/$BRANCH"
        fi
        AFTER="$(git_sha)"
    else
        ok "already at origin/$BRANCH ($(git_short))"
    fi
fi

# ── 3. What has to be rebuilt ────────────────────────────────────────────────
ALL_SERVICES="$(configured_services | grep -v '^nginx$' | tr '\n' ' ' || true)"

pick_services() {
    if [ -n "$EXPLICIT_SERVICES" ]; then
        echo "$EXPLICIT_SERVICES"; return
    fi
    if [ "$DO_ALL" = "1" ] || [ "$DO_PULL" = "0" ]; then
        echo "$ALL_SERVICES"; return
    fi
    if [ "$BEFORE" = "$AFTER" ]; then
        [ "$FORCE" = "1" ] && { echo "$ALL_SERVICES"; return; }
        echo ""; return
    fi

    local path out=""
    for path in $(git diff --name-only "$BEFORE" "$AFTER"); do
        local mapped; mapped="$(services_for_change "$path")"
        [ "$mapped" = "ALL" ] && { echo "$ALL_SERVICES"; return; }
        out="$out $mapped"
    done
    echo "$out"
}

# De-duplicate. `|| true` because an empty selection is the normal "nothing
# changed" case, and grep returning 1 would otherwise kill the script under
# `set -e` before it can say so.
SERVICES="$(pick_services | tr ' ' '\n' | grep -v '^$' | sort -u | tr '\n' ' ' || true)"
SERVICES="$(echo "$SERVICES" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

if [ -z "$SERVICES" ]; then
    ok "nothing changed — making sure the stack is up"
    [ "$DRY_RUN" = "1" ] || compose up -d
    record skipped "no code change"
    exit 0
fi

# Anything built from a Dockerfile needs an image build; db does not.
BUILD_SERVICES="$(echo "$SERVICES" | tr ' ' '\n' | grep -v '^db$' | tr '\n' ' ' || true)"

info "plan"
dim "      commit    ${BEFORE:0:12} -> ${AFTER:0:12}"
dim "      compose   $COMPOSE_FILE"
dim "      build     ${BUILD_SERVICES:-(none)}"
dim "      recreate  $SERVICES"
dim "      migrations run automatically when the backend container starts"

if [ "$DRY_RUN" = "1" ]; then
    ok "dry run — nothing changed"
    exit 0
fi

confirm "Restart the listed production services now?" || { record aborted "operator declined"; die "aborted"; }

# ── 4. Build ─────────────────────────────────────────────────────────────────
BUILD_ARGS=""
[ "$NO_CACHE" = "1" ] && BUILD_ARGS="--no-cache"

deploy_failed() {
    local reason="$1"
    warn "deploy failed: $reason"
    printf '\n%s--- last 60 log lines per affected service ---%s\n' "$C_DIM" "$C_OFF"
    local s
    for s in $SERVICES; do
        printf '\n%s### %s%s\n' "$C_YEL" "$s" "$C_OFF"
        compose logs --no-color --tail 60 "$s" 2>&1 | sed 's/^/      /'
    done

    if [ "$ROLLBACK" = "1" ] && [ "$BEFORE" != "$AFTER" ] && [ "$ALLOW_DIRTY" = "0" ]; then
        warn "rolling back the checkout to ${BEFORE:0:12} and rebuilding"
        warn "DATABASE MIGRATIONS ARE NOT ROLLED BACK — if 'alembic upgrade head' ran,"
        warn "the schema stays ahead of the code. Check ops/deploy.log and the backend log."
        git reset --hard "$BEFORE" >/dev/null
        AFTER="$BEFORE"
        # shellcheck disable=SC2086
        compose build $BUILD_SERVICES && compose up -d $SERVICES \
            && warn "rolled back to ${BEFORE:0:12}" \
            || warn "ROLLBACK ALSO FAILED — the stack needs manual attention"
    fi
    record failed "$reason"
    exit 1
}

info "building: ${BUILD_SERVICES:-(none)}"
if [ -n "$BUILD_SERVICES" ]; then
    # shellcheck disable=SC2086
    compose build $BUILD_ARGS $BUILD_SERVICES || deploy_failed "image build"
fi

# ── 5. Recreate ──────────────────────────────────────────────────────────────
info "recreating: $SERVICES"
# shellcheck disable=SC2086
compose up -d $SERVICES || deploy_failed "compose up"

# ── 6. Verify ────────────────────────────────────────────────────────────────
# The backend runs preflight + `alembic upgrade head` before uvicorn binds, so a
# slow first start after a migration is normal — hence the generous timeout.
info "waiting for health"
for svc in $SERVICES; do
    printf '      %-20s' "$svc"
    if wait_healthy "$svc" 240; then
        printf '%s ok%s\n' "$C_GRN" "$C_OFF"
    else
        printf '%s FAILED%s\n' "$C_RED" "$C_OFF"
        deploy_failed "$svc did not become healthy"
    fi
done

# A container that is up but restart-looping passes a single point check; the
# restart count catches it.
for svc in $SERVICES; do
    r="$(container_restarts "$svc")"
    [ "${r:-0}" -gt 3 ] && warn "$svc has restarted $r times — check its log"
done

[ "$PRUNE" = "1" ] && { info "pruning dangling images"; docker image prune -f >/dev/null; }

record ok "$(git log -1 --pretty=%s 2>/dev/null | tr '\t' ' ')"
ok "deployed ${AFTER:0:12} ($(git_branch))"
dim "      audit:  $OPS_DIR/deploy.log"
dim "      status: scripts/status.sh"
dim "      logs:   scripts/logs.sh -f"
