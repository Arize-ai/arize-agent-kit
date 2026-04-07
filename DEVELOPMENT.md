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
  __init__.py          Shared: package init
  constants.py         Shared: all path constants
  config.py            Shared: YAML config helper
  common.py            Shared: env vars, logging, state, span building, sending
  collector.py         Shared: background collector/exporter
  collector_ctl.py     Shared: collector lifecycle (start/stop/status/ensure)
  send_arize.py        Legacy: Arize AX gRPC sender
  hooks/
    claude/
      adapter.py       Adapter: PID-based state, session resolution, GC
      handlers.py      9 hook entry points (SessionStart, Stop, PostToolUse, etc.)
    codex/
      adapter.py       Adapter: thread-id state, debug_dump, multi-span
      handlers.py      Notify hook handler
      proxy.py         Codex proxy wrapper
    cursor/
      adapter.py       Adapter: deterministic trace IDs, state stack, sanitize
      handlers.py      Single dispatcher for all 12 hook events
  setup/
    claude.py          Interactive setup wizard for Claude
    codex.py           Interactive setup wizard for Codex
    cursor.py          Interactive setup wizard for Cursor

claude-code-tracing/   Documentation, plugin.json, skills
codex-tracing/         Documentation, skills
cursor-tracing/        Documentation, skills

install.py             Cross-platform installer
pyproject.toml         Package definition, CLI entry points
```

## How core/ Relates to Adapters

`core/common.py` contains all logic that is identical across harnesses:

- Environment variable declarations and defaults
- Logging (`log`, `log_always`, `error`, `log_to_file`)
- Utilities (`generate_uuid`, `get_timestamp_ms`)
- State primitives (`init_state`, `get_state`, `set_state`, `del_state`, `inc_state`, locking)
- Target detection (`get_target`)
- Span building (`build_span`, `build_multi_span`)
- Span sending (`send_span`, `send_to_phoenix`, `send_to_arize`)
- Requirements check (`check_requirements`)

Each adapter's `adapter.py` does three things:

1. Sets adapter-specific variables (`ARIZE_SERVICE_NAME`, `ARIZE_SCOPE_NAME`, `STATE_DIR`, `ARIZE_LOG_FILE`)
2. Imports shared functions from `core.common` and `core.constants`
3. Defines adapter-specific functions (session resolution, GC strategy, `ensure_session_initialized`)

The core `build_span()` and `build_multi_span()` read `ARIZE_SERVICE_NAME` and `ARIZE_SCOPE_NAME` to fill in the OTLP resource and scope fields. Adapters set these before calling core functions.

## Adding a new harness

Follow these steps to add tracing support for a new AI coding harness.

### Step 1: Create the adapter directory

```
core/hooks/<harness>/
  __init__.py
  adapter.py
  handlers.py
```

### Step 2: Write adapter.py

```python
"""Adapter for <harness> tracing."""

import os
from pathlib import Path

from core.common import (
    generate_uuid,
    get_timestamp_ms,
    init_state,
    get_state,
    set_state,
    log,
)
from core.constants import ARIZE_STATE_ROOT

# --- Adapter identity ---
ARIZE_SERVICE_NAME = "<harness>"
ARIZE_SCOPE_NAME = "arize-<harness>-plugin"

# --- Adapter-specific state ---
STATE_DIR = Path(ARIZE_STATE_ROOT) / "state" / "<harness>"
ARIZE_LOG_FILE = os.environ.get("ARIZE_LOG_FILE", "/tmp/arize-<harness>.log")


def resolve_session(session_key: str = "") -> None:
    """Resolve session state based on harness-specific key.

    Implement based on how the harness identifies sessions.
    Claude uses PID-based keys; Codex uses thread-id from the event payload.
    """
    if not session_key:
        session_key = generate_uuid()
    state_file = STATE_DIR / f"state_{session_key}.json"
    init_state(state_file)


