#!/usr/bin/env python3
"""Arize Claude Code Plugin - Interactive Setup.

Entry point for ``arize-setup-claude``.  The heavy lifting now lives in
``claude_code_tracing/install.py``; this module is kept for backwards
compatibility with the existing entry point and for helper functions used
by tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core.setup import print_color

# ---------------------------------------------------------------------------
# Helper functions preserved for existing tests (test_setup.py::TestClaudeSetup)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for arize-setup-claude."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    """Delegate to the install module in claude_code_tracing/.

    This replaces the old interactive flow so that ``arize-setup-claude``
    and the installer router share a single code path.
    """
    from claude_code_tracing.install import install

    install(with_skills=False)


if __name__ == "__main__":
    main()
