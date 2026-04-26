#!/usr/bin/env python3
"""Copilot tracing harness installer.

Handles install and uninstall for GitHub Copilot tracing hooks.
Copilot is dual-mode: VS Code uses per-event JSON files, CLI uses a
single hooks.json with version: 1.

Usage (called by the shell router):
    python copilot-tracing/install.py install   [--project NAME]
    python copilot-tracing/install.py uninstall
"""

from __future__ import annotations

# The directory is named "copilot-tracing" (hyphenated) so standard Python
# imports don't work.  Load constants from the sibling file via importlib.
import importlib.util as _ilu
import json
import sys
from pathlib import Path

from core.config import get_value, load_config
from core.setup import (
    dry_run,
    ensure_shared_runtime,
    info,
    merge_harness_entry,
    prompt_backend,
    prompt_project_name,
    prompt_user_id,
    remove_harness_entry,
    unlink_skills,
    venv_bin,
    write_config,
)

_spec = _ilu.spec_from_file_location("_copilot_constants", Path(__file__).with_name("constants.py"))
_constants = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_constants)  # type: ignore[union-attr]

CLI_EVENTS: dict[str, str] = _constants.CLI_EVENTS
CLI_HOOKS_FILE: Path = _constants.CLI_HOOKS_FILE
HARNESS_NAME: str = _constants.HARNESS_NAME
HOOKS_DIR: Path = _constants.HOOKS_DIR
VSCODE_EVENTS: dict[str, tuple[str, str]] = _constants.VSCODE_EVENTS


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    """Read a JSON file, returning empty dict on missing or malformed files."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Write *data* as pretty-printed JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# VS Code per-event files
# ---------------------------------------------------------------------------


def _install_vscode_hooks(hooks_dir: Path) -> None:
    """Write one JSON file per VS Code event into *hooks_dir*.

    Each file has the shape:
        {"hooks": [{"event": "<Event>", "command": "<venv_bin>"}]}

    If the file already exists and contains our entry, it is skipped;
    otherwise our hook is merged into the existing ``hooks`` array.
    """
    for event, (filename, entry_point) in VSCODE_EVENTS.items():
        filepath = hooks_dir / filename
        cmd = str(venv_bin(entry_point))

        if dry_run():
            info(f"would write VS Code hook {filepath} ({event})")
            continue

        data = _read_json(filepath)
        hooks_list: list = data.setdefault("hooks", [])

        # Deduplicate: skip if our command is already present
        already = any(h.get("command") == cmd for h in hooks_list)
        if already:
            continue

        hooks_list.append({"event": event, "command": cmd})
        _write_json(filepath, data)


def _uninstall_vscode_hooks(hooks_dir: Path) -> None:
    """Remove our entries from each VS Code per-event file.

    If a file's hooks array becomes empty after removal, the file is deleted.
    """
    for _event, (filename, entry_point) in VSCODE_EVENTS.items():
        filepath = hooks_dir / filename
        if not filepath.is_file():
            continue

        cmd = str(venv_bin(entry_point))

        if dry_run():
            info(f"would remove VS Code hook from {filepath}")
            continue

        data = _read_json(filepath)
        hooks_list = data.get("hooks", [])
        filtered = [h for h in hooks_list if h.get("command") != cmd]

        if not filtered:
            filepath.unlink()
        else:
            data["hooks"] = filtered
            _write_json(filepath, data)


# ---------------------------------------------------------------------------
# CLI hooks.json
# ---------------------------------------------------------------------------


def _install_cli_hooks(hooks_dir: Path) -> None:
    """Write/merge CLI events into hooks_dir/hooks.json.

    The file shape is:
        {"version": 1, "hooks": {"<camelEvent>": [{"bash": "<cmd>"}], ...}}
    """
    filepath = hooks_dir / CLI_HOOKS_FILE.name

    if dry_run():
        info(f"would write CLI hooks to {filepath}")
        return

    data = _read_json(filepath)
    data.setdefault("version", 1)
    hooks_map: dict = data.setdefault("hooks", {})

    for event, entry_point in CLI_EVENTS.items():
        cmd = str(venv_bin(entry_point))
        event_list: list = hooks_map.setdefault(event, [])

        already = any(h.get("bash") == cmd for h in event_list)
        if already:
            continue

        event_list.append({"bash": cmd})

    _write_json(filepath, data)


def _uninstall_cli_hooks(hooks_dir: Path) -> None:
    """Remove our entries from hooks.json.

    Empty event lists are pruned.  If hooks becomes empty the file is removed.
    """
    filepath = hooks_dir / CLI_HOOKS_FILE.name
    if not filepath.is_file():
        return

    if dry_run():
        info(f"would remove CLI hooks from {filepath}")
        return

    data = _read_json(filepath)
    hooks_map = data.get("hooks", {})

    for event, entry_point in CLI_EVENTS.items():
        cmd = str(venv_bin(entry_point))
        event_list = hooks_map.get(event, [])
        filtered = [h for h in event_list if h.get("bash") != cmd]
        if filtered:
            hooks_map[event] = filtered
        else:
            hooks_map.pop(event, None)

    if not hooks_map:
        filepath.unlink()
    else:
        data["hooks"] = hooks_map
        _write_json(filepath, data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install() -> None:
    """Install Copilot tracing hooks (VS Code + CLI) and register in config.yaml."""
    ensure_shared_runtime()

    # If this harness has no backend config yet, prompt; otherwise reuse.
    config = load_config()
    existing_entry = get_value(config, f"harnesses.{HARNESS_NAME}")

    if not existing_entry or not isinstance(existing_entry, dict) or "target" not in existing_entry:
        existing_harnesses = config.get("harnesses") if config else None
        target, credentials = prompt_backend(existing_harnesses)
        project_name = prompt_project_name(HARNESS_NAME)
        user_id = prompt_user_id()
        if not dry_run():
            write_config(target, credentials, HARNESS_NAME, project_name, user_id=user_id)
        else:
            info("would write config.yaml with backend credentials")
    else:
        project_name = prompt_project_name(existing_entry.get("project_name") or HARNESS_NAME)
        merge_harness_entry(HARNESS_NAME, project_name)

    hooks_dir = Path.cwd() / HOOKS_DIR

    if not dry_run():
        hooks_dir.mkdir(parents=True, exist_ok=True)

    _install_vscode_hooks(hooks_dir)
    _install_cli_hooks(hooks_dir)

    info("Copilot tracing installed")


def uninstall() -> None:
    """Remove Copilot tracing hooks and deregister from config.yaml."""
    hooks_dir = Path.cwd() / HOOKS_DIR

    _uninstall_vscode_hooks(hooks_dir)
    _uninstall_cli_hooks(hooks_dir)

    remove_harness_entry(HARNESS_NAME)
    unlink_skills(HARNESS_NAME)
    info("Copilot tracing uninstalled")


# ---------------------------------------------------------------------------
# CLI entry point (called by the shell router)
# ---------------------------------------------------------------------------


def main() -> None:
    """Dispatch install / uninstall from the command line."""
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall"):
        print(f"usage: {sys.argv[0]} {{install|uninstall}}", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]

    if action == "install":
        install()
    else:
        uninstall()


if __name__ == "__main__":
    main()
