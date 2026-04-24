"""Constants for the Claude Code harness installer."""

from pathlib import Path

HARNESS_NAME = "claude-code"
DISPLAY_NAME = "Claude Code"
HARNESS_HOME = ".claude"   # ~/.claude — presence check for soft install detection
HARNESS_BIN = "claude"     # binary name for shutil.which() fallback

SETTINGS_FILE = Path.home() / ".claude" / "settings.json"

# event name → venv binary basename
HOOK_EVENTS = {
    "SessionStart": "arize-hook-session-start",
    "UserPromptSubmit": "arize-hook-user-prompt-submit",
    "PreToolUse": "arize-hook-pre-tool-use",
    "PostToolUse": "arize-hook-post-tool-use",
    "Stop": "arize-hook-stop",
    "SubagentStop": "arize-hook-subagent-stop",
    "Notification": "arize-hook-notification",
    "PermissionRequest": "arize-hook-permission-request",
    "SessionEnd": "arize-hook-session-end",
}

# Env keys written into settings.json by the installer. Uninstall pops
# any of these present so stale values don't linger after teardown.
ARIZE_ENV_KEYS = (
    "ARIZE_TRACE_ENABLED",
    "ARIZE_PROJECT_NAME",
    "ARIZE_USER_ID",
    "ARIZE_API_KEY",
    "ARIZE_SPACE_ID",
    "ARIZE_OTLP_ENDPOINT",
    "PHOENIX_ENDPOINT",
    "PHOENIX_API_KEY",
    "ARIZE_DRY_RUN",
    "ARIZE_VERBOSE",
    "ARIZE_LOG_FILE",
)
