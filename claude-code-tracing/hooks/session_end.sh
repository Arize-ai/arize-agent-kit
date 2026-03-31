#!/bin/bash
# SessionEnd - Print summary and clean up
source "$(dirname "$0")/common.sh"

check_requirements

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

resolve_session "$input"

session_id=$(get_state "session_id")
[[ -z "$session_id" ]] && exit 0

trace_count=$(get_state "trace_count")
tool_count=$(get_state "tool_count")

log_always "Session complete: ${trace_count:-0} traces, ${tool_count:-0} tools"
log_always "View in Arize/Phoenix: session.id = $session_id"

# Clean up this session's state and lock
rm -f "$STATE_FILE" 2>/dev/null || true
rm -rf "$_LOCK_DIR" 2>/dev/null || true

# Clean up stale state files and locks for PIDs that are no longer running
gc_stale_state_files
