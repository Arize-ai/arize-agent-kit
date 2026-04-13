#!/usr/bin/env python3
"""Codex harness installer.

Handles notify hook, OTLP exporter, proxy wrapper, and env file.
Replaces setup_codex() (~200 lines) and _uninstall_codex() (~70 lines)
from install.sh.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import get_value
from core.constants import DEFAULT_COLLECTOR_PORT, STATE_BASE_DIR, VENV_DIR
from core.installer.harnesses.base import HarnessInstaller


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CODEX_CONFIG_DIR = Path.home() / ".codex"
CODEX_CONFIG_TOML = CODEX_CONFIG_DIR / "config.toml"
CODEX_ENV_FILE = CODEX_CONFIG_DIR / "arize-env.sh"
PROXY_DIR = Path.home() / ".local" / "bin"
PROXY_PATH = PROXY_DIR / "codex"
PROXY_BACKUP = PROXY_DIR / "codex.arize-backup"

ARIZE_COMMENT_NOTIFY = "# Arize tracing — OpenInference spans per turn"
ARIZE_COMMENT_OTEL = "# Arize shared collector — captures Codex events for rich span trees"
ARIZE_PROXY_MARKER = "ARIZE_CODEX_PROXY"

# Shell profiles checked during cleanup
SHELL_PROFILES = [
    Path.home() / ".zshrc",
    Path.home() / ".bashrc",
    Path.home() / ".bash_profile",
]


# ---------------------------------------------------------------------------
# TOML helpers (simple string manipulation — no TOML library)
# ---------------------------------------------------------------------------

def _venv_bin(name: str) -> Path:
    """Return the path to an entry-point script inside the harness venv."""
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / f"{name}.exe"
    return VENV_DIR / "bin" / name


def _read_lines(path: Path) -> List[str]:
    """Read file lines, returning empty list if file doesn't exist."""
    if not path.is_file():
        return []
    return path.read_text().splitlines()


