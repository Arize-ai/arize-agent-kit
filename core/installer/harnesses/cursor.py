#!/usr/bin/env python3
"""Cursor harness installer — register/remove hooks in ~/.cursor/hooks.json.

Ports setup_cursor() and _uninstall_cursor() from install.sh into a
HarnessInstaller subclass that the CLI and VS Code extension can call.
"""
from __future__ import annotations

import json
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.constants import STATE_BASE_DIR, VENV_DIR
from core.installer.harnesses.base import HarnessInstaller

# The 12 Cursor hook events that Arize registers.
CURSOR_HOOK_EVENTS: List[str] = [
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
]


def _cursor_dir() -> Path:
    """Return the Cursor config directory (~/.cursor)."""
    return Path.home() / ".cursor"


def _hooks_file() -> Path:
    """Return the path to ~/.cursor/hooks.json."""
    return _cursor_dir() / "hooks.json"


def _hook_command() -> str:
    """Return the full path to the arize-hook-cursor entry point in the venv."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "arize-hook-cursor.exe")
    return str(VENV_DIR / "bin" / "arize-hook-cursor")


def _load_hooks(hooks_path: Path) -> Dict[str, Any]:
    """Load hooks.json, returning a valid structure even on missing/corrupt file."""
    if hooks_path.is_file():
        try:
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "hooks": {}}


def _save_hooks(hooks_path: Path, data: Dict[str, Any]) -> None:
    """Write hooks.json with a trailing newline."""
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _is_arize_hook(entry: Dict[str, Any]) -> bool:
    """Return True if a hook entry belongs to Arize (match on 'arize' in command)."""
    cmd = entry.get("command", "")
    return "arize" in cmd.lower()


class CursorInstaller(HarnessInstaller):
    """Install / uninstall Arize tracing hooks for Cursor IDE."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__(harness_name="cursor", config_path=config_path)

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def install(
        self,
        backend: str = "local",
        credentials: Optional[Dict[str, str]] = None,
        user_id: str = "",
        non_interactive: bool = False,
    ) -> None:
        """Register Arize hooks in ~/.cursor/hooks.json and update config.yaml."""
        hooks_path = _hooks_file()
        hook_cmd = _hook_command()

        # Back up existing hooks.json before modifying
        if hooks_path.is_file():
            shutil.copy2(hooks_path, str(hooks_path) + ".bak")

        hooks_data = _load_hooks(hooks_path)
        hooks = hooks_data.setdefault("hooks", {})

        for event in CURSOR_HOOK_EVENTS:
            event_list: List[Dict[str, Any]] = hooks.setdefault(event, [])
            # Idempotent — skip if already present
            if not any(h.get("command") == hook_cmd for h in event_list):
                event_list.append({"command": hook_cmd})

        _save_hooks(hooks_path, hooks_data)

        # Create per-harness state directory
        state_dir = STATE_BASE_DIR / "cursor"
        state_dir.mkdir(parents=True, exist_ok=True)

        # Register in config.yaml
        self._add_harness_to_config("cursor")

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self, non_interactive: bool = False) -> None:
        """Remove Arize hooks from ~/.cursor/hooks.json, clean up state."""
        hooks_path = _hooks_file()

        if hooks_path.is_file():
            hooks_data = _load_hooks(hooks_path)
            hooks = hooks_data.get("hooks", {})

            # Filter out Arize entries from each event
            new_hooks: Dict[str, List[Dict[str, Any]]] = {}
            for event, entries in hooks.items():
                if not isinstance(entries, list):
                    continue
                filtered = [h for h in entries if not _is_arize_hook(h)]
                if filtered:
                    new_hooks[event] = filtered

            if new_hooks:
                hooks_data["hooks"] = new_hooks
                _save_hooks(hooks_path, hooks_data)
            else:
                # No hooks remain — remove the file entirely
                hooks_path.unlink()

        # Remove state directory
        state_dir = STATE_BASE_DIR / "cursor"
        if state_dir.is_dir():
            shutil.rmtree(state_dir)

        # Remove from config.yaml
        self._remove_harness_from_config()

    # ------------------------------------------------------------------
    # Status queries
    # ------------------------------------------------------------------

    def is_installed(self) -> bool:
        """Return True if cursor is registered in config.yaml."""
        from core.config import get_value

        config = self._load()
        return get_value(config, "harnesses.cursor") is not None

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for the extension sidebar.

        Keys:
            installed (bool): whether cursor is in config.yaml
            hooks_configured (bool): whether hooks.json contains Arize entries
            registered_events (int): number of hook events with an Arize entry
        """
        installed = self.is_installed()

        hooks_path = _hooks_file()
        hooks_configured = False
        registered_events = 0

        if hooks_path.is_file():
            hooks_data = _load_hooks(hooks_path)
            hooks = hooks_data.get("hooks", {})
            for _event, entries in hooks.items():
                if isinstance(entries, list) and any(_is_arize_hook(h) for h in entries):
                    hooks_configured = True
                    registered_events += 1

        return {
            "installed": installed,
            "hooks_configured": hooks_configured,
            "registered_events": registered_events,
        }
