#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  scripts/status.sh — one screen: what is deployed, what is running, what is
#  answering. Read-only; safe to run at any time.
#
#  Usage: scripts/status.sh [--no-health]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

DO_HEALTH=1
[ "${1:-}" = "--no-health" ] && DO_HEALTH=0

info "deployed version"
dim "      branch      $(git_branch)"
dim "      commit      $(git_short)  $(git log -1 --pretty='%s' 2>/dev/null || echo '?')"
dim "      committed   $(git log -1 --pretty='%cI' 2>/dev/null || echo '?')"
if git rev-parse --git-dir >/dev/null 2>&1; then
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        warn "working tree has uncommitted tracked changes — this VM is not running plain origin"
    fi
    BEHIND="$(git rev-list --count "HEAD..origin/$(git_branch)" 2>/dev/null || echo '?')"
    [ "$BEHIND" != "0" ] && [ "$BEHIND" != "?" ] && \
        warn "$BEHIND commit(s) behind origin/$(git_branch) — run scripts/deploy.sh (fetch first for an accurate count)"
fi

echo
info "containers"
compose_ro ps

echo
info "state"
for svc in $(configured_services); do
    st="$(container_state "$svc")"
    rs="$(container_restarts "$svc")"
    printf '      %-20s %-12s restarts=%s' "$svc" "$st" "$rs"
    if [ "$DO_HEALTH" = "1" ] && [ "$st" = "running" ]; then
        if health_of "$svc"; then printf '  %shealthy%s' "$C_GRN" "$C_OFF"
        else printf '  %sNOT ANSWERING%s' "$C_RED" "$C_OFF"; fi
    fi
    printf '\n'
done

echo
info "resources"
docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\tmem {{.MemUsage}}' 2>/dev/null \
    | sed 's/^/      /' || true
df -h "$ROOT" 2>/dev/null | sed 's/^/      /'

if [ -f "$OPS_DIR/deploy.log" ]; then
    echo
    info "last 5 deploys  (started, finished, result, commits, services, note)"
    tail -n 5 "$OPS_DIR/deploy.log" | sed 's/^/      /'
fi
