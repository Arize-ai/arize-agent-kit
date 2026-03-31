#!/bin/bash
# ARIZE_CODEX_PROXY
# Wrapper installed to ~/.local/bin/codex by install.sh.
# Ensures the local collector is running before execing the real Codex binary.

set -euo pipefail

REAL_CODEX="__REAL_CODEX__"
ARIZE_ENV_FILE="__ARIZE_ENV_FILE__"
COLLECTOR_CTL="__COLLECTOR_CTL__"

if [[ -f "$ARIZE_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ARIZE_ENV_FILE" >/dev/null 2>&1 || true
fi

if [[ -f "$COLLECTOR_CTL" ]]; then
  # shellcheck disable=SC1090
  source "$COLLECTOR_CTL" >/dev/null 2>&1 || true
  if declare -f collector_ensure >/dev/null 2>&1; then
    collector_ensure >/dev/null 2>&1 || true
  fi
fi

if [[ ! -x "$REAL_CODEX" ]]; then
  echo "[arize] REAL_CODEX not executable: $REAL_CODEX" >&2
  exit 1
fi

exec "$REAL_CODEX" "$@"
