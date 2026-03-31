#!/bin/bash
# Common utilities for Arize Claude Code tracing hooks

set -euo pipefail

# --- Config ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="${HOME}/.arize-claude-code"

# Derive Claude Code's PID (grandparent) for per-session state isolation
_CLAUDE_PID=$(ps -o ppid= -p "$PPID" 2>/dev/null | tr -d ' ') || true
STATE_FILE="${STATE_DIR}/state_${_CLAUDE_PID:-$$}.json"

ARIZE_API_KEY="${ARIZE_API_KEY:-}"
ARIZE_SPACE_ID="${ARIZE_SPACE_ID:-}"
PHOENIX_ENDPOINT="${PHOENIX_ENDPOINT:-}"
PHOENIX_API_KEY="${PHOENIX_API_KEY:-}"
ARIZE_PROJECT_NAME="${ARIZE_PROJECT_NAME:-}"
ARIZE_TRACE_ENABLED="${ARIZE_TRACE_ENABLED:-true}"
ARIZE_DRY_RUN="${ARIZE_DRY_RUN:-false}"
ARIZE_VERBOSE="${ARIZE_VERBOSE:-false}"
ARIZE_LOG_FILE="${ARIZE_LOG_FILE:-/tmp/arize-claude-code.log}"

# --- Logging ---
_log_to_file() { [[ -n "$ARIZE_LOG_FILE" ]] && echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$ARIZE_LOG_FILE" || true; }
log() { [[ "$ARIZE_VERBOSE" == "true" ]] && { echo "[arize] $*" >&2; _log_to_file "$*"; } || true; }
log_always() { echo "[arize] $*" >&2; _log_to_file "$*"; }
error() { echo "[arize] ERROR: $*" >&2; }

# --- Utilities ---
generate_uuid() {
  uuidgen 2>/dev/null | tr '[:upper:]' '[:lower:]' || \
    cat /proc/sys/kernel/random/uuid 2>/dev/null || \
    od -x /dev/urandom | head -1 | awk '{print $2$3"-"$4"-4"substr($5,2)"-a"substr($6,2)"-"$7$8$9}'
}

get_timestamp_ms() {
  python3 -c "import time; print(int(time.time() * 1000))" 2>/dev/null || \
    date +%s%3N 2>/dev/null || date +%s000
}

# --- State (per-session JSON file with mkdir-based locking) ---
init_state() {
  mkdir -p "$STATE_DIR"
  if [[ ! -f "$STATE_FILE" ]]; then
    echo '{}' > "$STATE_FILE"
  else
    jq empty "$STATE_FILE" 2>/dev/null || echo '{}' > "$STATE_FILE"
  fi
}

_LOCK_DIR="${STATE_DIR}/.lock_${_CLAUDE_PID:-$$}"

_lock_state() {
  local attempts=0
  while ! mkdir "$_LOCK_DIR" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [[ $attempts -gt 30 ]]; then
      # Stale lock recovery after ~3s
      rm -rf "$_LOCK_DIR"
      mkdir "$_LOCK_DIR" 2>/dev/null || true
      return 0
    fi
    sleep 0.1
  done
}

_unlock_state() {
  rmdir "$_LOCK_DIR" 2>/dev/null || true
}

get_state() {
  jq -r ".[\"$1\"] // empty" "$STATE_FILE" 2>/dev/null || echo ""
}

set_state() {
  _lock_state
  local tmp="${STATE_FILE}.tmp.$$"
  jq --arg k "$1" --arg v "$2" '. + {($k): $v}' "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

del_state() {
  _lock_state
  local tmp="${STATE_FILE}.tmp.$$"
  jq "del(.[\"$1\"])" "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

inc_state() {
  _lock_state
  local val
  val=$(jq -r ".[\"$1\"] // \"0\"" "$STATE_FILE" 2>/dev/null)
  local tmp="${STATE_FILE}.tmp.$$"
  jq --arg k "$1" --arg v "$((${val:-0} + 1))" '. + {($k): $v}' "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

# --- Target Detection ---
get_target() {
  if [[ -n "$PHOENIX_ENDPOINT" ]]; then echo "phoenix"
  elif [[ -n "$ARIZE_API_KEY" && -n "$ARIZE_SPACE_ID" ]]; then echo "arize"
  else echo "none"
  fi
}

# --- Send to Phoenix (REST API) ---
send_to_phoenix() {
  local span_json="$1"
  local project="${ARIZE_PROJECT_NAME:-claude-code}"

  local payload
  payload=$(echo "$span_json" | jq '{
    data: [.resourceSpans[].scopeSpans[].spans[] | {
      name: .name,
      context: { trace_id: .traceId, span_id: .spanId },
      parent_id: .parentSpanId,
      span_kind: "CHAIN",
      start_time: ((.startTimeUnixNano | tonumber) / 1e9 | strftime("%Y-%m-%dT%H:%M:%SZ")),
      end_time: ((.endTimeUnixNano | tonumber) / 1e9 | strftime("%Y-%m-%dT%H:%M:%SZ")),
      status_code: "OK",
      attributes: (reduce .attributes[] as $a ({}; . + {($a.key): ($a.value.stringValue // $a.value.intValue // "")}))
    }]
  }')

  # Build curl command with optional Authorization header
  local curl_cmd=(curl -sf -X POST "${PHOENIX_ENDPOINT}/v1/projects/${project}/spans" -H "Content-Type: application/json")
  [[ -n "$PHOENIX_API_KEY" ]] && curl_cmd+=(-H "Authorization: Bearer ${PHOENIX_API_KEY}")
  curl_cmd+=(-d "$payload")

  "${curl_cmd[@]}" >/dev/null
}

# --- Send to Arize AX (requires Python) ---
send_to_arize() {
  local span_json="$1"
  local script="${PLUGIN_DIR}/scripts/send_span.py"

  # Find python with opentelemetry (cached per session to avoid slow conda/pipx lookups)
  local py=""
  local cached_py
  cached_py=$(get_state "python_path")
  if [[ -n "$cached_py" ]] && "$cached_py" -c "import opentelemetry" 2>/dev/null; then
    py="$cached_py"
  else
    # Build candidate list: common paths + conda + pipx venvs
    local candidates=(python3 /usr/bin/python3 /usr/local/bin/python3 "$HOME/.local/bin/python3")
    local conda_base
    conda_base=$(conda info --base 2>/dev/null) && [[ -n "$conda_base" ]] && candidates+=("${conda_base}/bin/python3")
    local pipx_dir="${HOME}/.local/pipx/venvs"
    [[ -d "$pipx_dir" ]] || pipx_dir="${HOME}/.local/share/pipx/venvs"
    if [[ -d "$pipx_dir" ]]; then
      for venv in "$pipx_dir"/*/bin/python3; do
        [[ -x "$venv" ]] && candidates+=("$venv")
      done
    fi
    for p in "${candidates[@]}"; do
      "$p" -c "import opentelemetry" 2>/dev/null && { py="$p"; break; }
    done
    [[ -n "$py" ]] && set_state "python_path" "$py"
  fi

  [[ -z "$py" ]] && { error "Python with opentelemetry not found. Run: pip install opentelemetry-proto grpcio"; return 1; }
  [[ ! -f "$script" ]] && { error "send_span.py not found"; return 1; }

  local stderr_tmp
  stderr_tmp=$(mktemp)
  if echo "$span_json" | "$py" "$script" 2>"$stderr_tmp"; then
    _log_to_file "DEBUG send_to_arize succeeded"
    rm -f "$stderr_tmp"
  else
    _log_to_file "DEBUG send_to_arize FAILED (exit=$?)"
    [[ -s "$stderr_tmp" ]] && { _log_to_file "DEBUG stderr:"; cat "$stderr_tmp" >> "$ARIZE_LOG_FILE"; }
    rm -f "$stderr_tmp"
    return 1
  fi
}

# --- Main send function ---
send_span() {
  local span_json="$1"
  local target=$(get_target)

  if [[ "$ARIZE_DRY_RUN" == "true" ]]; then
    log_always "DRY RUN:"
    echo "$span_json" | jq -c '.resourceSpans[].scopeSpans[].spans[].name' >&2
    return 0
  fi

  [[ "$ARIZE_VERBOSE" == "true" ]] && echo "$span_json" | jq -c . >&2

  case "$target" in
    phoenix) send_to_phoenix "$span_json" ;;
    arize) send_to_arize "$span_json" ;;
    *) error "No target. Set PHOENIX_ENDPOINT or ARIZE_API_KEY + ARIZE_SPACE_ID"; return 1 ;;
  esac

  local span_name
  span_name=$(echo "$span_json" | jq -r '.resourceSpans[0].scopeSpans[0].spans[0].name // "unknown"' 2>/dev/null)
  log "Sent span: $span_name ($target)"
}

# --- Build OTLP span ---
build_span() {
  local name="$1" kind="$2" span_id="$3" trace_id="$4"
  local parent="${5:-}" start="$6" end="${7:-$start}" attrs
  attrs="${8:-"{}"}"

  local parent_json=""
  [[ -n "$parent" ]] && parent_json="\"parentSpanId\": \"$parent\","

  cat <<EOF
{"resourceSpans":[{"resource":{"attributes":[
  {"key":"service.name","value":{"stringValue":"claude-code"}}
]},"scopeSpans":[{"scope":{"name":"arize-claude-plugin"},"spans":[{
  "traceId":"$trace_id","spanId":"$span_id",$parent_json
  "name":"$name","kind":1,
  "startTimeUnixNano":"${start}000000","endTimeUnixNano":"${end}000000",
  "attributes":$(echo "$attrs" | jq -c '[to_entries[]|{"key":.key,"value":(if (.value|type)=="number" then (if ((.value|floor) == .value) then {"intValue":.value} else {"doubleValue":.value} end) else {"stringValue":(.value|tostring)} end)}]'),
  "status":{"code":1}
}]}]}]}
EOF
}

# --- Session Resolution (for Agent SDK compatibility) ---

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
