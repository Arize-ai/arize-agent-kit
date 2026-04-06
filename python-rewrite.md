# Python Rewrite — Cross-platform Shell-to-Python Migration

## Context

This repo (`arize-agent-kit`) instruments AI coding harnesses (Claude Code, Codex, Cursor) and sends OpenInference spans to Phoenix or Arize AX. The entire hook and infrastructure layer is currently bash scripts (~3750 lines across 21 files), which limits the project to macOS/Linux.

The goal is to rewrite every shell script as Python, using only stdlib + PyYAML (already in the collector venv). This eliminates the `jq`, `lsof`, `uuidgen`, `nohup`, `stat`, `curl`, and `awk` dependencies and makes the project work on Windows.

### Architecture after rewrite

```
core/
  __init__.py
  constants.py     — (NEW) single source of truth for all paths
  config.py        — (exists) YAML config helper
  collector.py     — (exists) background collector server
  collector_ctl.py — (NEW) collector lifecycle: start/stop/status/ensure
  common.py        — (NEW) shared library: span building, sending, state, logging, IDs
  send_arize.py    — (exists) Arize AX gRPC sender
  hooks/
    __init__.py
    claude/
      __init__.py
      adapter.py   — Claude-specific session resolution, GC, init
      handlers.py  — one exported function per Claude Code hook event
    codex/
      __init__.py
      adapter.py   — Codex-specific session resolution, GC, event drain
      handlers.py  — notify handler
    cursor/
      __init__.py
      adapter.py   — Cursor-specific state stack, ID generation, sanitize
      handlers.py  — 12-event dispatcher

claude-code-tracing/   — documentation, plugin.json, SKILL.md, README (no Python)
codex-tracing/         — documentation, SKILL.md, README, scripts/setup.py
cursor-tracing/        — documentation, SKILL.md, README, scripts/setup.py

install.py             — (NEW) cross-platform installer
tests/
  conftest.py, fixtures/, test_*.py
pyproject.toml         — package definition, CLI entry points, pytest config
```

All Python code lives under `core/` so it's part of a single installable package. The `claude-code-tracing/`, `codex-tracing/`, `cursor-tracing/` directories remain for documentation, plugin manifests, and per-harness setup scripts — but no hook logic.

### CLI entry points

After `pip install .`, the following commands are available in the venv:

```toml
[project.scripts]
# Core tools
arize-collector-ctl = "core.collector_ctl:main"
arize-config = "core.config:main"

# Claude Code hooks (one command per event, JSON on stdin)
arize-hook-session-start = "core.hooks.claude.handlers:session_start"
arize-hook-pre-tool-use = "core.hooks.claude.handlers:pre_tool_use"
arize-hook-post-tool-use = "core.hooks.claude.handlers:post_tool_use"
arize-hook-user-prompt-submit = "core.hooks.claude.handlers:user_prompt_submit"
arize-hook-stop = "core.hooks.claude.handlers:stop"
arize-hook-subagent-stop = "core.hooks.claude.handlers:subagent_stop"
arize-hook-notification = "core.hooks.claude.handlers:notification"
arize-hook-permission-request = "core.hooks.claude.handlers:permission_request"
arize-hook-session-end = "core.hooks.claude.handlers:session_end"

# Codex hook (JSON as argv[1])
arize-hook-codex-notify = "core.hooks.codex.handlers:notify"

# Cursor hook (single dispatcher, JSON on stdin, all 12 events)
arize-hook-cursor = "core.hooks.cursor.handlers:main"
```

### Hook invocation contracts

Hook commands in settings files reference CLI entry points directly — no paths, no `python3`, no `bash`. The stdin/argv contracts are unchanged:

- **Claude Code** (`settings.json`): each event maps to its own command, JSON on stdin
  ```json
  {
    "hooks": {
      "SessionStart": [{"type": "command", "command": "arize-hook-session-start"}],
      "PreToolUse": [{"type": "command", "command": "arize-hook-pre-tool-use"}],
      "PostToolUse": [{"type": "command", "command": "arize-hook-post-tool-use"}],
      "UserPromptSubmit": [{"type": "command", "command": "arize-hook-user-prompt-submit"}],
      "Stop": [{"type": "command", "command": "arize-hook-stop"}],
      "SubagentStop": [{"type": "command", "command": "arize-hook-subagent-stop"}],
      "Notification": [{"type": "command", "command": "arize-hook-notification"}],
      "PermissionRequest": [{"type": "command", "command": "arize-hook-permission-request"}],
      "SessionEnd": [{"type": "command", "command": "arize-hook-session-end"}]
    }
  }
  ```
- **Codex** (`config.toml`): `notify = ["arize-hook-codex-notify"]`, JSON as `$1`
- **Cursor** (`hooks.json`): all events → `arize-hook-cursor`, JSON on stdin

### What stays the same

- `core/config.py` — already Python
- `core/collector.py` — already Python
- `core/send_arize.py` — already Python (used as library by collector)
- YAML config schema and file location
- OTLP JSON span format
- Collector HTTP API (`/v1/spans`, `/health`, `/drain/{id}`)

### Dependencies available

- Python stdlib (json, os, sys, time, urllib.request, subprocess, pathlib, hashlib, threading, signal, socket, fcntl/msvcrt)
- PyYAML (from collector venv) — used for all internal data storage (config, state, stacks, debug dumps)
- `json` module (stdlib) — used only for protocol-level JSON: OTLP span payloads, hook stdin/stdout parsing, HTTP bodies
- No new packages added

## Conventions

- All new Python files use `#!/usr/bin/env python3` shebang
- Use `pathlib.Path` for all file operations (cross-platform)
- Use `yaml` module for all internal data storage (state files, stack files, config)
- Use `json` module only for protocol-level JSON (OTLP span payloads, hook stdin/stdout, HTTP request/response bodies)
- Use `os.urandom(16).hex()` for trace IDs (32-hex, replaces `uuidgen | tr -d '-'`)
- Use `os.urandom(8).hex()` for span IDs (16-hex, replaces `uuidgen | tr -d '-' | cut -c1-16`)
- Use `time.time_ns()` or `int(time.time() * 1000)` for timestamps (replaces `date +%s%3N`)
- Use `urllib.request` for HTTP (replaces `curl`) — no `requests` dependency
- Use `hashlib.md5` for deterministic trace IDs (replaces `md5sum`/`md5`/`shasum`)
- Use `os.urandom` for random span IDs (replaces `od /dev/urandom`)
- Use `subprocess.Popen` for process lifecycle (replaces `nohup`, `kill`, `lsof`)
- State files use YAML (read/write with `yaml.safe_load`/`yaml.safe_dump`, consistent with config)
- File locking uses `fcntl.flock` on Unix, `msvcrt.locking` on Windows — wrap in a cross-platform helper
- Config always uses `yaml.safe_load`/`yaml.safe_dump` via `core/config.py`
- Python code imports `from core.constants import ...`, `from core.config import ...` etc. — the package is installed via `pip install .` in the venv
- CLI entry points (`arize-config`, `arize-collector-ctl`) are available in the venv's PATH after install — any remaining shell scripts or external callers use these instead of `python3 core/config.py`
- Each harness has a single `hook.py` entrypoint (replaces multiple .sh files for Claude Code, matches existing pattern for Codex/Cursor)
- Error handling: hooks must never crash the host tool — wrap main() in try/except, log errors, exit 0

### Hook logging conventions

Hooks have strict I/O rules because the host tool (Claude Code, Codex, Cursor) reads their stdout as a protocol response. Misplaced output will break the host tool.

**The golden rule: stdout is ONLY for hook responses. All logging goes to file and/or stderr.**

**Three logging levels**, matching the bash patterns:

1. **`log(msg)`** — verbose operational messages. Only written when `ARIZE_VERBOSE=true`. Used for:
   - Span sent confirmations: `log("Turn 3 sent")`, `log("afterShellExecution: span abc123 (merged)")`
   - Event processing notes: `log("Collector drain attempt => 5 events")`, `log("Ignoring event type: foo")`
   - State changes: `log("Session initialized: sess-abc123")`, `log("beforeMCPExecution: pushed state for tool=edit gen=gen-1")`
   
2. **`error(msg)`** — failures that indicate something is wrong. Always written. Used for:
   - Missing config: `error("No config.yaml found at ...")`
   - Send failures: `error("Arize gRPC send failed: ...")`
   - Missing requirements: `error("PyYAML not available")`

3. **`debug_dump(label, data)`** — detailed payload dumps for trace-level debugging. Only written when `ARIZE_TRACE_DEBUG=true`. Writes YAML files to `{STATE_DIR}/debug/{label}_{timestamp}.yaml`. Used by Codex hooks for:
   - Raw input payloads: `debug_dump("notify_thread1_turn1_raw", input_json)`
   - Intermediate processing: `debug_dump("notify_thread1_turn1_token_enrichment", token_data)`
   - Final span payloads: `debug_dump("notify_thread1_turn1_parent_span", span_dict)`

**Per-harness stdout rules:**

| Harness | stdout | stderr |
|---------|--------|--------|
| Claude Code | Nothing (hooks have no return value) | `log()`/`error()` messages |
| Codex | Nothing (notify has no return value) | `log()`/`error()` messages |
| Cursor | Permissive JSON response ONLY: `{"permission": "allow"}` for `before*` events, `{"continue": true}` for all others | All `log()`/`error()` messages redirected to `ARIZE_LOG_FILE` |

**Cursor special case**: The bash version wraps the entire dispatch in `{ ... } 2>>"$ARIZE_LOG_FILE" || true` (line 471) to ensure NO stderr leaks to the host tool. The Python version must do the same — redirect `sys.stderr` to the log file before dispatching, then print the permissive response to stdout as the last action. Even on exception, the permissive response MUST be printed.

**Implementation pattern for each hook entry point:**

```python
def session_start():
    """Entry point for arize-hook-session-start. Claude Code hook."""
    try:
        input_json = json.loads(sys.stdin.read() or "{}")
        _handle_session_start(input_json)
    except Exception as e:
        error(f"session_start hook failed: {e}")
    # No stdout output — Claude Code doesn't expect a response

def main():
    """Entry point for arize-hook-cursor. Cursor hook."""
    # Redirect stderr to log file BEFORE any processing
    try:
        log_fd = open(env.log_file, "a")
        sys.stderr = log_fd
    except OSError:
        pass  # if log file can't be opened, stderr stays as-is

    event = ""
    try:
        input_json = json.loads(sys.stdin.read() or "{}")
        event = input_json.get("hook_event_name", "")
        _dispatch(event, input_json)
    except Exception as e:
        error(f"cursor hook failed ({event}): {e}")
    finally:
        # ALWAYS print permissive response, even on error
        response = '{"permission": "allow"}' if event.startswith("before") else '{"continue": true}'
        sys.stdout.write(response)
        sys.stdout.flush()

def notify():
    """Entry point for arize-hook-codex-notify. Codex hook."""
    try:
        input_json = json.loads(sys.argv[1] if len(sys.argv) > 1 else "{}")
        _handle_notify(input_json)
    except Exception as e:
        error(f"codex notify hook failed: {e}")
    # No stdout output — Codex doesn't expect a response
```

- Tests use pytest, one test file per module, in a top-level `tests/` directory
- Tests mock file I/O and HTTP where needed, but test real JSON/span building logic
- Test filenames mirror source: `core/common.py` → `tests/test_common.py`

## Task: Project structure and constants
Files: pyproject.toml (new), core/__init__.py (new), core/constants.py (new), core/hooks/__init__.py (new), core/hooks/claude/__init__.py (new), core/hooks/codex/__init__.py (new), core/hooks/cursor/__init__.py (new), tests/__init__.py (new), tests/conftest.py (new), tests/fixtures/ (new dir)

Set up the Python package structure, constants file, and test infrastructure so all subsequent tasks have a stable foundation.

### Implementation

**`pyproject.toml`** — minimal package definition at repo root:

```toml
[project]
name = "arize-agent-kit"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = ["pyyaml"]

[project.optional-dependencies]
dev = ["pytest", "pytest-timeout"]
arize = ["opentelemetry-proto", "grpcio"]

[project.scripts]
# Core tools
arize-collector-ctl = "core.collector_ctl:main"
arize-config = "core.config:main"
# Claude Code hooks
arize-hook-session-start = "core.hooks.claude.handlers:session_start"
arize-hook-pre-tool-use = "core.hooks.claude.handlers:pre_tool_use"
arize-hook-post-tool-use = "core.hooks.claude.handlers:post_tool_use"
arize-hook-user-prompt-submit = "core.hooks.claude.handlers:user_prompt_submit"
arize-hook-stop = "core.hooks.claude.handlers:stop"
arize-hook-subagent-stop = "core.hooks.claude.handlers:subagent_stop"
arize-hook-notification = "core.hooks.claude.handlers:notification"
arize-hook-permission-request = "core.hooks.claude.handlers:permission_request"
arize-hook-session-end = "core.hooks.claude.handlers:session_end"
# Codex hook
arize-hook-codex-notify = "core.hooks.codex.handlers:notify"
# Cursor hook
arize-hook-cursor = "core.hooks.cursor.handlers:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: marks tests as slow (deselect with '-m \"not slow\"')"]

[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.setuptools.packages.find]
include = ["core*"]
```

The `[project.scripts]` entries create platform-native CLI commands in the venv:
- On Unix: executable scripts in `~/.arize/harness/venv/bin/`
- On Windows: `.exe` wrappers in `~/.arize/harness/venv/Scripts/`

All hook logic lives under `core/` so it's part of the installable package. The installer runs `pip install .` into the collector venv, making `core` importable and installing all CLI entry points. Hook registrations in `settings.json` / `config.toml` / `hooks.json` reference the CLI command names directly — no paths, no interpreter, fully cross-platform.

**`core/__init__.py`** — empty file (package marker).

**`core/constants.py`** — single source of truth for all filesystem paths. Every other module imports from here. None of these paths should appear as string literals anywhere else in the codebase.

```python
#!/usr/bin/env python3
"""Single source of truth for all filesystem paths used by arize-agent-kit.

Every module that needs a path imports it from here. Tests monkeypatch these
values via the tmp_harness_dir fixture to avoid touching the real filesystem.
"""
from pathlib import Path

# --- Base layout ---
BASE_DIR = Path.home() / ".arize" / "harness"
CONFIG_FILE = BASE_DIR / "config.yaml"

# --- Collector runtime ---
PID_DIR = BASE_DIR / "run"
PID_FILE = PID_DIR / "collector.pid"
LOG_DIR = BASE_DIR / "logs"
COLLECTOR_LOG_FILE = LOG_DIR / "collector.log"
BIN_DIR = BASE_DIR / "bin"
COLLECTOR_BIN = BIN_DIR / "arize-collector"
VENV_DIR = BASE_DIR / "venv"

# --- Per-harness state ---
STATE_BASE_DIR = BASE_DIR / "state"

# --- Collector network defaults ---
DEFAULT_COLLECTOR_HOST = "127.0.0.1"
DEFAULT_COLLECTOR_PORT = 4318

# --- Harness metadata ---
# Used by adapters to look up service_name, scope_name, state_subdir, etc.
# Keys match the harness names used in config.yaml harnesses section.
HARNESSES = {
    "claude-code": {
        "service_name": "claude-code",
        "scope_name": "arize-claude-plugin",
        "default_project_name": "claude-code",
        "state_subdir": "claude-code",
        "default_log_file": Path("/tmp/arize-claude-code.log"),
    },
    "codex": {
        "service_name": "codex",
        "scope_name": "arize-codex-plugin",
        "default_project_name": "codex",
        "state_subdir": "codex",
        "default_log_file": Path("/tmp/arize-codex.log"),
    },
    "cursor": {
        "service_name": "cursor",
        "scope_name": "arize-cursor-plugin",
        "default_project_name": "cursor",
        "state_subdir": "cursor",
        "default_log_file": Path("/tmp/arize-cursor.log"),
    },
}
```

**`tests/__init__.py`** — empty file.

**`tests/conftest.py`** — shared fixtures used by every test file:

```python
"""Shared pytest fixtures for arize-agent-kit tests."""
import json
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import pytest
import yaml

# Ensure repo root is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def tmp_harness_dir(tmp_path, monkeypatch):
    """Create the full ~/.arize/harness directory tree in a temp location.

    Monkeypatches core.constants so all code sees the temp paths.
    Returns the base directory Path.
    """
    base = tmp_path / ".arize" / "harness"
    for subdir in ["bin", "run", "logs",
                    "state/claude-code", "state/codex", "state/cursor"]:
        (base / subdir).mkdir(parents=True)

    import core.constants as c
    monkeypatch.setattr(c, "BASE_DIR", base)
    monkeypatch.setattr(c, "CONFIG_FILE", base / "config.yaml")
    monkeypatch.setattr(c, "PID_DIR", base / "run")
    monkeypatch.setattr(c, "PID_FILE", base / "run" / "collector.pid")
    monkeypatch.setattr(c, "LOG_DIR", base / "logs")
    monkeypatch.setattr(c, "COLLECTOR_LOG_FILE", base / "logs" / "collector.log")
    monkeypatch.setattr(c, "BIN_DIR", base / "bin")
    monkeypatch.setattr(c, "COLLECTOR_BIN", base / "bin" / "arize-collector")
    monkeypatch.setattr(c, "VENV_DIR", base / "venv")
    monkeypatch.setattr(c, "STATE_BASE_DIR", base / "state")
    return base


@pytest.fixture
def sample_config(tmp_harness_dir):
    """Write a known-good config.yaml into the temp harness dir.

    Returns the config dict.
    """
    config = {
        "collector": {"host": "127.0.0.1", "port": 4318},
        "backend": {
            "target": "phoenix",
            "phoenix": {"endpoint": "http://localhost:6006", "api_key": ""},
            "arize": {"endpoint": "otlp.arize.com:443", "api_key": "", "space_id": ""},
        },
        "harnesses": {
            "claude-code": {"project_name": "claude-code"},
            "codex": {"project_name": "codex"},
            "cursor": {"project_name": "cursor"},
        },
    }
    config_path = tmp_harness_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f)
    return config


class _CollectorHandler(BaseHTTPRequestHandler):
    """Minimal mock HTTP handler that records POSTed spans."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server._received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence request logging in test output


@pytest.fixture
def mock_collector():
    """Start a real HTTP server on a random port.

    Accepts POST /v1/spans (records body) and GET /health (returns 200).
    Yields dict: {"url": "http://127.0.0.1:{port}", "received": [...], "port": int}
    Server is torn down after the test.
    """
    server = HTTPServer(("127.0.0.1", 0), _CollectorHandler)
    server._received = []
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"url": f"http://127.0.0.1:{port}", "received": server._received, "port": port}
    server.shutdown()


@pytest.fixture
def capture_log(tmp_path):
    """Provide a temp log file and a reader function.

    Returns (log_file_path, read_log_fn). read_log_fn() returns list of lines.
    """
    log_file = tmp_path / "test.log"
    def read_log():
        return log_file.read_text().splitlines() if log_file.exists() else []
    return log_file, read_log


def load_fixture(name: str):
    """Load a JSON fixture file from tests/fixtures/ by filename.

    Returns parsed dict/list.
    """
    fixture_path = Path(__file__).parent / "fixtures" / name
    return json.loads(fixture_path.read_text())
```

**Hook package `__init__.py` files** — empty files in:
- `core/hooks/__init__.py`
- `core/hooks/claude/__init__.py`
- `core/hooks/codex/__init__.py`
- `core/hooks/cursor/__init__.py`

**`tests/fixtures/`** directory with skeleton files:
- `tests/fixtures/README.md` — "Sample payloads for hook tests. Add .json files as needed."
- `tests/fixtures/claude_session_start.json`:
  ```json
  {"session_id": "sess-abc123", "cwd": "/home/user/project"}
  ```
- `tests/fixtures/claude_stop.json`:
  ```json
  {"session_id": "sess-abc123", "transcript_path": "/tmp/transcript.jsonl"}
  ```
- `tests/fixtures/codex_notify.json`:
  ```json
  {"type": "agent-turn-complete", "thread-id": "thread-1", "turn-id": "turn-1", "cwd": "/home/user/project", "input-messages": [{"role": "user", "content": "hello"}], "last-assistant-message": "I can help with that."}
  ```
- `tests/fixtures/cursor_before_submit.json`:
  ```json
  {"hook_event_name": "beforeSubmitPrompt", "conversation_id": "conv-1", "generation_id": "gen-1", "prompt": "fix the bug"}
  ```
- `tests/fixtures/cursor_after_shell.json`:
  ```json
  {"hook_event_name": "afterShellExecution", "conversation_id": "conv-1", "generation_id": "gen-1", "command": "ls -la", "output": "total 0", "exit_code": "0"}
  ```
- `tests/fixtures/sample_transcript.jsonl` (one JSON object per line):
  ```
  {"type": "user", "message": {"role": "user", "content": "fix the bug"}}
  {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "I found the issue."}], "model": "claude-sonnet-4-20250514", "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5}}}
  {"type": "tool_use", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Edit", "input": {"file": "main.py"}}]}}
  ```

