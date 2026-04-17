#!/usr/bin/env python3
"""Arize Cursor Tracing - Interactive Setup.

Replaces cursor-tracing/scripts/setup.sh.
Writes config.yaml and prints instructions for hooks.json.
"""

import sys

from core.config import get_value, load_config, save_config, set_value
from core.setup import info, print_color, prompt_backend, prompt_project_name, prompt_user_id, write_config


def main() -> None:
    """Entry point for arize-setup-cursor."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    print("")
    print_color("▸ ARIZE Cursor Tracing Setup", "green")
    print("")

    # Check for existing config
    config = load_config()
    existing_backend = get_value(config, "backend.target")

    # Project name
    project_name = prompt_project_name("cursor")

    if existing_backend:
        print_color(
            f"Existing config found: backend={existing_backend} in ~/.arize/harness/config.yaml",
            "yellow",
        )
        print("Skipping credential prompts — adding cursor harness entry.")
        print("")

        # Add cursor harness entry
        set_value(config, "harnesses.cursor.project_name", project_name)
        save_config(config)
        info("Added cursor harness to existing config")
    else:
        # No existing config — prompt for backend
        target, credentials = prompt_backend()
        info(
            f"Target: {'Phoenix at ' + credentials['endpoint'] if target == 'phoenix' else 'Arize AX (endpoint: ' + credentials['endpoint'] + ')'}"
        )

        # Write config.yaml
        write_config(target, credentials, "cursor", project_name)
        info("Wrote config to ~/.arize/harness/config.yaml")

    # Optional: User ID
    user_id = prompt_user_id()
    if user_id:
        config = load_config()
        set_value(config, "user_id", user_id)
        save_config(config)
        info(f"User ID set: {user_id}")

    # Summary
    print("")
    info("Setup complete!")
    print("")
    print("  Configuration:")
    print("    Config file: ~/.arize/harness/config.yaml")
    print("")
    print("  Next steps:")
    print("    1. Copy hooks.json into your Cursor settings:")
    print("       cp cursor-tracing/hooks/hooks.json ~/.cursor/hooks.json")
    print("")
    print("    2. Start the shared collector (if not already running):")
    print("       arize-collector-ctl start")
    print("")
    print("    3. Open Cursor — traces will be sent to your configured backend")
    print("")
    print("  To verify setup:")
    print("    ARIZE_VERBOSE=true cursor")
    print("")


if __name__ == "__main__":
    main()
