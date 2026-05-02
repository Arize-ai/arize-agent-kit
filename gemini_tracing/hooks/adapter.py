"""Gemini adapter — session resolution, initialization, and requirements check.

Simpler than Copilot: no dual-mode, no PID-based session keys.
Gemini CLI provides GEMINI_SESSION_ID as an env var on every hook invocation.
"""
import os

from core.common import StateManager, env, generate_trace_id, get_timestamp_ms, log
from core.constants import HARNESSES, STATE_BASE_DIR

# --- Module-level constants derived from HARNESSES ---
_HARNESS = HARNESSES["gemini"]
SERVICE_NAME = _HARNESS["service_name"]  # "gemini"
SCOPE_NAME = _HARNESS["scope_name"]  # "arize-gemini-plugin"
STATE_DIR = STATE_BASE_DIR / _HARNESS["state_subdir"]  # ~/.arize/harness/state/gemini

# Route hook stderr to a per-harness log file unless the user already set one.
os.environ.setdefault("ARIZE_LOG_FILE", str(_HARNESS["default_log_file"]))


def resolve_session(input_json: dict) -> StateManager:
    """Resolve the per-session state file from GEMINI_SESSION_ID env var.

    Returns a StateManager instance with state_file and lock_path set.
    Calls init_state() to ensure the file exists.
    """
    session_key = os.environ.get("GEMINI_SESSION_ID", "") or generate_trace_id()

    state_file = STATE_DIR / f"state_{session_key}.yaml"
    lock_path = STATE_DIR / f".lock_{session_key}"

    sm = StateManager(
        state_dir=STATE_DIR,
        state_file=state_file,
        lock_path=lock_path,
    )
    sm.init_state()
    return sm


def ensure_session_initialized(state: StateManager, input_json: dict) -> None:
    """Idempotent session initialization. No-op if session_id already in state.

    Sets the following state keys:
    - session_id: from GEMINI_SESSION_ID env or generate_trace_id()
    - session_start_time: get_timestamp_ms() as string
    - project_name: from ARIZE_PROJECT_NAME env, or basename of input_json["cwd"], or cwd
    - trace_count: "0"
    - tool_count: "0"
    - user_id: from env.user_id
    """
    existing = state.get("session_id")
    if existing is not None:
        return

    session_id = os.environ.get("GEMINI_SESSION_ID", "") or generate_trace_id()

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


def check_requirements() -> bool:
    """Check if tracing is enabled and initialize state directory.

    Returns False (and the hook should exit 0) if tracing is disabled.
    """
    if not env.trace_enabled:
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return True
