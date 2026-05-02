#!/usr/bin/env python3
"""Gemini adapter — single-mode (CLI-only) session resolution, initialization, and GC.

Gemini CLI provides GEMINI_SESSION_ID as an env var on every hook invocation,
so no PID-based session key derivation or dual-mode detection is needed.
"""
from __future__ import annotations

import os
import time

from core.common import StateManager, env, generate_span_id, generate_trace_id, get_timestamp_ms, log
from core.constants import HARNESSES, STATE_BASE_DIR

# --- Module-level constants derived from HARNESSES ---
_HARNESS = HARNESSES["gemini"]
SERVICE_NAME = _HARNESS["service_name"]  # "gemini"
SCOPE_NAME = _HARNESS["scope_name"]  # "arize-gemini-plugin"
STATE_DIR = STATE_BASE_DIR / _HARNESS["state_subdir"]  # ~/.arize/harness/state/gemini

# Route hook stderr to a per-harness log file unless the user already set one.
os.environ.setdefault("ARIZE_LOG_FILE", str(_HARNESS["default_log_file"]))


def check_requirements() -> bool:
    """Return True if env.trace_enabled is True. Create STATE_DIR if so."""
    if not env.trace_enabled:
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return True


def resolve_session(input_json: dict) -> StateManager:
    """Build a StateManager keyed off GEMINI_SESSION_ID env (preferred),
    else input_json.get('session_id'), else a generated trace ID.
    State file: STATE_DIR / f'state_{key}.yaml'.
    Lock path: STATE_DIR / f'.lock_{key}'.
    Calls sm.init_state() before returning.
    """
    key = os.environ.get("GEMINI_SESSION_ID", "")
    if not key:
        key = input_json.get("session_id", "")
    if not key:
        key = generate_trace_id()

    state_file = STATE_DIR / f"state_{key}.yaml"
    lock_path = STATE_DIR / f".lock_{key}"

    sm = StateManager(
        state_dir=STATE_DIR,
        state_file=state_file,
        lock_path=lock_path,
    )
    sm.init_state()
    return sm


def ensure_session_initialized(state: StateManager, input_json: dict) -> None:
    """Idempotent. If state already has 'session_id', no-op.
    Otherwise set: session_id (= the resolved key), session_start_time,
    project_name (= env.project_name or basename of cwd or basename of os.getcwd()),
    trace_count = '0', tool_count = '0', user_id (= env.user_id or '').
    """
    existing = state.get("session_id")
    if existing is not None:
        return

    # session_id: derive from state file name
    session_id = state.state_file.stem.replace("state_", "", 1) if state.state_file else generate_trace_id()

    # project_name
    project_name = env.project_name
    if not project_name:
        cwd = input_json.get("cwd", "")
        project_name = os.path.basename(cwd) if cwd else os.path.basename(os.getcwd())

    state.set("session_id", session_id)
    state.set("session_start_time", str(get_timestamp_ms()))
    state.set("project_name", project_name)
    state.set("trace_count", "0")
    state.set("tool_count", "0")

    user_id = env.user_id
    state.set("user_id", user_id)

    log(f"Session initialized: {session_id}")


def gc_stale_state_files() -> None:
    """Best-effort cleanup. Remove state files (and their lock files) where
    the .yaml file's mtime is older than 24h.
    """
    if not STATE_DIR.is_dir():
        return
    cutoff = time.time() - 86400
    for f in STATE_DIR.glob("state_*.yaml"):
        try:
            if f.stat().st_mtime < cutoff:
                key = f.stem.replace("state_", "", 1)
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
                lock_path = STATE_DIR / f".lock_{key}"
                if lock_path.is_dir():
                    try:
                        lock_path.rmdir()
                    except OSError:
                        pass
                elif lock_path.is_file():
                    try:
                        lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        except OSError:
            pass
