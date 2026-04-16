#!/usr/bin/env python3
"""Arize Copilot Tracing - Interactive Setup.

Configures tracing for GitHub Copilot in both VS Code and CLI modes.
Writes config.yaml to ~/.arize/harness/config.yaml.
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

    # Optional: User ID
    user_id = prompt_user_id()

    if existing_backend:
        print_color(
            f"Existing config found: backend={existing_backend} in ~/.arize/harness/config.yaml",
            "yellow",
        )
        print("Skipping credential prompts — adding copilot harness entry.")
        print("")

        # Add copilot harness entry
        set_value(config, "harnesses.copilot.project_name", project_name)
        if user_id:
            set_value(config, "user_id", user_id)
        save_config(config)
        info("Added copilot harness to existing config")
    else:
        # No existing config — prompt for backend
        target, credentials = prompt_backend()
        info(f"Target: {'Phoenix at ' + credentials['endpoint'] if target == 'phoenix' else 'Arize AX (endpoint: ' + credentials['endpoint'] + ')'}")

        # Write config.yaml
        write_config(target, credentials, "copilot", project_name, user_id=user_id)
        info("Wrote config to ~/.arize/harness/config.yaml")

    if user_id:
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
    print("  VS Code Copilot:")
    print("    Hooks are registered via .github/hooks/*.json or Claude-format settings.")
    print("    Traced events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse,")
    print("                   Stop, SubagentStop, ErrorOccurred, SessionEnd")
    print("    (SubagentStart and PreCompact are fired by VS Code but not traced)")
    print("")
    print("  Copilot CLI:")
    print("    Hooks are registered via .github/hooks/hooks.json (version: 1).")
    print("    Events: sessionStart, sessionEnd, userPromptSubmitted,")
    print("            preToolUse, postToolUse, errorOccurred")
    print("")
    print("  To verify setup:")
    print(f"    ARIZE_DRY_RUN=true arize-hook-copilot-session-start")
    print("")


if __name__ == "__main__":
    main()
