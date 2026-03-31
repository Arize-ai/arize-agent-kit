#!/bin/bash
# SessionStart - Initialize session state
source "$(dirname "$0")/common.sh"

check_requirements

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

resolve_session "$input"
ensure_session_initialized "$input"

log "Session started: $(get_state 'session_id')"
