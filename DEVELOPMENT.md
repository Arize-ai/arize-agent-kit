# Development Guide

Contributor guide for adding new harness adapters and working with the shared core.

## Architecture Overview

The system has two layers:

1. **Harness adapters** — build OpenInference spans from harness-specific events (hook payloads, session lifecycle, tool calls) and send them directly to the backend.
2. **Direct send** — `send_span()` in `core/common.py` sends spans directly to Phoenix (REST) or Arize AX (HTTP). Per-harness credentials are read from `harnesses.<name>.*` in config.

Harnesses are responsible for span construction and session state. The `send_span()` function handles backend export, credential resolution (from `harnesses.<name>.*` in config), retries, and logging. Codex additionally uses a lightweight buffer service (`codex_tracing/codex_buffer.py`) for native OTLP event buffering. See [TRACING_ARCHITECTURE.md](docs/TRACING_ARCHITECTURE.md) for the full architecture.

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
arize-codex-buffer status        # Check Codex buffer service status
arize-config get harnesses.claude-code.target  # Read config values
```

## Repo Structure

```
core/
  __init__.py        # Package init
  constants.py       # Single source of truth for all paths
  config.py          # YAML config helper (CLI: arize-config)
  common.py          # Shared: span building, direct send, state, logging, IDs
  setup/
    claude.py        # Interactive setup wizard for Claude
    codex.py         # Interactive setup wizard for Codex
    copilot.py       # Interactive setup wizard for Copilot
    cursor.py        # Interactive setup wizard for Cursor

claude_code_tracing/ # Claude Code CLI / Agent SDK — docs, plugin.json, skill
  hooks/
    adapter.py       # Claude-specific session resolution, GC, init
    handlers.py      # One exported function per Claude Code hook event
codex_tracing/       # OpenAI Codex CLI — docs, skill, setup script
  codex_buffer.py    # Codex-only: OTLP event buffer service (no export logic)
  codex_buffer_ctl.py # Codex buffer lifecycle (CLI: arize-codex-buffer)
  hooks/
    adapter.py       # Codex-specific session resolution, GC, event drain
    handlers.py      # Notify handler
    proxy.py         # Codex proxy script
copilot_tracing/     # GitHub Copilot — docs, skill, setup script
  hooks/
    adapter.py       # Copilot-specific session resolution, GC, init
    handlers.py      # Copilot hook handlers
cursor_tracing/      # Cursor IDE — docs, skill, setup script
  hooks/
    adapter.py       # Cursor-specific state stack, ID generation, sanitize
    handlers.py      # 12-event dispatcher

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
- Span sending (`send_span`)

Each adapter module (`<harness>_tracing/hooks/adapter.py`) provides:

1. Adapter-specific constants (`SERVICE_NAME`, `SCOPE_NAME`, `STATE_DIR`, `LOG_FILE`)
2. Session resolution logic (Claude uses PID-based keys; Codex uses thread-id; Cursor uses conversation_id)
3. Session initialization and garbage collection

The core `build_span()` function takes `service_name` and `scope_name` parameters to fill in the OTLP resource and scope fields. Adapters pass these from their constants.

## Adding a new harness

Follow these steps to add tracing support for a new AI coding harness.

### Step 1: Create the adapter module

```
<harness>_tracing/hooks/
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
from <harness>_tracing.hooks.adapter import (
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

Hook handlers call `send_span()` which sends the span payload directly to the configured backend (Phoenix REST or Arize AX HTTP). New harnesses should use `send_span()` from `core.common` rather than implementing their own export logic.

### Step 4: Register CLI entry points

Add entry points in `pyproject.toml`:

```toml
[project.scripts]
arize-hook-<harness>-<event> = "<harness>_tracing.hooks.handlers:<function>"
```

### Step 5: Update install.sh / install.bat

Add a `setup_<harness>` function to `install.sh` (and the equivalent in `install.bat`) for harness-specific configuration (hooks, env files, etc.). The direct send path is handled automatically by `send_span()` — your harness setup function does not need to start any background processes (unless your harness needs event buffering like Codex).

### Step 6: Write a README.md

Follow the pattern in existing adapter READMEs: features, configuration table, quick setup, troubleshooting. Place it in `<harness>_tracing/README.md`.

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
| `send_span(span_json)` | Send span directly to the configured backend (Phoenix REST or Arize AX HTTP) |

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
| `arize-codex-buffer` | `codex_tracing.codex_buffer_ctl:main` | Codex buffer service lifecycle: start/stop/status/ensure |
| `arize-config` | `core.config:main` | Config helper: get/set values in config.yaml |
| `arize-hook-session-start` | `claude_code_tracing.hooks.handlers:session_start` | Claude SessionStart hook |
| `arize-hook-pre-tool-use` | `claude_code_tracing.hooks.handlers:pre_tool_use` | Claude PreToolUse hook |
| `arize-hook-post-tool-use` | `claude_code_tracing.hooks.handlers:post_tool_use` | Claude PostToolUse hook |
| `arize-hook-user-prompt-submit` | `claude_code_tracing.hooks.handlers:user_prompt_submit` | Claude UserPromptSubmit hook |
| `arize-hook-stop` | `claude_code_tracing.hooks.handlers:stop` | Claude Stop hook |
| `arize-hook-subagent-stop` | `claude_code_tracing.hooks.handlers:subagent_stop` | Claude SubagentStop hook |
| `arize-hook-stop-failure` | `claude_code_tracing.hooks.handlers:stop_failure` | Claude StopFailure hook |
| `arize-hook-notification` | `claude_code_tracing.hooks.handlers:notification` | Claude Notification hook |
| `arize-hook-permission-request` | `claude_code_tracing.hooks.handlers:permission_request` | Claude PermissionRequest hook |
| `arize-hook-session-end` | `claude_code_tracing.hooks.handlers:session_end` | Claude SessionEnd hook |
| `arize-hook-codex-notify` | `codex_tracing.hooks.handlers:notify` | Codex notify hook |
| `arize-codex-proxy` | `codex_tracing.hooks.proxy:main` | Codex proxy script |
| `arize-hook-cursor` | `cursor_tracing.hooks.handlers:main` | Cursor 12-event dispatcher |

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

### Codex Buffer Service

Start, stop, or check the buffer service status using the CLI (only needed for Codex):

```bash
arize-codex-buffer start
arize-codex-buffer status
arize-codex-buffer stop
```
