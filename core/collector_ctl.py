#!/usr/bin/env python3
"""Collector lifecycle management: start, stop, status, ensure.

Replaces collector_ctl.sh with a cross-platform Python implementation.
All paths come from core.constants — never hardcoded here.
"""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from core.constants import (
    COLLECTOR_BIN,
    COLLECTOR_LOG_FILE,
    CONFIG_FILE,
    DEFAULT_COLLECTOR_HOST,
    DEFAULT_COLLECTOR_PORT,
    LOG_DIR,
    PID_DIR,
    PID_FILE,
)
from core.config import load_config, get_value


def _log(msg: str) -> None:
    """Log a message to stderr (never stdout)."""
    sys.stderr.write(f"[arize] {msg}\n")
    sys.stderr.flush()

def _is_windows():
    """Check if the operating system is Windows."""
    return os.name == "nt"

def _is_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is alive."""
    if pid <= 0:
        # Guard: PID 0 is the kernel/idle process, negative PIDs target
        # process groups on Unix. Neither is a valid collector PID.
        return False

    if _is_windows():
        # Windows: try OpenProcess, fall back to tasklist
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except (AttributeError, OSError):
            # ctypes.windll not available — fall back to tasklist
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True, timeout=5,
                )
                return str(pid) in result.stdout
            except (subprocess.SubprocessError, FileNotFoundError):
                return False
    else:
        # Unix: os.kill with signal 0
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _resolve_host_port() -> tuple:
    """Return (host, port) from config.yaml, falling back to defaults."""
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


def collector_status() -> tuple:
    """Check collector status.

    Returns:
        ("running", pid, "host:port") or ("stopped", None, None)
    """
    if not PID_FILE.is_file():
        return ("stopped", None, None)

    try:
        pid_text = PID_FILE.read_text().strip()
        pid = int(pid_text)
    except (ValueError, OSError):
        # Non-numeric or unreadable PID file — remove it
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return ("stopped", None, None)

    if not _is_process_alive(pid):
        # Stale PID file — clean up
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return ("stopped", None, None)

    host, port = _resolve_host_port()
    addr = f"{host}:{port}"

    # Health check — but process is alive, so give benefit of the doubt either way
    _health_check(host, port, timeout=2.0)
    return ("running", pid, addr)


def collector_start() -> bool:
    """Start the collector if not already running.

    Returns True if the collector is running after this call, False on failure.
    """
    status, _, _ = collector_status()
    if status == "running":
        return True

    # Config is required
    if not CONFIG_FILE.is_file():
        _log(f"ERROR: No config.yaml found at {CONFIG_FILE}")
        return False

    # Find collector runtime
    collector_py = Path(__file__).parent / "collector.py"
    if COLLECTOR_BIN.is_file() and os.access(COLLECTOR_BIN, os.X_OK):
        cmd = [str(COLLECTOR_BIN)]
    elif collector_py.is_file():
        cmd = [sys.executable, str(collector_py)]
    else:
        _log(f"Collector runtime not found at {COLLECTOR_BIN} or {collector_py}")
        return False

    host, port = _resolve_host_port()

    # Fast health check first — catches running collector even without PID file
    if _health_check(host, port, timeout=2.0):
        return True

    # Port-in-use check (raw socket)
    try:
        sock = socket.create_connection((host, port), timeout=1)
        sock.close()
        # Port is open but health check failed — something else owns it
        _log(
            f"ERROR: Port {port} is already in use by another process. "
            f"Set collector.port in {CONFIG_FILE} to use a different port"
        )
        return False
    except (ConnectionRefusedError, socket.timeout, OSError):
        pass  # Port is free — proceed

    # Ensure directories
    PID_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Launch process
    log_fd = open(COLLECTOR_LOG_FILE, "a")
    try:
        if _is_windows():
            proc = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                creationflags=(
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                ),
            )
        else:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as e:
        _log(f"Failed to launch collector: {e}")
        log_fd.close()
        return False
    log_fd.close()

    # Poll for health (20 attempts × 0.1s = 2s)
    for _ in range(20):
        time.sleep(0.1)
        if _health_check(host, port, timeout=1.0):
            return True

    # Health check didn't pass — check if process is still alive
    if _is_process_alive(proc.pid):
        return True  # benefit of the doubt
    else:
        _log("Failed to start collector (process exited)")
        return False


def _find_pid_on_port(port: int) -> "int | None":
    """Find the PID of a process listening on the given port, or None."""
    if _is_windows():
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    return int(parts[-1])
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip().splitlines()[0])
        except Exception:
            pass
    return None


def _kill_pid(pid: int) -> None:
    """Send SIGTERM to a process and wait up to 5s for it to die."""
    try:
        if _is_windows():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                subprocess.run(
                    ["taskkill", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        return

    for _ in range(50):
        time.sleep(0.1)
        if not _is_process_alive(pid):
            return


def collector_stop() -> str:
    """Stop the collector.

    Returns "stopped".
    """
    pid = None

    # Try PID file first
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            pid = None
        try:
            PID_FILE.unlink()
        except OSError:
            pass

    # Fallback: find process by port if PID file was missing or stale
    if pid is None or not _is_process_alive(pid):
        host, port = _resolve_host_port()
        if _health_check(host, port, timeout=1.0):
            pid = _find_pid_on_port(port)

    if pid and _is_process_alive(pid):
        _kill_pid(pid)

    return "stopped"


def collector_ensure() -> None:
    """Silent idempotent start. Never raises. Suitable for hooks."""
    try:
        if collector_status()[0] == "running":
            return
        collector_start()
    except Exception:
        pass


def main() -> None:
    """CLI entrypoint for arize-collector-ctl."""
    if len(sys.argv) < 2 or sys.argv[1] not in ("start", "stop", "status"):
        sys.stderr.write(
            "usage: arize-collector-ctl <start|stop|status>\n"
        )
        sys.exit(1)

    command = sys.argv[1]

    if command == "status":
        status, pid, addr = collector_status()
        if status == "running":
            print(f"running (PID {pid}, {addr})")
        else:
            print("stopped")

    elif command == "start":
        ok = collector_start()
        if ok:
            status, pid, addr = collector_status()
            if status == "running":
                print(f"running (PID {pid}, {addr})")
            else:
                print("started")
        else:
            print("failed to start collector")
            sys.exit(1)

    elif command == "stop":
        result = collector_stop()
        print(result)


if __name__ == "__main__":
    main()
