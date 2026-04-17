#!/usr/bin/env python3
"""Arize Codex Tracing Plugin - Interactive Setup.

Replaces codex-tracing/scripts/setup.sh.
Writes config.yaml, ~/.codex/arize-env.sh, and ~/.codex/config.toml.
"""

import os
import sys
from pathlib import Path

from core.config import get_value, load_config, save_config, set_value
from core.setup import err, info, print_color, prompt_backend, prompt_project_name, prompt_user_id, write_config


def _write_env_file(env_path: Path, target: str, credentials: dict, project_name: str = "codex") -> None:
    """Write ~/.codex/arize-env.sh with export statements."""
    env_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# Arize Codex tracing environment (auto-generated)"]
    lines.append("export ARIZE_TRACE_ENABLED=true")

    if target == "phoenix":
        lines.append(f'export PHOENIX_ENDPOINT="{credentials.get("endpoint", "http://localhost:6006")}"')
        api_key = credentials.get("api_key", "")
        if api_key:
            lines.append(f'export PHOENIX_API_KEY="{api_key}"')
    else:
        lines.append(f'export ARIZE_API_KEY="{credentials.get("api_key", "")}"')
        lines.append(f'export ARIZE_SPACE_ID="{credentials.get("space_id", "")}"')
        lines.append(f'export ARIZE_OTLP_ENDPOINT="{credentials.get("endpoint", "otlp.arize.com:443")}"')

    lines.append(f'export ARIZE_PROJECT_NAME="{project_name}"')

    env_path.write_text("\n".join(lines) + "\n")

    # chmod 600
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass  # Windows doesn't support chmod the same way


def _update_toml_otel_section(toml_path: Path, collector_port: int) -> None:
    """Add/replace [otel] section in codex config.toml."""
    if toml_path.exists():
        lines = toml_path.read_text().splitlines()
        # Remove existing [otel] section(s)
        filtered = []
        in_otel = False
        for line in lines:
            stripped = line.strip()
            if stripped == "[otel]" or stripped.startswith("[otel."):
                in_otel = True
                continue
            if in_otel and stripped.startswith("[") and stripped != "[otel]" and not stripped.startswith("[otel."):
                in_otel = False
            if not in_otel:
                filtered.append(line)
        # Remove trailing blank lines
        while filtered and not filtered[-1].strip():
            filtered.pop()
        lines = filtered
    else:
        toml_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []

    # Append new section
    lines.append("")
    lines.append("# Arize shared collector — captures Codex events for rich span trees")
    lines.append("[otel]")
    lines.append("[otel.exporter.otlp-http]")
    lines.append(f'endpoint = "http://127.0.0.1:{collector_port}/v1/logs"')
    lines.append('protocol = "json"')
    toml_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    """Entry point for arize-setup-codex."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    codex_config_dir = Path.home() / ".codex"
    codex_config = codex_config_dir / "config.toml"
    env_file = codex_config_dir / "arize-env.sh"

    print("")
    print_color("▸ ARIZE Codex Tracing Setup", "green")
    print("")

    # Check for existing config
    config = load_config()
    existing_backend = get_value(config, "backend.target")

    # Project name
    project_name = prompt_project_name("codex")

    if existing_backend:
        print_color(
            f"Existing config found: backend={existing_backend} in ~/.arize/harness/config.yaml",
            "yellow",
        )
        print("Skipping credential prompts — adding codex harness entry.")
        print("")

        # Add codex harness entry
        set_value(config, "harnesses.codex.project_name", project_name)
        save_config(config)
        info("Added codex harness to existing config")

        # Write env file from existing config
        if existing_backend == "phoenix":
            phoenix_ep = get_value(config, "backend.phoenix.endpoint") or "http://localhost:6006"
            phoenix_key = get_value(config, "backend.phoenix.api_key") or ""
            creds = {"endpoint": phoenix_ep, "api_key": phoenix_key}
        elif existing_backend == "arize":
            arize_ep = get_value(config, "backend.arize.endpoint") or "otlp.arize.com:443"
            arize_key = get_value(config, "backend.arize.api_key") or ""
            arize_space = get_value(config, "backend.arize.space_id") or ""
            creds = {"endpoint": arize_ep, "api_key": arize_key, "space_id": arize_space}
        else:
            err(f"Unknown backend in config: {existing_backend}")
            sys.exit(1)

        _write_env_file(env_file, existing_backend, creds, project_name)
        info(f"Wrote credentials to {env_file}")
    else:
        # No existing config — prompt for backend
        target, credentials = prompt_backend()
        info(
            f"Target: {'Phoenix at ' + credentials['endpoint'] if target == 'phoenix' else 'Arize AX (endpoint: ' + credentials['endpoint'] + ')'}"
        )

        # Write config.yaml
        write_config(target, credentials, "codex", project_name)
        info("Wrote config to ~/.arize/harness/config.yaml")

        # Write env file
        _write_env_file(env_file, target, credentials, project_name)
        info(f"Wrote credentials to {env_file}")

    # Configure OTLP exporter in ~/.codex/config.toml
    config = load_config()
    collector_port = get_value(config, "collector.port") or 4318
    _update_toml_otel_section(codex_config, collector_port)
    info(f"Added [otel] exporter pointing to shared collector (port {collector_port})")

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
    print("    Config file:  ~/.arize/harness/config.yaml")
    print(f"    Env file:     {env_file}")
    print(f"    Codex config: {codex_config}")
    print("")
    print("  Next steps:")
    print("    1. Start the shared collector (if not already running):")
    print("       arize-collector-ctl start")
    print("    2. Run codex — traces will be sent to your configured backend")
    print("")
    print("  To verify setup: ARIZE_DRY_RUN=true codex")
    print("")


if __name__ == "__main__":
    main()
