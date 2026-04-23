"""Cursor harness install/uninstall, invoked by the installer router."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from core.setup import (
    INSTALL_DIR,
    ensure_harness_installed,
    ensure_shared_runtime,
    dry_run,
    info,
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

# Load constants from the same directory (cursor-tracing/ has a hyphen,
# so it cannot be imported as a regular package).
_constants_path = Path(__file__).parent / "constants.py"
_spec = importlib.util.spec_from_file_location("cursor_tracing_constants", _constants_path)
_constants = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_constants)  # type: ignore[union-attr]

HARNESS_NAME: str = _constants.HARNESS_NAME
DISPLAY_NAME: str = _constants.DISPLAY_NAME
HARNESS_HOME: str = _constants.HARNESS_HOME
HARNESS_BIN: str = _constants.HARNESS_BIN
HOOK_BIN_NAME: str = _constants.HOOK_BIN_NAME
HOOK_EVENTS: tuple = _constants.HOOK_EVENTS
HOOKS_FILE: Path = _constants.HOOKS_FILE


def install(with_skills: bool = False) -> None:
    """Install Cursor tracing: configure backend, register hooks, optionally symlink skills."""
    if not ensure_harness_installed(DISPLAY_NAME, home_subdir=HARNESS_HOME, bin_name=HARNESS_BIN):
        info("Aborted.")
        return

    ensure_shared_runtime()

    # Create cursor state dir
    state_dir = INSTALL_DIR / "state" / HARNESS_NAME
    if dry_run():
        info(f"would create {state_dir}")
    else:
        state_dir.mkdir(parents=True, exist_ok=True)

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

    _register_cursor_hooks()
    if with_skills:
        symlink_skills(HARNESS_NAME)
    info(f"Cursor tracing installed ({HOOKS_FILE})")


def uninstall() -> None:
    """Remove Cursor tracing hooks, harness entry, and skill symlinks."""
    _unregister_cursor_hooks()
    remove_harness_entry(HARNESS_NAME)
    unlink_skills(HARNESS_NAME)
    info("Cursor tracing uninstalled")


def _load_hooks() -> dict:
    """Load HOOKS_FILE as JSON, returning a fresh skeleton if missing or malformed."""
    if not HOOKS_FILE.exists():
        return {"version": 1, "hooks": {}}
    try:
        data = json.loads(HOOKS_FILE.read_text())
        if not isinstance(data, dict):
            return {"version": 1, "hooks": {}}
        data.setdefault("version", 1)
        data.setdefault("hooks", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "hooks": {}}


def _save_hooks(data: dict) -> None:
    """Write hooks dict as formatted JSON with trailing newline."""
    HOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOOKS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _register_cursor_hooks() -> None:
    """Add hook entries for all HOOK_EVENTS to ~/.cursor/hooks.json.

    For each event, ensure an entry with ``command == venv_bin(HOOK_BIN_NAME)``
    exists — skip if already there.  Merges with existing entries without
    duplicating.  Honors dry_run().
    """
    data = _load_hooks()
    hooks = data["hooks"]
    hook_cmd = str(venv_bin(HOOK_BIN_NAME))

    for event in HOOK_EVENTS:
        event_list = hooks.setdefault(event, [])
        already = any(h.get("command") == hook_cmd for h in event_list)
        if not already:
            event_list.append({"command": hook_cmd})

    if dry_run():
        info(f"would write Cursor hooks to {HOOKS_FILE}")
        return

    _save_hooks(data)


def _unregister_cursor_hooks() -> None:
    """Remove our hook entries from ~/.cursor/hooks.json.

    Keeps other hooks intact.  Removes event keys that become empty after
    filtering.  No-op if file doesn't exist.  Honors dry_run().
    """
    if not HOOKS_FILE.exists():
        return

    data = _load_hooks()
    hooks = data.get("hooks", {})
    if not hooks:
        return

    hook_cmd = str(venv_bin(HOOK_BIN_NAME))

    for event in list(hooks.keys()):
        event_list = hooks[event]
        filtered = [h for h in event_list if h.get("command") != hook_cmd]
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]

    if dry_run():
        info(f"would remove Cursor hooks from {HOOKS_FILE}")
        return

    _save_hooks(data)


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