def _write_lines(path: Path, lines: List[str]) -> None:
    """Write lines to a file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _strip_trailing_blanks(lines: List[str]) -> List[str]:
    """Remove trailing blank lines."""
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _remove_otel_section(lines: List[str]) -> List[str]:
    """Remove [otel] and [otel.*] sections from TOML lines."""
    filtered: List[str] = []
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
    return filtered


def _remove_arize_comments(lines: List[str]) -> List[str]:
    """Remove Arize-specific comment lines."""
    return [l for l in lines if ARIZE_COMMENT_OTEL not in l]


# ---------------------------------------------------------------------------
# Proxy discovery
# ---------------------------------------------------------------------------

def _discover_real_codex() -> Optional[str]:
    """Find the real codex binary, looking through our proxy if installed.

    Returns the absolute path to the real codex binary, or None.
    """
    current = shutil.which("codex")
    if current is None:
        return None

    proxy_path = str(PROXY_PATH)
    if os.path.realpath(current) == os.path.realpath(proxy_path) and PROXY_PATH.is_file():
        # Our proxy is on PATH — extract the real path from it
        content = PROXY_PATH.read_text()
        match = re.search(r'^REAL_CODEX="([^"]+)"', content, re.MULTILINE)
        if match:
            candidate = match.group(1)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    if os.path.isfile(current) and os.access(current, os.X_OK):
        return current

    return None


# ---------------------------------------------------------------------------
# CodexInstaller
# ---------------------------------------------------------------------------

class CodexInstaller(HarnessInstaller):
    """Install/uninstall Arize tracing for the Codex CLI."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__(harness_name="codex", config_path=config_path)

    # ------------------------------------------------------------------
    # install
    # ------------------------------------------------------------------

    def install(
        self,
        backend: str = "local",
        credentials: Optional[Dict[str, str]] = None,
        user_id: str = "",
        non_interactive: bool = False,
    ) -> None:
        """Configure Codex CLI for Arize tracing.

        Steps:
          1. Configure notify hook in ~/.codex/config.toml
          2. Write env file template at ~/.codex/arize-env.sh (if missing)
          3. Add [otel] exporter section to config.toml
          4. Install codex proxy wrapper at ~/.local/bin/codex
          5. Register harness in config.yaml
        """
        credentials = credentials or {}

        CODEX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CODEX_CONFIG_TOML.is_file():
            CODEX_CONFIG_TOML.touch()

        # 1. Configure notify hook
        self._configure_notify_hook()

        # 2. Write env file template
        self._write_env_file_template()

        # 3. Configure OTLP exporter
        config = self._load()
        collector_port = get_value(config, "collector.port") or DEFAULT_COLLECTOR_PORT
        self._configure_otel_section(collector_port)

        # 4. Install proxy wrapper
        self._install_proxy()

        # 5. Clean up old collector auto-start lines from shell profiles
        self._clean_old_collector_autostart()

        # 6. Register in config.yaml
        self._add_harness_to_config("codex")

    # ------------------------------------------------------------------
    # uninstall
    # ------------------------------------------------------------------

    def uninstall(self, non_interactive: bool = False) -> None:
        """Remove all Codex tracing configuration.

        Steps:
          1. Remove notify hook and [otel] section from config.toml
          2. Remove codex proxy, restore backup if present
          3. Clean up PATH injection from shell profiles
          4. Remove state directory and env file
          5. Remove from config.yaml
        """
        # 1. Clean up config.toml
        if CODEX_CONFIG_TOML.is_file():
            lines = _read_lines(CODEX_CONFIG_TOML)

            # Remove Arize notify comment and notify lines referencing arize
            lines = [l for l in lines if ARIZE_COMMENT_NOTIFY not in l]
            lines = [l for l in lines if not (l.strip().startswith("notify") and "arize" in l.lower())]

            # Remove [otel] sections
            lines = _remove_otel_section(lines)

            # Remove Arize otel comment
            lines = _remove_arize_comments(lines)
            lines = _strip_trailing_blanks(lines)

            _write_lines(CODEX_CONFIG_TOML, lines) if lines else CODEX_CONFIG_TOML.write_text("")

        # 2. Remove proxy
        if PROXY_PATH.is_file():
            content = PROXY_PATH.read_text()
            if "arize" in content.lower() or ARIZE_PROXY_MARKER in content:
                PROXY_PATH.unlink()

        if PROXY_BACKUP.is_file():
            PROXY_BACKUP.rename(PROXY_PATH)
            PROXY_PATH.chmod(PROXY_PATH.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # 3. Clean up PATH injection from shell profiles
        self._clean_shell_profiles()

        # 4. Remove state directory and env file
        state_dir = STATE_BASE_DIR / "codex"
        if state_dir.is_dir():
            shutil.rmtree(state_dir, ignore_errors=True)

        if CODEX_ENV_FILE.is_file():
            CODEX_ENV_FILE.unlink()

        # 5. Remove from config.yaml
        self._remove_harness_from_config()

    # ------------------------------------------------------------------
    # is_installed / get_status
    # ------------------------------------------------------------------

    def is_installed(self) -> bool:
        """Check if codex harness is registered in config.yaml."""
        config = self._load()
        return get_value(config, "harnesses.codex") is not None

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for the extension sidebar."""
        config = self._load()
        harness_cfg = get_value(config, "harnesses.codex")

        proxy_installed = (
            PROXY_PATH.is_file()
            and ARIZE_PROXY_MARKER in PROXY_PATH.read_text()
        ) if PROXY_PATH.is_file() else False

        toml_configured = False
        if CODEX_CONFIG_TOML.is_file():
            content = CODEX_CONFIG_TOML.read_text()
            toml_configured = "arize" in content.lower() and "[otel]" in content

        return {
            "installed": harness_cfg is not None,
            "proxy_installed": proxy_installed,
            "config_toml_configured": toml_configured,
            "env_file_exists": CODEX_ENV_FILE.is_file(),
            "project_name": get_value(config, "harnesses.codex.project_name") or "",
        }

    # ------------------------------------------------------------------
    # Private: notify hook
    # ------------------------------------------------------------------

    def _configure_notify_hook(self) -> None:
        """Add or update the notify hook line in config.toml."""
        notify_cmd = str(_venv_bin("arize-hook-codex-notify"))
        notify_line = f'notify = ["{notify_cmd}"]'

        lines = _read_lines(CODEX_CONFIG_TOML)

        # Check if a notify line already exists
        for i, line in enumerate(lines):
            if line.strip().startswith("notify"):
                lines[i] = notify_line
                _write_lines(CODEX_CONFIG_TOML, lines)
                return

        # No existing notify — find first section header and insert before it
        first_section_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith("["):
                first_section_idx = i
                break

        new_lines = [
            "",
            ARIZE_COMMENT_NOTIFY,
            notify_line,
            "",
        ]

        if first_section_idx is not None:
            lines = lines[:first_section_idx] + new_lines + lines[first_section_idx:]
        else:
            lines.extend(new_lines)

        _write_lines(CODEX_CONFIG_TOML, lines)

    # ------------------------------------------------------------------
    # Private: env file
    # ------------------------------------------------------------------

    def _write_env_file_template(self) -> None:
        """Write the env file template if it doesn't already exist."""
        if CODEX_ENV_FILE.is_file():
            return

        CODEX_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        template = """\
# Arize Codex tracing environment
# Source this file in your shell profile or export vars before running codex.
#
# Uncomment and set the variables for your backend:

# Common
export ARIZE_TRACE_ENABLED=true
# export ARIZE_PROJECT_NAME=codex
# export ARIZE_USER_ID=

# Phoenix (self-hosted)
# export PHOENIX_ENDPOINT=http://localhost:6006

# Arize AX (cloud)
# export ARIZE_API_KEY=
# export ARIZE_SPACE_ID="""
        CODEX_ENV_FILE.write_text(template + "\n")
        try:
            os.chmod(CODEX_ENV_FILE, 0o600)
        except OSError:
            pass  # Windows doesn't support chmod the same way

    # ------------------------------------------------------------------
    # Private: OTLP / [otel] section
    # ------------------------------------------------------------------

    def _configure_otel_section(self, collector_port: int) -> None:
        """Add/replace [otel] section in config.toml."""
        lines = _read_lines(CODEX_CONFIG_TOML)

        # Remove existing [otel] section(s) and associated comments
        lines = _remove_otel_section(lines)
        lines = _remove_arize_comments(lines)
        lines = _strip_trailing_blanks(lines)

        # Append new section
        lines.append("")
        lines.append(ARIZE_COMMENT_OTEL)
        lines.append("[otel]")
        lines.append("[otel.exporter.otlp-http]")
        lines.append(f'endpoint = "http://127.0.0.1:{collector_port}/v1/logs"')
        lines.append('protocol = "json"')

        _write_lines(CODEX_CONFIG_TOML, lines)

    # ------------------------------------------------------------------
    # Private: proxy
    # ------------------------------------------------------------------

    def _install_proxy(self) -> None:
        """Install a codex proxy wrapper at ~/.local/bin/codex."""
        real_codex = _discover_real_codex()
        if real_codex is None:
            return  # codex not found — skip proxy

        PROXY_DIR.mkdir(parents=True, exist_ok=True)

        # Back up existing non-proxy codex if present
        if PROXY_PATH.is_file() and ARIZE_PROXY_MARKER not in PROXY_PATH.read_text():
            shutil.copy2(PROXY_PATH, PROXY_BACKUP)

        env_file = str(CODEX_ENV_FILE)
        ctl_cmd = str(_venv_bin("arize-collector-ctl"))

        proxy_script = f"""\
#!/bin/bash
# {ARIZE_PROXY_MARKER} — Arize tracing wrapper for Codex CLI
# Do not edit — regenerated by arize-install.

REAL_CODEX="{real_codex}"
ARIZE_CODEX_PROXY=true

# Source environment if available
if [ -f "{env_file}" ]; then
    . "{env_file}"
fi

# Ensure collector is running
if command -v "{ctl_cmd}" >/dev/null 2>&1; then
    "{ctl_cmd}" ensure >/dev/null 2>&1 || true
fi

exec "$REAL_CODEX" "$@"
"""
        PROXY_PATH.write_text(proxy_script)
        PROXY_PATH.chmod(PROXY_PATH.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # ------------------------------------------------------------------
    # Private: shell profile cleanup
    # ------------------------------------------------------------------

    def _clean_old_collector_autostart(self) -> None:
        """Remove old collector auto-start lines from shell profiles."""
        for profile in SHELL_PROFILES[:2]:  # .zshrc, .bashrc only
            if not profile.is_file():
                continue
            content = profile.read_text()
            if "collector_ctl.sh" not in content:
                continue
            lines = content.splitlines()
            lines = [
                l for l in lines
                if not re.search(r"arize-codex.*collector_ctl|collector_ensure|event_buffer_ensure", l)
            ]
            profile.write_text("\n".join(lines) + "\n")

    def _clean_shell_profiles(self) -> None:
        """Remove Arize PATH injection and collector lines from shell profiles."""
        for profile in SHELL_PROFILES:
            if not profile.is_file():
                continue
            content = profile.read_text()

            needs_cleanup = (
                "prepend ~/.local/bin for codex proxy" in content
                or "collector_ctl.sh" in content
            )
            if not needs_cleanup:
                continue

            lines = content.splitlines()
            lines = [l for l in lines if "Arize Codex tracing - prepend" not in l]
            lines = [l for l in lines if 'export PATH="$HOME/.local/bin:$PATH"' not in l]
            lines = [
                l for l in lines
                if not re.search(r"arize-codex.*collector_ctl|collector_ensure|event_buffer_ensure", l)
            ]
            profile.write_text("\n".join(lines) + "\n")
