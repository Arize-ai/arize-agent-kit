#!/bin/bash
# Codex event buffer lifecycle management.
#
# Manages the Codex-specific event buffer (collector.py) that receives native
# OTel log events and buffers them by thread-id for child-span assembly.
# This is separate from the shared span exporter (core/collector_ctl.sh).
#
# Provides: event_buffer_start, event_buffer_stop, event_buffer_status,
#           event_buffer_ensure
# Also provides legacy aliases: collector_start, collector_stop, etc.
# Source this file to use the functions.

# Source env for CODEX_EVENT_PORT if available
_COLLECTOR_CTL_ENV="${HOME}/.codex/arize-env.sh"
[[ -f "$_COLLECTOR_CTL_ENV" ]] && source "$_COLLECTOR_CTL_ENV" 2>/dev/null

# Event buffer defaults to port 4319 to avoid conflict with shared collector (4318)
_EVENT_BUFFER_PORT="${CODEX_EVENT_PORT:-${CODEX_COLLECTOR_PORT:-4319}}"
_EVENT_BUFFER_PID_FILE="${HOME}/.arize-codex/event_buffer.pid"
# Also check legacy PID file for backward compat during migration
_LEGACY_PID_FILE="${HOME}/.arize-codex/collector.pid"

# Resolve this script's directory even when sourced from zsh (no BASH_SOURCE).
_collector_ctl_source="${BASH_SOURCE[0]:-$0}"
_collector_ctl_dir="$(cd "$(dirname "$_collector_ctl_source")" 2>/dev/null && pwd)"

_EVENT_BUFFER_SCRIPT="${_collector_ctl_dir}/collector.py"

# Find the collector script relative to the adapter directory if needed
if [[ ! -f "$_EVENT_BUFFER_SCRIPT" ]]; then
  _EVENT_BUFFER_SCRIPT="${_collector_ctl_dir}/../scripts/collector.py"
fi

event_buffer_status() {
  # Returns 0 if running, 1 if not
  for pidfile in "$_EVENT_BUFFER_PID_FILE" "$_LEGACY_PID_FILE"; do
    if [[ -f "$pidfile" ]]; then
      local pid
      pid=$(cat "$pidfile" 2>/dev/null)
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        # Verify it's actually listening
        if curl -sf "http://127.0.0.1:${_EVENT_BUFFER_PORT}/health" >/dev/null 2>&1; then
          echo "running (PID $pid, port $_EVENT_BUFFER_PORT)"
          return 0
        fi
      fi
      # Stale PID file
      rm -f "$pidfile"
    fi
  done
  echo "stopped"
  return 1
}

event_buffer_start() {
  if event_buffer_status >/dev/null 2>&1; then
    return 0  # Already running
  fi

  if [[ ! -f "$_EVENT_BUFFER_SCRIPT" ]]; then
    echo "[arize] event buffer script not found at $_EVENT_BUFFER_SCRIPT" >&2
    return 1
  fi

  # Check if port is available
  if curl -sf "http://127.0.0.1:${_EVENT_BUFFER_PORT}/health" >/dev/null 2>&1; then
    echo "[arize] Port $_EVENT_BUFFER_PORT already in use, assuming event buffer is running" >&2
    return 0
  fi

  mkdir -p "$(dirname "$_EVENT_BUFFER_PID_FILE")"

  # Start in background, redirect output to log
  local log_file="${HOME}/.arize-codex/event_buffer.log"
  CODEX_EVENT_PORT="$_EVENT_BUFFER_PORT" \
    nohup python3 "$_EVENT_BUFFER_SCRIPT" >> "$log_file" 2>&1 &

  local bg_pid=$!

  # Wait briefly for startup
  local attempts=0
  while [[ $attempts -lt 20 ]]; do
    if curl -sf "http://127.0.0.1:${_EVENT_BUFFER_PORT}/health" >/dev/null 2>&1; then
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
    echo "[arize] Failed to start event buffer" >&2
    return 1
  fi
}

event_buffer_stop() {
  for pidfile in "$_EVENT_BUFFER_PID_FILE" "$_LEGACY_PID_FILE"; do
    if [[ -f "$pidfile" ]]; then
      local pid
      pid=$(cat "$pidfile" 2>/dev/null)
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        # Wait for clean shutdown
        local attempts=0
        while kill -0 "$pid" 2>/dev/null && [[ $attempts -lt 20 ]]; do
          sleep 0.1
          attempts=$((attempts + 1))
        done
      fi
      rm -f "$pidfile"
    fi
  done
  echo "stopped"
}

event_buffer_ensure() {
  # Idempotent start — no output on success (suitable for shell profile)
  event_buffer_status >/dev/null 2>&1 && return 0
  event_buffer_start >/dev/null 2>&1
}

# --- Legacy aliases for backward compatibility ---
collector_status() { event_buffer_status "$@"; }
collector_start() { event_buffer_start "$@"; }
collector_stop() { event_buffer_stop "$@"; }
collector_ensure() { event_buffer_ensure "$@"; }
