#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  scripts/restart.sh — restart deployed services without touching git.
#
#  Use when the code is already right and a process needs bouncing: a hung
#  worker, an .env edit, a stuck model download.
#
#  Usage:
#      scripts/restart.sh                    # restart every service
#      scripts/restart.sh backend frontend   # restart just these
#      scripts/restart.sh --recreate backend # recreate the container, not just
#                                            # the process — required after an
#                                            # .env / .env.server change, since
#                                            # environment is fixed at create
#                                            # time and `restart` keeps it
#      scripts/restart.sh --stop / --start
#
#  Options:
#      --recreate   docker compose up -d --force-recreate (picks up env changes)
#      --stop       stop the named services and exit
#      --start      start them without restarting anything already running
#      -y, --yes    no confirmation prompt
#      -h, --help   this text
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

MODE=restart
ASSUME_YES=0
TARGETS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --recreate) MODE=recreate; shift ;;
        --stop)     MODE=stop; shift ;;
        --start)    MODE=start; shift ;;
        -y|--yes)   ASSUME_YES=1; shift ;;
        -h|--help)  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)         die "unknown option: $1 (try --help)" ;;
        *)          TARGETS="$TARGETS $1"; shift ;;
    esac
done

KNOWN="$(configured_services | tr '\n' ' ')"
if [ -z "$TARGETS" ]; then
    TARGETS="$(echo "$KNOWN" | tr ' ' '\n' | grep -v '^nginx$' | tr '\n' ' ' || true)"
else
    for t in $TARGETS; do
        echo " $KNOWN " | grep -q " $t " || die "unknown service '$t'. Known: $KNOWN"
    done
fi
TARGETS="$(echo "$TARGETS" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

confirm "$MODE these production services: $TARGETS ?" || die "aborted"

# shellcheck disable=SC2086
case "$MODE" in
    restart)  info "restarting $TARGETS";  compose restart $TARGETS ;;
    recreate) info "recreating $TARGETS";  compose up -d --force-recreate $TARGETS ;;
    stop)     info "stopping $TARGETS";    compose stop $TARGETS; exit 0 ;;
    start)    info "starting $TARGETS";    compose up -d $TARGETS ;;
esac

info "waiting for health"
FAILED=0
for svc in $TARGETS; do
    printf '      %-20s' "$svc"
    if wait_healthy "$svc" 240; then
        printf '%s ok%s\n' "$C_GRN" "$C_OFF"
    else
        printf '%s FAILED%s\n' "$C_RED" "$C_OFF"
        FAILED=1
    fi
done

if [ "$FAILED" = "1" ]; then
    warn "at least one service is unhealthy — collect the evidence with:"
    warn "  scripts/collect-logs.sh --since 30m"
    exit 1
fi
ok "all restarted services are answering"
