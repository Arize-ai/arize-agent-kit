#!/bin/bash
# Codex notify handler — creates OpenInference LLM spans from agent-turn-complete events.
#
# Codex calls: notify = ["bash", "/path/to/notify.sh"]
# The notify payload is passed as a single JSON command-line argument:
#   { "type": "agent-turn-complete", "thread-id": "...", "turn-id": "...",
#     "cwd": "...", "input-messages": [...], "last-assistant-message": "..." }

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# Source env file if it exists (so env vars don't need to be in shell profile)
CODEX_ENV="${HOME}/.codex/arize-env.sh"
[[ -f "$CODEX_ENV" ]] && source "$CODEX_ENV"

source "${HOOK_DIR}/common.sh"

check_requirements

# --- Parse notify payload (passed as $1, not stdin) ---
input="${1:-'{}'}"

# Only handle agent-turn-complete events
event_type=$(echo "$input" | jq -r '.type // empty' 2>/dev/null || echo "")
if [[ "$event_type" != "agent-turn-complete" ]]; then
  log "Ignoring event type: $event_type"
  exit 0
fi

thread_id=$(echo "$input" | jq -r '.["thread-id"] // .["thread_id"] // .["threadId"] // empty' 2>/dev/null || echo "")
turn_id=$(echo "$input" | jq -r '.["turn-id"] // .["turn_id"] // .["turnId"] // empty' 2>/dev/null || echo "")
cwd=$(echo "$input" | jq -r '.cwd // .["working-directory"] // .["working_directory"] // empty' 2>/dev/null || echo "")
user_input=$(echo "$input" | jq -r '.["input-messages"] // .["input_messages"] // .["inputMessages"] // empty' 2>/dev/null || echo "")
assistant_message_json=$(echo "$input" | jq -c '.["last-assistant-message"] // .["last_assistant_message"] // .["lastAssistantMessage"] // ""' 2>/dev/null || echo '""')
debug_prefix="notify_${thread_id:-unknown}_${turn_id:-unknown}"
debug_dump "${debug_prefix}_raw" "$input"
assistant_output=$(printf '%s' "$assistant_message_json" | jq -r '
  def as_text($node):
    if $node == null then ""
    elif ($node | type) == "string" then $node
    elif ($node | type) == "array" then
      ($node | map(as_text(.)) | join("\n"))
    elif ($node | type) == "object" then
      ($node.text // as_text($node.content) // as_text($node.message) // as_text($node.data) // as_text($node.value) // tostring)
    else tostring end;
  as_text(.)
' 2>/dev/null || echo "")

# --- Resolve session ---
resolve_session "$thread_id"
ensure_session_initialized "$thread_id" "${cwd:-$(pwd)}"

session_id=$(get_state "session_id")
inc_state "trace_count"
trace_count=$(get_state "trace_count")
project_name=$(get_state "project_name")
user_id=$(get_state "user_id")

# --- Build user prompt from input-messages ---
# input-messages can be the full thread history as an array of strings/message
# objects, or a plain string. Keep only the latest user message for input.value.
user_prompt=""
if echo "$user_input" | jq -e 'type == "array"' &>/dev/null; then
  user_prompt=$(echo "$user_input" | jq -r '
    def as_text:
      if . == null then ""
      elif type == "string" then .
      elif type == "array" then map(. | as_text) | join("\n")
      elif type == "object" then (.text // .content // .message // .value // "" | as_text)
      else tostring end;
    (
      [.[] | select(type == "object" and (.role // "") == "user") | .content | as_text]
      | map(select(length > 0))
      | last
    ) // (
      [.[] | select(type == "string")]
      | map(select(length > 0))
      | last
    ) // ""
  ' 2>/dev/null || echo "$user_input")
elif echo "$user_input" | jq -e 'type == "string"' &>/dev/null; then
  user_prompt=$(echo "$user_input" | jq -r '.' 2>/dev/null || echo "$user_input")
else
  user_prompt="$user_input"
fi

# Truncate to reasonable sizes
user_prompt=$(printf '%s' "$user_prompt" | head -c 5000)
assistant_output=$(printf '%s' "$assistant_output" | head -c 5000)
[[ -z "$assistant_output" ]] && assistant_output="(No response)"
debug_dump "${debug_prefix}_text" "$(jq -nc --arg user "$user_prompt" --arg assistant "$assistant_output" '{input:$user,assistant:$assistant}')"

# --- Generate span IDs ---
trace_id=$(generate_uuid | tr -d '-')
span_id=$(generate_uuid | tr -d '-' | cut -c1-16)
start_time=$(get_timestamp_ms)
# The turn already completed, so start ~ end (we don't have precise timing from notify)
end_time="$start_time"

# --- Build OpenInference LLM span ---
output_messages=$(jq -nc --arg out "$assistant_output" '[{"message.role":"assistant","message.content":$out}]')

attrs=$(jq -nc \
  --arg sid "$session_id" \
  --arg num "$trace_count" \
  --arg proj "$project_name" \
  --arg in "$user_prompt" \
  --arg out "$assistant_output" \
  --arg turn_id "$turn_id" \
  --arg thread_id "$thread_id" \
  --arg uid "$user_id" \
  --argjson out_msgs "$output_messages" \
  '{
    "session.id": $sid,
    "trace.number": $num,
    "project.name": $proj,
    "openinference.span.kind": "LLM",
    "input.value": $in,
    "output.value": $out,
    "codex.turn_id": $turn_id,
    "codex.thread_id": $thread_id,
    "llm.output_messages": $out_msgs
  }
  + (if $uid != "" then {"user.id": $uid} else {} end)')

# Optional token usage metadata (many Codex builds embed it in the notify payload)
token_usage_json=$(echo "$input" | jq -c '
  def usage_from($obj):
    if $obj != null and ($obj | type) == "object" then
      ($obj.token_usage // $obj."token-usage" // $obj.usage // $obj."usage")
    else null end;
  usage_from(.)
  // usage_from(.["last-assistant-message"])
  // usage_from(.["last-assistant-message"].message)
' 2>/dev/null || echo "null")
if [[ -n "$token_usage_json" && "$token_usage_json" != "null" ]]; then
  attrs=$(echo "$attrs" | jq --arg usage "$token_usage_json" '. + {"codex.token_usage": $usage}')
  debug_dump "${debug_prefix}_token_usage" "$token_usage_json"
  token_counts=$(printf '%s' "$token_usage_json" | jq -c '
    def to_int($value):
      if $value == null then null
      elif ($value | type) == "number" then $value
      elif ($value | type) == "string" then (try ($value | tonumber) catch null)
      else null end;
    def pick_first($obj; $fields):
      reduce $fields[] as $key (null;
        if . == null then to_int($obj[$key]) else . end
      );
    {
      prompt: pick_first(.; ["prompt_tokens","input_tokens","promptTokens","inputTokens","prompt","input","cache_read_input_tokens","cache_creation_input_tokens"]),
      completion: pick_first(.; ["completion_tokens","output_tokens","completionTokens","outputTokens","completion","output"]),
      total: pick_first(.; ["total_tokens","totalTokens","tokens","token_count","overall","sum"])
    } as $counts
    | if $counts.total == null and ($counts.prompt != null and $counts.completion != null) then
        $counts + { total: ($counts.prompt + $counts.completion) }
      else
        $counts
      end
  ' 2>/dev/null || echo "")
  if [[ -n "$token_counts" && "$token_counts" != "null" ]]; then
    attrs=$(echo "$attrs" | jq --argjson tokens "$token_counts" '
      (if ($tokens.prompt // null) != null then . + {"llm.token_count.prompt": $tokens.prompt} else . end)
      | (if ($tokens.completion // null) != null then . + {"llm.token_count.completion": $tokens.completion} else . end)
      | (if ($tokens.total // null) != null then . + {"llm.token_count.total": $tokens.total} else . end)
    ')
  fi
fi

# Tool call details from the assistant payload when available
tool_calls_json=$(echo "$input" | jq -c '
  def tool_list($obj):
    if $obj == null then null
    elif ($obj | type) == "array" then $obj
    elif ($obj | type) == "object" then
      (
        $obj.tool_calls
        // $obj."tool-calls"
        // $obj.toolCalls
        // $obj.tool_invocations
        // $obj.toolInvocations
        // $obj.tools
        // $obj.tool_results
      ) | (if . == null then null elif (.|type) == "array" then . else [.] end)
    else null end;
  tool_list(.)
  // tool_list(.["last-assistant-message"])
  // tool_list(.["last-assistant-message"].message)
' 2>/dev/null || echo "null")
if [[ -n "$tool_calls_json" && "$tool_calls_json" != "null" ]]; then
  debug_dump "${debug_prefix}_tool_calls" "$tool_calls_json"
  tool_call_count=$(printf '%s' "$tool_calls_json" | jq 'length' 2>/dev/null || echo "")
  if [[ "$tool_call_count" =~ ^[0-9]+$ ]]; then
    attrs=$(echo "$attrs" | jq --argjson cnt "$tool_call_count" '. + {"llm.tool_call_count": $cnt}')
    tool_call_count_int=$tool_call_count
    if (( tool_call_count_int > 0 )); then
      tool_calls_preview=$(printf '%s' "$tool_calls_json" | jq -c '
        if type == "array" then
          if length > 5 then .[:5] else . end
        else
          .
        end
      ' 2>/dev/null || echo "")
      if [[ -n "$tool_calls_preview" && "$tool_calls_preview" != "null" ]]; then
        attrs=$(echo "$attrs" | jq --arg tc "$tool_calls_preview" '. + {"llm.tool_calls": $tc}')
      fi
      if (( tool_call_count_int > 5 )); then
        omitted=$((tool_call_count_int - 5))
        attrs=$(echo "$attrs" | jq --argjson om "$omitted" '. + {"llm.tool_calls_omitted": $om}')
      fi
    fi
  fi
fi

# --- Flush event buffer and build child spans ---
# The shared collector at 127.0.0.1:4318 buffers Codex OTLP log events
# (via POST /v1/logs) and serves them via GET /drain/{id} and GET /flush/{id}.
# notify.sh drains events for the current thread to assemble child spans.
COLLECTOR_PORT="${ARIZE_COLLECTOR_PORT:-4318}"

collector_events="[]"
if [[ -n "$thread_id" ]]; then
  last_collector_time_ns=$(get_state "last_collector_time_ns")
  [[ -z "$last_collector_time_ns" ]] && last_collector_time_ns="0"
  collector_events=$(curl -sf "http://127.0.0.1:${COLLECTOR_PORT}/drain/${thread_id}?since_ns=${last_collector_time_ns}" 2>/dev/null || echo "[]")
  if [[ -z "$collector_events" || "$collector_events" == "null" ]]; then
    collector_events="[]"
  fi
else
  log "Skipping event buffer drain because thread-id is missing"
fi
debug_dump "${debug_prefix}_collector_events" "$collector_events"

# Build child spans from collector events
child_spans=()
event_count=$(echo "$collector_events" | jq 'length' 2>/dev/null || echo "0")
if [[ "$event_count" -gt 0 ]]; then
  max_collector_time_ns=$(echo "$collector_events" | jq -r '[.[].time_ns | tonumber?] | max // 0' 2>/dev/null || echo "0")
  [[ -n "$max_collector_time_ns" && "$max_collector_time_ns" != "null" ]] && set_state "last_collector_time_ns" "$max_collector_time_ns"
fi

if [[ "$event_count" -gt 0 ]]; then
  log "Processing $event_count collector events"

  min_collector_time_ns=$(echo "$collector_events" | jq -r '[.[].time_ns | tonumber? | select(. > 0)] | min // 0' 2>/dev/null || echo "0")
  max_collector_time_ns=$(echo "$collector_events" | jq -r '[.[].time_ns | tonumber? | select(. > 0)] | max // 0' 2>/dev/null || echo "0")
  if [[ "${min_collector_time_ns:-0}" -gt 0 && "${max_collector_time_ns:-0}" -ge "${min_collector_time_ns:-0}" ]]; then
    start_time=$(( min_collector_time_ns / 1000000 ))
    end_time=$(( max_collector_time_ns / 1000000 ))
    trace_duration_ms=$(( end_time - start_time ))
    attrs=$(echo "$attrs" | jq --argjson duration "$trace_duration_ms" '. + {"codex.trace.duration_ms": $duration}')
  fi

  # --- Enrich parent span from events ---
  # Extract model name from codex.conversation_starts or codex.api_request
  event_model=$(echo "$collector_events" | jq -r '
    [.[] | select(.event == "codex.conversation_starts" or .event == "codex.api_request")]
    | first
    | .attrs.model // .attrs["llm.model_name"] // .attrs["model_name"] // empty
  ' 2>/dev/null || echo "")
  if [[ -n "$event_model" ]]; then
    attrs=$(echo "$attrs" | jq --arg m "$event_model" '. + {"llm.model_name": $m}')
  fi

  # Extract token counts from codex.sse_event (response.completed)
  event_tokens=$(echo "$collector_events" | jq -c '
    [.[] | select(.event == "codex.sse_event" and (.attrs.type == "response.completed" or .attrs["sse.type"] == "response.completed" or .attrs["event.kind"] == "response.completed"))]
    | last
    | .attrs // {}
  ' 2>/dev/null || echo "{}")
  if [[ -n "$event_tokens" && "$event_tokens" != "null" && "$event_tokens" != "{}" ]]; then
    prompt_tokens=$(echo "$event_tokens" | jq -r '(.prompt_tokens // .input_tokens // .input_token_count // .["usage.prompt_tokens"] // empty) | tostring' 2>/dev/null || echo "")
    completion_tokens=$(echo "$event_tokens" | jq -r '(.completion_tokens // .output_tokens // .output_token_count // .["usage.completion_tokens"] // empty) | tostring' 2>/dev/null || echo "")
    total_tokens=$(echo "$event_tokens" | jq -r '(.total_tokens // .["usage.total_tokens"] // empty) | tostring' 2>/dev/null || echo "")

    [[ -n "$prompt_tokens" && "$prompt_tokens" != "null" ]] || prompt_tokens=""
    [[ -n "$completion_tokens" && "$completion_tokens" != "null" ]] || completion_tokens=""
    [[ -n "$total_tokens" && "$total_tokens" != "null" ]] || total_tokens=""

    if [[ -z "$total_tokens" && -n "$prompt_tokens" && -n "$completion_tokens" ]]; then
      total_tokens=$((prompt_tokens + completion_tokens))
    fi

    token_enrichment=$(jq -nc \
      --arg prompt "$prompt_tokens" \
      --arg completion "$completion_tokens" \
      --arg total "$total_tokens" '
      {
        prompt: (if $prompt == "" then null else ($prompt | tonumber) end),
        completion: (if $completion == "" then null else ($completion | tonumber) end),
        total: (if $total == "" then null else ($total | tonumber) end)
      }')
    debug_dump "${debug_prefix}_token_enrichment" "$token_enrichment"

    attrs=$(echo "$attrs" | jq --arg prompt "$prompt_tokens" --arg completion "$completion_tokens" --arg total "$total_tokens" '
      (if $prompt != "" then . + {"llm.token_count.prompt": ($prompt | tonumber)} else . end)
      | (if $completion != "" then . + {"llm.token_count.completion": ($completion | tonumber)} else . end)
      | (if $total != "" then . + {"llm.token_count.total": ($total | tonumber)} else . end)
    ')
    debug_dump "${debug_prefix}_attrs_after_tokens" "$attrs"
  fi

  # Extract sandbox/approval settings from codex.conversation_starts
  conv_start_attrs=$(echo "$collector_events" | jq -c '
    [.[] | select(.event == "codex.conversation_starts")] | first | .attrs // {}
  ' 2>/dev/null || echo "{}")
  if [[ -n "$conv_start_attrs" && "$conv_start_attrs" != "null" && "$conv_start_attrs" != "{}" ]]; then
    sandbox=$(echo "$conv_start_attrs" | jq -r '.sandbox // .sandbox_mode // empty' 2>/dev/null || echo "")
    approval=$(echo "$conv_start_attrs" | jq -r '.approval_mode // .approval // empty' 2>/dev/null || echo "")
    [[ -n "$sandbox" ]] && attrs=$(echo "$attrs" | jq --arg v "$sandbox" '. + {"codex.sandbox_mode": $v}')
    [[ -n "$approval" ]] && attrs=$(echo "$attrs" | jq --arg v "$approval" '. + {"codex.approval_mode": $v}')
  fi

  # --- Build TOOL child spans from codex.tool_decision + codex.tool_result pairs ---
  tool_decisions=$(echo "$collector_events" | jq -c '[.[] | select(.event == "codex.tool_decision")]' 2>/dev/null || echo "[]")
  tool_results=$(echo "$collector_events" | jq -c '[.[] | select(.event == "codex.tool_result")]' 2>/dev/null || echo "[]")

  tool_decision_count=$(echo "$tool_decisions" | jq 'length' 2>/dev/null || echo "0")
  for (( i=0; i<tool_decision_count; i++ )); do
    decision=$(echo "$tool_decisions" | jq -c ".[$i]")
    tool_name=$(echo "$decision" | jq -r '.attrs.tool_name // .attrs["tool.name"] // .attrs.name // "unknown_tool"' 2>/dev/null)
    decision_time_ns=$(echo "$decision" | jq -r '.time_ns // "0"' 2>/dev/null)
    approval_status=$(echo "$decision" | jq -r '.attrs.approved // .attrs.approval // .attrs.decision // .attrs.status // "unknown"' 2>/dev/null)

    # Try to match a corresponding tool_result by tool name or index
    result=$(echo "$tool_results" | jq -c \
      --arg tool "$tool_name" \
      --argjson idx "$i" '
        [.[]
          | select((.attrs.tool_name // .attrs["tool.name"] // .attrs.name // "") == $tool)
        ]
        | first // .[$idx] // null
      ' 2>/dev/null || echo "null")

    result_time_ns="$decision_time_ns"
    tool_output=""
    if [[ -n "$result" && "$result" != "null" ]]; then
      result_time_ns=$(echo "$result" | jq -r '.time_ns // "0"' 2>/dev/null)
      tool_output=$(echo "$result" | jq -r '.attrs.output // .attrs.result // .attrs["tool.output"] // ""' 2>/dev/null | head -c 2000)
    fi

    # Convert nanosecond timestamps to milliseconds for build_span
    tool_start_ms=$(( ${decision_time_ns:-0} / 1000000 ))
    tool_end_ms=$(( ${result_time_ns:-$decision_time_ns} / 1000000 ))
    # Fallback to parent times if timestamps are zero/invalid
    [[ "$tool_start_ms" -le 0 ]] && tool_start_ms="$start_time"
    [[ "$tool_end_ms" -le 0 ]] && tool_end_ms="$tool_start_ms"

    child_span_id=$(generate_uuid | tr -d '-' | cut -c1-16)
    tool_attrs=$(jq -nc \
      --arg name "$tool_name" \
      --arg output "$tool_output" \
      --arg approval "$approval_status" \
      --arg sid "$session_id" \
      '{
        "openinference.span.kind": "TOOL",
        "tool.name": $name,
        "output.value": $output,
        "codex.tool.approval_status": $approval,
        "session.id": $sid
      }')

    child_span=$(build_span "$tool_name" "TOOL" "$child_span_id" "$trace_id" "$span_id" "$tool_start_ms" "$tool_end_ms" "$tool_attrs")
    child_spans+=("$child_span")
  done

  # --- Build INTERNAL child spans from API/websocket requests ---
  api_requests=$(echo "$collector_events" | jq -c '[.[] | select(.event == "codex.api_request" or .event == "codex.websocket_request")]' 2>/dev/null || echo "[]")
  api_count=$(echo "$api_requests" | jq 'length' 2>/dev/null || echo "0")
  for (( i=0; i<api_count; i++ )); do
    req=$(echo "$api_requests" | jq -c ".[$i]")
    req_model=$(echo "$req" | jq -r '.attrs.model // .attrs["llm.model_name"] // "unknown"' 2>/dev/null)
    req_status=$(echo "$req" | jq -r '.attrs.status // .attrs.status_code // .attrs.success // "ok"' 2>/dev/null)
    req_attempt=$(echo "$req" | jq -r '.attrs.attempt // "1"' 2>/dev/null)
    req_duration_ms=$(echo "$req" | jq -r '.attrs.duration_ms // "0"' 2>/dev/null)
    req_auth_mode=$(echo "$req" | jq -r '.attrs.auth_mode // empty' 2>/dev/null)
    req_connection_reused=$(echo "$req" | jq -r '.attrs["auth.connection_reused"] // empty' 2>/dev/null)
    req_time_ns=$(echo "$req" | jq -r '.time_ns // "0"' 2>/dev/null)

    req_start_ms=$(( ${req_time_ns:-0} / 1000000 ))
    [[ "$req_start_ms" -le 0 ]] && req_start_ms="$start_time"
    req_end_ms="$req_start_ms"  # Point-in-time event

    child_span_id=$(generate_uuid | tr -d '-' | cut -c1-16)
    request_attrs=$(jq -nc \
      --arg model "$req_model" \
      --arg status "$req_status" \
      --arg attempt "$req_attempt" \
      --arg duration_ms "$req_duration_ms" \
      --arg auth_mode "$req_auth_mode" \
      --arg connection_reused "$req_connection_reused" \
      --arg sid "$session_id" \
      '{
        "openinference.span.kind": "CHAIN",
        "codex.request.model": $model,
        "codex.request.status": $status,
        "codex.request.attempt": $attempt,
        "codex.request.duration_ms": ($duration_ms | tonumber? // 0),
        "codex.request.auth_mode": $auth_mode,
        "codex.request.connection_reused": (if $connection_reused == "" then null else ($connection_reused == "true") end),
        "session.id": $sid
      }
      | with_entries(select(.value != null and .value != ""))')

    child_span=$(build_span "API Request ($req_model)" "INTERNAL" "$child_span_id" "$trace_id" "$span_id" "$req_start_ms" "$req_end_ms" "$request_attrs")
    child_spans+=("$child_span")
  done
fi

# --- Build parent Turn span and assemble payload ---
parent_span=$(build_span "Turn $trace_count" "LLM" "$span_id" "$trace_id" "" "$start_time" "$end_time" "$attrs")
debug_dump "${debug_prefix}_parent_span" "$parent_span"

if [[ ${#child_spans[@]} -gt 0 ]]; then
  log "Building multi-span payload: 1 parent + ${#child_spans[@]} children"
  all_spans=("$parent_span" "${child_spans[@]}")
  multi_payload=$(build_multi_span "${all_spans[@]}")
  debug_dump "${debug_prefix}_multi_span" "$multi_payload"
  send_span "$multi_payload" || true
else
  # Fallback: single flat span (collector not running or no events)
  debug_dump "${debug_prefix}_span" "$parent_span"
  send_span "$parent_span" || true
fi

log "Turn $trace_count sent (thread=$thread_id, turn=$turn_id, children=${#child_spans[@]})"

# Periodic GC of stale state files
if [[ $((trace_count % 10)) -eq 0 ]]; then
  gc_stale_state_files
fi
