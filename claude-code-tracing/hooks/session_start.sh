#!/bin/bash
# SessionStart - Initialize session state and ensure collector is running
source "$(dirname "$0")/common.sh"

check_requirements

# Ensure the shared collector is running (idempotent, no-op if already up).
# The collector requires ~/.arize/harness/config.yaml to exist — for marketplace
# installs, users must run the setup skill first to create it.
# collector_ctl.sh falls back to running collector.py directly if the
# installed launcher at ~/.arize/harness/bin/arize-collector doesn't exist.
_COLLECTOR_CTL="${CORE_DIR}/collector_ctl.sh"
if [[ -f "$_COLLECTOR_CTL" ]]; then
  source "$_COLLECTOR_CTL"
  collector_ensure 2>/dev/null || true
fi

input=$(cat 2>/dev/null || echo '{}')
[[ -z "$input" ]] && input='{}'

resolve_session "$input"
ensure_session_initialized "$input"

log "Session started: $(get_state 'session_id')"
