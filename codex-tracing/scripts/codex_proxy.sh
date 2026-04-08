#!/bin/bash
# Arize codex proxy — ensures collector is running, then execs real codex.
# Placeholders are replaced by install.sh at install time.
ARIZE_CODEX_PROXY=true
REAL_CODEX="__REAL_CODEX__"
ARIZE_ENV_FILE="__ARIZE_ENV_FILE__"
COLLECTOR_CTL="__SHARED_COLLECTOR_CTL__"

# Source env file if it exists
if [[ -f "$ARIZE_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ARIZE_ENV_FILE"
fi

# Ensure collector is running (non-blocking, backgrounded)
if command -v curl >/dev/null 2>&1; then
    # Fast path: health check with 1s timeout
    if ! curl -sf --connect-timeout 1 --max-time 1 http://127.0.0.1:4318/health >/dev/null 2>&1; then
        # Collector not healthy — try to start it in the background
        if [[ -f "$COLLECTOR_CTL" ]]; then
            "$COLLECTOR_CTL" start >/dev/null 2>&1 &
        fi
    fi
elif [[ -f "$COLLECTOR_CTL" ]]; then
    # No curl — just try to start (idempotent), backgrounded
    "$COLLECTOR_CTL" start >/dev/null 2>&1 &
fi

exec "$REAL_CODEX" "$@"
