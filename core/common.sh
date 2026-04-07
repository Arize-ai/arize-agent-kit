#!/bin/bash
# Core shared utilities for Arize agent tracing
# Shared OTLP span building, sending, state management, and logging infrastructure
#
# Sourced by each harness adapter's common.sh. Adapters must set:
#   - STATE_DIR, STATE_FILE, _LOCK_DIR (state location)
#   - ARIZE_SERVICE_NAME, ARIZE_SCOPE_NAME (span identity)
# Adapters own: resolve_session(), ensure_session_initialized(), gc_stale_state_files()

set -euo pipefail

# --- Core directory ---
CORE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Config (env vars with defaults) ---
ARIZE_API_KEY="${ARIZE_API_KEY:-}"
ARIZE_SPACE_ID="${ARIZE_SPACE_ID:-}"
PHOENIX_ENDPOINT="${PHOENIX_ENDPOINT:-}"
PHOENIX_API_KEY="${PHOENIX_API_KEY:-}"
ARIZE_PROJECT_NAME="${ARIZE_PROJECT_NAME:-}"
ARIZE_USER_ID="${ARIZE_USER_ID:-}"
ARIZE_TRACE_ENABLED="${ARIZE_TRACE_ENABLED:-true}"
ARIZE_DRY_RUN="${ARIZE_DRY_RUN:-false}"
ARIZE_VERBOSE="${ARIZE_VERBOSE:-false}"
ARIZE_TRACE_DEBUG="${ARIZE_TRACE_DEBUG:-false}"
ARIZE_LOG_FILE="${ARIZE_LOG_FILE:-/tmp/arize-agent-kit.log}"

