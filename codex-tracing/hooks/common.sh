#!/bin/bash
# Codex adapter — harness-specific session resolution, state, GC, and multi-span building
#
# This file sets Codex-specific variables then sources core/common.sh for shared infra.
# Codex uses thread-id based state (provided in the notify payload).

set -euo pipefail

# --- Harness-specific variables (set BEFORE sourcing core) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="${HOME}/.arize/harness/state/codex"
ARIZE_SERVICE_NAME="codex"
ARIZE_SCOPE_NAME="arize-codex-plugin"
ARIZE_LOG_FILE="${ARIZE_LOG_FILE:-/tmp/arize-codex.log}"

# --- Source shared core ---
source "$(cd "$SCRIPT_DIR/../.." && pwd)/core/common.sh"

# --- Debug dump (Codex-specific) ---
debug_dump() {
  [[ "$ARIZE_TRACE_DEBUG" == "true" ]] || return 0
  local label="$1" data="$2"
  local safe_label
  safe_label=$(echo "$label" | tr -c '[:alnum:]_.-' '_')
  local ts
  ts=$(date +%s%3N 2>/dev/null || date +%s000)
  local dir="${STATE_DIR}/debug"
  mkdir -p "$dir"
  local file="${dir}/${safe_label}_${ts}.log"
  printf '%s\n' "$data" > "$file"
  _log_to_file "DEBUG wrote $safe_label to $file"
}

# --- State file declarations ---
STATE_FILE=""  # Set by resolve_session()
_LOCK_DIR=""

# --- Session Resolution ---
# Codex provides thread-id in the notify payload, used as session key.
resolve_session() {
  local thread_id="${1:-}"
  if [[ -z "$thread_id" ]]; then
    # Fallback: use a random session key
    thread_id=$(generate_uuid)
  fi

  STATE_FILE="${STATE_DIR}/state_${thread_id}.json"
  _LOCK_DIR="${STATE_DIR}/.lock_${thread_id}"
  init_state
}

ensure_session_initialized() {
  local thread_id="${1:-}"
  local cwd="${2:-$(pwd)}"

  local existing_sid
  existing_sid=$(get_state "session_id")
  if [[ -n "$existing_sid" ]]; then
    return 0
  fi

  local session_id="$thread_id"
  [[ -z "$session_id" ]] && session_id=$(generate_uuid)

  local project_name="${ARIZE_PROJECT_NAME:-}"
  [[ -z "$project_name" ]] && project_name=$(basename "$cwd")

  set_state "session_id" "$session_id"
  set_state "session_start_time" "$(get_timestamp_ms)"
  set_state "project_name" "$project_name"
  set_state "trace_count" "0"

  # Store user ID from env var if set
  local user_id="${ARIZE_USER_ID:-}"
  if [[ -n "$user_id" ]]; then
    set_state "user_id" "$user_id"
  fi

  log "Session initialized: $session_id"
}

# --- Garbage collect stale state files ---
gc_stale_state_files() {
  local now_s
  now_s=$(date +%s)
  for f in "${STATE_DIR}"/state_*.json; do
    [[ -f "$f" ]] || continue
    # Remove state files older than 24 hours
    local file_age_s
    if stat -f %m "$f" &>/dev/null; then
      file_age_s=$(( now_s - $(stat -f %m "$f") ))
    elif stat -c %Y "$f" &>/dev/null; then
      file_age_s=$(( now_s - $(stat -c %Y "$f") ))
    else
      continue
    fi
    if [[ $file_age_s -gt 86400 ]]; then
      local file_key
      file_key=$(basename "$f" | sed 's/state_//;s/\.json//')
      rm -f "$f"
      rm -rf "${STATE_DIR}/.lock_${file_key}"
    fi
  done
}

# --- Build multi-span OTLP payload ---
# Takes an array of individual span JSON objects (each from build_span()) and
# merges them into a single resourceSpans payload for batch sending.
build_multi_span() {
  # Usage: build_multi_span span1_json span2_json ...
  # Each argument is a complete OTLP JSON from build_span().
  # Returns a single resourceSpans payload with all spans under one scope.
  local spans_array="[]"
  for span_json in "$@"; do
    # Extract the span object from each build_span() output
    local extracted
    extracted=$(echo "$span_json" | jq -c '.resourceSpans[0].scopeSpans[0].spans[0]' 2>/dev/null) || continue
    [[ -z "$extracted" || "$extracted" == "null" ]] && continue
    spans_array=$(echo "$spans_array" | jq --argjson s "$extracted" '. + [$s]')
  done

  local span_count
  span_count=$(echo "$spans_array" | jq 'length')
  if [[ "$span_count" -eq 0 ]]; then
    echo "{}"
    return 1
  fi

  jq -nc --argjson spans "$spans_array" \
    --arg svc "${ARIZE_SERVICE_NAME}" \
    --arg scope "${ARIZE_SCOPE_NAME}" '{
    "resourceSpans": [{
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": $svc}}
        ]
      },
      "scopeSpans": [{
        "scope": {"name": $scope},
        "spans": $spans
      }]
    }]
  }'
}

# --- Requirements check ---
check_requirements() {
  [[ "$ARIZE_TRACE_ENABLED" != "true" ]] && exit 0
  command -v jq &>/dev/null || { error "jq required. Install: brew install jq"; exit 1; }
  mkdir -p "$STATE_DIR"
}
