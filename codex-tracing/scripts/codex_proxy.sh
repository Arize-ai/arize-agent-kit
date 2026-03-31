#!/bin/bash
# ARIZE_CODEX_PROXY
# Wrapper installed to ~/.local/bin/codex by install.sh.
# Ensures the shared collector and Codex event buffer are running before
# execing the real Codex binary.

set -euo pipefail

REAL_CODEX="__REAL_CODEX__"
ARIZE_ENV_FILE="__ARIZE_ENV_FILE__"
SHARED_COLLECTOR_CTL="__SHARED_COLLECTOR_CTL__"
EVENT_BUFFER_CTL="__EVENT_BUFFER_CTL__"

if [[ -f "$ARIZE_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ARIZE_ENV_FILE" >/dev/null 2>&1 || true
fi

# Start the shared span exporter (core/collector_ctl.sh)
if [[ -f "$SHARED_COLLECTOR_CTL" ]]; then
  # shellcheck disable=SC1090
  source "$SHARED_COLLECTOR_CTL" >/dev/null 2>&1 || true
  if declare -f collector_ensure >/dev/null 2>&1; then
    collector_ensure >/dev/null 2>&1 || true
  fi
fi

# Start the Codex event buffer (codex-tracing/scripts/collector_ctl.sh)
if [[ -f "$EVENT_BUFFER_CTL" ]]; then
  # shellcheck disable=SC1090
  source "$EVENT_BUFFER_CTL" >/dev/null 2>&1 || true
  if declare -f event_buffer_ensure >/dev/null 2>&1; then
    event_buffer_ensure >/dev/null 2>&1 || true
  fi
fi

if [[ ! -x "$REAL_CODEX" ]]; then
  echo "[arize] REAL_CODEX not executable: $REAL_CODEX" >&2
  exit 1
fi

exec "$REAL_CODEX" "$@"
