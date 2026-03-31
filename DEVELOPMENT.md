# Development Guide

Contributor guide for adding new harness adapters and working with the shared core.

## Architecture Overview

The system has two layers:

1. **Harness adapters** — build OpenInference spans from harness-specific events (hook payloads, session lifecycle, tool calls) and submit them locally.
2. **Shared collector/exporter** — a background process at `http://127.0.0.1:4318` that receives spans from all harnesses and exports them to Phoenix or Arize AX.

Harnesses are responsible for span construction and session state. The collector is responsible for backend export, credentials, retries, and logging. New harnesses should submit spans to the collector via `POST http://127.0.0.1:4318/v1/spans` rather than implementing direct export logic. See [COLLECTOR_ARCHITECTURE.md](COLLECTOR_ARCHITECTURE.md) for the full collector contract.

## Repo Structure

```
core/
  common.sh          # Shared: env vars, logging, utils, state primitives, span building, sending
  send_arize.py      # Shared: Arize AX gRPC sender (Python, opentelemetry-proto + grpcio)

claude-code-tracing/ # Claude Code CLI / Agent SDK adapter
  hooks/common.sh    # Adapter: PID-based state, session resolution, GC, sources core/common.sh
  hooks/*.sh         # 9 hook scripts (SessionStart, Stop, PostToolUse, etc.)
  scripts/setup.sh   # Interactive setup wizard
  .claude-plugin/    # plugin.json for Claude Code marketplace

codex-tracing/       # OpenAI Codex CLI adapter
  hooks/common.sh    # Adapter: thread-id state, debug_dump, multi-span, sources core/common.sh
  hooks/notify.sh    # Single event handler (Codex uses one hook for all events)
  scripts/           # collector.py, collector_ctl.sh
  skills/            # setup-codex-tracing/SKILL.md
  README.md          # Codex-specific setup and usage

install.sh           # Curl-pipe installer for non-marketplace harnesses
marketplace.json     # Claude Code marketplace listing
```

## How core/ Relates to Adapters

`core/common.sh` contains all logic that is identical across harnesses:

- Environment variable declarations and defaults
- Logging (`log`, `log_always`, `error`, `_log_to_file`)
- Utilities (`generate_uuid`, `get_timestamp_ms`)
- State primitives (`init_state`, `get_state`, `set_state`, `del_state`, `inc_state`, locking)
- Target detection (`get_target`)
- Span building (`build_span`, `build_multi_span`)
- Span sending (`send_span`, `send_to_phoenix`, `send_to_arize`)
- Requirements check (`check_requirements`)

Each adapter's `hooks/common.sh` does three things:

1. Sets adapter-specific variables (`ARIZE_SERVICE_NAME`, `ARIZE_SCOPE_NAME`, `STATE_DIR`, `ARIZE_LOG_FILE`)
2. Sources `core/common.sh` via relative path from `${BASH_SOURCE[0]}`
3. Defines adapter-specific functions (session resolution, GC strategy, `ensure_session_initialized`)

The core `build_span()` and `build_multi_span()` read `ARIZE_SERVICE_NAME` and `ARIZE_SCOPE_NAME` to fill in the OTLP resource and scope fields. Adapters set these before sourcing core.

## Adding a new harness

Follow these steps to add tracing support for a new AI coding harness.

### Step 1: Create the adapter directory

```
<harness>-tracing/
  hooks/
    common.sh
  .claude-plugin/
    plugin.json        # If the harness supports Claude Code plugin format
  skills/
    setup-<harness>-tracing/
      SKILL.md
  README.md
```

### Step 2: Write the adapter common.sh

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(dirname "$SCRIPT_DIR")"
CORE_DIR="$(cd "$ADAPTER_DIR/../core" && pwd)"

# --- Adapter identity ---
export ARIZE_SERVICE_NAME="<harness>"
export ARIZE_SCOPE_NAME="arize-<harness>-plugin"

# --- Adapter-specific state ---
export STATE_DIR="${HOME}/.arize-<harness>"
export ARIZE_LOG_FILE="${ARIZE_LOG_FILE:-/tmp/arize-<harness>.log}"

# --- Source shared core ---
# After sourcing, all core functions are available: build_span, send_span,
# state primitives, logging, check_requirements, etc.
# Hook scripts call check_requirements as their first action after sourcing
# this adapter common.sh — it verifies tracing is enabled, jq exists, and
# creates STATE_DIR. See Step 3 for the hook script pattern.
source "$CORE_DIR/common.sh"

