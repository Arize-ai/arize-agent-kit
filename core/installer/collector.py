#!/usr/bin/env python3
"""Collector management for the installer.

Wraps core.collector_ctl with install-specific operations: creating the
launcher script, checking status in a machine-readable format, and tearing
down collector artifacts on uninstall.

All paths come from core.constants — never hardcoded here.
"""

import os
import stat
import textwrap
import urllib.request
from pathlib import Path
from typing import Dict, Union

from core.constants import (
    BIN_DIR,
    COLLECTOR_BIN,
    COLLECTOR_LOG_FILE,
    DEFAULT_COLLECTOR_HOST,
    DEFAULT_COLLECTOR_PORT,
    LOG_DIR,
    PID_DIR,
    PID_FILE,
    VENV_DIR,
)


def _is_windows() -> bool:
    return os.name == "nt"


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def install_collector(python_cmd: str) -> None:
    """Create directories and write the collector launcher script.

    Args:
        python_cmd: Absolute path to the venv Python interpreter that should
            run the collector (e.g. ``~/.arize/harness/venv/bin/python3``).
    """
    # Ensure runtime directories exist
    for d in (BIN_DIR, PID_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)

    if _is_windows():
        _write_windows_launcher(python_cmd)
    else:
        _write_unix_launcher(python_cmd)


def _write_unix_launcher(python_cmd: str) -> None:
    """Write a Unix shell script that launches the collector via runpy."""
    script = textwrap.dedent(f"""\
        #!{python_cmd}
        import runpy, sys, os
        # Ensure the package root is importable so "core.collector" resolves.
        _pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _pkg_root not in sys.path:
            sys.path.insert(0, _pkg_root)
        runpy.run_module("core.collector", run_name="__main__")
    """)
    COLLECTOR_BIN.write_text(script)
    COLLECTOR_BIN.chmod(COLLECTOR_BIN.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_windows_launcher(python_cmd: str) -> None:
    """Write a .cmd wrapper that launches the collector on Windows.

    Writes to both ``COLLECTOR_BIN`` and ``COLLECTOR_BIN.with_suffix(".cmd")``
    so that ``collector_ctl.collector_start()`` can discover the launcher via
    the ``COLLECTOR_BIN`` path, and Windows shells can execute the ``.cmd``
    variant directly.
    """
    script = textwrap.dedent(f"""\
        @echo off
        "{python_cmd}" -m core.collector %*
    """)
    # Write to both paths so collector_ctl finds COLLECTOR_BIN
    COLLECTOR_BIN.write_text(script)
    COLLECTOR_BIN.with_suffix(".cmd").write_text(script)


# ---------------------------------------------------------------------------
# Start / Stop (delegates to core.collector_ctl)
# ---------------------------------------------------------------------------

def start_collector() -> bool:
    """Start the collector process.

    Returns True if the collector is healthy after startup.
    """
    from core.collector_ctl import collector_start
    return collector_start()


def stop_collector() -> bool:
    """Stop the collector process.

    Returns True if the collector is confirmed stopped, False if the process
    may still be running after the stop attempt.
    """
    from core.collector_ctl import collector_stop, collector_status as _ctl_status
    collector_stop()
    status_str, _pid, _addr = _ctl_status()
    return status_str != "running"


# ---------------------------------------------------------------------------
# Host/port resolution and health check (local implementations to avoid
# depending on private functions in core.collector_ctl)
# ---------------------------------------------------------------------------

def _resolve_host_port() -> tuple:
    """Return (host, port) from config.yaml, falling back to defaults."""
    from core.config import load_config, get_value
    from core.constants import CONFIG_FILE

    try:
        cfg = load_config(str(CONFIG_FILE))
        host = get_value(cfg, "collector.host")
        port = get_value(cfg, "collector.port")
    except Exception:
        host = None
        port = None

    if not host:
        host = DEFAULT_COLLECTOR_HOST
    if not port:
        port = DEFAULT_COLLECTOR_PORT
    return (str(host), int(port))


def _health_check(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if the collector health endpoint responds OK."""
    try:
        url = f"http://{host}:{port}/health"
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def collector_status() -> Dict[str, Union[bool, int, None]]:
    """Return machine-readable collector status.

    Returns a dict with keys:
        running (bool): Whether the collector process is alive.
        pid (int | None): PID if running, else None.
        port (int): Configured or default collector port.
        healthy (bool): Whether the health endpoint responded OK.
    """
    from core.collector_ctl import collector_status as _ctl_status

    status_str, pid, _addr = _ctl_status()
    running = status_str == "running"

    host, port = _resolve_host_port()
    healthy = _health_check(host, port, timeout=2.0) if running else False

    return {
        "running": running,
        "pid": pid if running else None,
        "port": port,
        "healthy": healthy,
    }


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

def uninstall_collector() -> None:
    """Stop the collector and remove all collector artifacts.

    Removes the launcher script, PID file, log file, and venv directory.
    Empty parent directories are cleaned up where possible.
    """
    stop_collector()

    # Remove launcher script(s)
    for p in (COLLECTOR_BIN, COLLECTOR_BIN.with_suffix(".cmd")):
        _remove_file(p)

    # Remove runtime files
    _remove_file(PID_FILE)
    _remove_file(COLLECTOR_LOG_FILE)

    # Remove venv
    if VENV_DIR.is_dir():
        import shutil
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    # Clean up empty directories (best-effort, innermost first)
    for d in (PID_DIR, LOG_DIR, BIN_DIR):
        _remove_empty_dir(d)


def _remove_file(path: Path) -> None:
    """Remove a file if it exists, silently ignoring errors."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _remove_empty_dir(path: Path) -> None:
    """Remove a directory only if it is empty."""
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass
