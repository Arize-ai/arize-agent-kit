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
  common.py          # Shared: state management (FileLock, StateManager), backed by YAML
  collector.py       # Shared: background collector/exporter (stdlib HTTP + Phoenix/Arize export)
  collector_ctl.py   # Shared: collector lifecycle (start/stop/status/ensure)
  config.py          # Shared: YAML config loader
  constants.py       # Shared: path constants
  send_arize.py      # Legacy: Arize AX gRPC sender (kept for ARIZE_DIRECT_SEND fallback)

claude-code-tracing/ # Claude Code CLI / Agent SDK adapter
  hooks/adapter.py   # Adapter: PID-based state, session resolution, GC
  hooks/             # 9 hook entry points (Python CLI commands)
  scripts/           # Setup scripts
  .claude-plugin/    # plugin.json for Claude Code marketplace

codex-tracing/       # OpenAI Codex CLI adapter
  hooks/adapter.py   # Adapter: thread-id state, debug_dump, multi-span
  hooks/             # Notify hook entry point (Codex uses one hook for all events)
  skills/            # setup-codex-tracing/SKILL.md
  README.md          # Codex-specific setup and usage

install.py           # Installer: shared collector setup + harness config
marketplace.json     # Claude Code marketplace listing
```

## How core/ Relates to Adapters

`core/common.py` provides the shared `FileLock` and `StateManager` classes used by all harnesses for per-session state management. `core/constants.py` defines path constants, and `core/config.py` provides YAML config loading.

Each adapter's `hooks/adapter.py` does three things:

1. Sets adapter-specific variables (`ARIZE_SERVICE_NAME`, `ARIZE_SCOPE_NAME`, `STATE_DIR`, `ARIZE_LOG_FILE`)
2. Imports shared classes from `core/common.py` and `core/constants.py`
3. Defines adapter-specific functions (session resolution, GC strategy, `ensure_session_initialized`)

The span building and sending logic uses `ARIZE_SERVICE_NAME` and `ARIZE_SCOPE_NAME` to fill in the OTLP resource and scope fields. Adapters set these before building spans.

## Adding a new harness

Follow these steps to add tracing support for a new AI coding harness.

### Step 1: Create the adapter directory

```
<harness>-tracing/
  hooks/
    adapter.py
  .claude-plugin/
    plugin.json        # If the harness supports Claude Code plugin format
  skills/
    setup-<harness>-tracing/
      SKILL.md
  README.md
```

### Step 2: Write the adapter hooks/adapter.py

```python
#!/usr/bin/env python3
"""Adapter for <harness> tracing."""

from pathlib import Path
from core.common import StateManager
from core.constants import STATE_BASE_DIR

# --- Adapter identity ---
ARIZE_SERVICE_NAME = "<harness>"
ARIZE_SCOPE_NAME = "arize-<harness>-plugin"

# --- Adapter-specific state ---
STATE_DIR = STATE_BASE_DIR / "<harness>"

def resolve_session(session_key: str = "") -> StateManager:
    """Resolve session state manager based on harness-specific key."""
    if not session_key:
        import uuid
        session_key = str(uuid.uuid4())
    state_file = STATE_DIR / f"state_{session_key}.yaml"
    lock_path = STATE_DIR / f".lock_{session_key}"
    mgr = StateManager(STATE_DIR, state_file, lock_path)
    mgr.init_state()
    return mgr

def ensure_session_initialized(mgr: StateManager, session_key: str = "", cwd: str = "") -> None:
    """Initialize session state if not already set."""
    if mgr.get("session_id"):
        return
    import uuid, time, os
    session_id = session_key or str(uuid.uuid4())
    project_name = os.environ.get("ARIZE_PROJECT_NAME", os.path.basename(cwd or os.getcwd()))
    mgr.set("session_id", session_id)
    mgr.set("session_start_time", str(int(time.time() * 1000)))
    mgr.set("project_name", project_name)
    mgr.set("trace_count", "0")
    mgr.set("tool_count", "0")
    user_id = os.environ.get("ARIZE_USER_ID", "")
    if user_id:
        mgr.set("user_id", user_id)
```

### Step 3: Write hook entry points

Each hook is a Python CLI entry point that reads JSON from stdin, resolves the session, builds an OTLP span, and submits it to the shared collector at `http://127.0.0.1:4318/v1/spans`. New harnesses should not implement direct backend export -- the collector handles Phoenix and Arize AX export for all harnesses.

### Step 4: Update install.py and marketplace.json

- Add a `setup_<harness>` function to `install.py` for harness-specific configuration (hooks, env files, etc.)
- The shared collector setup is handled automatically by `setup_shared_collector` -- your harness setup function does not need to start or configure the collector
- Add to `marketplace.json` if the harness supports the Claude Code plugin format

### Step 5: Write a README.md

Follow the pattern in existing adapter READMEs: features, configuration table, quick setup, troubleshooting.

## Core API Reference

### State Management (`core/common.py`)

| Class | Description |
|-------|-------------|
| `FileLock(lock_path, timeout)` | Cross-platform file lock (fcntl on Unix, msvcrt on Windows, mkdir fallback). Use as context manager. |
| `StateManager(state_dir, state_file, lock_path)` | Per-session key-value state backed by YAML files. |

**StateManager methods:**

| Method | Description |
|--------|-------------|
| `init_state()` | Create state directory and file. Idempotent. |
| `get(key)` | Read a value by key. Returns `None` if missing. No lock needed. |
| `set(key, value)` | Write a key-value pair (with locking). Value stored as string. |
| `delete(key)` | Remove a key (with locking). |
| `increment(key)` | Atomically increment a numeric value (with locking). |

State files are YAML, keyed per-session. Locking uses file-based locks. Each adapter sets `state_file` and `lock_path` in its `resolve_session()`.

### Collector Control (`core/collector_ctl.py`)

| Function | Description |
|----------|-------------|
| `collector_start()` | Start the collector if not already running. Returns True on success. |
| `collector_stop()` | Stop the collector. Returns "stopped". |
| `collector_status()` | Returns `("running", pid, "host:port")` or `("stopped", None, None)`. |
| `collector_ensure()` | Silent idempotent start. Suitable for hooks. |

CLI usage: `arize-collector-ctl start|stop|status`

## Adapter Constants

Each adapter must define these in its `hooks/adapter.py`:

| Variable | Purpose | Example |
|----------|---------|---------|
| `ARIZE_SERVICE_NAME` | OTLP `service.name` resource attribute | `"claude-code"`, `"codex"` |
| `ARIZE_SCOPE_NAME` | OTLP instrumentation scope name | `"arize-claude-plugin"` |
| `STATE_DIR` | Directory for per-session state files | `STATE_BASE_DIR / "claude-code"` |

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
ls ~/.arize/harness/state/<harness>/debug/
```

### Log File

All adapters write to a log file by default. Tail it to watch spans in real time:

```bash
tail -f /tmp/arize-<harness>.log
```

### Manual Span Test

Use the adapter module to build and inspect a span directly:

```python
from core.common import StateManager
from pathlib import Path
import json

mgr = StateManager(Path("/tmp/test-state"))
mgr.init_state()
# Build and inspect span payloads using the adapter's span builder
```
