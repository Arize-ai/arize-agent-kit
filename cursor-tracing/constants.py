"""Constants for the Cursor tracing harness."""

from pathlib import Path

HARNESS_NAME = "cursor"
HOOKS_FILE = Path.home() / ".cursor" / "hooks.json"
HOOK_BIN_NAME = "arize-hook-cursor"

# 12 events, all routed to a single CLI entry point (the handler dispatches
# based on hook_event_name in the JSON payload).
HOOK_EVENTS = (
    "beforeSubmitPrompt",
    "afterAgentResponse",
    "afterAgentThought",
    "beforeShellExecution",
    "afterShellExecution",
    "beforeMCPExecution",
    "afterMCPExecution",
    "beforeReadFile",
    "afterFileEdit",
    "stop",
    "beforeTabFileRead",
    "afterTabFileEdit",
)
