#!/bin/bash
# PostToolUse - Create tool span
source "$(dirname "$0")/common.sh"
check_requirements

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

resolve_session "$input"

session_id=$(get_state "session_id")
[[ -z "$session_id" ]] && exit 0

trace_id=$(get_state "current_trace_id")
parent_span_id=$(get_state "current_trace_span_id")
inc_state "tool_count"

tool_name=$(echo "$input" | jq -r '.tool_name // "unknown"' 2>/dev/null || echo "unknown")
tool_id=$(echo "$input" | jq -r '.tool_use_id // empty' 2>/dev/null || echo "")
tool_input_raw=$(echo "$input" | jq -c '.tool_input // {}' 2>/dev/null || echo '{}')
tool_input=$(echo "$tool_input_raw" | head -c 5000)
tool_response=$(echo "$input" | jq -r '.tool_response // empty' 2>/dev/null | head -c 5000) || true

# Track whether content was truncated
tool_input_truncated="false"
tool_response_truncated="false"
[[ ${#tool_input_raw} -gt 5000 ]] && tool_input_truncated="true"
raw_response=$(echo "$input" | jq -r '.tool_response // empty' 2>/dev/null || echo "")
[[ ${#raw_response} -gt 5000 ]] && tool_response_truncated="true"
truncated="false"
[[ "$tool_input_truncated" == "true" || "$tool_response_truncated" == "true" ]] && truncated="true"

# Extract tool-specific metadata for structured attributes
tool_description=""
tool_command=""
tool_file_path=""
tool_url=""
tool_query=""

case "$tool_name" in
  Bash)
    tool_command=$(echo "$tool_input_raw" | jq -r '.command // empty' 2>/dev/null || echo "")
    tool_description=$(echo "$tool_command" | head -c 200)
    ;;
  Read|Write|Edit|Glob)
    tool_file_path=$(echo "$tool_input_raw" | jq -r '.file_path // .pattern // empty' 2>/dev/null || echo "")
    tool_description=$(echo "$tool_file_path" | head -c 200)
    ;;
  WebSearch)
    tool_query=$(echo "$tool_input_raw" | jq -r '.query // empty' 2>/dev/null || echo "")
    tool_description=$(echo "$tool_query" | head -c 200)
    ;;
  WebFetch)
    tool_url=$(echo "$tool_input_raw" | jq -r '.url // empty' 2>/dev/null || echo "")
    tool_description=$(echo "$tool_url" | head -c 200)
    ;;
  Grep)
    tool_query=$(echo "$tool_input_raw" | jq -r '.pattern // empty' 2>/dev/null || echo "")
    tool_file_path=$(echo "$tool_input_raw" | jq -r '.path // empty' 2>/dev/null || echo "")
    tool_description="grep: $(echo "$tool_query" | head -c 100)"
    ;;
  *)
    tool_description=$(echo "$tool_input" | head -c 200)
    ;;
esac

start_time=$(get_state "tool_${tool_id}_start")
[[ -z "$start_time" ]] && start_time=$(get_timestamp_ms)
end_time=$(get_timestamp_ms)
del_state "tool_${tool_id}_start"

span_id=$(generate_uuid | tr -d '-' | cut -c1-16)

# Build base attributes
attrs=$(jq -n \
  --arg sid "$session_id" --arg tool "$tool_name" \
  --arg in "$tool_input" --arg out "$tool_response" \
  --arg desc "$tool_description" --arg trunc "$truncated" \
  '{"session.id":$sid,"openinference.span.kind":"tool","tool.name":$tool,"input.value":$in,"output.value":$out,"tool.description":$desc,"tool.truncated":$trunc}')

# Add tool-specific structured attributes
[[ -n "$tool_command" ]] && attrs=$(echo "$attrs" | jq --arg v "$tool_command" '. + {"tool.command":$v}')
[[ -n "$tool_file_path" ]] && attrs=$(echo "$attrs" | jq --arg v "$tool_file_path" '. + {"tool.file_path":$v}')
[[ -n "$tool_url" ]] && attrs=$(echo "$attrs" | jq --arg v "$tool_url" '. + {"tool.url":$v}')
[[ -n "$tool_query" ]] && attrs=$(echo "$attrs" | jq --arg v "$tool_query" '. + {"tool.query":$v}')

span=$(build_span "$tool_name" "TOOL" "$span_id" "$trace_id" "$parent_span_id" "$start_time" "$end_time" "$attrs")
send_span "$span" || true