### Expected behavior

- `pip install -e ".[dev]"` from repo root makes `core` importable and installs pytest
- `pytest tests/ --collect-only` discovers test files
- `from core.constants import BASE_DIR, CONFIG_FILE, PID_FILE` works
- `tmp_harness_dir` fixture creates complete isolated directory tree
- `mock_collector` starts a real HTTP server, records POSTed spans
- No test touches `~/.arize` or any real system state
- `load_fixture("codex_notify.json")` returns the parsed dict

### Test plan

- `tests/test_constants.py`:
  - Test: all paths in constants.py are `Path` objects
  - Test: `BASE_DIR` ends with `.arize/harness`
  - Test: `CONFIG_FILE` ends with `config.yaml`
  - Test: `HARNESSES` dict has entries for `claude-code`, `codex`, `cursor`
  - Test: each harness entry has `service_name`, `scope_name`, `state_subdir`, `default_log_file`
- Fixture verification (in any test file):
  - Test: `tmp_harness_dir` creates `bin/`, `run/`, `logs/`, `state/claude-code/`, `state/codex/`, `state/cursor/`
  - Test: `sample_config` writes valid YAML that round-trips through `yaml.safe_load`
  - Test: `mock_collector` accepts POST and records body, responds 200 to GET /health
  - Test: `load_fixture` returns parsed dict for each fixture file

---

## Task: Core library — collector_ctl.py
Files: core/collector_ctl.py (new), tests/test_collector_ctl.py (new)
Depends: project-structure-and-constants

Rewrite `core/collector_ctl.sh` (147 lines) as a Python module providing collector lifecycle management.

### Implementation

Import all paths from `core.constants` — never hardcode path strings. Import `load_config`/`get_value` from `core.config` for reading host/port from config.yaml.

**Helper: `_is_process_alive(pid: int) -> bool`**:
- Unix: `os.kill(pid, 0)` — returns True if no exception, False on `OSError`
- Windows: `ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)` — returns True if handle is non-zero (close handle after), or fall back to `subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True)` and check output
- Use `os.name == "nt"` to branch

**Helper: `_resolve_host_port() -> tuple[str, int]`**:
- Try `load_config()` → `get_value(cfg, "collector.host")` / `get_value(cfg, "collector.port")`
- Fall back to `DEFAULT_COLLECTOR_HOST` / `DEFAULT_COLLECTOR_PORT` from constants
- Returns `(host: str, port: int)`

**`collector_status() -> tuple[str, int | None, str | None]`**:
```
Returns: ("running", pid, "host:port") or ("stopped", None, None)
```
1. If `PID_FILE` doesn't exist → `("stopped", None, None)`
2. Read PID from file, parse as int. If parse fails → remove file → `("stopped", None, None)`
3. If `_is_process_alive(pid)` is False → remove stale PID file → `("stopped", None, None)`
4. Resolve host/port via `_resolve_host_port()`
5. HTTP health check: `urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2)`
6. If health OK → `("running", pid, f"{host}:{port}")`
7. If health fails but process alive → `("running", pid, f"{host}:{port}")` (benefit of the doubt — matches bash behavior at collector_ctl.sh line 46)

**`collector_start() -> bool`**:
```
Returns: True if collector is running after this call, False on failure.
```
1. Call `collector_status()`. If already `"running"` → return True (idempotent)
2. Check `CONFIG_FILE.is_file()`. If not → log error "No config.yaml found at {CONFIG_FILE}", return False
3. Find collector runtime (ordered preference):
   a. `COLLECTOR_BIN` if `COLLECTOR_BIN.is_file()` and `os.access(COLLECTOR_BIN, os.X_OK)` → cmd = `[str(COLLECTOR_BIN)]`
   b. Else: `Path(__file__).parent / "collector.py"` → cmd = `[sys.executable, str(collector_py)]`
   c. If neither exists → log error, return False
4. Resolve host/port via `_resolve_host_port()`
5. Port-in-use check: `socket.create_connection((host, port), timeout=1)`. If connects:
   - Try health check at that address. If responds → collector already running, return True
   - If no health response → port taken by something else → log error "Port {port} is already in use by another process. Set collector.port in {CONFIG_FILE} to use a different port", return False
6. Ensure directories: `PID_DIR.mkdir(parents=True, exist_ok=True)`, `LOG_DIR.mkdir(parents=True, exist_ok=True)`
7. Open log file for append: `log_fd = open(COLLECTOR_LOG_FILE, "a")`
8. Launch process:
   - Unix: `subprocess.Popen(cmd, stdout=log_fd, stderr=subprocess.STDOUT, start_new_session=True)`
   - Windows: `subprocess.Popen(cmd, stdout=log_fd, stderr=subprocess.STDOUT, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)`
9. Close `log_fd` (the child inherits the fd)
10. Poll health endpoint: 20 attempts × 0.1s sleep. If health responds → return True
11. If process still alive after timeout → return True (benefit of the doubt). Check with `_is_process_alive(proc.pid)`. If dead → log error "Failed to start collector (process exited)", return False

Note: PID file is written by `collector.py` itself (line 802 of collector.py), NOT by this module. This module waits for the health check instead.

**`collector_stop() -> str`**:
```
Returns: "stopped"
```
1. If `PID_FILE` doesn't exist → return `"stopped"`
2. Read PID, parse as int. If parse fails → remove file → return `"stopped"`
3. If `_is_process_alive(pid)`:
   - Unix: `os.kill(pid, signal.SIGTERM)`
   - Windows: `os.kill(pid, signal.SIGTERM)` (works on Python 3.9+) or fall back to `subprocess.run(["taskkill", "/PID", str(pid)])`
