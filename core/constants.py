#!/usr/bin/env python3
"""Single source of truth for all filesystem paths used by arize-agent-kit.

Every module that needs a path imports it from here. Tests monkeypatch these
values via the tmp_harness_dir fixture to avoid touching the real filesystem.
"""
from pathlib import Path

# --- Base layout ---
BASE_DIR = Path.home() / ".arize" / "harness"
CONFIG_FILE = BASE_DIR / "config.yaml"

# --- Runtime directories ---
PID_DIR = BASE_DIR / "run"
LOG_DIR = BASE_DIR / "logs"
BIN_DIR = BASE_DIR / "bin"
VENV_DIR = BASE_DIR / "venv"

# --- Codex buffer service runtime ---
CODEX_BUFFER_BIN = BIN_DIR / "arize-codex-buffer"
CODEX_BUFFER_PID_FILE = PID_DIR / "codex-buffer.pid"
CODEX_BUFFER_LOG_FILE = LOG_DIR / "codex-buffer.log"

# --- Buffer service network defaults ---
DEFAULT_BUFFER_HOST = "127.0.0.1"
DEFAULT_BUFFER_PORT = 4318

# --- Per-harness state ---
STATE_BASE_DIR = BASE_DIR / "state"

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
