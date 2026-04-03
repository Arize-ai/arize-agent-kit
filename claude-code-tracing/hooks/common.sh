#!/bin/bash
# Claude Code adapter for Arize tracing
# Sets harness-specific variables and sources shared core, then defines
# Claude-specific session resolution, initialization, and GC.

set -euo pipefail

# --- Harness-specific config (set BEFORE sourcing core) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="${HOME}/.arize/harness/state/claude-code"
ARIZE_SERVICE_NAME="claude-code"
ARIZE_SCOPE_NAME="arize-claude-plugin"
ARIZE_LOG_FILE="${ARIZE_LOG_FILE:-/tmp/arize-claude-code.log}"

# Derive Claude Code's PID (grandparent) for per-session state isolation
_CLAUDE_PID=$(ps -o ppid= -p "$PPID" 2>/dev/null | tr -d ' ') || true
STATE_FILE="${STATE_DIR}/state_${_CLAUDE_PID:-$$}.json"
_LOCK_DIR="${STATE_DIR}/.lock_${_CLAUDE_PID:-$$}"

# --- Source shared core ---
source "$(cd "$SCRIPT_DIR/../.." && pwd)/core/common.sh"

# --- Session Resolution (Claude-specific) ---

# Resolve session state file using session_id from hook input JSON.
# Call after reading stdin in each hook. Falls back to PID-based key if no session_id.
resolve_session() {
  local input="${1:-'{}'}"
  local sid
  sid=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null || echo "")

  if [[ -n "$sid" ]]; then
    _SESSION_KEY="$sid"
  elif [[ -n "${CLAUDE_SESSION_KEY:-}" ]]; then
    _SESSION_KEY="$CLAUDE_SESSION_KEY"
  else
    # Fall back to current PID-based derivation (already set at source time)
    return 0
  fi

  STATE_FILE="${STATE_DIR}/state_${_SESSION_KEY}.json"
  _LOCK_DIR="${STATE_DIR}/.lock_${_SESSION_KEY}"
  init_state
}

# Idempotent session initialization. If session_id is already in state, returns immediately.
# Used by SessionStart directly and as lazy init fallback in UserPromptSubmit
# (for environments like the Python Agent SDK where SessionStart doesn't fire).
ensure_session_initialized() {
  local input="${1:-'{}'}"

  # Skip if session already initialized
  local existing_sid
  existing_sid=$(get_state "session_id")
  if [[ -n "$existing_sid" ]]; then
    return 0
  fi

  local session_id
  session_id=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null || echo "")
  [[ -z "$session_id" ]] && session_id=$(generate_uuid)

  local project_name="${ARIZE_PROJECT_NAME:-}"
  if [[ -z "$project_name" ]]; then
    local cwd
    cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null || echo "")
    project_name=$(basename "${cwd:-$(pwd)}")
  fi

  set_state "session_id" "$session_id"
  set_state "session_start_time" "$(get_timestamp_ms)"
  set_state "project_name" "$project_name"
  set_state "trace_count" "0"
  set_state "tool_count" "0"

  # user_id priority: env var / config.yaml (already resolved in core/common.sh), then hook input JSON
  local user_id="${ARIZE_USER_ID:-}"
  if [[ -z "$user_id" ]]; then
    user_id=$(echo "$input" | jq -r '.user_id // empty' 2>/dev/null || echo "")
  fi
  set_state "user_id" "$user_id"

  log "Session initialized: $session_id"
}

# Garbage-collect orphaned state files for PIDs no longer running.
# Only cleans numeric (PID-based) keys; session_id-based files are cleaned by SessionEnd.
gc_stale_state_files() {
  for f in "${STATE_DIR}"/state_*.json; do
    [[ -f "$f" ]] || continue
    local file_key
    file_key=$(basename "$f" | sed 's/state_//;s/\.json//')
    # Only GC numeric (PID-based) keys; skip non-numeric session keys
    if [[ "$file_key" =~ ^[0-9]+$ ]] && ! kill -0 "$file_key" 2>/dev/null; then
      rm -f "$f"
      rm -rf "${STATE_DIR}/.lock_${file_key}"
    fi
  done
}

# --- Init ---
check_requirements() {
  [[ "$ARIZE_TRACE_ENABLED" != "true" ]] && exit 0
  command -v jq &>/dev/null || { error "jq required. Install: brew install jq"; exit 1; }
  init_state
}