4. Wait for process to die: 50 attempts × 0.1s. Check `_is_process_alive(pid)` each time.
5. Remove `PID_FILE` (even if process didn't die — matches bash behavior)
6. Return `"stopped"`

**`collector_ensure() -> None`**:
```
Silent idempotent start. Catches all exceptions. Returns nothing.
Suitable for calling from hooks where failure should not block the host tool.
```
```python
def collector_ensure() -> None:
    try:
        if collector_status()[0] == "running":
            return
        collector_start()
    except Exception:
        pass
```

**CLI entrypoint** — `main()` function (called by `arize-collector-ctl` entry point and `if __name__ == "__main__"`):
- `arize-collector-ctl status` → print status line (e.g., "running (PID 1234, 127.0.0.1:4318)" or "stopped")
- `arize-collector-ctl start` → call `collector_start()`, print result
- `arize-collector-ctl stop` → call `collector_stop()`, print result
- No args or unknown arg → print usage to stderr, exit 1
- Also works as `python3 core/collector_ctl.py start` for environments where entry points aren't installed

The old `collector_ctl.sh` is NOT deleted in this task — removed in the cleanup task after all callers are migrated.

### Expected behavior

- `collector_start()` is idempotent — calling twice returns True both times
- `collector_stop()` is safe to call when already stopped
- `collector_status()` cleans up stale PID files automatically
- Port conflict gives a clear error message pointing to `config.yaml`
- Works on macOS, Linux, and Windows
- No `lsof`, `nohup`, `kill`, or `curl` — all stdlib

### Test plan

`tests/test_collector_ctl.py`:
- Test: `_is_process_alive(os.getpid())` returns True
- Test: `_is_process_alive(99999)` returns False (dead PID)
- Test: `_resolve_host_port()` with `sample_config` returns `("127.0.0.1", 4318)`
- Test: `_resolve_host_port()` without config returns defaults
- Test: `collector_status()` returns `("stopped", None, None)` when no PID file
- Test: `collector_status()` returns `("stopped", None, None)` when PID file has dead PID (write `99999` to PID file, verify it's cleaned up)
- Test: `collector_status()` returns `("stopped", None, None)` when PID file has non-numeric content
- Test: `collector_start()` returns False when config file missing
- Test: `collector_start()` detects port in use — start `mock_collector` on a port, set config to that port, call `collector_start()`, verify it detects the conflict
- Test: `collector_ensure()` doesn't raise even when config is missing
- Test: CLI entrypoint prints usage on no args (capture stderr)
- Test: CLI entrypoint `status` prints "stopped" when no collector running
- Integration test (`@pytest.mark.slow`): full start → status → stop cycle with a real `collector.py` process (requires `sample_config`, `tmp_harness_dir`)

## Task: Core library — common.py (state management)
Files: core/common.py (new, partial), tests/test_common.py (new, partial)
Depends: project-structure-and-constants

Create the state management portion of `core/common.py`, replacing the `jq`-based state functions in `core/common.sh` (lines 46-109). This provides `FileLock` (used by all state operations across the codebase) and `StateManager` (key-value state per session).

### Implementation

**`FileLock` class** — cross-platform file locking context manager. This is the shared primitive used by `StateManager`, the Cursor state stack, and any other code needing exclusive file access.

```python
class FileLock:
    """Cross-platform file lock.

    Uses fcntl.flock on Unix, msvcrt.locking on Windows.
    Falls back to mkdir-based locking if neither is available.

    Usage:
        with FileLock(Path("/path/to/.lock"), timeout=3.0):
            # exclusive access

    The lock_path can be a file or directory path:
    - fcntl/msvcrt mode: creates/opens lock_path as a file
    - mkdir fallback: creates lock_path as a directory (matches bash behavior)
    """

    def __init__(self, lock_path: Path, timeout: float = 3.0) -> None:
        self.lock_path = lock_path
        self.timeout = timeout
        self._fd = None
        self._method = None  # "fcntl", "msvcrt", or "mkdir"

    def __enter__(self) -> "FileLock":
        ...

    def __exit__(self, *args) -> None:
        ...
```

Implementation details:
- **Detect platform at import time**, not per-lock:
  ```python
  try:
      import fcntl
      _LOCK_IMPL = "fcntl"
  except ImportError:
      try:
          import msvcrt
          _LOCK_IMPL = "msvcrt"
      except ImportError:
          _LOCK_IMPL = "mkdir"
  ```
- **fcntl path**: `open(lock_path, "w")` → `fcntl.flock(fd, LOCK_EX | LOCK_NB)` in retry loop (every 0.1s up to `timeout`). On timeout: force-acquire by closing and reopening (matches bash: after 30 failed attempts, remove and recreate).
- **msvcrt path**: `open(lock_path, "w")` → `msvcrt.locking(fd, LK_NBLCK, 1)` in retry loop. Same timeout behavior.
- **mkdir fallback**: `lock_path.mkdir()` in retry loop. On timeout: `shutil.rmtree(lock_path)` → `lock_path.mkdir()` (matches bash lines 67-70: `rm -rf "$_LOCK_DIR"` then `mkdir`).
- **`__exit__`**: fcntl/msvcrt → `fcntl.flock(fd, LOCK_UN)` / close fd. mkdir → `lock_path.rmdir()` (matches bash line 77: `rmdir "$_LOCK_DIR"`).
- Lock path parent directory is created if missing: `lock_path.parent.mkdir(parents=True, exist_ok=True)`

**`StateManager` class** — YAML-file-backed key-value state with file locking. Drop-in replacement for bash `get_state`/`set_state`/`del_state`/`inc_state`/`init_state`.

```python
class StateManager:
    """Per-session key-value state backed by a YAML file.

    All values are stored as strings (matching bash behavior where jq
    reads/writes everything as string arguments via --arg).

    The state_file and lock_path are set by the adapter when resolving
    the session (e.g., state_<session_id>.yaml with .lock_<session_id>).
    """

    def __init__(self, state_dir: Path,
                 state_file: Path | None = None,
                 lock_path: Path | None = None) -> None:
        self.state_dir = state_dir
        self.state_file = state_file  # set later by adapter.resolve_session()
        self._lock_path = lock_path   # set later by adapter.resolve_session()

    def init_state(self) -> None:
        """Create state directory and file.

        If file doesn't exist → create with empty dict.
        If file exists but is corrupted → overwrite with empty dict.
        Matches bash init_state() at common.sh:49-59.
        """

    def get(self, key: str) -> str | None:
        """Read a value by key. Returns None if key missing or file missing.

        Does NOT acquire lock (read-only, matches bash get_state which
        doesn't call _lock_state).
        """

    def set(self, key: str, value: str) -> None:
        """Set a key-value pair. Acquires lock.

        Value is always stored as string (matches bash: jq --arg v "$2").
        Uses atomic write: write to .tmp.{pid} then rename.
        """

    def delete(self, key: str) -> None:
        """Remove a key. No-op if missing. Acquires lock."""

    def increment(self, key: str) -> None:
        """Increment a numeric string value. Acquires lock.

        Missing key treated as "0" → becomes "1".
        Non-numeric value treated as 0 → becomes "1".
        Matches bash inc_state() at common.sh:101-108.
        """
```

Key behaviors that must match the bash version exactly:
1. **`get()` does NOT lock** — bash `get_state` (line 80) reads without calling `_lock_state`. This is intentional: reads are non-destructive and the slight race is acceptable for the hook use case.
2. **`set()`/`delete()`/`increment()` DO lock** — bash versions all call `_lock_state` / `_unlock_state`.
3. **All values are strings** — bash `set_state` uses `jq --arg v "$2"` which always produces a string. Even numeric values like trace_count are stored as `"3"` not `3`.
4. **Atomic writes** — bash uses `tmp="${STATE_FILE}.tmp.$$"` then `mv "$tmp" "$STATE_FILE"`. Python equivalent: `Path.with_suffix(f".tmp.{os.getpid()}")` then `tmp.replace(state_file)`.
5. **Silent failure** — bash `get_state` returns `""` on any error (`|| echo ""`). `set_state` silently eats jq failures (`|| rm -f "$tmp"`). Python should match: `get()` returns `None` on error, `set()`/`delete()`/`increment()` catch and log errors but don't raise.
6. **State file is YAML** — flat key-value mapping. Example content:
   ```yaml
   session_id: sess-abc123
   session_start_time: "1711987200000"
   project_name: my-project
   trace_count: "3"
   current_trace_id: abcdef1234567890abcdef1234567890
   ```

Internal helpers:
```python
def _read_safe(self) -> dict:
    """Read state file, return {} on any error (missing, corrupt, permission)."""

def _read(self) -> dict:
    """Read state file, raise on error."""

def _write(self, data: dict) -> None:
    """Write dict to state file atomically via tmp+rename."""
```

### Expected behavior

- `StateManager` is a drop-in replacement for `get_state`/`set_state`/`del_state`/`inc_state`/`init_state`
- `FileLock` is a reusable primitive used by `StateManager` and also by the Cursor state stack in `core/hooks/cursor/adapter.py`
- File locking prevents concurrent hook invocations from corrupting state
- Silent failure on reads (return None), silent failure on writes (log and continue)
- Works on macOS, Linux, and Windows

### Test plan

`tests/test_common.py` (state management section):

**FileLock tests:**
- Test: `FileLock` acquires and releases without error on empty dir
- Test: `FileLock` blocks second acquisition from another thread, releases when first exits
- Test: `FileLock` timeout — hold lock in thread A, attempt in thread B with `timeout=0.3`, verify B waits ~0.3s then force-acquires
- Test: `FileLock` cleans up lock file/dir on `__exit__`
- Test: `FileLock` creates parent directories if missing

**StateManager tests:**
- Test: `init_state()` creates directory and `.yaml` file containing `{}`
- Test: `init_state()` recovers corrupted file (write "{{garbage" to file, call init, verify `{}`)
- Test: `init_state()` preserves valid existing file
- Test: `set("key", "val")` then `get("key")` returns `"val"`
- Test: `set("count", "42")` stores as string, `get("count")` returns `"42"` (not int)
- Test: `get("missing_key")` returns `None`
- Test: `get("any")` returns `None` when state file doesn't exist (no error)
- Test: `delete("key")` removes it; subsequent `get` returns `None`
- Test: `delete("missing")` is no-op, no error
- Test: `increment("count")` on missing key → get returns `"1"`
- Test: `increment("count")` twice → get returns `"2"`
- Test: `increment` on non-numeric value (e.g., `"abc"`) → treats as 0, get returns `"1"`
- Test: concurrent `set` from 10 threads writing different keys → all keys present, no corruption
- Test: concurrent `increment` from 10 threads on same key → final value is `"10"`
- Test: atomic write — if process "crashes" between write and rename (simulate by making tmp file read-only), state file is not corrupted

## Task: Core library — common.py (span building)
Files: core/common.py (extend), tests/test_common.py (extend)
Depends: common-logging-utilities

Add OTLP span building to `core/common.py`, replacing `build_span()` from `core/common.sh` (lines 277-317) and `build_multi_span()` from `codex-tracing/hooks/common.sh` (lines 110-145). Pure Python dict construction — no `jq`, no subprocesses.

### Implementation

**Kind mapping** — matches the `case` statement in bash (lines 292-304):

```python
# Map string kind names to OTLP SpanKind integer values.
# Case-insensitive lookup (caller passes "LLM", "TOOL", etc.)
SPAN_KIND_MAP: dict[str, int] = {
    # kind 1 = SPAN_KIND_INTERNAL (used for LLM, CHAIN, TOOL, INTERNAL in OpenInference)
    "": 1, "llm": 1, "chain": 1, "tool": 1, "internal": 1,
    "span_kind_internal": 1,
    # kind 2 = SPAN_KIND_SERVER
    "server": 2, "span_kind_server": 2,
    # kind 3 = SPAN_KIND_CLIENT
    "client": 3, "span_kind_client": 3,
    # kind 4 = SPAN_KIND_PRODUCER
    "producer": 4, "span_kind_producer": 4,
    # kind 5 = SPAN_KIND_CONSUMER
    "consumer": 5, "span_kind_consumer": 5,
    # kind 0 = SPAN_KIND_UNSPECIFIED
    "unspecified": 0, "span_kind_unspecified": 0,
}
```

If the kind is a numeric string (e.g., `"3"`), parse it as int directly (matches bash `if [[ "$kind" =~ ^[0-9]+$ ]]`). If not found in map and not numeric, default to 1.

**Attribute conversion** — matches the `jq` expression in bash (line 313):
```
jq -c '[to_entries[]|{"key":.key,"value":(
  if (.value|type)=="number" then
    (if ((.value|floor) == .value) then {"intValue":.value}
     else {"doubleValue":.value} end)
  elif (.value|type)=="boolean" then {"boolValue":.value}
  else {"stringValue":(.value|tostring)} end
)}]'
```

Python equivalent:
```python
def _to_otlp_attr_value(value) -> dict:
    """Convert a Python value to OTLP attribute value dict.

    Matches the jq type-detection logic in build_span:
    - bool → {"boolValue": v}          (check BEFORE int — bool is subclass of int in Python)
    - int → {"intValue": v}
    - float with no fractional part → {"intValue": int(v)}   (matches jq: floor == value)
    - float with fractional part → {"doubleValue": v}
    - everything else → {"stringValue": str(v)}
    """

def _attrs_to_otlp(attrs: dict) -> list[dict]:
    """Convert a flat Python dict to OTLP attribute list.

    Input:  {"session.id": "abc", "llm.token_count.prompt": 100}
    Output: [{"key": "session.id", "value": {"stringValue": "abc"}},
             {"key": "llm.token_count.prompt", "value": {"intValue": 100}}]
    """
    return [{"key": k, "value": _to_otlp_attr_value(v)} for k, v in attrs.items()]
```

Important: check `isinstance(value, bool)` BEFORE `isinstance(value, int)` because in Python `bool` is a subclass of `int`. Without this, `True` would become `{"intValue": 1}` instead of `{"boolValue": true}`.

**`build_span` function**:
```python
def build_span(
    name: str,
    kind: str,
    span_id: str,
    trace_id: str,
    parent_span_id: str,      # "" or None for root spans
    start_ms: int | str,       # milliseconds since epoch
    end_ms: int | str,         # milliseconds since epoch (defaults to start_ms if empty)
    attrs: dict,               # flat dict of span attributes
    service_name: str = "arize-agent-kit",
    scope_name: str = "arize-agent-kit",
) -> dict:
    """Build an OTLP JSON span payload.

    Returns a dict matching the exact structure produced by core/common.sh:build_span().

    Timestamp handling: start_ms and end_ms are in milliseconds. The OTLP format
    requires nanoseconds as strings. Bash appends "000000" (line 312):
        "startTimeUnixNano":"${start}000000"
    Python does the same: f"{int(start_ms)}000000"

    If end_ms is empty/None/0, defaults to start_ms (matches bash: end="${7:-$start}").
    """
```

The returned structure (matches bash heredoc at lines 306-316):
```python
{
    "resourceSpans": [{
        "resource": {
            "attributes": [
                {"key": "service.name", "value": {"stringValue": service_name}}
            ]
        },
        "scopeSpans": [{
            "scope": {"name": scope_name},
            "spans": [{
                "traceId": trace_id,
                "spanId": span_id,
                # "parentSpanId": parent_span_id,  ← only if non-empty
                "name": name,
                "kind": kind_value,
                "startTimeUnixNano": f"{int(start_ms)}000000",
                "endTimeUnixNano": f"{int(end_ms)}000000",
                "attributes": _attrs_to_otlp(attrs),
                "status": {"code": 1},
            }]
        }]
    }]
}
```

Key detail: `parentSpanId` is ONLY included if `parent_span_id` is truthy (matches bash: `[[ -n "$parent" ]] && parent_json="\"parentSpanId\": \"$parent\""`).

**`build_multi_span` function** — replaces `codex-tracing/hooks/common.sh:build_multi_span()` (lines 110-145):
```python
def build_multi_span(
    span_payloads: list[dict],
    service_name: str,
    scope_name: str,
) -> dict:
    """Merge multiple build_span() outputs into a single resourceSpans payload.

    Extracts the span object from each payload's
    resourceSpans[0].scopeSpans[0].spans[0] and combines them under
    one resource/scope envelope.

    Returns {} if no valid spans found (matches bash: echo "{}"; return 1).
    """
```

### Expected behavior

- `build_span()` returns a dict that, when serialized to JSON, matches the output of `core/common.sh:build_span()` for identical inputs
- The collector (`core/collector.py`) accepts spans from the Python builder identically to the bash builder — it reads `traceId`, `spanId`, `name`, `kind`, `startTimeUnixNano`, `endTimeUnixNano`, `attributes`, `status` from the JSON
- `build_multi_span()` merges N payloads into one with N spans, preserving all span fields
- `build_multi_span([])` returns `{}`
- Attribute type detection handles the `bool`-before-`int` edge case correctly
- Numeric kinds (passed as string "3") are parsed to int

### Test plan

`tests/test_common.py` (span building section):

**Attribute conversion tests:**
- Test: `_to_otlp_attr_value("hello")` → `{"stringValue": "hello"}`
- Test: `_to_otlp_attr_value(42)` → `{"intValue": 42}`
- Test: `_to_otlp_attr_value(3.14)` → `{"doubleValue": 3.14}`
- Test: `_to_otlp_attr_value(3.0)` → `{"intValue": 3}` (float with no fractional part, matches jq `floor == value`)
- Test: `_to_otlp_attr_value(True)` → `{"boolValue": True}` (not `{"intValue": 1}`)
- Test: `_to_otlp_attr_value(False)` → `{"boolValue": False}`
- Test: `_attrs_to_otlp({"a": "b", "c": 1})` → list with 2 entries, correct types

**Kind mapping tests:**
- Test: `"LLM"` → 1, `"llm"` → 1 (case insensitive)
- Test: `"TOOL"` → 1, `"CHAIN"` → 1, `"INTERNAL"` → 1
- Test: `"SERVER"` → 2, `"CLIENT"` → 3, `"PRODUCER"` → 4, `"CONSUMER"` → 5
- Test: `"UNSPECIFIED"` → 0
- Test: `"3"` (numeric string) → 3
- Test: `"UNKNOWN_KIND"` → 1 (default)
- Test: `""` (empty string) → 1

**build_span tests:**
- Test: basic span has correct top-level structure (`resourceSpans[0].scopeSpans[0].spans[0]`)
- Test: `parentSpanId` absent when `parent_span_id=""` or `None`
- Test: `parentSpanId` present when `parent_span_id="abc123"`
- Test: timestamp formatting — `start_ms=1711987200000` → `startTimeUnixNano="1711987200000000000"`
- Test: `end_ms` defaults to `start_ms` when passed as `""` or `None` or `0`
- Test: `service_name` and `scope_name` appear in correct positions
- Test: attributes are converted to OTLP format
- Golden test: build a span with known inputs, `json.dumps()` the output, compare against `tests/fixtures/golden_span.json`

**build_multi_span tests:**
- Test: merge 3 payloads → result has 3 spans in `resourceSpans[0].scopeSpans[0].spans`
- Test: merge 1 payload → result has 1 span (same structure as build_span but re-wrapped)
- Test: merge 0 payloads → returns `{}`
- Test: malformed payload in the middle (missing keys) → skipped, other spans preserved
- Test: `service_name` and `scope_name` from the function args are used (not from input payloads)

**`tests/fixtures/golden_span.json`** — create this fixture with a known-good span. Generate it once by running the bash `build_span` with fixed inputs:
```bash
ARIZE_SERVICE_NAME="test-service" ARIZE_SCOPE_NAME="test-scope" \
  build_span "Turn 1" "LLM" "abcdef1234567890" "0123456789abcdef0123456789abcdef" \
  "" "1711987200000" "1711987201000" '{"session.id":"sess-1","input.value":"hello"}'
```
Save the output as the golden fixture. The Python test builds the same span and compares `json.loads()` output.

## Task: Core library — common.py (span sending)
Files: core/common.py (extend), tests/test_common.py (extend)
Depends: common-span-building, common-logging-utilities

Add span sending to `core/common.py`, replacing `send_span()`, `send_to_collector()`, `send_to_phoenix()`, `send_to_arize()` from `core/common.sh` (lines 147-275).

### Implementation

**`send_to_collector(span_dict: dict, collector_url: str) -> bool`**

Replaces bash `send_to_collector` (lines 148-156). POST JSON to `{collector_url}/v1/spans`.

```python
def send_to_collector(span_dict: dict, collector_url: str) -> bool:
    """POST span JSON to the shared collector.

    Matches bash: curl -sf -X POST "${_COLLECTOR_URL}/v1/spans"
      -H "Content-Type: application/json" -d "$span_json" --max-time 5
    """
    url = f"{collector_url}/v1/spans"
    data = json.dumps(span_dict).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
```

**`send_to_phoenix(span_dict: dict, endpoint: str, api_key: str, project_name: str) -> bool`**

Replaces bash `send_to_phoenix` (lines 160-183). Transforms OTLP format to Phoenix REST format, then POSTs.

The transformation (matching the `jq` expression at lines 165-176):
```python
# For each span in resourceSpans[*].scopeSpans[*].spans[*]:
{
    "name": span["name"],
    "context": {
        "trace_id": span["traceId"],
        "span_id": span["spanId"],
    },
    "parent_id": span.get("parentSpanId", ""),
    "span_kind": "CHAIN",     # hardcoded in bash
    "start_time": iso_format(span["startTimeUnixNano"]),  # nanoseconds → ISO 8601
    "end_time": iso_format(span["endTimeUnixNano"]),
    "status_code": "OK",      # hardcoded in bash
    "attributes": {            # flatten OTLP list back to dict
        attr["key"]: first_non_null(attr["value"], keys=["stringValue", "doubleValue", "intValue", "boolValue"])
        for attr in span["attributes"]
    },
}
```

ISO format: `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(nanoseconds / 1e9))` — matches bash `jq strftime`.

POST to: `{endpoint}/v1/projects/{project_name}/spans`
Headers: `Content-Type: application/json`, plus `Authorization: Bearer {api_key}` if api_key is non-empty.

**`send_to_arize(span_dict: dict) -> bool`**

Replaces bash `send_to_arize` (lines 187-228). The bash version finds a Python interpreter with `opentelemetry` and pipes JSON to `send_arize.py`. In the Python rewrite, we import and call directly:

```python
def send_to_arize(span_dict: dict) -> bool:
    """Send spans to Arize AX via gRPC.

    Imports core.send_arize.send_to_arize_grpc() and calls it directly.
    No subprocess, no interpreter discovery (we're already in Python).
    Loads credentials from config.yaml, falls back to env vars.
    """
    try:
        from core.config import load_config
        from core.send_arize import send_to_arize_grpc

        config = load_config()
        if config:
            arize_cfg = config.get("backend", {}).get("arize", {})
            api_key = arize_cfg.get("api_key", "") or env.api_key
            space_id = arize_cfg.get("space_id", "") or env.space_id
        else:
            api_key = env.api_key
            space_id = env.space_id

        if not api_key or not space_id:
            error("ARIZE_API_KEY and ARIZE_SPACE_ID required (set in config.yaml or env)")
            return False

        return send_to_arize_grpc(span_dict, api_key, space_id)
    except ImportError:
        error("opentelemetry-proto and grpcio required for Arize AX. Install: pip install opentelemetry-proto grpcio")
        return False
    except Exception as e:
        error(f"Arize gRPC send failed: {e}")
        return False
```

This is much simpler than the bash version which had to discover a Python interpreter and manage subprocess stderr. The Python version just imports and calls.

**`send_span(span_dict: dict) -> bool`**

Main entry point. Replaces bash `send_span` (lines 231-275). Follows the same priority:

```python
def send_span(span_dict: dict) -> bool:
    """Send a span payload. Tries collector first, falls back to direct send.

    Priority (matches bash send_span exactly):
    1. ARIZE_DRY_RUN=true → log span name to stderr, return True
    2. ARIZE_VERBOSE=true → log full JSON to stderr
    3. ARIZE_DIRECT_SEND != true → try collector at env.collector_url
    4. If collector fails or ARIZE_DIRECT_SEND=true → direct send:
       a. PHOENIX_ENDPOINT set → send_to_phoenix
       b. ARIZE_API_KEY + ARIZE_SPACE_ID set → send_to_arize
       c. neither → error, return False

    Never raises. Returns True on success, False on failure.
    """
```

Span name extraction helper (used for logging):
```python
def _extract_span_name(span_dict: dict) -> str:
    """Extract the first span name from an OTLP payload. Returns 'unknown' on error."""
    try:
        return span_dict["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"]
    except (KeyError, IndexError, TypeError):
        return "unknown"
```

Dry-run output matches bash (line 236): prints each span name from the payload to stderr.
Verbose output matches bash (line 240): prints compact JSON to stderr.
Collector failure logging matches bash (lines 253-260): logs the URL that failed.

### Expected behavior

- `send_span()` is a drop-in replacement for the bash `send_span` function
- Collector path is preferred; direct send is fallback
- Dry-run mode prints span names to stderr, sends nothing
- Verbose mode prints full JSON to stderr before sending
- `send_to_arize` is dramatically simpler than bash (direct import vs subprocess discovery)
- All functions catch exceptions and return `False` — never raise
- `send_to_phoenix` transformation matches the jq expression exactly

### Test plan

`tests/test_common.py` (span sending section):

**send_to_collector tests:**
- Test: POST to `mock_collector` → returns True, span appears in `mock_collector["received"]`
- Test: verify Content-Type header is `application/json`
- Test: verify body is valid JSON matching the input dict
- Test: unreachable URL → returns False, no exception
- Test: collector returns 500 → returns False

**send_to_phoenix tests:**
- Test: transformation correctness — build a span with `build_span`, pass to `send_to_phoenix` with a `mock_collector` standing in as Phoenix, verify the POSTed payload has:
  - `data` array with one entry
  - `name`, `context.trace_id`, `context.span_id` correct
  - `span_kind` is `"CHAIN"`
  - `start_time` and `end_time` are ISO 8601 format
  - `attributes` is a flat dict (not OTLP list format)
- Test: `api_key` present → `Authorization: Bearer {key}` header sent
- Test: `api_key` empty → no Authorization header
- Test: URL is `{endpoint}/v1/projects/{project}/spans`

**send_to_arize tests:**
- Test: missing credentials → returns False, logs error
- Test: `ImportError` (opentelemetry not installed) → returns False, logs clear message

**send_span integration tests:**
- Test: dry-run mode → no HTTP calls, stderr has span name (monkeypatch `env.dry_run=True`)
- Test: verbose mode → stderr has JSON output (monkeypatch `env.verbose=True`)
- Test: collector reachable → sends to collector, returns True (use `mock_collector`, set `env.collector_url`)
- Test: collector unreachable, Phoenix configured → falls back to Phoenix (use second `mock_collector` as Phoenix, monkeypatch `env.phoenix_endpoint`)
- Test: collector unreachable, no backend → returns False, logs error
- Test: `ARIZE_DIRECT_SEND=true` → skips collector entirely, goes direct (monkeypatch `env.direct_send=True`)

**_extract_span_name tests:**
- Test: valid payload → returns span name
- Test: empty dict → returns `"unknown"`
- Test: malformed payload → returns `"unknown"`

## Task: Core library — common.py (logging and utilities)
Files: core/common.py (extend), tests/test_common.py (extend)
Depends: project-structure-and-constants, common-state-management

Add environment configuration, logging infrastructure, and ID/timestamp utilities to `core/common.py`, replacing `core/common.sh` lines 15-44 and 111-137.

### Implementation

**Environment configuration** — a module-level `Env` class that reads env vars once and resolves config-file fallbacks. This replaces the bash env-var declarations (lines 15-26) and the config-resolution blocks (lines 121-137).

```python
class Env:
    """Reads environment variables with defaults, resolves config.yaml fallbacks.

    Instantiated once at module level. All other functions in common.py
    read from this instance rather than calling os.environ directly.

    This is a class (not a plain dict) so tests can monkeypatch individual
    attributes without re-reading the real environment.
    """

    def __init__(self) -> None:
        # --- Boolean flags ---
        self.trace_enabled: bool   # ARIZE_TRACE_ENABLED, default "true"
        self.dry_run: bool         # ARIZE_DRY_RUN, default "false"
        self.verbose: bool         # ARIZE_VERBOSE, default "false"
        self.trace_debug: bool     # ARIZE_TRACE_DEBUG, default "false"
        self.direct_send: bool     # ARIZE_DIRECT_SEND, default "false"

        # --- Paths ---
        self.log_file: Path        # ARIZE_LOG_FILE, default "/tmp/arize-agent-kit.log"

        # --- Backend credentials (empty string = not set) ---
        self.api_key: str          # ARIZE_API_KEY
        self.space_id: str         # ARIZE_SPACE_ID
        self.phoenix_endpoint: str # PHOENIX_ENDPOINT
        self.phoenix_api_key: str  # PHOENIX_API_KEY

        # --- Project/user ---
        self.project_name: str     # ARIZE_PROJECT_NAME
        self.user_id: str          # ARIZE_USER_ID (env → config.yaml → "")

        # --- Collector endpoint (env → config.yaml → defaults) ---
        self.collector_host: str   # resolved host
        self.collector_port: int   # resolved port
        self.collector_url: str    # "http://{host}:{port}"
```

Resolution priority (matches bash exactly):
1. **`collector_host`**: `ARIZE_COLLECTOR_HOST` env var → `DEFAULT_COLLECTOR_HOST` from constants. (Bash line 121: no config.yaml fallback for host.)
2. **`collector_port`**: `ARIZE_COLLECTOR_PORT` env var → `config.yaml collector.port` → `DEFAULT_COLLECTOR_PORT`. (Bash lines 122-128.)
3. **`user_id`**: `ARIZE_USER_ID` env var → `config.yaml user_id` → `""`. (Bash lines 132-137.)
4. **All other env vars**: env var → default (no config.yaml fallback). Matches bash lines 16-26 exactly.

The config.yaml reads use `core.config.load_config()` and `core.config.get_value()`. If config is missing or unreadable, silently fall back to defaults (matches bash `|| true` pattern).

```python
# Module-level singleton
env = Env()
```

**Logging functions** — replacing bash lines 28-32. Thread-safe. Stdout is NEVER written to (reserved for hook responses).

```python
_log_lock = threading.Lock()

def _log_to_file(msg: str) -> None:
    """Append timestamped line to env.log_file. Thread-safe.

    Matches bash: echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$ARIZE_LOG_FILE"
    Silently ignores write errors (matches bash `|| true`).
    """

def log(msg: str) -> None:
    """Log if ARIZE_VERBOSE=true. Writes to stderr AND file.

    Matches bash: [[ "$ARIZE_VERBOSE" == "true" ]] && { echo "[arize] $*" >&2; _log_to_file "$*"; }
    """

def log_always(msg: str) -> None:
    """Always log to stderr AND file.

    Matches bash: echo "[arize] $*" >&2; _log_to_file "$*"
    """

def error(msg: str) -> None:
    """Log error to stderr AND file.

    Matches bash: echo "[arize] ERROR: $*" >&2; _log_to_file "ERROR: $*"
    """
```

Format details:
- `_log_to_file` writes: `[2026-04-03 10:30:00] {msg}\n`
- `log`/`log_always` write to stderr: `[arize] {msg}\n`
- `error` writes to stderr: `[arize] ERROR: {msg}\n`
- File format uses `time.strftime('%Y-%m-%d %H:%M:%S')` (matches bash `date '+%Y-%m-%d %H:%M:%S'`)

**ID generation** — replacing bash lines 34-39.

```python
def generate_trace_id() -> str:
    """Generate a 32-hex random trace ID.

    Replaces bash: uuidgen | tr -d '-' (with fallbacks to /proc, /dev/urandom).
    Uses os.urandom(16) — 128 bits of cryptographic randomness.
    Returns lowercase hex string, e.g., "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6".
    """
    return os.urandom(16).hex()

def generate_span_id() -> str:
    """Generate a 16-hex random span ID.

    Replaces bash: uuidgen | tr -d '-' | cut -c1-16.
    Uses os.urandom(8) — 64 bits of cryptographic randomness.
    Returns lowercase hex string, e.g., "a1b2c3d4e5f6a7b8".
    """
    return os.urandom(8).hex()

def get_timestamp_ms() -> int:
    """Current time in milliseconds since Unix epoch.

    Replaces bash: python3 -c "import time; print(int(time.time() * 1000))"
    (Yes, the bash version already shells out to Python for this.)
    """
    return int(time.time() * 1000)
```

**Target detection** — replacing bash lines 132-137 (`get_target`):

```python
def get_target() -> str:
    """Detect backend target from env vars.

    Returns "phoenix", "arize", or "none".
    Matches bash get_target() at common.sh:139-137.
    """
    if env.phoenix_endpoint:
        return "phoenix"
    if env.api_key and env.space_id:
        return "arize"
    return "none"
```

### Expected behavior

- All logging goes to file + stderr, never stdout
- `log()` is silent unless `ARIZE_VERBOSE=true`
- `error()` and `log_always()` always write
- `_log_to_file()` silently handles missing directories or permission errors
- `Env` instance reads env vars once at import; tests monkeypatch `env.verbose`, `env.collector_port`, etc.
- Collector endpoint resolution matches bash priority: env var → config.yaml → constant default
- `user_id` resolution matches bash priority: env var → config.yaml → empty string
- ID generation produces the correct lengths (32 hex, 16 hex) with no UUID formatting
- `get_timestamp_ms()` returns milliseconds, not seconds or nanoseconds

### Test plan

`tests/test_common.py` (logging/utilities section):

**Env tests:**
- Test: default `Env()` with no env vars set → `trace_enabled=True`, `dry_run=False`, `verbose=False`, `log_file=Path("/tmp/arize-agent-kit.log")`, `collector_port=4318`, `collector_host="127.0.0.1"`
- Test: `ARIZE_VERBOSE=true` in env → `env.verbose` is `True`
- Test: `ARIZE_VERBOSE=TRUE` (uppercase) → still `True` (`.lower()` comparison)
- Test: `ARIZE_COLLECTOR_PORT=9999` in env → `env.collector_port` is `9999`, config.yaml not consulted
- Test: no `ARIZE_COLLECTOR_PORT` in env, `sample_config` has `port: 4318` → `env.collector_port` is `4318`
- Test: no `ARIZE_COLLECTOR_PORT` in env, no config file → `env.collector_port` is `4318` (default)
- Test: `ARIZE_USER_ID=alice` in env → `env.user_id` is `"alice"`, config.yaml not consulted
- Test: no `ARIZE_USER_ID` in env, config has `user_id: bob` → `env.user_id` is `"bob"`
- Test: no `ARIZE_USER_ID` in env, no config → `env.user_id` is `""`
- Test: monkeypatching `env.verbose = True` then calling `log()` writes output (verifies tests can override)

**Logging tests (use `capture_log` fixture):**
- Test: `log("msg")` with `env.verbose=False` → log file empty, stderr empty
- Test: `log("msg")` with `env.verbose=True` → log file has `[timestamp] msg`, stderr has `[arize] msg`
- Test: `log_always("msg")` → always writes to file and stderr regardless of verbose
- Test: `error("oops")` → file has `[timestamp] ERROR: oops`, stderr has `[arize] ERROR: oops`
- Test: `_log_to_file("msg")` with non-existent directory for log file → no exception raised
- Test: log file timestamp format matches `YYYY-MM-DD HH:MM:SS`
- Test: thread safety — 10 threads calling `log_always()` concurrently → no interleaved lines in file

**ID generation tests:**
- Test: `generate_trace_id()` returns `str` of length 32, all chars in `0-9a-f`
- Test: `generate_span_id()` returns `str` of length 16, all chars in `0-9a-f`
- Test: two consecutive `generate_trace_id()` calls return different values
- Test: two consecutive `generate_span_id()` calls return different values

**Timestamp tests:**
- Test: `get_timestamp_ms()` returns `int`
- Test: `get_timestamp_ms()` is within 1000ms of `int(time.time() * 1000)`
- Test: two calls 100ms apart differ by approximately 100 (within ±50ms tolerance)

**Target detection tests:**
- Test: `PHOENIX_ENDPOINT=http://localhost:6006` → `get_target()` returns `"phoenix"`
- Test: `ARIZE_API_KEY=key ARIZE_SPACE_ID=space` → `get_target()` returns `"arize"`
- Test: no backend env vars → `get_target()` returns `"none"`
- Test: both Phoenix and Arize set → `get_target()` returns `"phoenix"` (Phoenix takes priority, matches bash)

## Task: Claude Code adapter
Files: core/hooks/claude/adapter.py (new), tests/test_claude_adapter.py (new)
Depends: common-logging-utilities, common-state-management

Rewrite `claude-code-tracing/hooks/common.sh` (107 lines) as a Python adapter module. This module owns Claude-specific session resolution, initialization, and garbage collection. It does NOT handle individual hook events — those are in `handlers.py`.

### Implementation

Imports:
```python
from core.constants import HARNESSES, STATE_BASE_DIR
from core.common import (
    StateManager, env, log, error, generate_trace_id,
    generate_span_id, get_timestamp_ms,
)
```

**Module-level constants** — derived from `HARNESSES["claude-code"]`:
```python
_HARNESS = HARNESSES["claude-code"]
SERVICE_NAME = _HARNESS["service_name"]       # "claude-code"
SCOPE_NAME = _HARNESS["scope_name"]           # "arize-claude-plugin"
STATE_DIR = STATE_BASE_DIR / _HARNESS["state_subdir"]  # ~/.arize/harness/state/claude-code
```

**`resolve_session(input_json: dict) -> StateManager`**

Replaces bash `resolve_session()` at lines 28-45 of `claude-code-tracing/hooks/common.sh`.

```python
def resolve_session(input_json: dict) -> StateManager:
    """Resolve the per-session state file from hook input JSON.

    Priority for session key (matches bash lines 31-44):
    1. input_json["session_id"] — if present and non-empty
    2. CLAUDE_SESSION_KEY env var — if set
    3. Grandparent PID — Claude Code spawns: claude(grandparent) → node(parent) → bash(hook).
       In Python the hook IS the child process, so os.getppid() gives the parent,
       and we need the parent's parent.

    Returns a StateManager instance with state_file and lock_path set.
    Calls init_state() to ensure the file exists.
    """
```

PID derivation detail: The bash version uses `ps -o ppid= -p "$PPID"` to get the grandparent PID (line 17). This is Unix-specific. In Python:
- Unix: `os.getppid()` gives parent PID. To get grandparent, read `/proc/{ppid}/stat` on Linux or use `subprocess.check_output(["ps", "-o", "ppid=", "-p", str(os.getppid())])`. 
- Windows: grandparent PID discovery is more complex. Use `os.getppid()` as the session key directly — it won't match the bash behavior exactly, but the PID is only used as a unique key for state file naming, not for process management.
- Cross-platform fallback: use `os.getppid()` as the session key. Document that this differs from bash (which uses grandparent PID).

State file naming: `STATE_DIR / f"state_{session_key}.yaml"` with lock at `STATE_DIR / f".lock_{session_key}"`.

**`ensure_session_initialized(state: StateManager, input_json: dict) -> None`**

Replaces bash `ensure_session_initialized()` at lines 50-85.

```python
def ensure_session_initialized(state: StateManager, input_json: dict) -> None:
    """Idempotent session initialization. No-op if session_id already in state.

    Sets the following state keys (matching bash lines 71-82):
    - session_id: from input_json or generate_trace_id()
    - session_start_time: get_timestamp_ms() as string
    - project_name: from ARIZE_PROJECT_NAME env, or basename of input_json["cwd"], or cwd
    - trace_count: "0"
    - tool_count: "0"
    - user_id: from env.user_id, then input_json["user_id"], then ""
    """
```

Key behaviors matching bash:
1. Check `state.get("session_id")` first — if non-None, return immediately (line 56)
2. `session_id` comes from `input_json.get("session_id")` or `generate_trace_id()` (line 62)
3. `project_name` priority: `env.project_name` → `os.path.basename(input_json.get("cwd", ""))` → `os.path.basename(os.getcwd())` (lines 64-68)
4. `user_id` priority: `env.user_id` → `input_json.get("user_id", "")` (lines 78-82)

**`gc_stale_state_files() -> None`**

Replaces bash `gc_stale_state_files()` at lines 89-100.

```python
def gc_stale_state_files() -> None:
    """Remove state files for PIDs that are no longer running.

    Only cleans numeric (PID-based) filenames: state_12345.yaml
    Skips non-numeric session keys: state_sess-abc123.yaml
    Matches bash lines 90-99.
    """
    for f in STATE_DIR.glob("state_*.yaml"):
        # Extract key from filename: state_12345.yaml → "12345"
        key = f.stem.replace("state_", "")
        # Only GC numeric keys (PID-based)
        if not key.isdigit():
            continue
        pid = int(key)
        # Check if process is alive
        if not _is_pid_alive(pid):
            f.unlink(missing_ok=True)
            lock_dir = STATE_DIR / f".lock_{key}"
            if lock_dir.is_dir():
                lock_dir.rmdir()  # rmdir only works on empty dirs, matches bash
```

`_is_pid_alive(pid)`: `os.kill(pid, 0)` on Unix (catch `OSError`), platform check on Windows.

**`check_requirements() -> bool`**

Replaces bash `check_requirements()` at lines 103-107.

```python
def check_requirements() -> bool:
    """Check if tracing is enabled and initialize state.

    Returns False (and the hook should exit 0) if tracing is disabled.
    Matches bash: [[ "$ARIZE_TRACE_ENABLED" != "true" ]] && exit 0
    """
    if not env.trace_enabled:
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return True
```

Note: the bash version also checks `command -v jq` (line 105). The Python version doesn't need this since we no longer depend on `jq`.

### Expected behavior

- `resolve_session()` returns a `StateManager` with the correct state file path based on session_id or PID
- `ensure_session_initialized()` is idempotent — calling twice with the same input writes state only once
- `ensure_session_initialized()` writes exactly the same state keys as the bash version
- `gc_stale_state_files()` only removes PID-based files, never session-id-based files
- `check_requirements()` returns False when tracing disabled, True otherwise
- All functions are cross-platform (PID-based GC degrades gracefully on Windows)

### Test plan

`tests/test_claude_adapter.py`:

**resolve_session tests:**
- Test: input with `session_id: "sess-abc"` → state file is `state_sess-abc.yaml`
- Test: input without `session_id`, `CLAUDE_SESSION_KEY=custom-key` in env → state file is `state_custom-key.yaml`
- Test: input without `session_id`, no env var → state file uses PID-based key (`state_{ppid}.yaml`)
- Test: returned `StateManager` has `init_state()` called (state file exists and contains `{}`)
- Test: calling `resolve_session` twice with same input returns `StateManager` pointing to same file

**ensure_session_initialized tests:**
- Test: first call sets all expected keys (`session_id`, `session_start_time`, `project_name`, `trace_count`, `tool_count`, `user_id`)
- Test: second call with same state is no-op (values unchanged, especially `session_start_time`)
- Test: `session_id` from input is used when present
- Test: `session_id` is generated when not in input (32-hex format)
- Test: `project_name` from `env.project_name` takes priority over `cwd`
- Test: `project_name` from `input_json["cwd"]` → basename extracted (e.g., `/home/user/my-project` → `my-project`)
- Test: `user_id` from `env.user_id` takes priority over `input_json["user_id"]`
- Test: `user_id` from `input_json` used when env is empty
- Test: `trace_count` starts at `"0"`, `tool_count` starts at `"0"`

**gc_stale_state_files tests:**
- Test: state file `state_99999.yaml` (dead PID) → removed
- Test: state file `state_{os.getpid()}.yaml` (live PID) → kept
- Test: state file `state_sess-abc123.yaml` (non-numeric key) → kept (not GC'd)
- Test: associated lock dir `.lock_99999` → removed when state file removed
- Test: empty STATE_DIR → no errors

**check_requirements tests:**
- Test: `env.trace_enabled=True` → returns True, STATE_DIR created
- Test: `env.trace_enabled=False` → returns False, STATE_DIR not created

## Task: Claude Code hook handlers
Files: core/hooks/claude/handlers.py (new), tests/test_claude_hook.py (new)
Depends: claude-code-adapter, common-span-building, common-span-sending

Rewrite all 9 Claude Code hook scripts as exported handler functions in a single module. Each function is a CLI entry point via `pyproject.toml [project.scripts]`. The module has no module-level side effects — all setup happens inside each function.

### Implementation

**Module structure:**

```python
"""Claude Code hook handlers. One exported function per hook event."""
import json
import os
import sys
from pathlib import Path

from core.hooks.claude.adapter import (
    resolve_session, ensure_session_initialized,
    gc_stale_state_files, check_requirements,
    SERVICE_NAME, SCOPE_NAME,
)
from core.common import (
    build_span, send_span, log, log_always, error, _log_to_file,
    generate_trace_id, generate_span_id, get_timestamp_ms, env,
)
from core.collector_ctl import collector_ensure
```

**Shared pattern** — every exported function follows this shape (matching hook logging conventions):

```python
def session_start():
    """Entry point for arize-hook-session-start. Claude Code hook."""
    try:
        input_json = json.loads(sys.stdin.read() or "{}")
        _handle_session_start(input_json)
    except Exception as e:
        error(f"session_start hook failed: {e}")
    # No stdout — Claude Code doesn't expect a response
```

The internal `_handle_*` functions contain the actual logic. This separation makes testing easier — tests call `_handle_*` directly with prepared input, without needing to mock stdin.

---

**`_handle_session_start(input_json: dict)`** — replaces `session_start.sh` (24 lines)

```
1. collector_ensure()  — ensure background collector is running
2. state = resolve_session(input_json)
3. ensure_session_initialized(state, input_json)
4. log(f"Session started: {state.get('session_id')}")
```

That's it — this is the simplest handler.

---

**`_handle_pre_tool_use(input_json: dict)`** — replaces `pre_tool_use.sh` (15 lines)

```
1. state = resolve_session(input_json)
2. tool_id = input_json.get("tool_use_id") or generate_trace_id()
3. state.set(f"tool_{tool_id}_start", str(get_timestamp_ms()))
```

Records the start timestamp keyed by tool_use_id so `post_tool_use` can compute duration.

---

**`_handle_post_tool_use(input_json: dict)`** — replaces `post_tool_use.sh` (91 lines)

The most complex non-transcript handler. Builds a TOOL span with structured metadata.

```
1. state = resolve_session(input_json)
2. session_id = state.get("session_id")  — exit if None
3. trace_id = state.get("current_trace_id")
4. parent_span_id = state.get("current_trace_span_id")
5. state.increment("tool_count")

6. Extract fields from input_json:
   - tool_name: input_json.get("tool_name", "unknown")
   - tool_id: input_json.get("tool_use_id", "")
   - tool_input_raw: json.dumps(input_json.get("tool_input", {}))
   - tool_input: tool_input_raw[:5000]
   - tool_response: str(input_json.get("tool_response", ""))[:5000]

7. Truncation tracking:
   - tool_input_truncated = len(tool_input_raw) > 5000
   - tool_response_truncated = len(raw_response) > 5000
   - truncated = str(tool_input_truncated or tool_response_truncated).lower()

8. Tool-specific metadata extraction (matches bash case statement, lines 40-65):
   tool_description = ""
   tool_command = tool_file_path = tool_url = tool_query = ""

   if tool_name == "Bash":
       tool_command = input_json.get("tool_input", {}).get("command", "")
       tool_description = tool_command[:200]
   elif tool_name in ("Read", "Write", "Edit", "Glob"):
       tool_file_path = input_json.get("tool_input", {}).get("file_path")
                     or input_json.get("tool_input", {}).get("pattern", "")
       tool_description = tool_file_path[:200]
   elif tool_name == "WebSearch":
       tool_query = input_json.get("tool_input", {}).get("query", "")
       tool_description = tool_query[:200]
   elif tool_name == "WebFetch":
       tool_url = input_json.get("tool_input", {}).get("url", "")
       tool_description = tool_url[:200]
   elif tool_name == "Grep":
       tool_query = input_json.get("tool_input", {}).get("pattern", "")
       tool_file_path = input_json.get("tool_input", {}).get("path", "")
       tool_description = f"grep: {tool_query[:100]}"
   else:
       tool_description = tool_input[:200]

9. Timing:
   start_time = state.get(f"tool_{tool_id}_start") or str(get_timestamp_ms())
   end_time = str(get_timestamp_ms())
   state.delete(f"tool_{tool_id}_start")

10. Build attrs dict:
    attrs = {
        "session.id": session_id,
        "openinference.span.kind": "tool",
        "tool.name": tool_name,
        "input.value": tool_input,
        "output.value": tool_response,
        "tool.description": tool_description,
        "tool.truncated": truncated,
    }
    # Conditional attributes (only if non-empty):
    if user_id: attrs["user.id"] = user_id
    if tool_command: attrs["tool.command"] = tool_command
    if tool_file_path: attrs["tool.file_path"] = tool_file_path
    if tool_url: attrs["tool.url"] = tool_url
    if tool_query: attrs["tool.query"] = tool_query

11. span = build_span(tool_name, "TOOL", span_id, trace_id, parent_span_id,
                      start_time, end_time, attrs, SERVICE_NAME, SCOPE_NAME)
12. send_span(span)
```

---

**`_handle_user_prompt_submit(input_json: dict)`** — replaces `user_prompt_submit.sh` (57 lines)

Critical handler — sets up the trace that `stop` will complete.

```
1. state = resolve_session(input_json)
2. ensure_session_initialized(state, input_json)  — lazy init for Python Agent SDK
3. session_id = state.get("session_id")

4. Fail-safe: close any orphaned Turn span (lines 18-41 of bash):
   prev_trace_id = state.get("current_trace_id")
   prev_span_id = state.get("current_trace_span_id")
   if prev_trace_id and prev_span_id:
       # Build and send a fail-safe LLM span with output "(Turn closed by fail-safe...)"
       # Delete current_trace_* state keys
       log("Fail-safe: closed orphaned Turn {prev_count}")

5. state.increment("trace_count")

6. Set up new trace state:
   state.set("current_trace_id", generate_trace_id())
   state.set("current_trace_span_id", generate_span_id())
   state.set("current_trace_start_time", str(get_timestamp_ms()))
   state.set("current_trace_prompt", (input_json.get("prompt", "") or "")[:1000])

7. Track transcript position:
   transcript = input_json.get("transcript_path", "")
   if transcript and Path(transcript).is_file():
       line_count = sum(1 for _ in open(transcript))
       state.set("trace_start_line", str(line_count))
   else:
       state.set("trace_start_line", "0")
```

---

**`_handle_stop(input_json: dict)`** — replaces `stop.sh` (83 lines)

The most complex handler. Parses a JSONL transcript to extract assistant response and token counts.

```
1. state = resolve_session(input_json)
2. session_id = state.get("session_id")
3. trace_id = state.get("current_trace_id")
   — exit if either is None

4. Read state: trace_span_id, trace_start_time, user_prompt, project_name,
   trace_count, user_id

5. Parse transcript:
   transcript_path = input_json.get("transcript_path", "")
   output = ""
   model = ""
   in_tokens = 0
   out_tokens = 0

   if transcript_path and Path(transcript_path).is_file():
       start_line = int(state.get("trace_start_line") or "0")
       with open(transcript_path) as f:
           for i, line in enumerate(f):
               if i < start_line:
                   continue   # skip already-processed lines (replaces tail -n +N)
               line = line.strip()
               if not line:
                   continue
               try:
                   entry = json.loads(line)
               except json.JSONDecodeError:
                   continue
               if entry.get("type") != "assistant":
                   continue

               # Extract text from message.content
               content = entry.get("message", {}).get("content")
               if isinstance(content, list):
                   text = "\n".join(
                       item.get("text", "")
                       for item in content
                       if isinstance(item, dict) and item.get("type") == "text"
                   )
               elif isinstance(content, str):
                   text = content
               else:
                   text = ""
               if text:
                   output = f"{output}\n{text}" if output else text

               # Extract model
               model = entry.get("message", {}).get("model", "") or model

               # Accumulate token counts (lines 42-49 of bash)
               usage = entry.get("message", {}).get("usage", {})
               for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                   val = usage.get(key, 0)
                   if isinstance(val, int):
                       in_tokens += val
               val = usage.get("output_tokens", 0)
               if isinstance(val, int):
                   out_tokens += val

   output = output[:5000] or "(No response)"
   total_tokens = in_tokens + out_tokens

6. Build attrs dict:
   output_messages = [{"message.role": "assistant", "message.content": output}]
   attrs = {
       "session.id": session_id,
       "trace.number": trace_count,
       "project.name": project_name,
       "openinference.span.kind": "LLM",
       "llm.model_name": model,
       "llm.token_count.prompt": in_tokens,
       "llm.token_count.completion": out_tokens,
       "llm.token_count.total": total_tokens,
       "input.value": user_prompt,
       "output.value": output,
       "llm.output_messages": output_messages,
   }
   if user_id: attrs["user.id"] = user_id

7. span = build_span(f"Turn {trace_count}", "LLM", trace_span_id, trace_id, "",
                      trace_start_time, str(get_timestamp_ms()), attrs,
                      SERVICE_NAME, SCOPE_NAME)
   send_span(span)

8. Clean up state:
   state.delete("current_trace_id")
   state.delete("current_trace_span_id")
   state.delete("current_trace_start_time")
   state.delete("current_trace_prompt")
   log(f"Turn {trace_count} sent")

9. Periodic GC (every 5 turns):
   if int(trace_count or "0") % 5 == 0:
       gc_stale_state_files()
```

---

**`_handle_subagent_stop(input_json: dict)`** — replaces `subagent_stop.sh` (90 lines)

Similar to `stop` but parses a subagent transcript and uses file creation time for start.

```
1. state = resolve_session(input_json)
2. trace_id = state.get("current_trace_id")  — exit if None
3. session_id = state.get("session_id")
4. agent_id = input_json.get("agent_id", "")
5. agent_type = input_json.get("agent_type", "")
   — exit if agent_type is empty/unknown/null (line 19 of bash)

6. span_id = generate_span_id()
   end_time = str(get_timestamp_ms())
   parent = state.get("current_trace_span_id")

7. Parse subagent transcript (if agent_transcript_path exists):
   - Get file creation time for start_time:
     Path(transcript_path).stat().st_birthtime (macOS) or .st_ctime (Linux/Windows)
     Convert to milliseconds. Fall back to end_time if unavailable.
   - Parse JSONL same as _handle_stop: extract last assistant text, accumulate tokens
   - Truncate output to 5000 chars

   Cross-platform note: st_birthtime is macOS-only. Use:
     try: start_time = int(Path(p).stat().st_birthtime * 1000)
     except AttributeError: start_time = int(Path(p).stat().st_ctime * 1000)
   st_ctime is "creation time" on Windows, "last metadata change" on Linux.
   This is acceptable — the bash version has the same Linux limitation.

8. Build attrs:
   attrs = {
       "session.id": session_id,
       "openinference.span.kind": "chain",
       "subagent.id": agent_id,
       "subagent.type": agent_type,
       "llm.model_name": model,
       "llm.token_count.prompt": in_tokens,
       "llm.token_count.completion": out_tokens,
       "llm.token_count.total": total_tokens,
   }
   if subagent_output: attrs["output.value"] = subagent_output
   if user_id: attrs["user.id"] = user_id

9. Build and send span: "Subagent: {agent_type}"
```

---

**`_handle_notification(input_json: dict)`** — replaces `notification.sh` (34 lines)

Simple CHAIN span for system notifications.

```
1. state = resolve_session(input_json)
2. trace_id = state.get("current_trace_id")  — exit if None
3. Extract: message, title, notification_type (default "info")
4. Build attrs: session.id, openinference.span.kind=chain,
   notification.message, notification.title, notification.type, input.value=message
   + user.id if present
5. Build and send span: "Notification: {notification_type}"
```

---

**`_handle_permission_request(input_json: dict)`** — replaces `permission_request.sh` (33 lines)

Simple CHAIN span for permission requests.

```
1. state = resolve_session(input_json)
2. _log_to_file(f"DEBUG permission_request input: {json.dumps(input_json)}")
3. trace_id = state.get("current_trace_id")  — exit if None
4. Extract: permission, tool_name, tool_input (as JSON string)
5. Build attrs: session.id, openinference.span.kind=chain,
   permission.type, permission.tool, input.value=tool_input
   + user.id if present
6. Build and send span: "Permission Request"
```

---

**`_handle_session_end(input_json: dict)`** — replaces `session_end.sh` (26 lines)

No span — just logging and cleanup.

```
1. state = resolve_session(input_json)
2. session_id = state.get("session_id")  — exit if None
3. trace_count = state.get("trace_count") or "0"
4. tool_count = state.get("tool_count") or "0"
5. log_always(f"Session complete: {trace_count} traces, {tool_count} tools")
6. log_always(f"View in Arize/Phoenix: session.id = {session_id}")
7. Clean up: state.state_file.unlink(missing_ok=True)
   Remove lock dir if it exists
8. gc_stale_state_files()
```

---

### Shared helper: `_read_stdin() -> dict`

All Claude Code hooks read JSON from stdin. Factor this out:
```python
def _read_stdin() -> dict:
    """Read JSON from stdin. Returns {} on empty/invalid input."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return {}
```

### Expected behavior

- Every hook event produces the same spans as the bash version
- Transcript parsing in `stop` and `subagent_stop` extracts identical text and token counts
- The fail-safe in `user_prompt_submit` closes orphaned turns
- `post_tool_use` extracts tool-specific metadata (command, file_path, url, query) per tool type
- All hooks exit 0 even on unhandled exceptions
- No stdout output from any Claude Code hook

### Test plan

`tests/test_claude_hook.py`:

**session_start tests:**
- Test: calls `collector_ensure()` (mock it, verify called)
- Test: calls `resolve_session` and `ensure_session_initialized`

**pre_tool_use tests:**
- Test: sets `tool_{tool_id}_start` in state with current timestamp
- Test: missing `tool_use_id` → generates one, still sets start time

**post_tool_use tests:**
- Test: builds TOOL span with correct name, kind, trace/span IDs from state
- Test: `tool_name="Bash"` → `tool.command` attribute set, `tool.description` is command[:200]
- Test: `tool_name="Read"` → `tool.file_path` attribute set
- Test: `tool_name="Grep"` → both `tool.query` and `tool.file_path` set, description prefixed "grep: "
- Test: `tool_name="WebFetch"` → `tool.url` attribute set
- Test: unknown tool_name → description is first 200 chars of input
- Test: input > 5000 chars → truncated, `tool.truncated` is `"true"`
- Test: timing uses pre_tool_use start time if available, falls back to current time
- Test: `tool_{id}_start` state key cleaned up after span sent

**user_prompt_submit tests:**
- Test: sets `current_trace_id`, `current_trace_span_id`, `current_trace_start_time`, `current_trace_prompt`
- Test: increments `trace_count`
- Test: records `trace_start_line` from transcript file line count
- Test: fail-safe — if `current_trace_id` already in state, sends a fail-safe LLM span before setting up new trace
- Test: fail-safe span has output "(Turn closed by fail-safe: Stop hook did not fire)"
- Test: prompt truncated to 1000 chars

**stop tests:**
- Test: parses transcript, extracts assistant text from `message.content` (string format)
- Test: parses transcript, extracts assistant text from `message.content` (array format with type=text)
- Test: accumulates tokens: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` → `llm.token_count.prompt`
- Test: accumulates `output_tokens` → `llm.token_count.completion`
- Test: `total = prompt + completion`
- Test: skips lines before `trace_start_line` (set by user_prompt_submit)
- Test: output truncated to 5000 chars
- Test: no transcript file → output is "(No response)"
- Test: cleans up `current_trace_*` state keys after sending
- Test: GC runs every 5 turns
- Golden test: use `tests/fixtures/sample_transcript.jsonl`, verify exact token counts and output text

**subagent_stop tests:**
- Test: skips empty/unknown agent_type
- Test: parses subagent transcript for output and tokens (same as stop)
- Test: uses file creation time for start_time (mock `Path.stat()`)
- Test: falls back to end_time when creation time unavailable

**notification tests:**
- Test: builds CHAIN span with notification.message, notification.title, notification.type
- Test: default notification_type is "info"

**permission_request tests:**
- Test: builds CHAIN span with permission.type, permission.tool, input.value
- Test: logs debug input via `_log_to_file`

**session_end tests:**
- Test: logs session summary via `log_always`
- Test: removes state file and lock dir
- Test: calls `gc_stale_state_files`
- Test: graceful when session_id is None (exits early)

**Error handling tests:**
- Test: exception in any `_handle_*` → exported function catches it, logs error, doesn't crash
- Test: malformed stdin JSON → `_read_stdin()` returns `{}`
- Test: empty stdin → `_read_stdin()` returns `{}`

## Task: Codex adapter
Files: core/hooks/codex/adapter.py (new), tests/test_codex_adapter.py (new)
Depends: common-logging-utilities, common-state-management

Rewrite `codex-tracing/hooks/common.sh` (152 lines) as a Python adapter module. Codex differs from Claude Code in several ways: sessions are keyed by `thread-id` (not PID), GC is time-based (not PID liveness), and there's a `debug_dump` facility for trace-level debugging.

### Implementation

Imports:
```python
from core.constants import HARNESSES, STATE_BASE_DIR
from core.common import (
    StateManager, env, log, error, _log_to_file,
    generate_trace_id, get_timestamp_ms,
)
```

**Module-level constants** — derived from `HARNESSES["codex"]`:
```python
_HARNESS = HARNESSES["codex"]
SERVICE_NAME = _HARNESS["service_name"]       # "codex"
SCOPE_NAME = _HARNESS["scope_name"]           # "arize-codex-plugin"
STATE_DIR = STATE_BASE_DIR / _HARNESS["state_subdir"]  # ~/.arize/harness/state/codex
```

**`resolve_session(thread_id: str) -> StateManager`**

Replaces bash `resolve_session()` at lines 41-51 of `codex-tracing/hooks/common.sh`.

```python
def resolve_session(thread_id: str) -> StateManager:
    """Resolve per-session state file from Codex thread_id.

    Codex provides thread-id in the notify payload. Unlike Claude Code
    (which uses PID-based keys), Codex always has a thread_id.

    If thread_id is empty, generate a random one as fallback (matches bash line 45).

    Returns a StateManager with state_file and lock_path set.
    """
    if not thread_id:
        thread_id = generate_trace_id()

    state = StateManager(
        state_dir=STATE_DIR,
        state_file=STATE_DIR / f"state_{thread_id}.yaml",
        lock_path=STATE_DIR / f".lock_{thread_id}",
    )
    state.init_state()
    return state
```

Simpler than Claude Code — no PID derivation, no env var fallback.

**`ensure_session_initialized(state: StateManager, thread_id: str, cwd: str) -> None`**

Replaces bash `ensure_session_initialized()` at lines 53-81.

```python
def ensure_session_initialized(state: StateManager, thread_id: str, cwd: str) -> None:
    """Idempotent session initialization. No-op if session_id already in state.

    Sets (matching bash lines 63-80):
    - session_id: thread_id or generate_trace_id()
    - session_start_time: get_timestamp_ms() as string
    - project_name: from env.project_name or basename of cwd
    - trace_count: "0"
    - user_id: from env.user_id (if set)

    Note: Codex does NOT set tool_count (unlike Claude Code).
    Note: Codex does NOT read user_id from input_json (unlike Claude Code).
    Only env.user_id is used (bash lines 75-78: only from env var).
    """
```

Key differences from Claude Code adapter:
1. `session_id` is `thread_id` directly (not from input JSON field)
2. No `tool_count` state key
3. `user_id` only from env var, never from input

**`gc_stale_state_files() -> None`**

Replaces bash `gc_stale_state_files()` at lines 84-105.

```python
def gc_stale_state_files() -> None:
    """Remove state files older than 24 hours.

    Unlike Claude Code (which checks PID liveness), Codex uses time-based GC
    because thread_ids are not PIDs.

    Uses Path.stat().st_mtime (cross-platform, replaces macOS stat -f %m
    and Linux stat -c %Y at bash lines 91-94).

    24h = 86400 seconds (matches bash line 98).
    """
    now = time.time()
    for f in STATE_DIR.glob("state_*.yaml"):
        try:
            file_age_s = now - f.stat().st_mtime
        except OSError:
            continue
        if file_age_s > 86400:
            key = f.stem.replace("state_", "")
            f.unlink(missing_ok=True)
            lock_dir = STATE_DIR / f".lock_{key}"
            if lock_dir.is_dir():
                lock_dir.rmdir()
```

Cross-platform: `st_mtime` is available on all platforms. No `stat -f %m` / `stat -c %Y` branching needed.

**`debug_dump(label: str, data: str | dict) -> None`**

Replaces bash `debug_dump()` at lines 21-33.

```python
def debug_dump(label: str, data) -> None:
    """Write a debug YAML file when ARIZE_TRACE_DEBUG=true.

    Files written to {STATE_DIR}/debug/{sanitized_label}_{timestamp}.yaml

    Matches bash:
      [[ "$ARIZE_TRACE_DEBUG" == "true" ]] || return 0
      printf '%s\n' "$data" > "$file"
      _log_to_file "DEBUG wrote $safe_label to $file"

    Args:
        label: descriptive prefix, e.g., "notify_thread1_turn1_raw"
        data: string or dict to dump. Dicts are yaml.safe_dump'd, strings written as-is.
    """
    if not env.trace_debug:
        return

    import re
    safe_label = re.sub(r'[^a-zA-Z0-9._-]', '_', label)
    ts = get_timestamp_ms()
    debug_dir = STATE_DIR / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    out_file = debug_dir / f"{safe_label}_{ts}.yaml"

    if isinstance(data, dict):
        import yaml
        out_file.write_text(yaml.safe_dump(data, default_flow_style=False))
    else:
        out_file.write_text(str(data))

    _log_to_file(f"DEBUG wrote {safe_label} to {out_file}")
```

**`check_requirements() -> bool`**

Replaces bash `check_requirements()` at lines 148-152.

```python
def check_requirements() -> bool:
    """Check tracing enabled, create state directory.

    Returns False if tracing disabled (hook should exit 0).
    Matches bash: [[ "$ARIZE_TRACE_ENABLED" != "true" ]] && exit 0
    Note: bash also checks for jq (line 150) — not needed in Python.
    """
    if not env.trace_enabled:
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return True
```

**`load_env_file(path: Path) -> None`**

Codex-specific utility — replaces bash `source "$CODEX_ENV"` at `notify.sh` line 13.

```python
def load_env_file(path: Path) -> None:
    """Parse a shell-style env file and set variables in os.environ.

    Reads lines like:
        export ARIZE_API_KEY="abc123"
        PHOENIX_ENDPOINT=http://localhost:6006

    Handles: export prefix (optional), quoted values (single or double),
    comments (#), blank lines.

    On Windows, env files may not exist — this is a no-op if file missing.
    """
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ[key] = value
```

This is needed because Codex hooks source `~/.codex/arize-env.sh` before running. The Python version parses it directly instead of shelling out.

### Expected behavior

- `resolve_session()` returns a `StateManager` keyed by thread_id
- `ensure_session_initialized()` is idempotent — only writes on first call
- `ensure_session_initialized()` does NOT set `tool_count` (unlike Claude Code)
- `ensure_session_initialized()` only reads `user_id` from env, not from input
- `gc_stale_state_files()` removes files older than 24h, uses `st_mtime` (cross-platform)
- `debug_dump()` writes YAML files only when `ARIZE_TRACE_DEBUG=true`, no-op otherwise
- `load_env_file()` parses shell export syntax, handles missing file gracefully
- All functions are cross-platform

### Test plan

`tests/test_codex_adapter.py`:

**resolve_session tests:**
- Test: `resolve_session("thread-abc")` → state file is `state_thread-abc.yaml`
- Test: `resolve_session("")` → generates random key, state file is `state_{random}.yaml`
- Test: returned `StateManager` has `init_state()` called (file exists with `{}`)

**ensure_session_initialized tests:**
- Test: first call sets `session_id`, `session_start_time`, `project_name`, `trace_count`
- Test: second call is no-op (values unchanged)
- Test: `session_id` equals the `thread_id` passed in
- Test: `project_name` from `env.project_name` when set
- Test: `project_name` from `os.path.basename(cwd)` when env not set
- Test: `user_id` set when `env.user_id` is non-empty
- Test: `user_id` NOT set from input (only env — verify by passing user_id in input, checking it's ignored)
- Test: does NOT set `tool_count` key (unlike Claude Code)

**gc_stale_state_files tests:**
- Test: state file with mtime > 24h ago → removed
- Test: state file with mtime < 24h ago → kept
- Test: associated lock dir removed when state file removed
- Test: non-state files in STATE_DIR → not touched
- Test: empty STATE_DIR → no errors
- Test: file with unreadable stat → skipped (OSError caught)

**debug_dump tests:**
- Test: `env.trace_debug=True` → file written in `STATE_DIR/debug/`
- Test: `env.trace_debug=False` → no file written, directory not even created
- Test: dict data → YAML-formatted output
- Test: string data → written as-is
- Test: label with special characters → sanitized in filename (e.g., `"foo/bar:baz"` → `"foo_bar_baz"`)
- Test: `_log_to_file` called with debug message

**check_requirements tests:**
- Test: `env.trace_enabled=True` → returns True, STATE_DIR created
- Test: `env.trace_enabled=False` → returns False

**load_env_file tests:**
- Test: `export ARIZE_API_KEY="abc123"` → `os.environ["ARIZE_API_KEY"] == "abc123"`
- Test: `PHOENIX_ENDPOINT=http://localhost:6006` (no export prefix) → set correctly
- Test: single-quoted value → quotes stripped
- Test: double-quoted value → quotes stripped
- Test: comments and blank lines → skipped
- Test: missing file → no error, no-op
- Test: line without `=` → skipped

## Task: Codex hook handler
Files: core/hooks/codex/handlers.py (new), tests/test_codex_hook.py (new)
Depends: codex-adapter, common-span-building, common-span-sending

Rewrite `codex-tracing/hooks/notify.sh` (445 lines) as Python. This is the largest and most complex hook in the codebase. It builds a parent LLM span, enriches it with token counts and tool calls from the payload, drains collector events for child spans, and sends a multi-span payload.

### Implementation

**Entry point:**
```python
def notify():
    """Entry point for arize-hook-codex-notify. Codex hook.

    Input contract: JSON as sys.argv[1] (NOT stdin — Codex passes JSON as a CLI arg).
    No stdout output — Codex doesn't expect a response.
    """
    try:
        # Load env file before anything else (matches bash line 13)
        load_env_file(Path.home() / ".codex" / "arize-env.sh")

        if not check_requirements():
            return

        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        input_json = json.loads(raw)
        _handle_notify(input_json)
    except Exception as e:
        error(f"codex notify hook failed: {e}")
```

**`_handle_notify(input_json: dict)`** — the main handler, broken into phases:

---

**Phase 1: Event filtering** (bash lines 22-27)

```python
event_type = input_json.get("type", "")
if event_type != "agent-turn-complete":
    log(f"Ignoring event type: {event_type}")
    return
```

---

**Phase 2: Parse payload with flexible key names** (bash lines 29-46)

Codex payloads use inconsistent key naming (hyphenated, underscored, camelCase). Helper:

```python
def _flex_get(d: dict, *keys, default=""):
    """Try multiple key names, return first non-None/non-empty value."""
    for key in keys:
        val = d.get(key)
        if val is not None and val != "":
            return val
    return default
```

Extract fields:
```python
thread_id = _flex_get(input_json, "thread-id", "thread_id", "threadId")
turn_id = _flex_get(input_json, "turn-id", "turn_id", "turnId")
cwd = _flex_get(input_json, "cwd", "working-directory", "working_directory")
user_input = _flex_get(input_json, "input-messages", "input_messages", "inputMessages")
assistant_msg = _flex_get(input_json, "last-assistant-message", "last_assistant_message", "lastAssistantMessage")
```

**Extract assistant text** — recursive `as_text` (replaces bash jq `def as_text` at lines 37-46):

```python
def _as_text(node) -> str:
    """Recursively extract text from a nested message structure.

    Handles: str, list (join with newlines), dict (try .text, .content,
    .message, .data, .value, then json.dumps as fallback), None → "".
    Matches the jq as_text function in notify.sh lines 37-44.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(_as_text(item) for item in node)
    if isinstance(node, dict):
        for key in ("text", "content", "message", "data", "value"):
            if key in node:
                result = _as_text(node[key])
                if result:
                    return result
        return json.dumps(node)
    return str(node)
```

**Extract user prompt from input-messages** (bash lines 61-84):

```python
def _extract_user_prompt(user_input) -> str:
    """Extract the last user message from input-messages.

    input-messages can be:
    - list of message objects → find last with role=="user", extract content
    - list of strings → use last non-empty string
    - plain string → use directly

    Matches the jq expression at bash lines 63-79.
    """
    if isinstance(user_input, list):
        # Try: last user-role message object
        for msg in reversed(user_input):
            if isinstance(msg, dict) and msg.get("role") == "user":
                text = _as_text(msg.get("content", ""))
                if text:
                    return text
        # Fallback: last non-empty string in the array
        for msg in reversed(user_input):
            if isinstance(msg, str) and msg:
                return msg
        return ""
    if isinstance(user_input, str):
        return user_input
    return str(user_input) if user_input else ""
```

Truncate both to 5000 chars. If assistant_output is empty → `"(No response)"`.

Debug dumps after extraction:
```python
debug_prefix = f"notify_{thread_id or 'unknown'}_{turn_id or 'unknown'}"
debug_dump(f"{debug_prefix}_raw", input_json)
debug_dump(f"{debug_prefix}_text", {"input": user_prompt, "assistant": assistant_output})
```

---

**Phase 3: Resolve session and state** (bash lines 48-56)

```python
state = resolve_session(thread_id)
ensure_session_initialized(state, thread_id, cwd or os.getcwd())
session_id = state.get("session_id")
state.increment("trace_count")
trace_count = state.get("trace_count")
project_name = state.get("project_name")
user_id = state.get("user_id")
```

---

**Phase 4: Generate IDs and build base attributes** (bash lines 92-123)

```python
trace_id = generate_trace_id()
span_id = generate_span_id()
start_time = get_timestamp_ms()
end_time = start_time  # Turn already completed, no precise timing from notify

output_messages = [{"message.role": "assistant", "message.content": assistant_output}]

attrs = {
    "session.id": session_id,
    "trace.number": trace_count,
    "project.name": project_name,
    "openinference.span.kind": "LLM",
    "input.value": user_prompt,
    "output.value": assistant_output,
    "codex.turn_id": turn_id,
    "codex.thread_id": thread_id,
    "llm.output_messages": output_messages,
}
if user_id:
    attrs["user.id"] = user_id
```

---

**Phase 5: Token enrichment from notify payload** (bash lines 125-166)

Search for token usage in multiple locations (matching bash `usage_from` at lines 127-134):

```python
def _find_token_usage(input_json: dict) -> dict | None:
    """Search for token usage dict in multiple payload locations.

    Tries (matching bash lines 131-133):
    1. input_json itself: .token_usage / .token-usage / .usage
    2. input_json["last-assistant-message"]: same keys
    3. input_json["last-assistant-message"]["message"]: same keys
    """
    usage_keys = ("token_usage", "token-usage", "usage")
    for obj in [
        input_json,
        _flex_get_obj(input_json, "last-assistant-message", "last_assistant_message", "lastAssistantMessage"),
        _nested_get(input_json, "last-assistant-message", "message"),
    ]:
        if not isinstance(obj, dict):
            continue
        for key in usage_keys:
            val = obj.get(key)
            if isinstance(val, dict):
                return val
    return None
```

Extract token counts from usage dict (matching bash `pick_first` at lines 144-151):

```python
def _extract_token_counts(usage: dict) -> dict:
    """Extract prompt/completion/total counts, trying multiple key variants.

    Returns {"prompt": int|None, "completion": int|None, "total": int|None}.
    Auto-computes total if prompt + completion are present but total isn't.
    """
    def pick_first(*keys):
        for k in keys:
            val = usage.get(k)
            if val is not None:
                try: return int(val)
                except (ValueError, TypeError): pass
        return None

    prompt = pick_first(
        "prompt_tokens", "input_tokens", "promptTokens", "inputTokens",
        "prompt", "input", "cache_read_input_tokens", "cache_creation_input_tokens",
    )
    completion = pick_first(
        "completion_tokens", "output_tokens", "completionTokens", "outputTokens",
        "completion", "output",
    )
    total = pick_first(
        "total_tokens", "totalTokens", "tokens", "token_count", "overall", "sum",
    )
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion

    return {"prompt": prompt, "completion": completion, "total": total}
```

Apply to attrs:
```python
usage = _find_token_usage(input_json)
if usage:
    attrs["codex.token_usage"] = json.dumps(usage)
    debug_dump(f"{debug_prefix}_token_usage", usage)
    counts = _extract_token_counts(usage)
    if counts["prompt"] is not None:
        attrs["llm.token_count.prompt"] = counts["prompt"]
    if counts["completion"] is not None:
        attrs["llm.token_count.completion"] = counts["completion"]
    if counts["total"] is not None:
        attrs["llm.token_count.total"] = counts["total"]
```

---

**Phase 6: Tool call extraction from notify payload** (bash lines 168-211)

```python
def _find_tool_calls(input_json: dict) -> list | None:
    """Search for tool calls list in multiple payload locations.

    Tries keys: tool_calls, tool-calls, toolCalls, tool_invocations,
    toolInvocations, tools, tool_results.
    Searches: root, last-assistant-message, last-assistant-message.message
    """
```

If tool calls found:
```python
if tool_calls:
    count = len(tool_calls)
    attrs["llm.tool_call_count"] = count
    if count > 0:
        preview = tool_calls[:5]
        attrs["llm.tool_calls"] = json.dumps(preview)
        if count > 5:
            attrs["llm.tool_calls_omitted"] = count - 5
    debug_dump(f"{debug_prefix}_tool_calls", tool_calls)
```

---

**Phase 7: Drain collector event buffer** (bash lines 213-246)

```python
def _drain_events(thread_id: str, state: StateManager) -> list:
    """Drain buffered events from the collector for this thread.

    HTTP GET http://127.0.0.1:{port}/drain/{thread_id}?since_ns={last}&wait_ms=8000&quiet_ms=1200

    Retry schedule (matches bash drain_attempts array at line 225):
    - Attempt 1: immediate
    - Attempt 2: wait 1.2s, then request
    - Attempt 3: wait 2.0s, then request

    Returns list of event dicts. Returns [] on any failure.
    """
    if not thread_id:
        log("Skipping event buffer drain because thread-id is missing")
        return []

    last_ns = state.get("last_collector_time_ns") or "0"
    port = env.collector_port
    url = f"http://127.0.0.1:{port}/drain/{thread_id}"
    query = f"since_ns={last_ns}&wait_ms=8000&quiet_ms=1200"
    retry_waits = [0, 1.2, 2.0]  # seconds (matches bash: 0, 1200ms, 2000ms)

    for wait in retry_waits:
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(f"{url}?{query}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                events = json.loads(resp.read())
        except Exception:
            events = []

        if not isinstance(events, list):
            events = []

        log(f"Collector drain attempt (thread={thread_id}, wait={wait}s) => {len(events)} events")
        if events:
            return events

    return []
```

After draining, save `last_collector_time_ns` for next turn (bash line 253):
```python
events = _drain_events(thread_id, state)
debug_dump(f"{debug_prefix}_collector_events", events)
if events:
    max_ns = max((int(e.get("time_ns", 0)) for e in events), default=0)
    if max_ns > 0:
        state.set("last_collector_time_ns", str(max_ns))
```

---

**Phase 8: Enrich parent span and build child spans from events** (bash lines 256-422)

If events are present:

**8a. Adjust timing from event timestamps** (lines 259-266):
```python
timestamps_ns = [int(e.get("time_ns", 0)) for e in events if int(e.get("time_ns", 0)) > 0]
if timestamps_ns:
    start_time = min(timestamps_ns) // 1_000_000
    end_time = max(timestamps_ns) // 1_000_000
    attrs["codex.trace.duration_ms"] = end_time - start_time
```

**8b. Model name enrichment** (lines 270-277):
```python
for e in events:
    if e.get("event") in ("codex.conversation_starts", "codex.api_request"):
        a = e.get("attrs", {})
        model = a.get("model") or a.get("llm.model_name") or a.get("model_name")
        if model:
            attrs["llm.model_name"] = model
            break
```

**8c. Token enrichment from SSE events** (lines 280-315):
Search for `codex.sse_event` with `response.completed` type. Extract prompt/completion/total tokens using multiple key variants. Auto-compute total if missing. Same `pick_first` pattern as Phase 5 but from event attrs.

**8d. Sandbox/approval from conversation_starts** (lines 317-326):
```python
for e in events:
    if e.get("event") == "codex.conversation_starts":
        a = e.get("attrs", {})
        sandbox = a.get("sandbox") or a.get("sandbox_mode")
        approval = a.get("approval_mode") or a.get("approval")
        if sandbox: attrs["codex.sandbox_mode"] = sandbox
        if approval: attrs["codex.approval_mode"] = approval
        break
```

**8e. TOOL child spans from tool_decision + tool_result pairs** (lines 328-379):
```python
child_spans = []
decisions = [e for e in events if e.get("event") == "codex.tool_decision"]
results = [e for e in events if e.get("event") == "codex.tool_result"]

for i, decision in enumerate(decisions):
    da = decision.get("attrs", {})
    tool_name = da.get("tool_name") or da.get("tool.name") or da.get("name") or "unknown_tool"
    decision_ns = int(decision.get("time_ns", 0))
    approval_status = (da.get("approved") or da.get("approval")
                       or da.get("decision") or da.get("status") or "unknown")

    # Match result by tool name, fall back to index
    result = None
    for r in results:
        ra = r.get("attrs", {})
        rname = ra.get("tool_name") or ra.get("tool.name") or ra.get("name")
        if rname == tool_name:
            result = r
            break
    if result is None and i < len(results):
        result = results[i]

    result_ns = int(result.get("time_ns", 0)) if result else decision_ns
    tool_output = ""
    if result:
        ra = result.get("attrs", {})
        tool_output = str(ra.get("output") or ra.get("result") or ra.get("tool.output") or "")[:2000]

    tool_start_ms = decision_ns // 1_000_000 or start_time
    tool_end_ms = result_ns // 1_000_000 or tool_start_ms

    tool_attrs = {
        "openinference.span.kind": "TOOL",
        "tool.name": tool_name,
        "output.value": tool_output,
        "codex.tool.approval_status": approval_status,
        "session.id": session_id,
    }
    child_span = build_span(tool_name, "TOOL", generate_span_id(), trace_id,
                             span_id, tool_start_ms, tool_end_ms, tool_attrs,
                             SERVICE_NAME, SCOPE_NAME)
    child_spans.append(child_span)
```

**8f. INTERNAL child spans from API/websocket requests** (lines 381-421):
```python
api_events = [e for e in events if e.get("event") in ("codex.api_request", "codex.websocket_request")]
for req_event in api_events:
    ra = req_event.get("attrs", {})
    req_model = ra.get("model") or ra.get("llm.model_name") or "unknown"
    req_status = ra.get("status") or ra.get("status_code") or ra.get("success") or "ok"
    req_attempt = ra.get("attempt", "1")
    req_duration_ms = ra.get("duration_ms", "0")
    req_auth_mode = ra.get("auth_mode", "")
    req_conn_reused = ra.get("auth.connection_reused", "")
    req_ns = int(req_event.get("time_ns", 0))
    req_start_ms = req_ns // 1_000_000 or start_time

    request_attrs = {
        "openinference.span.kind": "CHAIN",
        "codex.request.model": req_model,
        "codex.request.status": req_status,
        "codex.request.attempt": req_attempt,
        "codex.request.duration_ms": int(req_duration_ms) if req_duration_ms else 0,
        "session.id": session_id,
    }
    # Only include non-empty optional attrs (matches bash with_entries filter)
    if req_auth_mode: request_attrs["codex.request.auth_mode"] = req_auth_mode
    if req_conn_reused: request_attrs["codex.request.connection_reused"] = req_conn_reused == "true"

    child_span = build_span(f"API Request ({req_model})", "INTERNAL",
                             generate_span_id(), trace_id, span_id,
                             req_start_ms, req_start_ms, request_attrs,
                             SERVICE_NAME, SCOPE_NAME)
    child_spans.append(child_span)
```

---

**Phase 9: Build and send** (bash lines 424-438)

```python
parent_span = build_span(f"Turn {trace_count}", "LLM", span_id, trace_id, "",
                          start_time, end_time, attrs, SERVICE_NAME, SCOPE_NAME)
debug_dump(f"{debug_prefix}_parent_span", parent_span)

if child_spans:
    log(f"Building multi-span payload: 1 parent + {len(child_spans)} children")
    all_spans = [parent_span] + child_spans
    multi_payload = build_multi_span(all_spans, SERVICE_NAME, SCOPE_NAME)
    debug_dump(f"{debug_prefix}_multi_span", multi_payload)
    send_span(multi_payload)
else:
    debug_dump(f"{debug_prefix}_span", parent_span)
    send_span(parent_span)

log(f"Turn {trace_count} sent (thread={thread_id}, turn={turn_id}, children={len(child_spans)})")
```

---

**Phase 10: Periodic GC** (bash lines 442-445)

```python
if int(trace_count or "0") % 10 == 0:
    gc_stale_state_files()
```

### Expected behavior

- Produces identical spans to the bash version for the same input
- Event buffer drain retry logic matches bash timing (0s, 1.2s, 2.0s)
- `_as_text` recursion handles all nested message structures (str, list, dict)
- `_flex_get` handles all three key naming conventions (hyphen, underscore, camelCase)
- Token extraction handles all key name variants from both payload and collector events
- Tool decision/result pairing matches by tool name first, then by index
- API request spans include all metadata fields, filtering out empty optional attrs
- Multi-span payload sent when children exist, single span otherwise
- No stdout output — Codex doesn't expect a response
- Exception in any phase is caught at entry point level

### Test plan

`tests/test_codex_hook.py`:

**Event filtering tests:**
- Test: `type: "agent-turn-complete"` → processes normally
- Test: `type: "session-start"` → logs and returns (no span sent)
- Test: missing `type` → logs and returns

**Payload parsing tests:**
- Test: `_flex_get` with `thread-id` key → found
- Test: `_flex_get` with `thread_id` key → found
- Test: `_flex_get` with `threadId` key → found
- Test: `_flex_get` with none of the above → returns default
- Test: `_as_text(None)` → `""`
- Test: `_as_text("hello")` → `"hello"`
- Test: `_as_text(["a", "b"])` → `"a\nb"`
- Test: `_as_text({"text": "hello"})` → `"hello"`
- Test: `_as_text({"content": {"text": "nested"}})` → `"nested"`
- Test: `_as_text(42)` → `"42"`
- Test: `_extract_user_prompt` with list of user/assistant messages → last user content
- Test: `_extract_user_prompt` with list of strings → last non-empty string
- Test: `_extract_user_prompt` with plain string → string itself
- Test: truncation to 5000 chars for both prompt and assistant output
- Test: empty assistant output → `"(No response)"`

**Token enrichment tests (from payload):**
- Test: `_find_token_usage` finds `token_usage` at root
- Test: `_find_token_usage` finds `usage` in `last-assistant-message`
- Test: `_find_token_usage` returns None when no usage present
- Test: `_extract_token_counts` with `prompt_tokens` + `completion_tokens` → both extracted
- Test: `_extract_token_counts` with `inputTokens` (camelCase) → found
- Test: `_extract_token_counts` auto-computes total when missing
- Test: `_extract_token_counts` with string values → converted to int

**Tool call extraction tests:**
- Test: `_find_tool_calls` finds `tool_calls` at root
- Test: `_find_tool_calls` finds `toolCalls` in `last-assistant-message`
- Test: tool count attribute set, preview is first 5
- Test: > 5 tool calls → `llm.tool_calls_omitted` attribute set
- Test: no tool calls → no tool attributes

**Event drain tests:**
- Test: `_drain_events` with `mock_collector` returning events → parsed correctly
- Test: `_drain_events` with empty response → returns `[]`
- Test: `_drain_events` retry — first attempt returns `[]`, second returns events (mock server returns empty then events)
- Test: `_drain_events` with missing thread_id → returns `[]`, logs skip message
- Test: `last_collector_time_ns` saved in state after drain

**Child span building tests (from events):**
- Test: `codex.tool_decision` + matching `codex.tool_result` → TOOL child span with correct name, output, timing
- Test: `codex.tool_decision` without matching result → child span with fallback timing
- Test: `codex.api_request` → INTERNAL child span with model, status, attempt, duration
- Test: `codex.websocket_request` → also creates INTERNAL child span
- Test: optional attrs (auth_mode, connection_reused) omitted when empty

**Event enrichment tests:**
- Test: `codex.conversation_starts` → `llm.model_name` enriched on parent attrs
- Test: `codex.sse_event` with `response.completed` → token counts enriched
- Test: `codex.conversation_starts` → sandbox/approval mode attributes set
- Test: timing adjusted from event timestamps (min → start_time, max → end_time)

**Multi-span assembly tests:**
- Test: with child spans → multi-span payload sent (contains parent + children)
- Test: without child spans → single parent span sent
- Test: debug dumps written at each stage when trace_debug enabled

**Integration test:**
- Test: full `_handle_notify` with `codex_notify.json` fixture + `mock_collector` for drain → verify parent span attributes, child count, and span was sent to mock collector

**Error handling:**
- Test: exception in `_handle_notify` → `notify()` catches it, logs error, doesn't crash
- Test: invalid JSON in argv → handled gracefully

## Task: Cursor adapter
Files: core/hooks/cursor/adapter.py (new), tests/test_cursor_adapter.py (new)
Depends: common-logging-utilities, common-state-management

Rewrite `cursor-tracing/hooks/common.sh` (195 lines) as a Python adapter module. Cursor is architecturally different from Claude Code and Codex — it uses a single dispatcher for all 12 hook events, deterministic trace IDs from generation IDs, and a disk-backed state stack for merging before/after hook pairs.

### Implementation

Imports:
```python
import hashlib
import os
import re
import time
from pathlib import Path

import yaml

from core.constants import HARNESSES, STATE_BASE_DIR
from core.common import FileLock, env, log, error, get_timestamp_ms
```

**Module-level constants** — from `HARNESSES["cursor"]`:
```python
_HARNESS = HARNESSES["cursor"]
SERVICE_NAME = _HARNESS["service_name"]       # "cursor"
SCOPE_NAME = _HARNESS["scope_name"]           # "arize-cursor-plugin"
STATE_DIR = STATE_BASE_DIR / _HARNESS["state_subdir"]  # ~/.arize/harness/state/cursor
MAX_ATTR_CHARS = int(os.environ.get("CURSOR_TRACE_MAX_ATTR_CHARS", "100000"))
```

Note: Cursor doesn't use `StateManager` — it has its own state model. No per-session state file. Instead it uses:
- Root span files: `STATE_DIR/root_{sanitized_gen_id}` — plain text, one span_id
- Stack files: `STATE_DIR/{key}.stack.yaml` — YAML lists for before/after merging
- No session_id, no trace_count, no `resolve_session()`

---

**`trace_id_from_generation(gen_id: str) -> str`**

Replaces bash `trace_id_from_generation()` at lines 33-45.

```python
def trace_id_from_generation(gen_id: str) -> str:
    """Deterministic 32-hex trace ID from a Cursor generation_id.

    Maps one Cursor "turn" (generation) to one trace.
    Uses MD5 hash — matches bash: printf '%s' "$gen_id" | md5sum | cut -c1-32

    MD5 is NOT used for security here — it's used for deterministic mapping
    so all spans in the same generation share a trace_id.
    """
    return hashlib.md5(gen_id.encode()).hexdigest()[:32]
```

Note: `md5().hexdigest()` always returns 32 chars, so `[:32]` is technically redundant but documents the intent.

**`span_id_16() -> str`**

Replaces bash `span_id_16()` at lines 48-51.

```python
def span_id_16() -> str:
    """Generate 16-hex random span ID.

    Replaces bash: od -An -tx1 -N8 /dev/urandom | tr -d ' \n' | cut -c1-16
    """
    return os.urandom(8).hex()
```

**`sanitize(s: str) -> str`**

Replaces bash `sanitize()` at lines 181-183.

```python
def sanitize(s: str) -> str:
    """Replace non-alphanumeric characters (except ._-) with underscore.

    Matches bash: printf '%s' "$1" | tr -c '[:alnum:]._-' '_'
    """
    return re.sub(r'[^a-zA-Z0-9._-]', '_', s)
```

**`truncate_attr(s: str, max_chars: int | None = None) -> str`**

Replaces bash `truncate_attr()` at lines 186-194.

```python
def truncate_attr(s: str, max_chars: int | None = None) -> str:
    """Truncate string to MAX_ATTR_CHARS (default 100000).

    Matches bash: if [[ ${#str} -gt $max ]]; then printf '%s' "${str:0:$max}"
    """
    limit = max_chars if max_chars is not None else MAX_ATTR_CHARS
    return s[:limit] if len(s) > limit else s
```

---

**Disk-backed state stack** — replaces bash `state_push`/`state_pop` at lines 59-132. Used to merge before/after hook pairs (e.g., `beforeShellExecution` pushes command + start time, `afterShellExecution` pops it to create a merged span).

```python
def state_push(key: str, value: dict) -> None:
    """Push a dict onto a named stack.

    Stack file: STATE_DIR/{key}.stack.yaml — a YAML list.
    Uses FileLock for concurrent access.

    Matches bash state_push() at lines 59-87:
    - mkdir-based lock → FileLock
    - Initialize with [] if missing
    - Append value to YAML list
    """
    stack_file = STATE_DIR / f"{key}.stack.yaml"
    lock_path = STATE_DIR / f".lock_{key}"

    with FileLock(lock_path):
        if stack_file.exists():
            try:
                data = yaml.safe_load(stack_file.read_text()) or []
            except yaml.YAMLError:
                data = []
        else:
            data = []

        if not isinstance(data, list):
            data = []

        data.append(value)

        tmp = stack_file.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(yaml.safe_dump(data, default_flow_style=False))
        tmp.replace(stack_file)


def state_pop(key: str) -> dict | None:
    """Pop the last value from a named stack. Returns None if empty.

    Matches bash state_pop() at lines 91-132:
    - Read JSON array → read YAML list
    - Get last element ([-1])
    - Remove last element ([:-1])
    - Return value or "null" → return dict or None
    """
    stack_file = STATE_DIR / f"{key}.stack.yaml"
    lock_path = STATE_DIR / f".lock_{key}"

    if not stack_file.exists():
        return None

    with FileLock(lock_path):
        try:
            data = yaml.safe_load(stack_file.read_text()) or []
        except yaml.YAMLError:
            return None

        if not isinstance(data, list) or len(data) == 0:
            return None

        value = data[-1]
        data = data[:-1]

        tmp = stack_file.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(yaml.safe_dump(data, default_flow_style=False))
        tmp.replace(stack_file)

    return value if isinstance(value, dict) else None
```

Key difference from `StateManager`: the stack is a YAML list (not a key-value mapping), and push/pop semantics are LIFO (last-in-first-out). The bash version uses jq to manipulate JSON arrays; the Python version uses yaml lists.

---

**Root span tracking per generation** — replaces bash lines 138-155.

```python
def gen_root_span_save(gen_id: str, span_id: str) -> None:
    """Save the root span ID for a generation.

    Written by beforeSubmitPrompt, read by all other events to set parent_span_id.
    File: STATE_DIR/root_{sanitized_gen_id}
    Contains: just the span_id as plain text.
    """
    safe = sanitize(gen_id)
    (STATE_DIR / f"root_{safe}").write_text(span_id)


def gen_root_span_get(gen_id: str) -> str:
    """Get the root span ID for a generation. Returns "" if not found."""
    if not gen_id:
        return ""
    safe = sanitize(gen_id)
    root_file = STATE_DIR / f"root_{safe}"
    if root_file.exists():
        return root_file.read_text().strip()
    return ""
```

---

**Generation cleanup** — replaces bash `state_cleanup_generation()` at lines 159-176.

```python
def state_cleanup_generation(gen_id: str) -> None:
    """Remove all state files for a generation (called by stop hook).

    Cleans up:
    1. Root span file: root_{sanitized_gen_id}
    2. Stack files: *{sanitized_gen_id}*.stack.yaml
    3. Lock dirs: .lock_*{sanitized_gen_id}*

    Matches bash lines 159-176.
    """
    safe = sanitize(gen_id)

    # Root span file
    root_file = STATE_DIR / f"root_{safe}"
    root_file.unlink(missing_ok=True)

    # Stack files containing this generation ID
    for f in STATE_DIR.glob(f"*{safe}*.stack.yaml"):
        f.unlink(missing_ok=True)

    # Lock dirs containing this generation ID
    for d in STATE_DIR.glob(f".lock_*{safe}*"):
        if d.is_dir():
            try:
                d.rmdir()  # only works on empty dirs
            except OSError:
                pass
```

---

**`check_requirements() -> bool`**

```python
def check_requirements() -> bool:
    """Check tracing enabled, ensure state directory exists."""
    if not env.trace_enabled:
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return True
```

No `jq` check needed (bash line 44 in hook-handler.sh: `command -v jq &>/dev/null`).

### Expected behavior

- `trace_id_from_generation("gen-abc")` returns the same 32-hex string as `echo -n "gen-abc" | md5sum | cut -c1-32`
- `span_id_16()` returns 16 random hex chars, different each call
- `sanitize("foo/bar:baz!@#")` → `"foo_bar_baz___"`
- `truncate_attr` respects `CURSOR_TRACE_MAX_ATTR_CHARS` env var
- `state_push` + `state_pop` is LIFO — push A, push B, pop → B, pop → A
- `state_push`/`state_pop` is concurrency-safe (FileLock)
- `gen_root_span_save` + `gen_root_span_get` round-trips a span_id
- `state_cleanup_generation` removes all files matching the generation ID pattern
- All functions are cross-platform (no `/dev/urandom` reads, no `md5sum`/`md5` binary, no `stat`)

### Test plan

`tests/test_cursor_adapter.py`:

**trace_id_from_generation tests:**
- Test: `trace_id_from_generation("gen-abc")` returns 32-char hex string
- Test: same input always returns same output (deterministic)
- Test: different inputs return different outputs
- Test: output matches `echo -n "gen-abc" | md5sum | cut -c1-32` (verify against known hash — `md5("gen-abc")` = specific hex value, compute it once and hardcode in test)

**span_id_16 tests:**
- Test: returns 16-char hex string
- Test: two calls return different values

**sanitize tests:**
- Test: `sanitize("hello")` → `"hello"` (unchanged)
- Test: `sanitize("foo/bar")` → `"foo_bar"`
- Test: `sanitize("foo.bar-baz_qux")` → `"foo.bar-baz_qux"` (dots, hyphens, underscores preserved)
- Test: `sanitize("a@b#c$d")` → `"a_b_c_d"`
- Test: `sanitize("")` → `""`

**truncate_attr tests:**
- Test: string shorter than max → unchanged
- Test: string longer than max → truncated to max
- Test: exact length → unchanged
- Test: custom max_chars parameter overrides default
- Test: `CURSOR_TRACE_MAX_ATTR_CHARS` env var respected

**state_push / state_pop tests:**
- Test: push A, pop → A
- Test: push A, push B, pop → B, pop → A (LIFO order)
- Test: pop from empty/missing stack → None
- Test: pop from corrupted stack file → None
- Test: push creates stack file if missing
- Test: after pop removes last item, stack file contains `[]`
- Test: concurrent push from 5 threads → all values present (order may vary but no corruption)
- Test: stack file is valid YAML after push/pop

**gen_root_span tests:**
- Test: save then get → returns saved span_id
- Test: get with no save → returns ""
- Test: get with empty gen_id → returns ""
- Test: save overwrites previous value

**state_cleanup_generation tests:**
- Test: creates root file + 2 stack files + lock dir, cleanup removes all
- Test: cleanup with gen_id that has no files → no error
- Test: cleanup doesn't remove files for OTHER generations
- Test: cleanup handles non-empty lock dir gracefully (rmdir fails, no crash)

**check_requirements tests:**
- Test: `env.trace_enabled=True` → returns True, STATE_DIR exists
- Test: `env.trace_enabled=False` → returns False

## Task: Cursor hook handler
Files: core/hooks/cursor/handlers.py (new), tests/test_cursor_hook.py (new)
Depends: cursor-adapter, common-span-building, common-span-sending

Rewrite `cursor-tracing/hooks/hook-handler.sh` (475 lines) as Python. Single entry point that dispatches all 12 Cursor hook events. Critical constraint: stdout is reserved for the permissive JSON response — all logging goes to the log file via stderr redirect.

### Implementation

**Entry point:**

```python
def main():
    """Entry point for arize-hook-cursor. Cursor hook.

    Input contract: JSON on stdin, all 12 events routed here.
    stdout: MUST print permissive JSON response, even on error.
    stderr: redirected to ARIZE_LOG_FILE before dispatch.
    """
    event = ""
    try:
        # Redirect stderr to log file BEFORE any processing
        # (matches bash: { ... } 2>>"$ARIZE_LOG_FILE" || true at line 471)
        try:
            _log_fd = open(env.log_file, "a")
            sys.stderr = _log_fd
        except OSError:
            pass

        if not check_requirements():
            _print_permissive(event)
            return

        input_json = json.loads(sys.stdin.read() or "{}")
        event = input_json.get("hook_event_name", "")
        _dispatch(event, input_json)
    except Exception as e:
        error(f"cursor hook failed ({event}): {e}")
    finally:
        # ALWAYS print permissive response — this is the LAST thing that happens
        _print_permissive(event)
```

**Permissive response** — replaces bash `permissive()` at lines 55-61:

```python
def _print_permissive(event: str) -> None:
    """Print the permissive JSON response to stdout.

    before* events → {"permission": "allow"}
    all others → {"continue": true}

    Uses sys.__stdout__ (the original stdout) since sys.stderr may have been redirected.
    """
    if event.startswith("before"):
        sys.__stdout__.write('{"permission": "allow"}')
    else:
        sys.__stdout__.write('{"continue": true}')
    sys.__stdout__.flush()
```

Important: use `sys.__stdout__` (the original stdout saved by Python) NOT `sys.stdout`, in case something else has redirected it. The bash version prints to stdout after the `{ } 2>>log` block (line 474).

**Early exit checks** — replaces bash lines 28-44:

```python
# Inside _dispatch, before event handling:
if not env.trace_enabled:
    return

target = get_target()
if target == "none":
    # Check collector health before giving up (matches bash lines 36-40)
    try:
        urllib.request.urlopen(f"{env.collector_url}/health", timeout=1)
    except Exception:
        log("No backend configured and collector not reachable, skipping")
        return
```

**Field extraction helper** — replaces bash `jq_str()` at lines 64-66:

```python
def _jq_str(input_json: dict, *keys, default: str = "") -> str:
    """Try multiple keys in order, return first non-None/non-empty string value.

    Matches bash: echo "$INPUT" | jq -r "$1" 2>/dev/null || echo "${2:-}"
    """
    for key in keys:
        val = input_json.get(key)
        if val is not None and val != "":
            return str(val)
    return default
```

**Common preamble** for all events — extracted into `_dispatch`:

```python
def _dispatch(event: str, input_json: dict) -> None:
    conversation_id = input_json.get("conversation_id", "")
    gen_id = input_json.get("generation_id", "")

    # Early exits (tracing, backend checks) ...

    trace_id = trace_id_from_generation(gen_id) if gen_id else ""
    now_ms = get_timestamp_ms()

    HANDLERS = {
        "beforeSubmitPrompt": _handle_before_submit_prompt,
        "afterAgentResponse": _handle_after_agent_response,
        "afterAgentThought": _handle_after_agent_thought,
        "beforeShellExecution": _handle_before_shell_execution,
        "afterShellExecution": _handle_after_shell_execution,
        "beforeMCPExecution": _handle_before_mcp_execution,
        "afterMCPExecution": _handle_after_mcp_execution,
        "beforeReadFile": _handle_before_read_file,
        "afterFileEdit": _handle_after_file_edit,
        "beforeTabFileRead": _handle_before_tab_file_read,
        "afterTabFileEdit": _handle_after_tab_file_edit,
        "stop": _handle_stop,
    }

    handler = HANDLERS.get(event)
    if handler:
        handler(input_json, conversation_id, gen_id, trace_id, now_ms)
    else:
        log(f"Unknown hook event: {event}")
```

All handlers receive `(input_json, conversation_id, gen_id, trace_id, now_ms)`.

---

**`_handle_before_submit_prompt`** — replaces bash lines 75-105. Root span for the turn.

```
1. sid = span_id_16()
2. gen_root_span_save(gen_id, sid)  — save root span so children can reference it
3. prompt = truncate_attr(_jq_str(input_json, "prompt", "input", "text"))
4. model = _jq_str(input_json, "model_name", "model")
5. attrs = {
       "openinference.span.kind": "CHAIN",
       "input.value": prompt,
       "session.id": conversation_id,
   }
   if model: attrs["llm.model_name"] = model
6. span = build_span("User Prompt", "CHAIN", sid, trace_id, "",
                      now_ms, now_ms, attrs, SERVICE_NAME, SCOPE_NAME)
7. send_span(span)
8. log(f"beforeSubmitPrompt: root span {sid} (trace={trace_id})")
```

---

**`_handle_after_agent_response`** — replaces bash lines 110-133. LLM response span.

```
1. sid = span_id_16()
2. parent = gen_root_span_get(gen_id)
3. response = truncate_attr(_jq_str(input_json, "response", "output", "text"))
4. model = _jq_str(input_json, "model_name", "model")
5. attrs = {
       "openinference.span.kind": "LLM",
       "output.value": response,
       "session.id": conversation_id,
   }
   if model: attrs["llm.model_name"] = model
6. span = build_span("Agent Response", "LLM", sid, trace_id, parent,
                      now_ms, now_ms, attrs, SERVICE_NAME, SCOPE_NAME)
7. send_span(span)
```

---

**`_handle_after_agent_thought`** — replaces bash lines 138-158. CHAIN span for thinking.

```
1. sid = span_id_16()
2. parent = gen_root_span_get(gen_id)
3. thought = truncate_attr(_jq_str(input_json, "thought", "thinking", "text"))
4. attrs = {"openinference.span.kind": "CHAIN", "output.value": thought,
            "session.id": conversation_id}
5. Build and send span: "Agent Thinking", kind="CHAIN"
```

---

**`_handle_before_shell_execution`** — replaces bash lines 163-179. State push only, no span.

```
1. if not gen_id: return
2. command = _jq_str(input_json, "command", "shell_command")
3. cwd = _jq_str(input_json, "cwd", "working_directory")
4. state_push(f"shell_{sanitize(gen_id)}", {
       "command": command,
       "cwd": cwd,
       "start_ms": str(now_ms),
       "trace_id": trace_id,
       "conversation_id": conversation_id,
   })
5. log(f"beforeShellExecution: pushed state for gen={gen_id}")
```

---

**`_handle_after_shell_execution`** — replaces bash lines 184-232. Merge with before state, create TOOL span.

```
1. sid = span_id_16()
2. parent = gen_root_span_get(gen_id)
3. popped = state_pop(f"shell_{sanitize(gen_id)}") if gen_id else None

4. # Extract before-state fields
   if popped:
       start_ms = popped.get("start_ms", "")
       command = popped.get("command", "")
   else:
       start_ms = ""
       command = ""
   start_ms = start_ms or str(now_ms)

5. # Override command from after-event if present (bash lines 205-206)
   after_cmd = _jq_str(input_json, "command", "shell_command")
   if after_cmd: command = after_cmd

6. output = truncate_attr(_jq_str(input_json, "output", "stdout", "result"))
   command = truncate_attr(command)
   exit_code = _jq_str(input_json, "exit_code", "exitCode")

7. attrs = {
       "openinference.span.kind": "TOOL",
       "tool.name": "shell",
       "input.value": command,
       "output.value": output,
       "session.id": conversation_id,
   }
   if exit_code: attrs["shell.exit_code"] = exit_code

8. Build and send span: "Shell", kind="TOOL", start=start_ms, end=now_ms
```

---

**`_handle_before_mcp_execution`** — replaces bash lines 237-257. State push only, no span.

```
1. if not gen_id: return
2. tool_name = _jq_str(input_json, "tool_name", "toolName", "name")
3. tool_input = _jq_str(input_json, "tool_input", "toolInput", "input", "arguments")
4. mcp_url = _jq_str(input_json, "url", "server_url", "serverUrl")
5. mcp_cmd = _jq_str(input_json, "command")
6. state_push(f"mcp_{sanitize(gen_id)}", {
       "tool_name": tool_name,
       "tool_input": tool_input,
       "url": mcp_url,
       "command": mcp_cmd,
       "start_ms": str(now_ms),
       "trace_id": trace_id,
       "conversation_id": conversation_id,
   })
```

---

**`_handle_after_mcp_execution`** — replaces bash lines 262-312. Merge with before state, create TOOL span.

```
1. sid = span_id_16()
2. parent = gen_root_span_get(gen_id)
3. popped = state_pop(f"mcp_{sanitize(gen_id)}") if gen_id else None

4. # Extract before-state fields
   if popped:
       start_ms = popped.get("start_ms", "")
       tool_name = popped.get("tool_name", "")
       tool_input = popped.get("tool_input", "")
   else:
       start_ms = ""
       tool_name = ""
       tool_input = ""
   start_ms = start_ms or str(now_ms)

5. # Override tool name from after-event if present (bash lines 285-287)
   after_tool = _jq_str(input_json, "tool_name", "toolName", "name")
   if after_tool: tool_name = after_tool
   tool_name = tool_name or "unknown"

6. result = truncate_attr(_jq_str(input_json, "result", "output", "result_json"))
   tool_input = truncate_attr(tool_input)

7. attrs = {
       "openinference.span.kind": "TOOL",
       "tool.name": tool_name,
       "input.value": tool_input,
       "output.value": result,
       "session.id": conversation_id,
   }

8. Build and send span: f"MCP: {tool_name}", kind="TOOL", start=start_ms, end=now_ms
```

---

**`_handle_before_read_file`** — replaces bash lines 317-339. TOOL span.

```
1. sid = span_id_16()
2. parent = gen_root_span_get(gen_id)
3. file_path = truncate_attr(_jq_str(input_json, "file_path", "filePath", "path"))
4. attrs = {"openinference.span.kind": "TOOL", "tool.name": "read_file",
            "input.value": file_path, "session.id": conversation_id}
5. Build and send span: "Read File", kind="TOOL", start=end=now_ms
```

---

**`_handle_after_file_edit`** — replaces bash lines 344-371. TOOL span.

```
1. sid = span_id_16()
2. parent = gen_root_span_get(gen_id)
3. file_path = _jq_str(input_json, "file_path", "filePath", "path")
4. edits = _jq_str(input_json, "edits", "changes", "diff")
5. input_val = f"{file_path}: {edits}" if edits else file_path
6. input_val = truncate_attr(input_val)
7. attrs = {"openinference.span.kind": "TOOL", "tool.name": "edit_file",
            "input.value": input_val, "session.id": conversation_id}
8. Build and send span: "File Edit", kind="TOOL"
```

---

**`_handle_before_tab_file_read`** — replaces bash lines 376-398. Same pattern as `before_read_file` with `tool.name: "read_file_tab"`, span name `"Tab Read File"`.

**`_handle_after_tab_file_edit`** — replaces bash lines 403-430. Same pattern as `after_file_edit` with `tool.name: "edit_file_tab"`, span name `"Tab File Edit"`.

---

**`_handle_stop`** — replaces bash lines 435-462. CHAIN span + generation cleanup.

```
1. sid = span_id_16()
2. parent = gen_root_span_get(gen_id)
3. status = _jq_str(input_json, "status", "reason")
4. loop_count = _jq_str(input_json, "loop_count", "loopCount", "iterations")
5. attrs = {
       "openinference.span.kind": "CHAIN",
       "session.id": conversation_id,
   }
   if status: attrs["cursor.stop.status"] = status
   if loop_count: attrs["cursor.stop.loop_count"] = loop_count

6. Build and send span: "Agent Stop", kind="CHAIN"

7. if gen_id:
       state_cleanup_generation(gen_id)
8. log(f"stop: span {sid}, cleaned up gen={gen_id}")
```

---

### Expected behavior

- Every event produces the same span as the bash version (same name, kind, attributes)
- Before/after shell execution merge: `beforeShellExecution` pushes state, `afterShellExecution` pops and creates a single TOOL span with the before-state's start time and command, plus the after-state's output and exit code
- Before/after MCP execution merge: same pattern — before pushes tool name/input, after pops and merges result
- `beforeSubmitPrompt` saves root span ID; all subsequent events in the same generation use it as parent
- `stop` event cleans up all generation state files
- Permissive JSON response is ALWAYS printed to stdout, even on exception
- stderr is redirected to log file — nothing leaks to the host tool
- Tracing-disabled early exit still prints permissive response
- Unknown events are logged and ignored (still return permissive response)

### Test plan

`tests/test_cursor_hook.py`:

**Entry point / permissive response tests:**
- Test: `main()` with `beforeSubmitPrompt` → stdout is `{"permission": "allow"}`
- Test: `main()` with `afterAgentResponse` → stdout is `{"continue": true}`
- Test: `main()` with `stop` → stdout is `{"continue": true}`
- Test: `main()` with exception in handler → stdout still has permissive response
- Test: `main()` with empty stdin → stdout has permissive response, no crash
- Test: `main()` with tracing disabled → stdout has permissive response, no span sent

**Early exit tests:**
- Test: `env.trace_enabled=False` → no span sent, permissive response returned
- Test: no backend configured + collector unreachable → no span sent, permissive response returned
- Test: no backend configured + collector reachable → proceeds normally

**beforeSubmitPrompt tests:**
- Test: saves root span via `gen_root_span_save`
- Test: builds CHAIN span with `input.value` = prompt text
- Test: `llm.model_name` included when model present in input
- Test: `llm.model_name` omitted when model absent

**afterAgentResponse tests:**
- Test: builds LLM span with `output.value` = response text
- Test: parent span ID is the root span saved by `beforeSubmitPrompt`
- Test: `truncate_attr` applied to response

**afterAgentThought tests:**
- Test: builds CHAIN span with `output.value` = thought text
- Test: parent span from root

**beforeShellExecution / afterShellExecution merge tests:**
- Test: before pushes, after pops → merged TOOL span has before's start_ms and after's end (now_ms)
- Test: merged span has command from before-state
- Test: command from after-event overrides before-state command (bash lines 205-206)
- Test: output and exit_code from after-event
- Test: `exit_code` omitted when empty
- Test: no matching before-state (pop returns None) → span still created with now_ms as start
- Test: `truncate_attr` applied to command and output

**beforeMCPExecution / afterMCPExecution merge tests:**
- Test: before pushes tool_name + tool_input, after pops → merged TOOL span
- Test: tool name from after-event overrides before-state (bash lines 285-287)
- Test: missing tool name defaults to "unknown"
- Test: span name is `"MCP: {tool_name}"`
- Test: `truncate_attr` applied to tool_input and result

**beforeReadFile tests:**
- Test: TOOL span with `tool.name: "read_file"`, `input.value: file_path`
- Test: tries keys `file_path`, `filePath`, `path` in order

**afterFileEdit tests:**
- Test: TOOL span with `tool.name: "edit_file"`
- Test: input_value includes edits when present: `"{file_path}: {edits}"`
- Test: input_value is just file_path when no edits

**beforeTabFileRead / afterTabFileEdit tests:**
- Test: same patterns as readFile/fileEdit but with `tool.name: "read_file_tab"` / `"edit_file_tab"`
- Test: span names are `"Tab Read File"` / `"Tab File Edit"`

**stop tests:**
- Test: CHAIN span with `cursor.stop.status` and `cursor.stop.loop_count` when present
- Test: optional attrs omitted when empty
- Test: `state_cleanup_generation` called with gen_id
- Test: parent span from root

**_jq_str tests:**
- Test: first key present → returns its value
- Test: first key missing, second present → returns second
- Test: no keys present → returns default
- Test: value is None → skipped, tries next key
- Test: value is empty string → skipped, tries next key

**Dispatch tests:**
- Test: unknown event → logged, no span sent, permissive response returned
- Test: empty `hook_event_name` → logged, permissive response returned
- Test: missing `generation_id` → trace_id is empty string, handlers still run

**stderr redirect test:**
- Test: `log()` calls during dispatch go to log file, NOT to original stderr
- Test: after `main()` completes, original stdout was used for permissive response (not redirected stderr)

## Task: Codex proxy script
Files: core/hooks/codex/proxy.py (new), tests/test_codex_proxy.py (new)
Depends: collector-ctl-py, codex-adapter

Rewrite `codex-tracing/scripts/codex_proxy.sh` (31 lines) as Python. This is a wrapper installed to the user's PATH that ensures the collector is running before exec-ing the real Codex binary. The bash version uses placeholder strings (`__REAL_CODEX__`, etc.) replaced by the installer.

### Implementation

The proxy lives in `core/hooks/codex/proxy.py` (part of the package) and is registered as a CLI entry point:

```toml
# Add to pyproject.toml [project.scripts]:
arize-codex-proxy = "core.hooks.codex.proxy:main"
```

The installer creates a wrapper at `~/.local/bin/codex` (Unix) or equivalent (Windows) that calls `arize-codex-proxy`. Alternatively, the installer can symlink/alias `codex` → `arize-codex-proxy`.

```python
def main():
    """Codex proxy entry point. Ensures collector running, then execs real codex."""
    try:
        # 1. Load env file (matches bash lines 12-15)
        from core.hooks.codex.adapter import load_env_file
        load_env_file(Path.home() / ".codex" / "arize-env.sh")

        # 2. Ensure collector running (matches bash lines 18-24)
        from core.collector_ctl import collector_ensure
        collector_ensure()
    except Exception:
        pass  # Never prevent codex from starting

    # 3. Find and exec the real codex binary
    real_codex = _find_real_codex()
    if not real_codex:
        print("[arize] Could not find real codex binary on PATH", file=sys.stderr)
        sys.exit(1)

    # 4. exec replaces this process (matches bash line 31: exec "$REAL_CODEX" "$@")
    if os.name == "nt":
        # Windows: no exec, use subprocess with exit code passthrough
        result = subprocess.run([str(real_codex)] + sys.argv[1:])
        sys.exit(result.returncode)
    else:
        os.execvp(str(real_codex), [str(real_codex)] + sys.argv[1:])
```

**`_find_real_codex() -> Path | None`**

```python
def _find_real_codex() -> Path | None:
    """Find the real codex binary on PATH, skipping the proxy itself.

    Strategy:
    1. Get this script's resolved path (handles symlinks)
    2. Scan PATH entries for 'codex' (or 'codex.exe' on Windows)
    3. Skip any that resolve to the same path as this script
    4. Return the first non-self match, or None
    """
    self_path = Path(__file__).resolve()
    # Also check if we're running as an entry point script
    self_entry = Path(sys.argv[0]).resolve() if sys.argv else None

    codex_name = "codex.exe" if os.name == "nt" else "codex"
    for dir_str in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(dir_str) / codex_name
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved == self_path or resolved == self_entry:
            continue
        # Check it's executable
        if os.access(candidate, os.X_OK):
            return candidate
    return None
```

Note: the bash version uses hardcoded `__REAL_CODEX__` (replaced by the installer). The Python version discovers it dynamically at runtime, which is more robust and doesn't require installer templating.

### Expected behavior

- `arize-codex-proxy` ensures collector running, then execs the real codex
- Collector failure doesn't prevent codex from starting (try/except)
- PATH scanning skips the proxy itself (no infinite loop)
- On Unix: `os.execvp` replaces the process (matching bash `exec`)
- On Windows: `subprocess.run` with exit code passthrough
- All args (`sys.argv[1:]`) passed through to the real binary

### Test plan

`tests/test_codex_proxy.py`:
- Test: `_find_real_codex` with a fake PATH containing a mock `codex` binary → returns it
- Test: `_find_real_codex` skips entries that resolve to the proxy itself
- Test: `_find_real_codex` returns None when no codex on PATH
- Test: `load_env_file` called before `collector_ensure` (verify ordering via mock)
- Test: exception in collector_ensure → real codex still found and would be exec'd
- Test: missing env file → no error, proceeds normally

## Task: Per-harness setup scripts
Files: core/setup/claude.py (new), core/setup/codex.py (new), core/setup/cursor.py (new), core/setup/__init__.py (new), tests/test_setup.py (new)
Depends: project-structure-and-constants, config-helper (core/config.py)

Rewrite per-harness `setup.sh` scripts (claude: 137 lines, codex: 264 lines, cursor: 180 lines) as Python modules. These are interactive wizards that prompt for backend credentials and write configuration files. They live in `core/setup/` so they're part of the installable package.

### Implementation

Add CLI entry points:
```toml
# Add to pyproject.toml [project.scripts]:
arize-setup-claude = "core.setup.claude:main"
arize-setup-codex = "core.setup.codex:main"
arize-setup-cursor = "core.setup.cursor:main"
```

**Shared setup logic** — `core/setup/__init__.py`:

```python
"""Shared setup utilities for all harness setup wizards."""

def prompt_backend() -> tuple[str, dict]:
    """Interactive backend selection. Returns (target, credentials_dict).

    Prompts:
    1. Backend choice: Phoenix (1) or Arize AX (2)
    2. If Phoenix: endpoint (default http://localhost:6006)
    3. If Arize: api_key, space_id (required), otlp_endpoint (default otlp.arize.com:443)

    Returns:
        ("phoenix", {"endpoint": "...", "api_key": ""})
        or ("arize", {"endpoint": "...", "api_key": "...", "space_id": "..."})
    """

def prompt_user_id() -> str:
    """Optional user ID prompt. Returns "" if skipped."""

def write_config(target: str, credentials: dict, harness_name: str,
                 project_name: str, user_id: str = "") -> None:
    """Write or merge config.yaml with backend credentials and harness entry.

    If config.yaml exists with valid backend → only add/update the harness entry.
    If no config → create fresh with all fields.
    Uses core.config.load_config / save_config / set_value.
    """

def print_color(msg: str, color: str = "") -> None:
    """Print with ANSI color. No-op on Windows if terminal doesn't support it.

    Colors: "green", "yellow", "blue", "red", "" (no color).
    Uses os.name and sys.stdout.isatty() to decide.
    """
```

**Claude Code setup** — `core/setup/claude.py`:

Replaces `claude-code-tracing/scripts/setup.sh` (137 lines). Claude Code setup is different from Codex/Cursor — it writes env vars to `~/.claude/settings.json` (or `.claude/settings.local.json`) rather than to `config.yaml`. This is because Claude Code hooks read credentials from the settings.json env block.

```python
def main():
    """Entry point for arize-setup-claude."""
    # 1. Choose settings scope (project-local vs global)
    #    matches bash lines 43-61
    choice = input("Where should tracing env vars be stored?\n"
                   "  1) Project-local (.claude/settings.local.json)\n"
                   "  2) Global (~/.claude/settings.json)\n"
                   "Enter choice [1/2]: ").strip()
    settings_path = ...  # resolve based on choice

    # 2. Check existing config (matches bash lines 25-41)
    #    If Phoenix or Arize already configured, ask to overwrite

    # 3. Prompt backend + credentials (shared prompt_backend)

    # 4. Write env vars to settings.json (matches bash lines 81-107)
    #    Read existing JSON, merge .env block, write back
    #    Keys: PHOENIX_ENDPOINT or ARIZE_API_KEY+ARIZE_SPACE_ID+ARIZE_OTLP_ENDPOINT
    #    Always set ARIZE_TRACE_ENABLED=true

    # 5. Optional user ID (matches bash lines 121-131)

    # 6. Also write config.yaml for the collector (shared write_config)
```

JSON merging for settings.json — read/merge/write via `json` module:
```python
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
env_block = settings.setdefault("env", {})
env_block["PHOENIX_ENDPOINT"] = phoenix_endpoint
env_block["ARIZE_TRACE_ENABLED"] = "true"
settings_path.write_text(json.dumps(settings, indent=2))
```

**Codex setup** — `core/setup/codex.py`:

Replaces `codex-tracing/scripts/setup.sh` (264 lines). Codex setup writes to both `config.yaml` and `~/.codex/arize-env.sh` + `~/.codex/config.toml`.

```python
def main():
    """Entry point for arize-setup-codex."""
    # 1. Check existing config.yaml (via core.config.load_config)
    #    If backend already configured → skip credential prompts, just add harness entry

    # 2. If no config → prompt_backend() + write_config()

    # 3. Write ~/.codex/arize-env.sh with export statements
    #    (Still needed even with Python hooks — Codex loads this file)

    # 4. Write/update ~/.codex/config.toml [otel] section
    #    - Read existing file
    #    - Remove old [otel] section if present (line-based: find [otel], delete until next [section])
    #    - Append new [otel] section with notify command
    #    Uses line-based editing — no toml library dependency

    # 5. Optional user_id → write to config.yaml via core.config.set_value

    # 6. Print summary + next steps
```

TOML editing (no library, line-based — replaces bash `awk` section removal):
```python
def _update_toml_otel_section(toml_path: Path, notify_cmd: str) -> None:
    """Add/replace [otel] section in codex config.toml.

    Reads file, removes existing [otel]...[next_section] block,
    appends new [otel] section at the end.
    """
    if toml_path.exists():
        lines = toml_path.read_text().splitlines()
        # Remove existing [otel] section
        filtered = []
        in_otel = False
        for line in lines:
            if line.strip() == "[otel]":
                in_otel = True
                continue
            if in_otel and line.strip().startswith("["):
                in_otel = False
            if not in_otel:
                filtered.append(line)
        lines = filtered
    else:
        lines = []

    # Append new section
    lines.append("")
    lines.append("[otel]")
    lines.append(f'notify = ["{notify_cmd}"]')
    toml_path.write_text("\n".join(lines) + "\n")
```

**Cursor setup** — `core/setup/cursor.py`:

Replaces `cursor-tracing/scripts/setup.sh` (180 lines). Writes `config.yaml` and prints instructions for copying `hooks.json`.

```python
def main():
    """Entry point for arize-setup-cursor."""
    # 1. Check existing config.yaml → skip credential prompts if present
    # 2. If no config → prompt_backend() + write_config()
    # 3. Optional user_id
    # 4. Print summary with next steps:
    #    - Copy hooks.json to ~/.cursor/hooks.json
    #    - Start collector: arize-collector-ctl start
    #    - Open Cursor
```

Note: cursor hooks.json should reference `arize-hook-cursor` (the CLI entry point), not a bash script path.

### Expected behavior

- All three setup wizards work identically to their bash versions
- `input()` replaces `read -rp` for interactive prompts
- JSON settings files are read-merge-written (no data loss)
- TOML editing removes old `[otel]` section before adding new one
- `config.yaml` is written via `core.config` (not heredoc)
- Color output degrades gracefully on Windows
- All three are available as CLI commands after `pip install .`

### Test plan

`tests/test_setup.py`:

**Shared utility tests:**
- Test: `prompt_backend` with input "1" → returns ("phoenix", {endpoint, api_key})
- Test: `prompt_backend` with input "2" + credentials → returns ("arize", {api_key, space_id, endpoint})
- Test: `write_config` creates new config.yaml with correct structure
- Test: `write_config` merges harness into existing config without clobbering backend
- Test: `print_color` with non-tty → no ANSI codes in output

**Claude setup tests:**
- Test: settings.json created with correct env block for Phoenix
- Test: settings.json created with correct env block for Arize AX
- Test: existing settings.json merged (other keys preserved)
- Test: overwrite prompt — input "n" → exits without changes

**Codex setup tests:**
- Test: existing config → skips credential prompts, adds harness entry only
- Test: `~/.codex/arize-env.sh` written with correct export statements
- Test: `_update_toml_otel_section` adds [otel] to empty file
- Test: `_update_toml_otel_section` replaces existing [otel] section
- Test: `_update_toml_otel_section` preserves other sections in config.toml

**Cursor setup tests:**
- Test: config.yaml written with cursor harness entry
- Test: existing config → harness entry added, backend preserved

## Task: Install script
Files: install.py (new), tests/test_install.py (new)
Depends: collector-ctl-py, per-harness-setup-scripts

Rewrite `install.sh` (1458 lines) as a cross-platform Python installer. This is the largest task. The installer is invoked via `curl | python3` for remote install, or `python3 install.py` for local install.

### Implementation

**CLI interface** — matches bash:
```
python3 install.py claude    # install claude-code harness
python3 install.py codex     # install codex harness
python3 install.py cursor    # install cursor harness
python3 install.py update    # update existing installation
python3 install.py uninstall # uninstall (prompts for confirmation)
```

**Module structure** — `install.py` at repo root (NOT inside `core/` — it runs before the package is installed):

```python
#!/usr/bin/env python3
"""Arize Agent Kit — Cross-platform installer."""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

# --- Constants (duplicated from core/constants.py since core isn't installed yet) ---
INSTALL_DIR = Path.home() / ".arize" / "harness"
CONFIG_FILE = INSTALL_DIR / "config.yaml"
VENV_DIR = INSTALL_DIR / "venv"
BIN_DIR = INSTALL_DIR / "bin"
PID_DIR = INSTALL_DIR / "run"
LOG_DIR = INSTALL_DIR / "logs"

REPO_URL = "https://github.com/Arize-ai/arize-agent-kit.git"
TARBALL_URL = "https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/main.tar.gz"
```

Important: `install.py` cannot import from `core/` at startup because `core/` isn't installed yet. It must bootstrap itself. After creating the venv and running `pip install .`, it can import from `core/` for config operations.

**Major functions:**

1. **`download_or_update()`** — replaces bash lines ~130-190:
   - If `git` available: `git clone` or `git pull`
   - Else: download tarball via `urllib.request`, extract with `tarfile`
   - Target: `INSTALL_DIR/src/` (or directly into `INSTALL_DIR` for the core/ package)

2. **`setup_venv(python_cmd, backend_target)`** — replaces bash `setup_collector_venv()` (lines 71-116):
   - Find Python 3.9+: try `python3`, `python`, common paths, pyenv, homebrew
   - Create venv: `subprocess.run([python_cmd, "-m", "venv", str(VENV_DIR)])`
   - Install package: `pip install .` (installs core + pyyaml + CLI entry points)
   - If Arize AX: also `pip install opentelemetry-proto grpcio`
   - Idempotent: skip if venv exists and packages are up to date

3. **`write_config(backend_target, credentials, harness_name, project_name)`** — replaces bash config writing (lines 306-340):
   - After venv exists, use `core.config` via venv python
   - Or write YAML directly with `yaml.safe_dump` (since we have PyYAML in the venv)

4. **`setup_claude()`** — replaces bash `setup_claude()` (lines 490-598):
   - Write hook commands to `~/.claude/settings.json`
   - Hook commands are CLI entry point names: `arize-hook-session-start`, etc.
   - Uses full venv path as prefix if CLI commands aren't on PATH:
     `~/.arize/harness/venv/bin/arize-hook-session-start`

5. **`setup_codex()`** — replaces bash `setup_codex()` (lines 742-1100):
   - Write `~/.codex/config.toml` with `notify = ["arize-hook-codex-notify"]`
   - Write `~/.codex/arize-env.sh`
   - Install codex proxy wrapper

6. **`setup_cursor()`** — replaces bash `setup_cursor()` (lines 600-740):
   - Write `~/.cursor/hooks.json` with `arize-hook-cursor` command
   - Or print instructions for manual hooks.json setup

7. **`uninstall(harness=None)`** — replaces bash `_uninstall_*` functions (lines 1170-1300):
   - Stop collector: `arize-collector-ctl stop` or direct Python call
   - Remove harness entry from config.yaml
   - Remove harness-specific files (hooks, proxy, env file)
   - Optionally remove shared files (venv, config, logs) with confirmation

8. **`start_collector()`** — replaces bash collector start in install flow:
   - Call `arize-collector-ctl start` via the venv

**Terminal interaction:**
- `input()` for all prompts
- ANSI colors via helper function (skip on Windows if not supported)
- Progress messages: `info()`, `warn()`, `err()` matching bash output format

**Cross-platform considerations:**
- PATH manipulation: add venv `bin/` (or `Scripts/`) to PATH in shell profile
  - Unix: append to `~/.bashrc` / `~/.zshrc` / `~/.profile`
  - Windows: use `setx` or print instructions
- Hook command paths: use full venv path as fallback if PATH modification isn't feasible
- File permissions: `os.chmod(CONFIG_FILE, 0o600)` — Windows ignores this silently, which is acceptable

### Expected behavior

- `python3 install.py claude` downloads repo, creates venv, installs package, writes config, registers hooks
- `python3 install.py update` updates repo and reinstalls package
- `python3 install.py uninstall` stops collector, removes files (with confirmation)
- Idempotent — safe to run multiple times
- Works on macOS, Linux, and Windows
- Hook registrations use CLI entry point names, with full venv path as fallback

### Test plan

`tests/test_install.py`:
- Test: `python3 -c "import ast; ast.parse(open('install.py').read())"` — syntax valid
- Test: `find_python()` finds a working Python 3.9+ interpreter
- Test: `setup_venv()` creates venv directory with pip (mock subprocess, verify commands)
- Test: config writing produces valid YAML with correct structure
- Test: `setup_claude()` writes correct hook commands to settings.json (mock filesystem)
- Test: `setup_codex()` writes correct [otel] section to config.toml
- Test: `setup_cursor()` writes correct hooks.json
- Test: `uninstall()` removes expected files (mock filesystem)
- Test: CLI arg parsing — "claude", "codex", "cursor", "update", "uninstall" all recognized
- Test: unknown arg → error message

## Task: Hook registration updates
Files: claude-code-tracing/.claude-plugin/plugin.json, SKILL.md files, README.md files
Depends: claude-code-hook-handlers, codex-hook-handler, cursor-hook-handler, install-script

Update hook registrations and documentation to reference CLI entry point commands instead of bash scripts.

### Implementation

**`claude-code-tracing/.claude-plugin/plugin.json`**:

Change all hook commands from `bash ${CLAUDE_PLUGIN_ROOT}/hooks/<event>.sh` to CLI entry points. Since plugin.json hooks may need the full venv path (the venv `bin/` may not be on PATH), use the full path pattern:

```json
{
  "hooks": {
    "SessionStart": [{
      "type": "command",
      "command": "~/.arize/harness/venv/bin/arize-hook-session-start"
    }],
    "Stop": [{
      "type": "command",
      "command": "~/.arize/harness/venv/bin/arize-hook-stop"
    }]
  }
}
```

Alternatively, if Claude Code resolves commands via PATH and the installer added the venv to PATH, use short names: `arize-hook-session-start`. Document both approaches — the installer should choose based on whether it successfully modified PATH.

**Codex config.toml**:
```toml
[otel]
notify = ["~/.arize/harness/venv/bin/arize-hook-codex-notify"]
```

**Cursor hooks.json**:
```json
{
  "hooks": [
    {
      "event": "*",
      "command": "~/.arize/harness/venv/bin/arize-hook-cursor"
    }
  ]
}
```

**SKILL.md files** (all three harnesses):
- Replace all `bash .../hook.sh` references with CLI entry point commands
- Replace `jq` config manipulation examples with `arize-config get/set` commands
- Replace `source core/collector_ctl.sh && collector_start` with `arize-collector-ctl start`
- Update troubleshooting sections

**README.md files** (root + all three harnesses):
- Update architecture sections to describe Python hooks + CLI entry points
- Remove bash/jq/curl prerequisites — only Python 3.9+ required
- Update install commands
- Update troubleshooting with new command names

**DEVELOPMENT.md**:
- Update dev setup to use `pip install -e ".[dev]"` + `pytest`
- Document the CLI entry points
- Remove bash-specific development notes

### Expected behavior

- All three harnesses invoke Python CLI entry points
- Documentation is consistent — no remaining bash/jq/curl references
- Works on macOS, Linux, and Windows

### Test plan

- `grep -r "bash " claude-code-tracing/ codex-tracing/ cursor-tracing/ --include="*.json" --include="*.md"` → no hook references
- `grep -r "\.sh" claude-code-tracing/ codex-tracing/ cursor-tracing/ --include="*.json" --include="*.md"` → no hook script references
- `grep -r "jq " --include="*.md"` → no jq references in docs (except possibly historical context)
- Verify `plugin.json` is valid JSON
- Verify every CLI command referenced in docs exists in `pyproject.toml [project.scripts]`

## Task: Cleanup old bash scripts
Files: all .sh files in repo
Depends: hook-registration-updates, install-script

Remove all superseded bash scripts after Python replacements are validated and all references updated.

### Implementation

**Remove these files:**

Core (2 files):
- `core/collector_ctl.sh` → replaced by `core/collector_ctl.py`
- `core/common.sh` → replaced by `core/common.py`

Claude Code hooks (10 files):
- `claude-code-tracing/hooks/common.sh` → replaced by `core/hooks/claude/adapter.py`
- `claude-code-tracing/hooks/session_start.sh` → `arize-hook-session-start`
- `claude-code-tracing/hooks/pre_tool_use.sh` → `arize-hook-pre-tool-use`
- `claude-code-tracing/hooks/post_tool_use.sh` → `arize-hook-post-tool-use`
- `claude-code-tracing/hooks/user_prompt_submit.sh` → `arize-hook-user-prompt-submit`
- `claude-code-tracing/hooks/stop.sh` → `arize-hook-stop`
- `claude-code-tracing/hooks/subagent_stop.sh` → `arize-hook-subagent-stop`
- `claude-code-tracing/hooks/notification.sh` → `arize-hook-notification`
- `claude-code-tracing/hooks/permission_request.sh` → `arize-hook-permission-request`
- `claude-code-tracing/hooks/session_end.sh` → `arize-hook-session-end`

Codex (3 files):
- `codex-tracing/hooks/common.sh` → replaced by `core/hooks/codex/adapter.py`
- `codex-tracing/hooks/notify.sh` → `arize-hook-codex-notify`
- `codex-tracing/scripts/codex_proxy.sh` → `arize-codex-proxy`

Cursor (2 files):
- `cursor-tracing/hooks/common.sh` → replaced by `core/hooks/cursor/adapter.py`
- `cursor-tracing/hooks/hook-handler.sh` → `arize-hook-cursor`

Setup scripts (3 files):
- `claude-code-tracing/scripts/setup.sh` → `arize-setup-claude`
- `codex-tracing/scripts/setup.sh` → `arize-setup-codex`
- `cursor-tracing/scripts/setup.sh` → `arize-setup-cursor`

Installer (1 file):
- `install.sh` → `install.py`

**Total: 21 .sh files removed.**

**Keep:**
- `~/.codex/arize-env.sh` — user-side file, not in repo. The Python Codex hooks still read it via `load_env_file()`.

**Post-removal checks:**
- `grep -r "\.sh" --include="*.py" --include="*.json" --include="*.md"` — verify no remaining references to removed scripts (except historical context in changelogs, if any)
- `grep -r "bash " --include="*.py"` — verify no subprocess bash calls
- Update `.gitignore` if any patterns reference `.sh` files

### Expected behavior

- No `.sh` files remain in the repository (outside `.git/` and `.venv/`)
- All Python tests pass
- All CLI entry points work: `arize-hook-*`, `arize-collector-ctl`, `arize-config`, `arize-setup-*`, `arize-codex-proxy`

### Test plan

- `find . -name "*.sh" -not -path "./.git/*" -not -path "./.venv/*"` → returns empty
- `pytest tests/` → all tests pass
- Integration smoke test (`@pytest.mark.slow`):
  1. `python3 install.py claude` → completes without error
  2. `arize-collector-ctl status` → responds
  3. `arize-hook-session-start` with sample JSON on stdin → no crash
  4. `arize-collector-ctl stop` → collector stopped
  5. `python3 install.py uninstall` → cleans up