# --- Session resolution (harness-specific) ---
# Implement resolve_session() based on how the harness identifies sessions.
# Claude uses PID-based keys; Codex uses thread-id from the event payload.
resolve_session() {
  local session_key="${1:-}"
  [[ -z "$session_key" ]] && session_key=$(generate_uuid)
  STATE_FILE="${STATE_DIR}/state_${session_key}.json"
  _LOCK_DIR="${STATE_DIR}/.lock_${session_key}"
  init_state
}

# --- Session initialization ---
ensure_session_initialized() {
  local session_key="${1:-}"
  local cwd="${2:-$(pwd)}"

  local existing_sid
  existing_sid=$(get_state "session_id")
  [[ -n "$existing_sid" ]] && return 0

  local session_id="${session_key:-$(generate_uuid)}"
  local project_name="${ARIZE_PROJECT_NAME:-$(basename "$cwd")}"

  set_state "session_id" "$session_id"
  set_state "session_start_time" "$(get_timestamp_ms)"
  set_state "project_name" "$project_name"
  set_state "trace_count" "0"
  set_state "tool_count" "0"

  # ARIZE_USER_ID support
  local user_id="${ARIZE_USER_ID:-}"
  [[ -n "$user_id" ]] && set_state "user_id" "$user_id"

  log "Session initialized: $session_id"
}

# --- Garbage collection (harness-specific) ---
# Implement based on how stale sessions can be detected.
# This is optional — leave as a no-op if the harness manages its own lifecycle.
# Claude uses PID liveness checks; Codex uses file age with a 24h threshold.
gc_stale_state_files() {
  # Example: remove state files older than 24 hours
  local now_s max_age_s
  now_s=$(date +%s)
  max_age_s=86400
  for f in "${STATE_DIR}"/state_*.json; do
    [[ -f "$f" ]] || continue
    # Cross-platform: stat -f %m is macOS (BSD), stat -c %Y is Linux (GNU).
    # The fallback to $now_s ensures the file is never GC'd if both fail.
    local file_age_s=$(( now_s - $(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo "$now_s") ))
    if (( file_age_s > max_age_s )); then
      rm -f "$f"
      log "GC: removed stale state file $(basename "$f")"
    fi
  done
}
```

### Step 3: Write hook scripts

Each hook script follows this pattern:

```bash
#!/bin/bash
source "$(dirname "$0")/common.sh"
check_requirements

input=$(cat)
# ... parse input JSON with jq ...
# ... resolve session, build span, send span ...
```

Hook scripts call `send_span` which submits the span payload to the shared collector at `http://127.0.0.1:4318/v1/spans`. New harnesses should not implement direct backend export — the collector handles Phoenix and Arize AX export for all harnesses.

Include `ARIZE_USER_ID` in spans:

```bash
user_id=$(get_state "user_id")
attrs=$(jq -nc \
  --arg key "value" \
  --arg uid "$user_id" \
  '{"key": $key} + (if $uid != "" then {"user.id": $uid} else {} end)')
```

### Step 4: Update install.sh and marketplace.json

- Add the new harness to `install.sh` if it should be installable via curl-pipe
- Add to `marketplace.json` if the harness supports the Claude Code plugin format

### Step 5: Write a README.md

Follow the pattern in existing adapter READMEs: features, configuration table, quick setup, troubleshooting.

## Core API Reference

### Span Building

| Function | Signature | Description |
|----------|-----------|-------------|
| `build_span` | `name kind span_id trace_id [parent] start [end] [attrs_json]` | Build a single OTLP span JSON payload. Uses `$ARIZE_SERVICE_NAME` and `$ARIZE_SCOPE_NAME`. |
| `build_multi_span` | `full_payload1 full_payload2 ...` | Batch multiple spans into one OTLP request. Each input must be a complete `build_span()` output (already wrapped with resource/scope). The function unwraps each payload to extract the inner span objects, then re-wraps all spans under a single resource/scope envelope using the current `$ARIZE_SERVICE_NAME` and `$ARIZE_SCOPE_NAME`. Do **not** pass raw span objects — pass full `build_span()` outputs. |

**`build_span` parameters:**

- `name` — Span name (e.g., `"tool_use"`, `"user_prompt"`)
- `kind` — Span kind: `INTERNAL`, `SERVER`, `CLIENT`, `PRODUCER`, `CONSUMER`, or numeric `0-5`
- `span_id` — 16-char hex string
- `trace_id` — 32-char hex string
- `parent` — Parent span ID (empty string for root spans)
- `start` — Start time in milliseconds since epoch
- `end` — End time in milliseconds (defaults to `start`)
- `attrs_json` — JSON object of key-value attributes (defaults to `"{}"`)

