#!/bin/bash
# UserPromptSubmit - Store state for trace (span created at Stop)
source "$(dirname "$0")/common.sh"
check_requirements

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

# Resolve state file from session_id in input JSON
resolve_session "$input"

# Lazy init: if SessionStart never fired (e.g., Python Agent SDK), initialize now
ensure_session_initialized "$input"

session_id=$(get_state "session_id")

# --- Fail-safe: close any prior Turn span that Stop never emitted ---
prev_trace_id=$(get_state "current_trace_id")
prev_span_id=$(get_state "current_trace_span_id")
if [[ -n "$prev_trace_id" && -n "$prev_span_id" ]]; then
  prev_start=$(get_state "current_trace_start_time")
  prev_prompt=$(get_state "current_trace_prompt")
  prev_count=$(get_state "trace_count")
  project_name=$(get_state "project_name")
  end_time=$(get_timestamp_ms)

  attrs=$(jq -nc \
    --arg sid "$session_id" --arg num "$prev_count" --arg proj "$project_name" \
    --arg in "$prev_prompt" \
    '{"session.id":$sid,"trace.number":$num,"project.name":$proj,"openinference.span.kind":"LLM","input.value":$in,"output.value":"(Turn closed by fail-safe: Stop hook did not fire)"}')

  span=$(build_span "Turn $prev_count" "LLM" "$prev_span_id" "$prev_trace_id" "" "$prev_start" "$end_time" "$attrs")
  send_span "$span" || true

  del_state "current_trace_id"
  del_state "current_trace_span_id"
  del_state "current_trace_start_time"
  del_state "current_trace_prompt"
  log "Fail-safe: closed orphaned Turn $prev_count"
fi

inc_state "trace_count"

# Generate trace IDs now, create span at Stop (so it has output)
set_state "current_trace_id" "$(generate_uuid | tr -d '-')"
set_state "current_trace_span_id" "$(generate_uuid | tr -d '-' | cut -c1-16)"
set_state "current_trace_start_time" "$(get_timestamp_ms)"
set_state "current_trace_prompt" "$(echo "$input" | jq -r '.prompt // empty' 2>/dev/null | head -c 1000)"

# Track transcript position for parsing AI response later
transcript=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null || echo "")
if [[ -n "$transcript" && -f "$transcript" ]]; then
  set_state "trace_start_line" "$(wc -l < "$transcript" | tr -d ' ')"
else
  set_state "trace_start_line" "0"
fi