def ensure_session_initialized(session_key: str = "", cwd: str = "") -> None:
    """Initialize session state if not already present."""
    if not cwd:
        cwd = os.getcwd()

    existing_sid = get_state("session_id")
    if existing_sid:
        return

    session_id = session_key or generate_uuid()
    project_name = os.environ.get("ARIZE_PROJECT_NAME", Path(cwd).name)

    set_state("session_id", session_id)
    set_state("session_start_time", str(get_timestamp_ms()))
    set_state("project_name", project_name)
    set_state("trace_count", "0")
    set_state("tool_count", "0")

    user_id = os.environ.get("ARIZE_USER_ID", "")
    if user_id:
        set_state("user_id", user_id)

    log(f"Session initialized: {session_id}")


def gc_stale_state_files(max_age_seconds: int = 86400) -> None:
    """Remove state files older than max_age_seconds.

    Implement based on how stale sessions can be detected.
    This is optional -- leave as a no-op if the harness manages its own lifecycle.
    Claude uses PID liveness checks; Codex uses file age with a 24h threshold.
    """
    import time

    now = time.time()
    for state_file in STATE_DIR.glob("state_*.json"):
        file_age = now - state_file.stat().st_mtime
        if file_age > max_age_seconds:
            state_file.unlink(missing_ok=True)
            log(f"GC: removed stale state file {state_file.name}")
```

### Step 3: Write handlers.py

Each handler module processes hook events and builds spans:

```python
"""Hook handlers for <harness> tracing."""

import json
import sys

from core.common import (
    build_span,
    send_span,
    check_requirements,
    generate_uuid,
    get_timestamp_ms,
    get_state,
)
from .adapter import resolve_session, ensure_session_initialized


def handle_event(event_name: str, payload: dict) -> None:
    """Dispatch a hook event to the appropriate handler."""
    check_requirements()
    resolve_session(payload.get("session_key", ""))
    ensure_session_initialized(payload.get("session_key", ""))

    # Build span attributes from the event payload
    attrs = {"event.name": event_name}
    user_id = get_state("user_id")
    if user_id:
        attrs["user.id"] = user_id

    span_id = generate_uuid().replace("-", "")[:16]
    trace_id = generate_uuid().replace("-", "")
    start_time = get_timestamp_ms()

    span = build_span(
        name=event_name,
        kind="INTERNAL",
        span_id=span_id,
        trace_id=trace_id,
        parent="",
        start=start_time,
        end=start_time,
        attrs=attrs,
    )
    send_span(span)
```

Hook handlers call `send_span()` which submits the span payload to the shared collector at `http://127.0.0.1:4318/v1/spans`. New harnesses should not implement direct backend export -- the collector handles Phoenix and Arize AX export for all harnesses.

### Step 4: Update install.py and pyproject.toml

- Add a `setup_<harness>()` function to `install.py` for harness-specific configuration (hooks, env files, etc.)
- The shared collector setup is handled automatically by the installer -- your harness setup function does not need to start or configure the collector
- Add CLI entry points to `pyproject.toml` if the harness needs standalone commands

### Step 5: Write a README.md

Follow the pattern in existing adapter READMEs: features, configuration table, quick setup, troubleshooting.

## Core API Reference

All functions below are Python functions in the `core.common` module. Import them with `from core.common import <function>`.

### Span Building

| Function | Signature | Description |
|----------|-----------|-------------|
| `build_span` | `(name, kind, span_id, trace_id, parent, start, end, attrs)` | Build a single OTLP span JSON payload. Uses `ARIZE_SERVICE_NAME` and `ARIZE_SCOPE_NAME`. |
| `build_multi_span` | `(*payloads)` | Batch multiple spans into one OTLP request. Each input must be a complete `build_span()` output (already wrapped with resource/scope). The function unwraps each payload to extract the inner span objects, then re-wraps all spans under a single resource/scope envelope using the current `ARIZE_SERVICE_NAME` and `ARIZE_SCOPE_NAME`. Do **not** pass raw span objects -- pass full `build_span()` outputs. |

**`build_span` parameters:**

- `name` -- Span name (e.g., `"tool_use"`, `"user_prompt"`)
- `kind` -- Span kind: `INTERNAL`, `SERVER`, `CLIENT`, `PRODUCER`, `CONSUMER`, or numeric `0-5`
- `span_id` -- 16-char hex string
- `trace_id` -- 32-char hex string
- `parent` -- Parent span ID (empty string for root spans)
- `start` -- Start time in milliseconds since epoch
- `end` -- End time in milliseconds (defaults to `start`)
- `attrs` -- Dictionary of key-value attributes (defaults to `{}`)

