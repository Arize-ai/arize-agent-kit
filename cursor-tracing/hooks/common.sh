#!/bin/bash
# Cursor adapter for Arize tracing
# Sets harness-specific variables and sources shared core, then defines
# Cursor-specific state management for before/after hook merging.

set -euo pipefail

# --- Harness-specific config (set BEFORE sourcing core) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="${HOME}/.arize-cursor"
ARIZE_SERVICE_NAME="cursor"
ARIZE_SCOPE_NAME="arize-cursor-plugin"
ARIZE_PROJECT_NAME="${ARIZE_PROJECT_NAME:-cursor}"
ARIZE_LOG_FILE="${ARIZE_LOG_FILE:-/tmp/arize-cursor.log}"

# Max attribute size (characters) for input.value / output.value
CURSOR_TRACE_MAX_ATTR_CHARS="${CURSOR_TRACE_MAX_ATTR_CHARS:-100000}"

# Lock dir for state operations
_LOCK_DIR="${STATE_DIR}/.lock"

# --- Source shared core (provides build_span, send_span, log, error, etc.) ---
source "$(cd "$SCRIPT_DIR/../.." && pwd)/core/common.sh"

# --- Ensure state directory exists ---
mkdir -p "$STATE_DIR"

# --- Cursor-specific ID generation ---

# Deterministic 32-hex trace ID from generation_id.
# Maps one Cursor "turn" (generation) to one trace.
trace_id_from_generation() {
  local gen_id="$1"
  if command -v md5sum &>/dev/null; then
    printf '%s' "$gen_id" | md5sum | cut -c1-32
  elif command -v md5 &>/dev/null; then
    printf '%s' "$gen_id" | md5 | cut -c1-32
  elif command -v shasum &>/dev/null; then
    printf '%s' "$gen_id" | shasum -a 256 | cut -c1-32
  else
    # Last resort: use generate_uuid from core
    generate_uuid | tr -d '-'
  fi
}

# Generate 16-hex random span ID from /dev/urandom.
span_id_16() {
  od -An -tx1 -N8 /dev/urandom 2>/dev/null | tr -d ' \n' | cut -c1-16 || \
    generate_uuid | tr -d '-' | cut -c1-16
}

# --- Disk-backed state stack (for before/after hook merging) ---
# Used to merge beforeShellExecution/afterShellExecution and
# beforeMCPExecution/afterMCPExecution into single spans.

# Push a JSON value onto a named stack.
# Stack files live at ${STATE_DIR}/<key>.stack
state_push() {
  local key="$1" value="$2"
  local stack_file="${STATE_DIR}/${key}.stack"
  local lock="${STATE_DIR}/.lock_${key}"

  # mkdir-based lock
  local attempts=0
  while ! mkdir "$lock" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [[ $attempts -gt 30 ]]; then
      rm -rf "$lock"
      mkdir "$lock" 2>/dev/null || true
      break
    fi
    sleep 0.1
  done

  # Initialize stack file if missing
  if [[ ! -f "$stack_file" ]]; then
    echo '[]' > "$stack_file"
  fi

  # Append value to JSON array
  local tmp="${stack_file}.tmp.$$"
  jq --argjson v "$value" '. + [$v]' "$stack_file" > "$tmp" 2>/dev/null && \
    mv "$tmp" "$stack_file" || rm -f "$tmp"

  rmdir "$lock" 2>/dev/null || true
}

# Pop the most recent value from a named stack.
# Outputs the popped JSON value to stdout. Returns 1 if stack is empty.
state_pop() {
  local key="$1"
  local stack_file="${STATE_DIR}/${key}.stack"
  local lock="${STATE_DIR}/.lock_${key}"

  if [[ ! -f "$stack_file" ]]; then
    echo "null"
    return 1
  fi

  # mkdir-based lock
  local attempts=0
  while ! mkdir "$lock" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [[ $attempts -gt 30 ]]; then
      rm -rf "$lock"
      mkdir "$lock" 2>/dev/null || true
      break
    fi
    sleep 0.1
  done

  local count
  count=$(jq 'length' "$stack_file" 2>/dev/null || echo "0")
  if [[ "$count" -le 0 ]]; then
    rmdir "$lock" 2>/dev/null || true
    echo "null"
    return 1
  fi

  # Get last element
  local val
  val=$(jq -c '.[-1]' "$stack_file" 2>/dev/null || echo "null")

  # Remove last element
  local tmp="${stack_file}.tmp.$$"
  jq '.[:-1]' "$stack_file" > "$tmp" 2>/dev/null && \
    mv "$tmp" "$stack_file" || rm -f "$tmp"

  rmdir "$lock" 2>/dev/null || true
  echo "$val"
}

# --- Root span tracking per generation ---
# The root span (from beforeSubmitPrompt) is the parent for all other spans
# in the same generation.

gen_root_span_save() {
  local gen_id="$1" span_id="$2"
  local safe_gen
  safe_gen=$(sanitize "$gen_id")
  echo "$span_id" > "${STATE_DIR}/root_${safe_gen}"
}

gen_root_span_get() {
  local gen_id="$1"
  local safe_gen
  safe_gen=$(sanitize "$gen_id")
  local root_file="${STATE_DIR}/root_${safe_gen}"
  if [[ -f "$root_file" ]]; then
    cat "$root_file"
  else
    echo ""
  fi
}

# --- Generation state cleanup ---
# Remove all state files for a generation (called by stop hook).
state_cleanup_generation() {
  local gen_id="$1"
  local safe_gen
  safe_gen=$(sanitize "$gen_id")

  # Remove root span file
  rm -f "${STATE_DIR}/root_${safe_gen}"

  # Remove any stack files that contain this generation ID
  for f in "${STATE_DIR}/"*"${safe_gen}"*.stack; do
    [[ -f "$f" ]] && rm -f "$f"
  done

  # Remove any lock dirs for this generation
  for d in "${STATE_DIR}/.lock_"*"${safe_gen}"*; do
    [[ -d "$d" ]] && rmdir "$d" 2>/dev/null || true
  done
}

# --- Utility functions ---

# Clean string for use in filenames (replace non-alphanumeric with underscore).
sanitize() {
  printf '%s' "$1" | tr -c '[:alnum:]._-' '_'
}

# Truncate a string to CURSOR_TRACE_MAX_ATTR_CHARS.
truncate_attr() {
  local str="$1"
  local max="${CURSOR_TRACE_MAX_ATTR_CHARS:-100000}"
  if [[ ${#str} -gt $max ]]; then
    printf '%s' "${str:0:$max}"
  else
    printf '%s' "$str"
  fi
}

