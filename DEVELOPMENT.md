# Development Guide

Contributor guide for adding new harness adapters and working with the shared core.

## Architecture Overview

The system has two layers:

1. **Harness adapters** — build OpenInference spans from harness-specific events (hook payloads, session lifecycle, tool calls) and submit them locally.
2. **Shared collector/exporter** — a background process at `http://127.0.0.1:4318` that receives spans from all harnesses and exports them to Phoenix or Arize AX.

Harnesses are responsible for span construction and session state. The collector is responsible for backend export, credentials, retries, and logging. New harnesses should submit spans to the collector via `POST http://127.0.0.1:4318/v1/spans` rather than implementing direct export logic. See [COLLECTOR_ARCHITECTURE.md](docs/COLLECTOR_ARCHITECTURE.md) for the full collector contract.

## Dev Setup

```bash
# Clone and install in editable mode with dev dependencies
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
pip install -e ".[dev]"

# Run tests
pytest

# Run a specific test file
pytest tests/test_common.py

# Run with verbose output
pytest -v
```

After `pip install -e .`, all CLI entry points are available in your PATH:

```bash
arize-collector-ctl status       # Check collector status
arize-config get backend.target  # Read config values
```

## Repo Structure

```
core/
  __init__.py        # Package init
  constants.py       # Single source of truth for all paths
  config.py          # YAML config helper (CLI: arize-config)
  collector.py       # Shared: background collector/exporter (stdlib HTTP + Phoenix/Arize export)
  collector_ctl.py   # Shared: collector lifecycle (CLI: arize-collector-ctl)
  common.py          # Shared: span building, sending, state, logging, IDs
  send_arize.py      # Arize AX gRPC sender (used by collector)
  hooks/
    __init__.py
    claude/
      __init__.py
      adapter.py     # Claude-specific session resolution, GC, init
      handlers.py    # One exported function per Claude Code hook event
    codex/
      __init__.py
      adapter.py     # Codex-specific session resolution, GC, event drain
      handlers.py    # Notify handler
      proxy.py       # Codex proxy script
    cursor/
      __init__.py
      adapter.py     # Cursor-specific state stack, ID generation, sanitize
      handlers.py    # 12-event dispatcher
  setup/
    claude.py        # Interactive setup wizard for Claude
    codex.py         # Interactive setup wizard for Codex
    cursor.py        # Interactive setup wizard for Cursor

claude-code-tracing/ # Claude Code CLI / Agent SDK — docs, plugin.json, skill
codex-tracing/       # OpenAI Codex CLI — docs, skill, setup script
cursor-tracing/      # Cursor IDE — docs, skill, setup script

install.sh           # Cross-platform installer (Unix/macOS)
install.bat          # Cross-platform installer (Windows)
tests/
  conftest.py        # Shared fixtures
  test_*.py          # One test file per module
pyproject.toml       # Package definition, CLI entry points, pytest config
```

## How core/ Relates to Adapters

`core/common.py` contains all logic that is identical across harnesses:

- Logging (`log`, `error`, `debug_dump`)
- Utilities (`generate_trace_id`, `generate_span_id`, `get_timestamp_ms`)
- State primitives (`init_state`, `get_state`, `set_state`, `del_state`, `inc_state`, file locking)
- Target detection (`get_target`)
- Span building (`build_span`, `build_multi_span`)
- Span sending (`send_span`, `send_to_collector`)

Each adapter module (`core/hooks/<harness>/adapter.py`) provides:

1. Adapter-specific constants (`SERVICE_NAME`, `SCOPE_NAME`, `STATE_DIR`, `LOG_FILE`)
2. Session resolution logic (Claude uses PID-based keys; Codex uses thread-id; Cursor uses conversation_id)
3. Session initialization and garbage collection

The core `build_span()` function takes `service_name` and `scope_name` parameters to fill in the OTLP resource and scope fields. Adapters pass these from their constants.

## Adding a new harness

Follow these steps to add tracing support for a new AI coding harness.

### Step 1: Create the adapter module