### Span Sending

| Function | Signature | Description |
|----------|-----------|-------------|
| `send_span` | `(span_json)` | Submit span to the shared collector at `http://127.0.0.1:4318/v1/spans`. Handles dry run and verbose modes. The collector routes to the configured backend (Phoenix or Arize AX). |
| `send_to_collector` | `(span_json)` | Low-level HTTP POST to the shared collector endpoint. Called by `send_span`. |
| `send_to_phoenix` | `(span_json)` | (Legacy fallback) Send directly to Phoenix REST API. Only used when `ARIZE_DIRECT_SEND=true` and the collector is unreachable. |
| `send_to_arize` | `(span_json)` | (Legacy fallback) Send to Arize AX via `core/send_arize.py`. Only used when `ARIZE_DIRECT_SEND=true` and the collector is unreachable. Requires `opentelemetry-proto` and `grpcio`. |
| `get_target` | `()` | (Legacy) Returns `"phoenix"`, `"arize"`, or `"none"` based on env vars. Used only by the legacy direct-send fallback path. |

### State Management

| Function | Signature | Description |
|----------|-----------|-------------|
| `init_state` | `(state_file)` | Create `STATE_DIR` and initialize the state file as empty JSON if missing. |
| `get_state` | `(key)` | Read a value from the session state file. Returns empty string if missing. |
| `set_state` | `(key, value)` | Write a key-value pair to state (with locking). |
| `del_state` | `(key)` | Remove a key from state (with locking). |
| `inc_state` | `(key)` | Atomically increment a numeric state value (with locking). |

State files are JSON, keyed per-session. Locking uses file-based advisory locks. Each adapter sets the state file path in its `resolve_session()`.

### Logging

| Function | Signature | Description |
|----------|-----------|-------------|
| `log` | `(message)` | Log to stderr and file (only when `ARIZE_VERBOSE=true`). |
| `log_always` | `(message)` | Always log to stderr and file. |
| `error` | `(message)` | Log error to stderr and file. |
| `debug_dump` | `(label, data)` | Write data to `STATE_DIR/debug/` (only when `ARIZE_TRACE_DEBUG=true`). |

### Utilities

| Function | Signature | Description |
|----------|-----------|-------------|
| `generate_uuid` | `()` | Generate a lowercase UUID via `uuid.uuid4()`. |
| `get_timestamp_ms` | `()` | Current time in milliseconds since epoch. |
| `check_requirements` | `()` | Exit if tracing disabled; create state dir. |

## Adapter Environment Variables

Each adapter sets these in its `adapter.py`:

| Variable | Purpose | Example |
|----------|---------|---------|
| `ARIZE_SERVICE_NAME` | OTLP `service.name` resource attribute | `"claude-code"`, `"codex"` |
| `ARIZE_SCOPE_NAME` | OTLP instrumentation scope name | `"arize-claude-plugin"` |
| `STATE_DIR` | Directory for per-session state files | `"$HOME/.arize/harness/state/claude-code"` |
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

Write raw span data to files for inspection:

```bash
ARIZE_TRACE_DEBUG=true <run-your-harness>
ls ~/.arize/harness/state/<harness>/debug/
```

### Log File

All adapters write to a log file by default. Tail it to watch spans in real time:

```bash
tail -f /tmp/arize-<harness>.log
```

### Running Tests

Run the full test suite with pytest:

```bash
pytest tests/
```

### Collector Control

Start, stop, or check the collector status using the CLI:

```bash
arize-collector-ctl start
arize-collector-ctl status
arize-collector-ctl stop
```

### Manual Span Test

Import the core module and build a span directly:

```python
from core.common import build_span, generate_uuid, get_timestamp_ms

span_id = generate_uuid().replace("-", "")[:16]
trace_id = generate_uuid().replace("-", "")

span = build_span(
    name="test",
    kind="INTERNAL",
    span_id=span_id,
    trace_id=trace_id,
    parent="",
    start=get_timestamp_ms(),
    end=get_timestamp_ms(),
    attrs={"test.key": "value"},
)
print(span)
```
