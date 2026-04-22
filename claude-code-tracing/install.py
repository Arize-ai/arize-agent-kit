"""Claude Code harness install/uninstall, invoked by the installer router."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core.setup import (
    ensure_shared_runtime,
    harness_dir,
    info,
    dry_run,
    merge_harness_entry,
    prompt_backend,
    prompt_project_name,
    prompt_user_id,
    remove_harness_entry,
    symlink_skills,
    unlink_skills,
    venv_bin,
)
from core.config import get_value, load_config

# constants.py is a sibling file — make sure sys.path includes this file's parent.
sys.path.insert(0, str(Path(__file__).parent))
from constants import HARNESS_NAME, HOOK_EVENTS, SETTINGS_FILE


def install(with_skills: bool = False) -> None:
    """Install Claude Code tracing: configure backend, register hooks, optionally symlink skills."""
    ensure_shared_runtime()

    # If config has no backend yet, prompt; otherwise reuse.
    config = load_config()
    if not get_value(config, "backend.target"):
        target, credentials = prompt_backend()
        project_name = prompt_project_name(HARNESS_NAME)
        user_id = prompt_user_id()
        if not dry_run():
            from core.setup import write_config

            write_config(target, credentials, HARNESS_NAME, project_name, user_id=user_id)
        else:
            info("would write config.yaml with backend credentials")
    else:
        project_name = prompt_project_name(
            get_value(config, f"harnesses.{HARNESS_NAME}.project_name") or HARNESS_NAME
        )
        merge_harness_entry(HARNESS_NAME, project_name)

    _register_claude_hooks(project_name)
    if with_skills:
        symlink_skills(HARNESS_NAME)
    info(f"Claude Code tracing installed ({SETTINGS_FILE})")


def uninstall() -> None:
    """Remove Claude Code tracing hooks, harness entry, and skill symlinks."""
    _unregister_claude_hooks()
    remove_harness_entry(HARNESS_NAME)
    unlink_skills(HARNESS_NAME)
    info("Claude Code tracing uninstalled")


def _load_settings() -> dict:
    """Load SETTINGS_FILE as JSON, returning {} if missing or malformed."""
    if not SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(settings: dict) -> None:
    """Write settings dict as formatted JSON with trailing newline."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n")


def _register_claude_hooks(project_name: str = HARNESS_NAME) -> None:
    """Read SETTINGS_FILE (or init to {}), add plugin reference + hook commands.

    Merges with existing entries without duplicating. Uses venv_bin() for each
    HOOK_EVENTS entry point. Honors dry_run().
    """
    settings = _load_settings()
    plugin_dir = str(harness_dir("claude-code"))

    # Add plugin reference
    plugins = settings.setdefault("plugins", [])
    has_plugin = any(
        (isinstance(p, str) and p == plugin_dir)
        or (isinstance(p, dict) and p.get("path") == plugin_dir)
        for p in plugins
    )
    if not has_plugin:
        plugins.append({"type": "local", "path": plugin_dir})

    # Set env vars (only if absent)
    env_block = settings.setdefault("env", {})
    if not env_block.get("ARIZE_PROJECT_NAME"):
        env_block["ARIZE_PROJECT_NAME"] = project_name
    env_block.setdefault("ARIZE_TRACE_ENABLED", "true")

    # Register hooks
    hooks = settings.setdefault("hooks", {})
    for event, entry_point in HOOK_EVENTS.items():
        hook_cmd = str(venv_bin(entry_point))
        event_hooks = hooks.setdefault(event, [])
        already = any(
            h.get("command", "") == hook_cmd
            for entry in event_hooks
            for h in entry.get("hooks", [])
        )
        if not already:
            event_hooks.append({"hooks": [{"type": "command", "command": hook_cmd}]})

    if dry_run():
        info(f"would write Claude hooks to {SETTINGS_FILE}")
        return

    _save_settings(settings)


def _unregister_claude_hooks() -> None:
    """Remove our hook entries and plugin reference from SETTINGS_FILE.

    Keeps other hooks and env vars intact. No-op if file doesn't exist.
    Honors dry_run().
    """
    if not SETTINGS_FILE.exists():
        return

    settings = _load_settings()
    if not settings:
        return

    plugin_dir = str(harness_dir("claude-code"))

    # Remove our plugin entries
    plugins = settings.get("plugins", [])
    settings["plugins"] = [
        p
        for p in plugins
        if not (
            (isinstance(p, str) and p == plugin_dir)
            or (isinstance(p, dict) and p.get("path") == plugin_dir)
        )
    ]
    if not settings["plugins"]:
        del settings["plugins"]

    # Remove our hook entries
    our_commands = {str(venv_bin(ep)) for ep in HOOK_EVENTS.values()}
    hooks = settings.get("hooks", {})
    for event in list(hooks.keys()):
        event_hooks = hooks[event]
        filtered = [
            entry
            for entry in event_hooks
            if not all(h.get("command", "") in our_commands for h in entry.get("hooks", []))
        ]
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]
    if not hooks and "hooks" in settings:
        del settings["hooks"]

    if dry_run():
        info(f"would remove Claude hooks from {SETTINGS_FILE}")
        return

    _save_settings(settings)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    flags = set(sys.argv[2:])
    if cmd == "install":
        install(with_skills="--with-skills" in flags)
    elif cmd == "uninstall":
        uninstall()
    else:
        print("usage: install.py {install|uninstall} [--with-skills]", file=sys.stderr)
        sys.exit(2)
