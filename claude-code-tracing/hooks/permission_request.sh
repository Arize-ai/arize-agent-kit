#!/bin/bash
# PermissionRequest - Create span for permission requests
source "$(dirname "$0")/common.sh"
check_requirements

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

resolve_session "$input"

_log_to_file "DEBUG permission_request input: $(echo "$input" | jq -c .)"

trace_id=$(get_state "current_trace_id")
[[ -z "$trace_id" ]] && exit 0

permission=$(echo "$input" | jq -r '.permission // empty' 2>/dev/null || echo "")
tool=$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
tool_input=$(echo "$input" | jq -c '.tool_input // empty' 2>/dev/null || echo "")
tool_input=$(redact_content "$ARIZE_LOG_TOOL_DETAILS" "$tool_input")

span_id=$(generate_uuid | tr -d '-' | cut -c1-16)
ts=$(get_timestamp_ms)
parent=$(get_state "current_trace_span_id")

session_id=$(get_state "session_id")

user_id=$(get_state "user_id")

attrs=$(jq -n --arg sid "$session_id" --arg perm "$permission" --arg tool "$tool" --arg tinput "$tool_input" \
  --arg uid "$user_id" \
  '{"session.id":$sid,"openinference.span.kind":"chain","permission.type":$perm,"permission.tool":$tool,"input.value":$tinput} + (if $uid != "" then {"user.id":$uid} else {} end)')

span=$(build_span "Permission Request" "CHAIN" "$span_id" "$trace_id" "$parent" "$ts" "$ts" "$attrs")
send_span "$span" || true
