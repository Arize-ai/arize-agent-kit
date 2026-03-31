#!/bin/bash
# Stop - Create trace span with input and output
source "$(dirname "$0")/common.sh"
check_requirements

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

resolve_session "$input"

session_id=$(get_state "session_id")
trace_id=$(get_state "current_trace_id")
[[ -z "$session_id" || -z "$trace_id" ]] && exit 0

trace_span_id=$(get_state "current_trace_span_id")
trace_start_time=$(get_state "current_trace_start_time")
user_prompt=$(get_state "current_trace_prompt")
project_name=$(get_state "project_name")
trace_count=$(get_state "trace_count")

# Parse transcript for AI response and tokens
transcript=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null || echo "")
output="" model="" in_tokens=0 out_tokens=0

if [[ -f "$transcript" ]]; then
  start_line=$(get_state "trace_start_line")
  skip_lines=$((${start_line:-0}))

  # Use tail to skip already-processed lines instead of iterating from line 0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue

    [[ $(echo "$line" | jq -r '.type' 2>/dev/null) == "assistant" ]] || continue

    # Extract text
    text=$(echo "$line" | jq -r '.message.content | if type=="array" then [.[]|select(.type=="text")|.text]|join("\n") else . end' 2>/dev/null)
    [[ -n "$text" && "$text" != "null" ]] && output="${output:+$output
}$text"

    # Extract model and tokens (safe: validate numeric before arithmetic)
    model=$(echo "$line" | jq -r '.message.model // empty' 2>/dev/null)
    val=$(echo "$line" | jq -r '.message.usage.input_tokens // 0' 2>/dev/null)
    [[ "$val" =~ ^[0-9]+$ ]] && in_tokens=$((in_tokens + val))
    val=$(echo "$line" | jq -r '.message.usage.output_tokens // 0' 2>/dev/null)
    [[ "$val" =~ ^[0-9]+$ ]] && out_tokens=$((out_tokens + val))
    val=$(echo "$line" | jq -r '.message.usage.cache_read_input_tokens // 0' 2>/dev/null)
    [[ "$val" =~ ^[0-9]+$ ]] && in_tokens=$((in_tokens + val))
    val=$(echo "$line" | jq -r '.message.usage.cache_creation_input_tokens // 0' 2>/dev/null)
    [[ "$val" =~ ^[0-9]+$ ]] && in_tokens=$((in_tokens + val))
  done < <(tail -n +"$((skip_lines + 1))" "$transcript")
fi

output=$(printf '%s' "$output" | head -c 5000)
[[ -z "$output" ]] && output="(No response)"

# Compute total token count
total_tokens=$((in_tokens + out_tokens))

output_messages=$(jq -nc --arg out "$output" '[{"message.role":"assistant","message.content":$out}]')

attrs=$(jq -nc \
  --arg sid "$session_id" --arg num "$trace_count" --arg proj "$project_name" \
  --arg in "$user_prompt" --arg out "$output" --arg model "$model" \
  --argjson in_tok "$in_tokens" --argjson out_tok "$out_tokens" --argjson total_tok "$total_tokens" \
  --argjson out_msgs "$output_messages" \
  '{"session.id":$sid,"trace.number":$num,"project.name":$proj,"openinference.span.kind":"LLM","llm.model_name":$model,"llm.token_count.prompt":$in_tok,"llm.token_count.completion":$out_tok,"llm.token_count.total":$total_tok,"input.value":$in,"output.value":$out,"llm.output_messages":$out_msgs}')

span=$(build_span "Turn $trace_count" "LLM" "$trace_span_id" "$trace_id" "" "$trace_start_time" "$(get_timestamp_ms)" "$attrs")
send_span "$span" || true

del_state "current_trace_id"
del_state "current_trace_span_id"
del_state "current_trace_start_time"
del_state "current_trace_prompt"
log "Turn $trace_count sent"

# Opportunistic GC for environments without SessionEnd (e.g., Python Agent SDK)
if [[ $((trace_count % 5)) -eq 0 ]]; then
  gc_stale_state_files
fi
