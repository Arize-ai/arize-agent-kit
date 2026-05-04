"""Constants for the Copilot tracing harness installer."""

from __future__ import annotations

from pathlib import Path

HARNESS_NAME = "copilot"
HOOKS_DIR = Path(".github/hooks")  # project-local (relative)
CLI_HOOKS_FILE = HOOKS_DIR / "hooks.json"

# VS Code mode -- one JSON file per event, {event -> (filename, entry_point)}
VSCODE_EVENTS: dict[str, tuple[str, str]] = {
    "SessionStart": ("session-start.json", "arize-hook-copilot-session-start"),
    "UserPromptSubmit": ("user-prompt.json", "arize-hook-copilot-user-prompt"),
    "PreToolUse": ("pre-tool.json", "arize-hook-copilot-pre-tool"),
    "PostToolUse": ("post-tool.json", "arize-hook-copilot-post-tool"),
    "Stop": ("stop.json", "arize-hook-copilot-stop"),
    "SubagentStop": ("subagent-stop.json", "arize-hook-copilot-subagent-stop"),
}

# CLI mode -- single hooks.json, {camelCaseEvent -> entry_point}
CLI_EVENTS: dict[str, str] = {
    "sessionStart": "arize-hook-copilot-session-start",
    "userPromptSubmitted": "arize-hook-copilot-user-prompt",
    "preToolUse": "arize-hook-copilot-pre-tool",
    "postToolUse": "arize-hook-copilot-post-tool",
    "errorOccurred": "arize-hook-copilot-error",
    "sessionEnd": "arize-hook-copilot-session-end",
}