### Span Sending

| Function | Signature | Description |
|----------|-----------|-------------|
| `send_span` | `span_json` | Submit span to the shared collector at `http://127.0.0.1:4318/v1/spans`. Handles dry run and verbose modes. The collector routes to the configured backend (Phoenix or Arize AX). |
| `send_to_phoenix` | `span_json` | (Legacy) Send directly to Phoenix REST API. Uses `$PHOENIX_ENDPOINT`, `$PHOENIX_API_KEY`. Being moved into the collector. |
| `send_to_arize` | `span_json` | (Legacy) Send to Arize AX via `core/send_arize.py`. Being moved into the collector. |
| `get_target` | (none) | (Legacy) Returns `"phoenix"`, `"arize"`, or `"none"` based on env vars. Being replaced by collector config. |

### State Management

| Function | Signature | Description |
|----------|-----------|-------------|
| `init_state` | (none) | Create `$STATE_DIR` and initialize `$STATE_FILE` as empty JSON if missing. |
| `get_state` | `key` | Read a value from the session state file. Returns empty string if missing. |
| `set_state` | `key value` | Write a key-value pair to state (with locking). |
| `del_state` | `key` | Remove a key from state (with locking). |
| `inc_state` | `key` | Atomically increment a numeric state value (with locking). |

State files are JSON, keyed per-session. Locking uses `mkdir`-based advisory locks via `$_LOCK_DIR`. Each adapter sets `$STATE_FILE` and `$_LOCK_DIR` in its `resolve_session()`.

### Logging

| Function | Signature | Description |
|----------|-----------|-------------|
| `log` | `message` | Log to stderr and file (only when `ARIZE_VERBOSE=true`). |
| `log_always` | `message` | Always log to stderr and file. |
| `error` | `message` | Log error to stderr and file. |
| `debug_dump` | `label data` | Write data to `$STATE_DIR/debug/` (only when `ARIZE_TRACE_DEBUG=true`). |

### Utilities

| Function | Signature | Description |
|----------|-----------|-------------|
| `generate_uuid` | (none) | Generate a lowercase UUID. Tries `uuidgen`, `/proc/sys/kernel/random/uuid`, then `od`. |
| `get_timestamp_ms` | (none) | Current time in milliseconds. Tries `python3`, `date +%s%3N`, then `date +%s000`. |
| `check_requirements` | (none) | Exit if tracing disabled; error if `jq` missing; create state dir. |

## Adapter Environment Variables

Each adapter must set these before sourcing `core/common.sh`:

| Variable | Purpose | Example |
|----------|---------|---------|
| `ARIZE_SERVICE_NAME` | OTLP `service.name` resource attribute | `"claude-code"`, `"codex"` |
| `ARIZE_SCOPE_NAME` | OTLP instrumentation scope name | `"arize-claude-plugin"` |
| `STATE_DIR` | Directory for per-session state files | `"$HOME/.arize-claude-code"` |
| `ARIZE_LOG_FILE` | Log file path (set by adapter as default) | `"/tmp/arize-codex.log"` |

## Testing

### Dry Run Mode

Validate span structure without sending to any backend:

```bash
ARIZE_DRY_RUN=true ARIZE_TRACE_ENABLED=true <run-your-harness>
```

Dry run prints span names to stderr. Combine with `ARIZE_VERBOSE=true` to see the full JSON:

```bash
ARIZE_DRY_RUN=true ARIZE_VERBOSE=true <run-your-harness>
```

### Debug Mode

Write raw span data to files for inspection (Codex adapter only, unless added to your adapter):

```bash
ARIZE_TRACE_DEBUG=true <run-your-harness>
ls ~/.arize-<harness>/debug/
```

### Log File

All adapters write to a log file by default. Tail it to watch spans in real time:

```bash
tail -f /tmp/arize-<harness>.log
```

### Manual Span Test

Source the adapter common and build a span directly:

```bash
source <harness>-tracing/hooks/common.sh
span=$(build_span "test" "INTERNAL" "$(generate_uuid | tr -d '-' | head -c 16)" \
  "$(generate_uuid | tr -d '-')" "" "$(get_timestamp_ms)" "" '{"test.key":"value"}')
echo "$span" | jq .
```