```
core/hooks/<harness>/
  __init__.py
  adapter.py     # Adapter-specific session resolution, GC, init
  handlers.py    # Hook entry point(s)
```

### Step 2: Write the adapter

```python
#!/usr/bin/env python3
"""Adapter for <harness> tracing."""

from pathlib import Path
from core.constants import HARNESS_STATE_DIR
from core.common import (
    generate_trace_id, generate_span_id, get_timestamp_ms,
    init_state, get_state, set_state, log
)

# --- Adapter identity ---
SERVICE_NAME = "<harness>"
SCOPE_NAME = "arize-<harness>-plugin"

# --- Adapter-specific state ---
STATE_DIR = HARNESS_STATE_DIR / "<harness>"
LOG_FILE = Path("/tmp/arize-<harness>.log")


def resolve_session(session_key: str = "") -> dict:
    """Resolve session state file based on harness-specific key."""
    if not session_key:
        session_key = generate_trace_id()[:16]
    state_file = STATE_DIR / f"state_{session_key}.yaml"
    init_state(state_file)
    return {"state_file": state_file, "session_key": session_key}


def ensure_session_initialized(state_file, session_key="", cwd=""):
    """Initialize session state if not already present."""
    existing = get_state(state_file, "session_id")
    if existing:
        return

    session_id = session_key or generate_trace_id()[:16]
    set_state(state_file, "session_id", session_id)
    set_state(state_file, "session_start_time", get_timestamp_ms())
    set_state(state_file, "trace_count", 0)
    set_state(state_file, "tool_count", 0)
    log(f"Session initialized: {session_id}")


def gc_stale_state_files():
    """Remove stale state files older than 24 hours."""
    import time
    now = time.time()
    max_age = 86400
    for f in STATE_DIR.glob("state_*.yaml"):
        age = now - f.stat().st_mtime
        if age > max_age:
            f.unlink(missing_ok=True)
            log(f"GC: removed stale state file {f.name}")
```

### Step 3: Write hook handlers

Each handler is a CLI entry point function:

```python
#!/usr/bin/env python3
"""Hook handlers for <harness>."""

import json
import sys
from core.common import build_span, send_span, error
from core.hooks.<harness>.adapter import (
    SERVICE_NAME, SCOPE_NAME, resolve_session
)


def my_hook():
    """Entry point for arize-hook-<harness>-<event>."""
    try:
        input_json = json.loads(sys.stdin.read() or "{}")
        _handle(input_json)
    except Exception as e:
        error(f"<harness> hook failed: {e}")
    # No stdout output unless the harness expects a response
```

Hook handlers call `send_span()` which submits the span payload to the shared collector at `http://127.0.0.1:4318/v1/spans`. New harnesses should not implement direct backend export — the collector handles Phoenix and Arize AX export for all harnesses.

### Step 4: Register CLI entry points

Add entry points in `pyproject.toml`:

```toml
[project.scripts]
arize-hook-<harness>-<event> = "core.hooks.<harness>.handlers:<function>"
```

### Step 5: Update install.sh / install.bat

Add a `setup_<harness>` function to `install.sh` (and the equivalent in `install.bat`) for harness-specific configuration (hooks, env files, etc.). The shared collector setup is handled automatically — your harness setup function does not need to start or configure the collector.

### Step 6: Write a README.md

Follow the pattern in existing adapter READMEs: features, configuration table, quick setup, troubleshooting. Place it in `<harness>-tracing/README.md`.

## Core API Reference

All functions below are Python functions in the `core.common` module. Import them with `from core.common import <function>`.

### Span Building

| Function | Description |
|----------|-------------|
| `build_span(name, kind, span_id, trace_id, parent, start, end, attrs)` | Build a single OTLP span JSON payload |
| `build_multi_span(*payloads)` | Batch multiple spans into one OTLP request |

### Span Sending

| Function | Description |
|----------|-------------|
| `send_span(span_json)` | Submit span to the shared collector at `http://127.0.0.1:4318/v1/spans` |
| `send_to_collector(span_json)` | Low-level HTTP POST to the shared collector endpoint |

### State Management

