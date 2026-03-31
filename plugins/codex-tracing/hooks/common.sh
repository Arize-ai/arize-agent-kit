#!/bin/bash
# Common utilities for Arize Codex tracing
# Shared OTLP span building and sending infrastructure

set -euo pipefail

# --- Config ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="${HOME}/.arize-codex"

ARIZE_API_KEY="${ARIZE_API_KEY:-}"
ARIZE_SPACE_ID="${ARIZE_SPACE_ID:-}"
PHOENIX_ENDPOINT="${PHOENIX_ENDPOINT:-}"
PHOENIX_API_KEY="${PHOENIX_API_KEY:-}"
ARIZE_PROJECT_NAME="${ARIZE_PROJECT_NAME:-}"
ARIZE_TRACE_ENABLED="${ARIZE_TRACE_ENABLED:-true}"
ARIZE_DRY_RUN="${ARIZE_DRY_RUN:-false}"
ARIZE_VERBOSE="${ARIZE_VERBOSE:-false}"
ARIZE_TRACE_DEBUG="${ARIZE_TRACE_DEBUG:-false}"
ARIZE_LOG_FILE="${ARIZE_LOG_FILE:-/tmp/arize-codex.log}"

# --- Logging ---
_log_to_file() { [[ -n "$ARIZE_LOG_FILE" ]] && echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$ARIZE_LOG_FILE" || true; }
log() { [[ "$ARIZE_VERBOSE" == "true" ]] && { echo "[arize] $*" >&2; _log_to_file "$*"; } || true; }
log_always() { echo "[arize] $*" >&2; _log_to_file "$*"; }
error() { echo "[arize] ERROR: $*" >&2; _log_to_file "ERROR: $*"; }

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
# Codex provides thread-id as session key, so state files are keyed by thread-id.
STATE_FILE=""  # Set by resolve_session()

init_state() {
  mkdir -p "$STATE_DIR"
  if [[ -n "$STATE_FILE" ]]; then
    if [[ ! -f "$STATE_FILE" ]]; then
      echo '{}' > "$STATE_FILE"
    else
      jq empty "$STATE_FILE" 2>/dev/null || echo '{}' > "$STATE_FILE"
    fi
  fi
}

_LOCK_DIR=""

_lock_state() {
  [[ -z "$_LOCK_DIR" ]] && return 0
  local attempts=0
  while ! mkdir "$_LOCK_DIR" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [[ $attempts -gt 30 ]]; then
      rm -rf "$_LOCK_DIR"
      mkdir "$_LOCK_DIR" 2>/dev/null || true
      return 0
    fi
    sleep 0.1
  done
}

_unlock_state() {
  [[ -n "$_LOCK_DIR" ]] && rmdir "$_LOCK_DIR" 2>/dev/null || true
}

get_state() {
  [[ -z "$STATE_FILE" || ! -f "$STATE_FILE" ]] && { echo ""; return 0; }
  jq -r ".[\"$1\"] // empty" "$STATE_FILE" 2>/dev/null || echo ""
}

set_state() {
  [[ -z "$STATE_FILE" ]] && return 0
  _lock_state
  local tmp="${STATE_FILE}.tmp.$$"
  jq --arg k "$1" --arg v "$2" '. + {($k): $v}' "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

del_state() {
  [[ -z "$STATE_FILE" ]] && return 0
  _lock_state
  local tmp="${STATE_FILE}.tmp.$$"
  jq "del(.[\"$1\"])" "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

inc_state() {
  [[ -z "$STATE_FILE" ]] && return 0
  _lock_state
  local val
  val=$(jq -r ".[\"$1\"] // \"0\"" "$STATE_FILE" 2>/dev/null)
  local tmp="${STATE_FILE}.tmp.$$"
  jq --arg k "$1" --arg v "$((${val:-0} + 1))" '. + {($k): $v}' "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

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

  log "Session initialized: $session_id"
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
  local project="${ARIZE_PROJECT_NAME:-codex}"

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
      attributes: (reduce .attributes[] as $a ({}; . + {($a.key): ($a.value.stringValue // $a.value.doubleValue // $a.value.intValue // $a.value.boolValue // "")}))
    }]
  }')

  local curl_cmd=(curl -sf -X POST "${PHOENIX_ENDPOINT}/v1/projects/${project}/spans" -H "Content-Type: application/json")
  [[ -n "$PHOENIX_API_KEY" ]] && curl_cmd+=(-H "Authorization: Bearer ${PHOENIX_API_KEY}")
  curl_cmd+=(-d "$payload")

  "${curl_cmd[@]}" >/dev/null
}

# --- Send to Arize AX (requires Python) ---
send_to_arize() {
  local span_json="$1"
  local script="${PLUGIN_DIR}/scripts/send_span.py"

  # Find python with opentelemetry (cached per session)
  local py=""
  local cached_py
  cached_py=$(get_state "python_path")
  if [[ -n "$cached_py" ]] && "$cached_py" -c "import opentelemetry" 2>/dev/null; then
    py="$cached_py"
  else
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

  local kind_value="1"
  local kind_upper
  kind_upper=$(printf '%s' "${kind:-}" | tr '[:lower:]' '[:upper:]')
  case "$kind_upper" in
    ""|"LLM"|"CHAIN"|"TOOL"|"INTERNAL"|"SPAN_KIND_INTERNAL") kind_value="1" ;;
    "SERVER"|"SPAN_KIND_SERVER") kind_value="2" ;;
    "CLIENT"|"SPAN_KIND_CLIENT") kind_value="3" ;;
    "PRODUCER"|"SPAN_KIND_PRODUCER") kind_value="4" ;;
    "CONSUMER"|"SPAN_KIND_CONSUMER") kind_value="5" ;;
    "UNSPECIFIED"|"SPAN_KIND_UNSPECIFIED") kind_value="0" ;;
    *)
      if [[ "$kind" =~ ^[0-9]+$ ]]; then
        kind_value="$kind"
      fi
      ;;
  esac

  cat <<EOF
{"resourceSpans":[{"resource":{"attributes":[
  {"key":"service.name","value":{"stringValue":"codex"}}
]},"scopeSpans":[{"scope":{"name":"arize-codex-plugin"},"spans":[{
  "traceId":"$trace_id","spanId":"$span_id",$parent_json
  "name":"$name","kind":$kind_value,
  "startTimeUnixNano":"${start}000000","endTimeUnixNano":"${end}000000",
  "attributes":$(echo "$attrs" | jq -c '[to_entries[]|{"key":.key,"value":(if (.value|type)=="number" then (if ((.value|floor) == .value) then {"intValue":.value} else {"doubleValue":.value} end) elif (.value|type)=="boolean" then {"boolValue":.value} else {"stringValue":(.value|tostring)} end)}]'),
  "status":{"code":1}
}]}]}]}
EOF
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

  jq -nc --argjson spans "$spans_array" '{
    "resourceSpans": [{
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "codex"}}
        ]
      },
      "scopeSpans": [{
        "scope": {"name": "arize-codex-plugin"},
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
