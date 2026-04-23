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