| Function | Description |
|----------|-------------|
| `init_state(state_file)` | Create state directory and initialize state file if missing |
| `get_state(state_file, key)` | Read a value from the session state file |
| `set_state(state_file, key, value)` | Write a key-value pair to state (with file locking) |
| `del_state(state_file, key)` | Remove a key from state (with file locking) |
| `inc_state(state_file, key)` | Atomically increment a numeric state value (with file locking) |

State files use YAML format (`yaml.safe_load`/`yaml.safe_dump`). File locking uses `fcntl.flock` on Unix, `msvcrt.locking` on Windows, wrapped in a cross-platform helper.

### Logging

| Function | Description |
|----------|-------------|
| `log(message)` | Log to file/stderr (only when `ARIZE_VERBOSE=true`) |
| `error(message)` | Always log error to file/stderr |
| `debug_dump(label, data)` | Write YAML data to debug dir (only when `ARIZE_TRACE_DEBUG=true`) |

### Utilities

| Function | Description |
|----------|-------------|
| `generate_trace_id()` | Generate a 32-hex trace ID via `os.urandom(16).hex()` |
| `generate_span_id()` | Generate a 16-hex span ID via `os.urandom(8).hex()` |
| `get_timestamp_ms()` | Current time in milliseconds via `int(time.time() * 1000)` |
| `deterministic_trace_id(value)` | MD5-based deterministic trace ID via `hashlib.md5` |

## CLI Entry Points

After `pip install .`, the following commands are available:

| Command | Module | Description |
|---------|--------|-------------|
| `arize-collector-ctl` | `core.collector_ctl:main` | Collector lifecycle: start/stop/status/ensure |
| `arize-config` | `core.config:main` | Config helper: get/set values in config.yaml |
| `arize-hook-session-start` | `core.hooks.claude.handlers:session_start` | Claude SessionStart hook |
| `arize-hook-pre-tool-use` | `core.hooks.claude.handlers:pre_tool_use` | Claude PreToolUse hook |
| `arize-hook-post-tool-use` | `core.hooks.claude.handlers:post_tool_use` | Claude PostToolUse hook |
| `arize-hook-user-prompt-submit` | `core.hooks.claude.handlers:user_prompt_submit` | Claude UserPromptSubmit hook |
| `arize-hook-stop` | `core.hooks.claude.handlers:stop` | Claude Stop hook |
| `arize-hook-subagent-stop` | `core.hooks.claude.handlers:subagent_stop` | Claude SubagentStop hook |
| `arize-hook-notification` | `core.hooks.claude.handlers:notification` | Claude Notification hook |
| `arize-hook-permission-request` | `core.hooks.claude.handlers:permission_request` | Claude PermissionRequest hook |
| `arize-hook-session-end` | `core.hooks.claude.handlers:session_end` | Claude SessionEnd hook |
| `arize-hook-codex-notify` | `core.hooks.codex.handlers:notify` | Codex notify hook |
| `arize-codex-proxy` | `core.hooks.codex.proxy:main` | Codex proxy script |
| `arize-hook-cursor` | `core.hooks.cursor.handlers:main` | Cursor 12-event dispatcher |

## Testing

Tests use pytest and live in the top-level `tests/` directory. One test file per module:

```bash
pytest                          # Run all tests
pytest tests/test_common.py     # Run specific test file
pytest -v                       # Verbose output
pytest -k "test_build_span"     # Run specific test
```

### Dry Run Mode

Validate span structure without sending to any backend:

```bash
ARIZE_DRY_RUN=true ARIZE_TRACE_ENABLED=true <run-your-harness>
```

### Debug Mode

Write raw span data to files for inspection:

```bash
ARIZE_TRACE_DEBUG=true <run-your-harness>
ls ~/.arize/harness/state/<harness>/debug/
```

### Log File

All adapters write to a log file by default:

```bash
tail -f /tmp/arize-<harness>.log
```

### Collector Control

Start, stop, or check the collector status using the CLI:

```bash
arize-collector-ctl start
arize-collector-ctl status
arize-collector-ctl stop
```
