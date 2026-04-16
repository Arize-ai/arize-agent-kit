#!/bin/bash
# Arize codex proxy — ensures buffer service is running, then execs real codex.
# Placeholders are replaced by install.sh at install time.
ARIZE_CODEX_PROXY=true
REAL_CODEX="__REAL_CODEX__"
ARIZE_ENV_FILE="__ARIZE_ENV_FILE__"
BUFFER_CTL="__SHARED_COLLECTOR_CTL__"
DRAIN_CMD="__DRAIN_CMD__"

# Source env file if it exists
if [[ -f "$ARIZE_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ARIZE_ENV_FILE"
fi

# Ensure buffer service is running (blocking — codex needs it before sending events)
if command -v curl >/dev/null 2>&1; then
    if ! curl -sf --connect-timeout 1 --max-time 1 http://127.0.0.1:4318/health >/dev/null 2>&1; then
        if [[ -f "$BUFFER_CTL" ]]; then
            "$BUFFER_CTL" start >/dev/null 2>&1
            # Wait briefly for health (up to 2s)
            for _ in $(seq 1 20); do
                curl -sf --connect-timeout 0.1 --max-time 0.1 http://127.0.0.1:4318/health >/dev/null 2>&1 && break
                sleep 0.1
            done
        fi
    fi
elif [[ -f "$BUFFER_CTL" ]]; then
    "$BUFFER_CTL" start >/dev/null 2>&1
fi

# Check if any arg is "exec" (non-interactive mode)
_is_exec=false
for _arg in "$@"; do
    [[ "$_arg" == "exec" ]] && _is_exec=true && break
done

if [[ "$_is_exec" == true ]]; then
    # Run as subprocess so we can drain the buffer after exit
    "$REAL_CODEX" "$@"
    EXIT_CODE=$?
    # Drain idle conversations from the buffer
    if [[ -f "$DRAIN_CMD" ]]; then
        "$DRAIN_CMD" >/dev/null 2>&1 || true
    fi
    exit $EXIT_CODE
else
    exec "$REAL_CODEX" "$@"
fi
