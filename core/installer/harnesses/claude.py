#!/usr/bin/env python3
"""Claude Code harness installer.

Registers hooks, plugin reference, and env vars in Claude's settings.json.
Replaces the setup_claude() and cleanup_claude_config() bash functions from
install.sh with a proper Python module.
"""
from __future__ import annotations

import json
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import get_value
from core.constants import BASE_DIR, STATE_BASE_DIR, VENV_DIR
from core.installer.harnesses.base import HarnessInstaller
from core.setup import info, write_config


# ---------------------------------------------------------------------------
# Hook event -> entry-point mapping (matches pyproject.toml [project.scripts])
# ---------------------------------------------------------------------------

HOOK_EVENTS: Dict[str, str] = {
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

# Env keys that we write during install and remove during uninstall.
_ARIZE_ENV_KEYS = frozenset({
    "ARIZE_TRACE_ENABLED",
    "PHOENIX_ENDPOINT",
    "PHOENIX_API_KEY",
    "ARIZE_API_KEY",
    "ARIZE_SPACE_ID",
    "ARIZE_OTLP_ENDPOINT",
    "ARIZE_PROJECT_NAME",
    "ARIZE_USER_ID",
    "ARIZE_DRY_RUN",
    "ARIZE_VERBOSE",
    "ARIZE_LOG_FILE",
})


# ---------------------------------------------------------------------------
# Settings-file helpers (JSON read/write for Claude's settings.json)
# ---------------------------------------------------------------------------

def _load_settings(settings_path: Path) -> dict:
    """Load JSON settings, returning empty dict if missing or malformed."""
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(settings_path: Path, settings: dict) -> None:
    """Write settings dict as formatted JSON."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _hook_bin_path(entry_point: str) -> str:
    """Return the full path to a venv entry-point script."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / entry_point)
    return str(VENV_DIR / "bin" / entry_point)


def _plugin_dir() -> str:
    """Return the path to the Claude Code tracing plugin directory."""
    return str(BASE_DIR / "claude-code-tracing")


def _settings_path_for_scope(scope: str) -> Path:
    """Return the settings file path for the given scope."""
    if scope == "global":
        return Path.home() / ".claude" / "settings.json"
    return Path(".claude") / "settings.local.json"


# ---------------------------------------------------------------------------
# Matching helpers (used by both install and uninstall)
# ---------------------------------------------------------------------------

def _is_arize_plugin(entry: Any) -> bool:
    """Return True if a plugin entry was created by this installer."""
    if isinstance(entry, dict):
        path = entry.get("path", "")
        return "arize" in path.lower()
    if isinstance(entry, str):
        return "arize" in entry.lower()
    return False


def _is_arize_hook(command: str) -> bool:
    """Return True if a hook command string looks like one of ours."""
    return "arize" in command.lower()


# ---------------------------------------------------------------------------
# ClaudeInstaller
# ---------------------------------------------------------------------------

class ClaudeInstaller(HarnessInstaller):
    """Install/uninstall the Arize tracing hooks for Claude Code."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__(harness_name="claude-code", config_path=config_path)

    # ------------------------------------------------------------------ install

    def install(
        self,
        backend: str = "local",
        credentials: Optional[Dict[str, str]] = None,
        user_id: str = "",
        non_interactive: bool = False,
        scope: str = "global",
        project_name: str = "claude-code",
    ) -> None:
        """Register hooks, write env vars, and update config.yaml."""
        credentials = credentials or {}
        settings_path = _settings_path_for_scope(scope)

        # Load (or create) settings
        settings = _load_settings(settings_path)

        # --- Plugin reference ---
        self._ensure_plugin(settings)

        # --- Hook registration ---
        self._ensure_hooks(settings)

        # --- Env vars ---
        self._write_env_vars(settings, backend, credentials, user_id)

        # Persist
        _save_settings(settings_path, settings)

        # Update shared config.yaml
        self._add_harness_to_config(project_name)
        write_config(
            backend,
            credentials,
            self.harness_name,
            project_name,
            user_id=user_id,
            config_path=self._config_path,
        )

        info(f"Claude Code configured (scope={scope}, backend={backend})")

    # ---------------------------------------------------------------- uninstall

    def uninstall(self, non_interactive: bool = False) -> None:
        """Remove all Arize traces from Claude Code settings and config.yaml."""
        # Process both global and local settings files
        for settings_path in (
            Path.home() / ".claude" / "settings.json",
            Path(".claude") / "settings.local.json",
        ):
            if not settings_path.is_file():
                continue

            settings = _load_settings(settings_path)
            changed = False

            # Remove plugin references
            if self._remove_plugins(settings):
                changed = True

            # Remove hook entries
            if self._remove_hooks(settings):
                changed = True

            # Remove env vars
            if self._remove_env_vars(settings):
                changed = True

            if changed:
                if not non_interactive:
                    confirm = input(
                        f"Remove Arize config from {settings_path}? [y/N]: "
                    ).strip()
                    if confirm.lower() != "y":
                        info(f"Skipped {settings_path}")
                        continue

                _save_settings(settings_path, settings)
                info(f"Cleaned {settings_path}")

        # Remove per-harness state directory
        state_dir = STATE_BASE_DIR / "claude-code"
        if state_dir.is_dir():
            if non_interactive or _confirm(f"Remove state directory {state_dir}?"):
                shutil.rmtree(state_dir)
                info(f"Removed {state_dir}")

        # Remove from config.yaml
        self._remove_harness_from_config()
        info("Claude Code harness removed from config.yaml")

    # ------------------------------------------------------------- is_installed

    def is_installed(self) -> bool:
        """Check if claude-code is registered in config.yaml."""
        config = self._load()
        return get_value(config, f"harnesses.{self.harness_name}") is not None

    # -------------------------------------------------------------- get_status

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for the extension sidebar."""
        config = self._load()
        harness_cfg = get_value(config, f"harnesses.{self.harness_name}") or {}
        project_name = harness_cfg.get("project_name", "")

        # Determine which scope has hooks registered
        scope = None
        hooks_registered = False
        for label, path in (
            ("global", Path.home() / ".claude" / "settings.json"),
            ("local", Path(".claude") / "settings.local.json"),
        ):
            if path.is_file():
                settings = _load_settings(path)
                hooks = settings.get("hooks", {})
                for event_hooks in hooks.values():
                    if isinstance(event_hooks, list):
                        for entry in event_hooks:
                            cmd = entry.get("command", "") if isinstance(entry, dict) else str(entry)
                            if _is_arize_hook(cmd):
                                scope = label
                                hooks_registered = True
                                break
                    if hooks_registered:
                        break
            if hooks_registered:
                break

        return {
            "harness": self.harness_name,
            "installed": self.is_installed(),
            "project_name": project_name,
            "scope": scope,
            "hooks_registered": hooks_registered,
        }

    # ----------------------------------------------------------------- private

    def _ensure_plugin(self, settings: dict) -> None:
        """Add plugin entry if not already present (idempotent)."""
        plugins: List[Any] = settings.setdefault("plugins", [])
        plugin_path = _plugin_dir()

        # Check for existing entry
        for entry in plugins:
            if isinstance(entry, dict) and entry.get("path") == plugin_path:
                return
            if isinstance(entry, str) and entry == plugin_path:
                return

        plugins.append({"type": "local", "path": plugin_path})

    def _ensure_hooks(self, settings: dict) -> None:
        """Register all 9 hook events (idempotent)."""
        hooks: dict = settings.setdefault("hooks", {})

        for event, entry_point in HOOK_EVENTS.items():
            event_hooks: List[Any] = hooks.setdefault(event, [])
            cmd = _hook_bin_path(entry_point)

            # Skip if already present
            already = False
            for entry in event_hooks:
                existing_cmd = entry.get("command", "") if isinstance(entry, dict) else str(entry)
                if existing_cmd == cmd or _is_arize_hook(existing_cmd):
                    already = True
                    break

            if not already:
                event_hooks.append({"command": cmd})

    def _write_env_vars(
        self,
        settings: dict,
        backend: str,
        credentials: Dict[str, str],
        user_id: str,
    ) -> None:
        """Write backend-specific env vars into settings."""
        env: dict = settings.setdefault("env", {})
        env["ARIZE_TRACE_ENABLED"] = "true"

        if backend == "phoenix":
            env["PHOENIX_ENDPOINT"] = credentials.get("endpoint", "http://localhost:6006")
        elif backend == "arize":
            env["ARIZE_API_KEY"] = credentials.get("api_key", "")
            env["ARIZE_SPACE_ID"] = credentials.get("space_id", "")
            env["ARIZE_OTLP_ENDPOINT"] = credentials.get("endpoint", "otlp.arize.com:443")

        if user_id:
            env["ARIZE_USER_ID"] = user_id

    def _remove_plugins(self, settings: dict) -> bool:
        """Remove Arize plugin entries. Returns True if anything changed."""
        plugins = settings.get("plugins")
        if not isinstance(plugins, list):
            return False

        original_len = len(plugins)
        settings["plugins"] = [p for p in plugins if not _is_arize_plugin(p)]

        # Clean up empty list
        if not settings["plugins"]:
            del settings["plugins"]

        return len(settings.get("plugins", [])) != original_len

    def _remove_hooks(self, settings: dict) -> bool:
        """Remove Arize hook entries. Returns True if anything changed."""
        hooks = settings.get("hooks")
        if not isinstance(hooks, dict):
            return False

        changed = False
        for event in list(hooks.keys()):
            event_hooks = hooks[event]
            if not isinstance(event_hooks, list):
                continue

            original_len = len(event_hooks)
            hooks[event] = [
                entry for entry in event_hooks
                if not _is_arize_hook(
                    entry.get("command", "") if isinstance(entry, dict) else str(entry)
                )
            ]

            if len(hooks[event]) != original_len:
                changed = True

            # Remove empty event list
            if not hooks[event]:
                del hooks[event]

        # Remove empty hooks dict
        if not hooks:
            settings.pop("hooks", None)

        return changed

    def _remove_env_vars(self, settings: dict) -> bool:
        """Remove Arize env keys. Returns True if anything changed."""
        env = settings.get("env")
        if not isinstance(env, dict):
            return False

        changed = False
        for key in _ARIZE_ENV_KEYS:
            if key in env:
                del env[key]
                changed = True

        # Remove empty env dict
        if not env:
            settings.pop("env", None)

        return changed


def _confirm(message: str) -> bool:
    """Prompt for y/N confirmation."""
    answer = input(f"{message} [y/N]: ").strip()
    return answer.lower() == "y"
