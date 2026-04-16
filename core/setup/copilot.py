#!/usr/bin/env python3
"""Arize Copilot Tracing - Interactive Setup.

Writes config.yaml and prints instructions for both VS Code and CLI modes.
"""

import sys

from core.config import load_config, get_value, set_value, save_config
from core.setup import (
    info,
    print_color,
    prompt_backend,
    prompt_project_name,
    prompt_user_id,
    write_config,
)


def main() -> None:
    """Entry point for arize-setup-copilot."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    print("")
    print_color("▸ ARIZE Copilot Tracing Setup", "green")
    print("")

    # Check for existing config
    config = load_config()
    existing_backend = get_value(config, "backend.target")

    # Project name
    project_name = prompt_project_name("copilot")

    if existing_backend:
        print_color(
            f"Existing config found: backend={existing_backend} in ~/.arize/harness/config.yaml",
            "yellow",
        )
        print("Skipping credential prompts — adding copilot harness entry.")
        print("")

        # Add copilot harness entry
        set_value(config, "harnesses.copilot.project_name", project_name)
        save_config(config)
        info("Added copilot harness to existing config")
    else:
        # No existing config — prompt for backend
        target, credentials = prompt_backend()
        info(f"Target: {'Phoenix at ' + credentials['endpoint'] if target == 'phoenix' else 'Arize AX (endpoint: ' + credentials['endpoint'] + ')'}")

        # Write config.yaml
        write_config(target, credentials, "copilot", project_name)
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
    print("  Copilot tracing supports both VS Code and CLI modes.")
    print("")
    print("  Configuration:")
    print("    Config file: ~/.arize/harness/config.yaml")
    print("")
    print("  Next steps:")
    print("    1. Register hooks in your project:")
    print("       VS Code: .github/hooks/*.json (command field)")
    print("       CLI:     .github/hooks/hooks.json (bash field)")
    print("")
    print("    2. Start the shared collector (if not already running):")
    print("       arize-collector-ctl start")
    print("")
    print("    3. Open Copilot — traces will be sent to your configured backend")
    print("")
    print("  To verify setup:")
    print("    ARIZE_DRY_RUN=true arize-hook-copilot-session-start")
    print("")


if __name__ == "__main__":
    main()
