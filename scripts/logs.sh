#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  scripts/logs.sh — live, unified log view across every container.
#
#  For watching a problem happen. To hand something over, use collect-logs.sh.
#
#  Usage:
#      scripts/logs.sh -f                       # follow everything, timestamped
#      scripts/logs.sh -f backend frontend
#      scripts/logs.sh -n 500 --grep ERROR
#      scripts/logs.sh --since 15m --errors     # only error-ish lines
#      scripts/logs.sh -f --redact              # safe to screen-share
#
#  Options:
#      -f, --follow     keep streaming
#      -n, --tail N     lines per service (default 200; 'all' for everything)
#          --since S    30m, 6h, or an RFC3339 timestamp
#          --grep RE    keep matching lines only
#          --errors     shorthand for a broad error/exception/traceback filter
#          --redact     strip secrets from the stream
#      -h, --help       this text
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$_here/lib/common.sh"

FOLLOW=""
TAILN=200
SINCE=""
PATTERN=""
DO_REDACT=0
TARGETS=""

while [ $# -gt 0 ]; do
    case "$1" in
        -f|--follow) FOLLOW="--follow"; shift ;;
        -n|--tail)   TAILN="${2:?--tail needs a value}"; shift 2 ;;
        --since)     SINCE="${2:?--since needs a value}"; shift 2 ;;
        --grep)      PATTERN="${2:?--grep needs a value}"; shift 2 ;;
        # Deliberately NOT a case-insensitive /error/: the schema has an `error`
        # column, so every SQL echo would match and bury the real thing.
        --errors)    PATTERN='(^|[^A-Za-z_.])(ERROR|CRITICAL|FATAL)([^A-Za-z_]|$)|Traceback \(most recent call last\)|[A-Za-z]+(Error|Exception):|"level": *"(error|critical)"|HTTP/1\.[01]" 5[0-9][0-9]'; shift ;;
        --redact)    DO_REDACT=1; shift ;;
        -h|--help)   sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)          die "unknown option: $1 (try --help)" ;;
        *)           TARGETS="$TARGETS $1"; shift ;;
    esac
done

ARGS="--no-color --timestamps --tail $TAILN"
[ -n "$FOLLOW" ] && ARGS="$ARGS $FOLLOW"
[ -n "$SINCE" ] && ARGS="$ARGS --since $SINCE"

run() {
    # shellcheck disable=SC2086
    compose_ro logs $ARGS $TARGETS
}

filter() {
    if [ -n "$PATTERN" ]; then grep -E --line-buffered "$PATTERN" || true
    else cat; fi
}

if [ "$DO_REDACT" = "1" ]; then
    # shellcheck source=lib/redact.sh
    . "$_here/lib/redact.sh"
    SED_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/rlalab-redact.XXXXXX")"
    trap 'rm -f "$SED_SCRIPT"' EXIT
    build_redaction_script "$SED_SCRIPT"
    # -u keeps a followed stream from stalling in sed's buffer. GNU sed has it,
    # BSD sed does not — probe once rather than running the pipeline twice.
    SED_UNBUF=""
    printf 'x\n' | sed -u -E 's/x/y/' >/dev/null 2>&1 && SED_UNBUF="-u"
    # shellcheck disable=SC2086
    run | filter | sed -E $SED_UNBUF -f "$SED_SCRIPT"
else
    run | filter
fi
