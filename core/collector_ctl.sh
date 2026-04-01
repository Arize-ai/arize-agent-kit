#!/bin/bash
# Shared collector lifecycle management for Arize Agent Kit.
#
# Provides: collector_start, collector_stop, collector_status, collector_ensure
# Source this file to use the functions.

# Note: no `set -euo pipefail` here — this file is designed to be sourced,
# and setting shell options would change the caller's environment.

# --- Shared layout ---
_AK_BASE="${HOME}/.arize/harness"
_AK_CONFIG="${_AK_BASE}/config.json"
_AK_PID_FILE="${_AK_BASE}/run/collector.pid"
_AK_LOG_FILE="${_AK_BASE}/logs/collector.log"
_AK_BIN="${_AK_BASE}/bin/arize-collector"

# Default collector endpoint
_AK_HOST="127.0.0.1"
_AK_PORT="4318"

# Resolve the collector.py script relative to this file
_ctl_source="${BASH_SOURCE[0]:-$0}"
_ctl_dir="$(cd "$(dirname "$_ctl_source")" 2>/dev/null && pwd)"
_AK_COLLECTOR_PY="${_ctl_dir}/collector.py"

# Read host/port from config if available
if command -v jq >/dev/null 2>&1 && [[ -f "$_AK_CONFIG" ]]; then
  _cfg_host=$(jq -r '.collector.host // empty' "$_AK_CONFIG" 2>/dev/null) || true
  _cfg_port=$(jq -r '.collector.port // empty' "$_AK_CONFIG" 2>/dev/null) || true
  [[ -n "${_cfg_host:-}" ]] && _AK_HOST="$_cfg_host"
  [[ -n "${_cfg_port:-}" ]] && _AK_PORT="$_cfg_port"
fi

_ak_log() {
  echo "[arize] $*" >&2
}

collector_status() {
  # Returns 0 if running, 1 if not
  if [[ -f "$_AK_PID_FILE" ]]; then
    local pid
    pid=$(cat "$_AK_PID_FILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      if curl -sf "http://${_AK_HOST}:${_AK_PORT}/health" >/dev/null 2>&1; then
        echo "running (PID $pid, ${_AK_HOST}:${_AK_PORT})"
        return 0
      fi
    fi
    # Stale PID file
    rm -f "$_AK_PID_FILE"
  fi
  echo "stopped"
  return 1
}

collector_start() {
  # Idempotent: if already running, return success
  if collector_status >/dev/null 2>&1; then
    return 0
  fi

  # Config is required — collector reads all settings from config.json
  if [[ ! -f "$_AK_CONFIG" ]]; then
    _ak_log "ERROR: No config.json found at $_AK_CONFIG — cannot start collector"
    _ak_log "Run install.sh or use the setup skill to create it"
    return 1
  fi

  # Find collector runtime: prefer installed bin, fall back to source
  local collector_cmd=()
  if [[ -x "$_AK_BIN" ]]; then
    collector_cmd=("$_AK_BIN")
  elif [[ -f "$_AK_COLLECTOR_PY" ]]; then
    collector_cmd=(python3 "$_AK_COLLECTOR_PY")
  else
    _ak_log "Collector runtime not found at $_AK_BIN or $_AK_COLLECTOR_PY"
    return 1
  fi

  # Check if port is already in use by something else
  if curl -sf "http://${_AK_HOST}:${_AK_PORT}/health" >/dev/null 2>&1; then
    _ak_log "Port ${_AK_PORT} already in use — assuming collector is running"
    return 0
  fi

  # Ensure directories exist
  mkdir -p "$(dirname "$_AK_PID_FILE")"
  mkdir -p "$(dirname "$_AK_LOG_FILE")"

  # Start in background
  nohup "${collector_cmd[@]}" >> "$_AK_LOG_FILE" 2>&1 &
  local bg_pid=$!

  # Wait for startup (up to 2 seconds)
  local attempts=0
  while [[ $attempts -lt 20 ]]; do
    if curl -sf "http://${_AK_HOST}:${_AK_PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done

  # Check if process is still alive
  if kill -0 "$bg_pid" 2>/dev/null; then
    # Running but health check not ready yet — give it the benefit of the doubt
    return 0
  else
    _ak_log "Failed to start collector (process exited)"
    return 1
  fi
}

collector_stop() {
  if [[ -f "$_AK_PID_FILE" ]]; then
    local pid
    pid=$(cat "$_AK_PID_FILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      # Wait for clean shutdown (up to 5 seconds for flush)
      local attempts=0
      while kill -0 "$pid" 2>/dev/null && [[ $attempts -lt 50 ]]; do
        sleep 0.1
        attempts=$((attempts + 1))
      done
    fi
    rm -f "$_AK_PID_FILE"
  fi
  echo "stopped"
}

collector_ensure() {
  # Idempotent start — no output on success (suitable for hooks/profile)
  collector_status >/dev/null 2>&1 && return 0
  collector_start >/dev/null 2>&1
}
