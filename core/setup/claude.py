#!/usr/bin/env python3
"""Arize Claude Code Plugin - Interactive Setup.

Replaces claude-code-tracing/scripts/setup.sh.
Writes env vars to ~/.claude/settings.json or .claude/settings.local.json.
"""

import json
import sys
from pathlib import Path

from core.setup import (
    err,
    info,
    print_color,
    prompt_backend,
    prompt_user_id,
    write_config,
)


def _ensure_settings_file(settings_path: Path) -> None:
    """Create settings file and parent dirs if they don't exist."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings_path.exists():
        settings_path.write_text("{}")


def _load_settings(settings_path: Path) -> dict:
    """Load JSON settings file, returning empty dict if missing."""
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(settings_path: Path, settings: dict) -> None:
    """Write settings dict as formatted JSON."""
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")


def _check_existing_configuration(settings_path: Path) -> bool:
    """Check for existing config, prompt to overwrite. Returns True if should proceed."""
    settings = _load_settings(settings_path)
    env_block = settings.get("env", {})

    existing_phoenix = env_block.get("PHOENIX_ENDPOINT", "")
    existing_arize = env_block.get("ARIZE_API_KEY", "")

    if existing_phoenix:
        print_color(
            f"Existing config found in {settings_path}: Phoenix at {existing_phoenix}",
            "yellow",
        )
        overwrite = input("Overwrite? [y/N]: ").strip()
        if overwrite.lower() != "y":
            print("Setup cancelled.")
            return False
        print("")
    elif existing_arize:
        print_color(
            f"Existing config found in {settings_path}: Arize AX",
            "yellow",
        )
        overwrite = input("Overwrite? [y/N]: ").strip()
        if overwrite.lower() != "y":
            print("Setup cancelled.")
            return False
        print("")

    return True


def main() -> None:
    """Entry point for arize-setup-claude."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    global_settings = Path.home() / ".claude" / "settings.json"
    local_settings = Path(".claude") / "settings.local.json"

    print("")
    print_color("▸ ARIZE Claude Code Tracing Setup", "green")
    print("")

    # 1. Choose settings scope
    print("Where should Claude tracing env vars be stored?")
    print("")
    print("  1) Project-local (.claude/settings.local.json)")
    print("  2) Global (~/.claude/settings.json)")
    print("")
    settings_choice = input("Enter choice [1/2]: ").strip()

    if settings_choice in ("1", ""):
        settings_path = local_settings
    elif settings_choice == "2":
        settings_path = global_settings
    else:
        err("Invalid choice. Run setup again.")
        sys.exit(1)

    # 2. Check existing config
    if not _check_existing_configuration(settings_path):
        sys.exit(0)

    # 3. Prompt backend + credentials
    target, credentials = prompt_backend()

    # 4. Write env vars to settings.json
    _ensure_settings_file(settings_path)
    settings = _load_settings(settings_path)
    env_block = settings.setdefault("env", {})

    if target == "phoenix":
        env_block["PHOENIX_ENDPOINT"] = credentials["endpoint"]
        env_block["ARIZE_TRACE_ENABLED"] = "true"
        print("")
        print_color(f"✓ Configured for Phoenix at {credentials['endpoint']}", "green")
    else:
        env_block["ARIZE_API_KEY"] = credentials["api_key"]
        env_block["ARIZE_SPACE_ID"] = credentials["space_id"]
        env_block["ARIZE_OTLP_ENDPOINT"] = credentials["endpoint"]
        env_block["ARIZE_TRACE_ENABLED"] = "true"
        print("")
        print_color(f"✓ Configured for Arize AX (endpoint: {credentials['endpoint']})", "green")
        print("")
        print_color("Note: Arize AX requires Python dependencies:", "yellow")
        print("  pip install opentelemetry-proto grpcio")

    _save_settings(settings_path, settings)

    # 5. Optional user ID
    user_id = prompt_user_id()
    if user_id:
        env_block["ARIZE_USER_ID"] = user_id
        _save_settings(settings_path, settings)
        print_color(f"✓ User ID set: {user_id}", "green")

    # 6. Summary
    print("")
    print(f"Configuration saved to {settings_path}")
    print("")
    print("Start a new Claude Code session to begin tracing!")
    print("")


if __name__ == "__main__":
    main()
