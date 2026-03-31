#!/bin/bash
# Notification - Create span for system notifications
source "$(dirname "$0")/common.sh"
check_requirements

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

resolve_session "$input"

trace_id=$(get_state "current_trace_id")
[[ -z "$trace_id" ]] && exit 0

session_id=$(get_state "session_id")
message=$(echo "$input" | jq -r '.message // empty' 2>/dev/null || echo "")
title=$(echo "$input" | jq -r '.title // empty' 2>/dev/null || echo "")
notif_type=$(echo "$input" | jq -r '.notification_type // "info"' 2>/dev/null || echo "info")

span_id=$(generate_uuid | tr -d '-' | cut -c1-16)
ts=$(get_timestamp_ms)
parent=$(get_state "current_trace_span_id")

attrs=$(jq -n \
  --arg sid "$session_id" \
  --arg msg "$message" \
  --arg title "$title" \
  --arg type "$notif_type" \
  '{"session.id":$sid,"openinference.span.kind":"chain","notification.message":$msg,"notification.title":$title,"notification.type":$type,"input.value":$msg}')

span=$(build_span "Notification: $notif_type" "CHAIN" "$span_id" "$trace_id" "$parent" "$ts" "$ts" "$attrs")
send_span "$span" || true
