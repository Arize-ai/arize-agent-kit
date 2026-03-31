#!/bin/bash
# Collector lifecycle management for Codex OTel event collector.
#
# Provides: collector_start, collector_stop, collector_status, collector_ensure
# Source this file to use the functions.

# Source env for CODEX_COLLECTOR_PORT if available
_COLLECTOR_CTL_ENV="${HOME}/.codex/arize-env.sh"
[[ -f "$_COLLECTOR_CTL_ENV" ]] && source "$_COLLECTOR_CTL_ENV" 2>/dev/null

_COLLECTOR_PORT="${CODEX_COLLECTOR_PORT:-4318}"
_COLLECTOR_PID_FILE="${HOME}/.arize-codex/collector.pid"

# Resolve this script's directory even when sourced from zsh (no BASH_SOURCE).
_collector_ctl_source="${BASH_SOURCE[0]:-$0}"
_collector_ctl_dir="$(cd "$(dirname "$_collector_ctl_source")" 2>/dev/null && pwd)"

_COLLECTOR_SCRIPT="${_collector_ctl_dir}/collector.py"

# Find the collector script relative to the plugin directory if needed
if [[ ! -f "$_COLLECTOR_SCRIPT" ]]; then
  _COLLECTOR_SCRIPT="${_collector_ctl_dir}/../scripts/collector.py"
fi

collector_status() {
  # Returns 0 if running, 1 if not
  if [[ -f "$_COLLECTOR_PID_FILE" ]]; then
    local pid
    pid=$(cat "$_COLLECTOR_PID_FILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      # Verify it's actually listening
      if curl -sf "http://127.0.0.1:${_COLLECTOR_PORT}/health" >/dev/null 2>&1; then
        echo "running (PID $pid, port $_COLLECTOR_PORT)"
        return 0
      fi
    fi
    # Stale PID file
    rm -f "$_COLLECTOR_PID_FILE"
  fi
  echo "stopped"
  return 1
}

collector_start() {
  if collector_status >/dev/null 2>&1; then
    return 0  # Already running
  fi

  if [[ ! -f "$_COLLECTOR_SCRIPT" ]]; then
    echo "[arize] collector.py not found at $_COLLECTOR_SCRIPT" >&2
    return 1
  fi

  # Check if port is available
  if curl -sf "http://127.0.0.1:${_COLLECTOR_PORT}/health" >/dev/null 2>&1; then
    # Something else is listening — could be another collector instance
    echo "[arize] Port $_COLLECTOR_PORT already in use, assuming collector is running" >&2
    return 0
  fi

  mkdir -p "$(dirname "$_COLLECTOR_PID_FILE")"

  # Start in background, redirect output to log
  local log_file="${HOME}/.arize-codex/collector.log"
  CODEX_COLLECTOR_PORT="$_COLLECTOR_PORT" \
    nohup python3 "$_COLLECTOR_SCRIPT" >> "$log_file" 2>&1 &

  local bg_pid=$!

  # Wait briefly for startup
  local attempts=0
  while [[ $attempts -lt 20 ]]; do
    if curl -sf "http://127.0.0.1:${_COLLECTOR_PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done

  # Check if process is still alive
  if kill -0 "$bg_pid" 2>/dev/null; then
    # Running but health check failed — give it more time
    return 0
  else
    echo "[arize] Failed to start collector" >&2
    return 1
  fi
}

collector_stop() {
  if [[ -f "$_COLLECTOR_PID_FILE" ]]; then
    local pid
    pid=$(cat "$_COLLECTOR_PID_FILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      # Wait for clean shutdown
      local attempts=0
      while kill -0 "$pid" 2>/dev/null && [[ $attempts -lt 20 ]]; do
        sleep 0.1
        attempts=$((attempts + 1))
      done
    fi
    rm -f "$_COLLECTOR_PID_FILE"
  fi
  echo "stopped"
}

collector_ensure() {
  # Idempotent start — no output on success (suitable for shell profile)
  collector_status >/dev/null 2>&1 && return 0
  collector_start >/dev/null 2>&1
}