# --- Logging ---
_log_to_file() { [[ -n "$ARIZE_LOG_FILE" ]] && echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$ARIZE_LOG_FILE" || true; }
log() { [[ "$ARIZE_VERBOSE" == "true" ]] && { echo "[arize] $*" >&2; _log_to_file "$*"; } || true; }
log_always() { echo "[arize] $*" >&2; _log_to_file "$*"; }
error() { echo "[arize] ERROR: $*" >&2; _log_to_file "ERROR: $*"; }

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
# STATE_FILE and _LOCK_DIR must be set by the adapter before calling these.

init_state() {
  if [[ -n "${STATE_DIR:-}" ]]; then
    mkdir -p "$STATE_DIR"
  fi
  if [[ -n "${STATE_FILE:-}" ]]; then
    if [[ ! -f "$STATE_FILE" ]]; then
      echo '{}' > "$STATE_FILE"
    else
      jq empty "$STATE_FILE" 2>/dev/null || echo '{}' > "$STATE_FILE"
    fi
  fi
}

_lock_state() {
  [[ -z "${_LOCK_DIR:-}" ]] && return 0
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
  [[ -n "${_LOCK_DIR:-}" ]] && rmdir "$_LOCK_DIR" 2>/dev/null || true
}

get_state() {
  [[ -z "${STATE_FILE:-}" || ! -f "${STATE_FILE:-}" ]] && { echo ""; return 0; }
  jq -r ".[\"$1\"] // empty" "$STATE_FILE" 2>/dev/null || echo ""
}

set_state() {
  [[ -z "${STATE_FILE:-}" ]] && return 0
  _lock_state
  local tmp="${STATE_FILE}.tmp.$$"
  jq --arg k "$1" --arg v "$2" '. + {($k): $v}' "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

del_state() {
  [[ -z "${STATE_FILE:-}" ]] && return 0
  _lock_state
  local tmp="${STATE_FILE}.tmp.$$"
  jq "del(.[\"$1\"])" "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

inc_state() {
  [[ -z "${STATE_FILE:-}" ]] && return 0
  _lock_state
  local val
  val=$(jq -r ".[\"$1\"] // \"0\"" "$STATE_FILE" 2>/dev/null)
  local tmp="${STATE_FILE}.tmp.$$"
  jq --arg k "$1" --arg v "$((${val:-0} + 1))" '. + {($k): $v}' "$STATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" || rm -f "$tmp"
  _unlock_state
}

# --- Shared collector endpoint ---
_ARIZE_SHARED_CONFIG="${HOME}/.arize/harness/config.yaml"

# Helper: read a dotted key from config.yaml via core/config.py
_cfg_get() {
  local _cfg_py="${HOME}/.arize/harness/venv/bin/python3"
  [[ -x "$_cfg_py" ]] || _cfg_py="python3"
  "$_cfg_py" "${CORE_DIR}/config.py" get "$1" 2>/dev/null
}

ARIZE_COLLECTOR_HOST="${ARIZE_COLLECTOR_HOST:-127.0.0.1}"
if [[ -z "${ARIZE_COLLECTOR_PORT:-}" && -f "$_ARIZE_SHARED_CONFIG" ]]; then
  _cfg_collector_port=$(_cfg_get "collector.port") || true
  if [[ -n "${_cfg_collector_port:-}" ]]; then
    ARIZE_COLLECTOR_PORT="$_cfg_collector_port"
  fi
fi
ARIZE_COLLECTOR_PORT="${ARIZE_COLLECTOR_PORT:-4318}"
_COLLECTOR_URL="http://${ARIZE_COLLECTOR_HOST}:${ARIZE_COLLECTOR_PORT}"

# Read user_id from config.yaml if not set via env var
if [[ -z "${ARIZE_USER_ID:-}" && -f "$_ARIZE_SHARED_CONFIG" ]]; then
  _cfg_user_id=$(_cfg_get "user_id") || true
  if [[ -n "${_cfg_user_id:-}" ]]; then
    ARIZE_USER_ID="$_cfg_user_id"
  fi
fi

# --- Target Detection ---
get_target() {
  if [[ -n "$PHOENIX_ENDPOINT" ]]; then echo "phoenix"
  elif [[ -n "$ARIZE_API_KEY" && -n "$ARIZE_SPACE_ID" ]]; then echo "arize"
  else echo "none"
  fi
}

# --- Send to shared collector ---
send_to_collector() {
  local span_json="$1"

  curl -sf -X POST "${_COLLECTOR_URL}/v1/spans" \
    -H "Content-Type: application/json" \
    -d "$span_json" \
    --max-time 5 \
    >/dev/null
}

# --- Legacy direct send to Phoenix (REST API) ---
# Kept as fallback when ARIZE_DIRECT_SEND=true and collector is unavailable
send_to_phoenix() {
  local span_json="$1"
  local project="${ARIZE_PROJECT_NAME:-default}"

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

# --- Legacy direct send to Arize AX (requires Python) ---
# Kept as fallback when ARIZE_DIRECT_SEND=true and collector is unavailable
send_to_arize() {
  local span_json="$1"
  local script="${CORE_DIR}/send_arize.py"

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
  [[ ! -f "$script" ]] && { error "send_arize.py not found at $script"; return 1; }

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

  if [[ "$ARIZE_DRY_RUN" == "true" ]]; then
    log_always "DRY RUN:"
    echo "$span_json" | jq -c '.resourceSpans[].scopeSpans[].spans[].name' >&2
    return 0
  fi

  [[ "$ARIZE_VERBOSE" == "true" ]] && echo "$span_json" | jq -c . >&2

  # Try the shared collector first (preferred — handles all backend transport)
  if [[ "${ARIZE_DIRECT_SEND:-}" != "true" ]]; then
    local collector_err
    collector_err=$(mktemp)
    if send_to_collector "$span_json" 2>"$collector_err"; then
      rm -f "$collector_err"
      local span_name
      span_name=$(echo "$span_json" | jq -r '.resourceSpans[0].scopeSpans[0].spans[0].name // "unknown"' 2>/dev/null)
      log "Sent span: $span_name (collector)"
      return 0
    fi
    if [[ -s "$collector_err" ]]; then
      _log_to_file "Collector send failed for ${_COLLECTOR_URL}/v1/spans:"
      cat "$collector_err" >> "$ARIZE_LOG_FILE"
    else
      _log_to_file "Collector send failed for ${_COLLECTOR_URL}/v1/spans with no stderr output"
    fi
    rm -f "$collector_err"
    log "Collector not reachable, falling back to direct send"
  fi

  # Direct send — used when collector isn't running (e.g. marketplace install)
  # or when ARIZE_DIRECT_SEND=true is set explicitly
  local target
  target=$(get_target)
  case "$target" in
    phoenix) send_to_phoenix "$span_json" ;;
    arize) send_to_arize "$span_json" ;;
    *) error "No target configured. Set PHOENIX_ENDPOINT or ARIZE_API_KEY + ARIZE_SPACE_ID, or start the collector."; return 1 ;;
  esac
  local span_name
  span_name=$(echo "$span_json" | jq -r '.resourceSpans[0].scopeSpans[0].spans[0].name // "unknown"' 2>/dev/null)
  log "Sent span: $span_name ($target, direct)"
}

# --- Build OTLP span ---
build_span() {
  local name="$1" kind="$2" span_id="$3" trace_id="$4"
  local parent="${5:-}" start="$6" end="${7:-$start}" attrs
  attrs="${8:-"{}"}"

  local service_name="${ARIZE_SERVICE_NAME:-arize-agent-kit}"
  local scope_name="${ARIZE_SCOPE_NAME:-arize-agent-kit}"

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
  {"key":"service.name","value":{"stringValue":"${service_name}"}}
]},"scopeSpans":[{"scope":{"name":"${scope_name}"},"spans":[{
  "traceId":"$trace_id","spanId":"$span_id",$parent_json
  "name":"$name","kind":$kind_value,
  "startTimeUnixNano":"${start}000000","endTimeUnixNano":"${end}000000",
  "attributes":$(echo "$attrs" | jq -c '[to_entries[]|{"key":.key,"value":(if (.value|type)=="number" then (if ((.value|floor) == .value) then {"intValue":.value} else {"doubleValue":.value} end) elif (.value|type)=="boolean" then {"boolValue":.value} else {"stringValue":(.value|tostring)} end)}]'),
  "status":{"code":1}
}]}]}]}
EOF
}
