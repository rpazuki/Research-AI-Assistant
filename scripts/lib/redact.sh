# shellcheck shell=bash
# ─────────────────────────────────────────────────────────────────────────────
#  scripts/lib/redact.sh — strip secrets out of anything leaving the VM.
#
#  Two layers, because either alone is insufficient:
#
#    1. LITERAL. The actual values of the known secret keys in .env are read and
#       replaced verbatim. This is the layer that matters: it catches a password
#       printed in a shape no pattern anticipated (a DSN in a traceback, an
#       argv dump, a JSON body).
#    2. PATTERN. Shapes of secrets that were never in .env — session JWTs,
#       Authorization headers, cookies, provider keys echoed by a third-party
#       library.
#
#  verify_no_secrets() then greps the finished bundle for the literal values as
#  a last check before anything is handed over. Redaction is best-effort by
#  nature; that check is what turns it into something you can rely on.
# ─────────────────────────────────────────────────────────────────────────────

if [ -n "${_RLALAB_REDACT_SOURCED:-}" ]; then return 0; fi
_RLALAB_REDACT_SOURCED=1

# Keys whose *values* are searched for and removed. Add to this list whenever a
# new secret is introduced into .env.
REDACT_KEYS="POSTGRES_PASSWORD SECRET_KEY ANTHROPIC_API_KEY LLM_API_KEY NCBI_API_KEY SENDGRID_API_KEY SMTP_PASSWORD ADMIN_PASSWORD OPENAI_API_KEY"

# Values too generic to blank out literally. A POSTGRES_PASSWORD of "postgres"
# would otherwise turn every "postgresql://", "/var/run/postgresql" and
# "postgres[27] LOG:" in the bundle into ***REDACTED***, i.e. destroy the log to
# hide a word that is not a secret. Such keys are skipped by both the redactor
# and the verifier, and reported — a production password in this list is itself
# the finding.
REDACT_WEAK_VALUES="postgres password passwd changeme admin secret rlalab test dev local"

# Keys skipped for the above reason; filled in by build_redaction_script().
REDACT_SKIPPED=""

_is_weak_value() {
    local v w
    v="$(printf '%s' "$1" | tr 'A-Z' 'a-z')"
    for w in $REDACT_WEAK_VALUES; do
        [ "$v" = "$w" ] && return 0
    done
    return 1
}

# Escape a literal string for use on the left-hand side of `sed -E s///`.
sed_escape() { printf '%s' "$1" | sed -e 's/[][\\/$*.^|?+(){}&]/\\&/g'; }

# build_redaction_script OUTFILE [--mask-emails]
build_redaction_script() {
    local out="$1"; shift
    local mask_emails=1
    [ "${1:-}" = "--keep-emails" ] && mask_emails=0

    : > "$out"

    # ── Layer 1: literal values from .env ────────────────────────────────────
    REDACT_SKIPPED=""
    local key value
    for key in $REDACT_KEYS; do
        value="$(env_get "$key" 2>/dev/null || true)"
        [ -n "$value" ] || continue
        # A short value would match half the log file and destroy it.
        if [ "${#value}" -lt 6 ] || _is_weak_value "$value"; then
            REDACT_SKIPPED="$REDACT_SKIPPED $key"
            warn "$key is a short or dictionary value — not removed literally (it would"
            warn "  shred the logs); the pattern rules still cover it. In production this"
            warn "  is a weak credential and should be rotated."
            continue
        fi
        printf 's/%s/***REDACTED-%s***/g\n' "$(sed_escape "$value")" "$key" >> "$out"
    done

    # ── Layer 2: shapes ──────────────────────────────────────────────────────
    cat >> "$out" <<'SEDEOF'
s#(postgres(ql)?(\+[a-z]+)?://[^:/@[:space:]]+:)[^@[:space:]]+@#\1***REDACTED-DBPASS***@#g
s/eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]+/***REDACTED-JWT***/g
s/([Bb][Ee][Aa][Rr][Ee][Rr] )[A-Za-z0-9._~+/=-]{12,}/\1***REDACTED-TOKEN***/g
s/sk-ant-[A-Za-z0-9_-]{8,}/***REDACTED-ANTHROPIC-KEY***/g
s/sk-[A-Za-z0-9]{20,}/***REDACTED-KEY***/g
s/(([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Aa][Pp][Ii][-_]?[Kk][Ee][Yy]|[Aa][Cc][Cc][Ee][Ss][Ss][-_]?[Tt][Oo][Kk][Ee][Nn]|[Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn])"?[[:space:]]*[:=][[:space:]]*"?)[^",;[:space:]]{3,}/\1***REDACTED***/g
s/((rlalab|session|auth)[A-Za-z_-]*=)[A-Za-z0-9._~+/=-]{12,}/\1***REDACTED-COOKIE***/g
SEDEOF

    # ── Optional: pseudonymise addresses ─────────────────────────────────────
    # Two leading characters survive so the same person stays recognisable
    # across lines without the mailbox being readable.
    if [ "$mask_emails" = "1" ]; then
        printf 's/([A-Za-z0-9._%%+-]{1,2})[A-Za-z0-9._%%+-]*@([A-Za-z0-9.-]+\\.[A-Za-z]{2,})/\\1***@\\2/g\n' >> "$out"
    fi
}

# redact_file SCRIPT FILE — rewrite FILE in place.
redact_file() {
    local script="$1" file="$2" tmp="$2.redacting"
    sed -E -f "$script" "$file" > "$tmp" && mv "$tmp" "$file"
}

# verify_no_secrets DIR → 0 clean, 1 a literal secret survived.
# Keys deliberately skipped above are skipped here too: greping for "postgres"
# would fail every bundle without telling anyone anything.
verify_no_secrets() {
    local dir="$1" key value hits rc=0
    for key in $REDACT_KEYS; do
        echo " $REDACT_SKIPPED " | grep -q " $key " && continue
        value="$(env_get "$key" 2>/dev/null || true)"
        [ -n "$value" ] || continue
        [ "${#value}" -ge 6 ] || continue
        _is_weak_value "$value" && continue
        hits="$(grep -rIlF -- "$value" "$dir" 2>/dev/null || true)"
        if [ -n "$hits" ]; then
            warn "SECRET LEAK: the value of $key still appears in:"
            printf '%s\n' "$hits" | sed 's/^/        /' >&2
            rc=1
        fi
    done
    return $rc
}
