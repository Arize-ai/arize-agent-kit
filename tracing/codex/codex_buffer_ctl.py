#!/usr/bin/env python3
"""Codex buffer service lifecycle management: start, stop, status, ensure.

Manages the Codex-specific HTTP buffer process that holds native OTLP log
events between hook invocations.  All paths come from core.constants.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from core.config import get_value, load_config
from core.constants import (
    CODEX_BUFFER_BIN,
    CODEX_BUFFER_LOG_FILE,
    CODEX_BUFFER_PID_FILE,
    CONFIG_FILE,
    DEFAULT_BUFFER_HOST,
    DEFAULT_BUFFER_PORT,
    LOG_DIR,
    PID_DIR,
)


def _log(msg: str) -> None:
    """Log a message to stderr (never stdout)."""
    sys.stderr.write(f"[arize-codex-buffer] {msg}\n")
    sys.stderr.flush()


def _is_windows():
    """Check if the operating system is Windows."""
    return os.name == "nt"


def _is_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is alive."""
    if pid <= 0:
        # Guard: PID 0 is the kernel/idle process, negative PIDs target
        # process groups on Unix. Neither is a valid buffer PID.
        return False

    if _is_windows():
        # Windows: try OpenProcess, fall back to tasklist
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)  # type: ignore[attr-defined]
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
                return True
            return False
        except (AttributeError, OSError):
            # ctypes.windll not available — fall back to tasklist
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
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
        host = get_value(cfg, "harnesses.codex.collector.host") or DEFAULT_BUFFER_HOST
        port = get_value(cfg, "harnesses.codex.collector.port") or DEFAULT_BUFFER_PORT
    except Exception:
        host = DEFAULT_BUFFER_HOST
        port = DEFAULT_BUFFER_PORT
    return (str(host), int(port))


def _health_check(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if the buffer health endpoint responds OK."""
    try:
        url = f"http://{host}:{port}/health"
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def _health_identity(host: str, port: int, timeout: float = 2.0) -> dict:
    """GET /health and parse identity fields from JSON response.

    Returns dict with keys pid, build_path, started_at if present, else empty dict.
    """
    try:
        url = f"http://{host}:{port}/health"
        resp = urllib.request.urlopen(url, timeout=timeout)
        data = json.loads(resp.read())
        result: dict = {}
        if "pid" in data:
            result["pid"] = int(data["pid"])
        if "build_path" in data:
            result["build_path"] = str(data["build_path"])
        if "started_at" in data:
            result["started_at"] = float(data["started_at"])
        return result
    except Exception:
        return {}


def _listener_pid(host: str, port: int) -> int | None:
    """Discover the PID of the process listening on host:port.

    Tries /health identity first, then falls back to lsof.
    """
    identity = _health_identity(host, port)
    pid = identity.get("pid")
    if pid is not None and _is_process_alive(pid):
        return pid

    # Fall back to lsof — filter by host for non-loopback addresses
    _loopback = {"127.0.0.1", "localhost", "::1"}
    lsof_addr = f"-iTCP:{port}" if host in _loopback else f"-iTCP@{host}:{port}"
    try:
        result = subprocess.run(
            ["lsof", "-nP", lsof_addr, "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def _expected_build_path() -> str:
    """Return the canonical path to codex_buffer.py next to this file."""
    return str((Path(__file__).parent / "codex_buffer.py").resolve())


def _evict_stale(pid: int, host: str, port: int, reason: str) -> bool:
    """Evict a stale buffer process. Returns True on success."""
    # Safety: never kill PID 0, 1, negative, or ourselves
    if pid <= 1 or pid == os.getpid():
        _log(f"Refusing to evict PID {pid} (safety guard)")
        return False

    _log(f"Evicting stale buffer at PID {pid}: {reason}")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True  # already gone
    except OSError:
        return False

    # Poll port up to 5s (50 × 0.1s) — only ConnectionRefusedError means freed
    for _ in range(50):
        time.sleep(0.1)
        try:
            conn = socket.create_connection((host, port), timeout=0.5)
            conn.close()
        except ConnectionRefusedError:
            return True  # port freed
        except (socket.timeout, OSError):
            continue  # inconclusive — keep polling

    # Still up — escalate to SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    # Poll once more for 1s (10 × 0.1s)
    for _ in range(10):
        time.sleep(0.1)
        try:
            conn = socket.create_connection((host, port), timeout=0.5)
            conn.close()
        except ConnectionRefusedError:
            return True
        except (socket.timeout, OSError):
            continue

    return False


def buffer_status() -> tuple:
    """Check buffer service status.

    Returns:
        ("running", pid, "host:port") or ("stopped", None, None)
    """
    host, port = _resolve_host_port()
    addr = f"{host}:{port}"

    # Try PID file first
    if CODEX_BUFFER_PID_FILE.is_file():
        try:
            pid_text = CODEX_BUFFER_PID_FILE.read_text().strip()
            pid = int(pid_text)
        except (ValueError, OSError):
            pid = None

        if pid and _is_process_alive(pid):
            return ("running", pid, addr)

        # Stale PID file — clean up
        try:
            CODEX_BUFFER_PID_FILE.unlink()
        except OSError:
            pass

    # No valid PID file — fall back to health check (buffer may have been
    # started by the proxy or another process without writing a PID file)
    if _health_check(host, port, timeout=2.0):
        pid = _listener_pid(host, port)
        return ("running", pid, addr)

    return ("stopped", None, None)


def buffer_start(evict_stale: bool = True) -> bool:
    """Start the buffer service if not already running.

    Args:
        evict_stale: When True, replace a healthy listener whose build identity
            does not match this package. Hook-time callers pass False because the
            buffer is in-memory; evicting it right before a drain drops the tool
            events accumulated during the turn.

    Returns True if the buffer is running after this call, False on failure.
    """
    host, port = _resolve_host_port()

    if not evict_stale and _health_check(host, port, timeout=2.0):
        return True

    # If a pidfile exists and the process is alive, verify its identity before
    # trusting it.  A stale old-build daemon with a surviving pidfile must not
    # prevent recovery.
    if CODEX_BUFFER_PID_FILE.is_file():
        try:
            pid_text = CODEX_BUFFER_PID_FILE.read_text().strip()
            pid = int(pid_text)
        except (ValueError, OSError):
            pid = None
        if pid and _is_process_alive(pid):
            identity = _health_identity(host, port)
            remote_bp = identity.get("build_path")
            expected = _expected_build_path()
            if remote_bp and os.path.realpath(remote_bp) == os.path.realpath(expected):
                return True
            if not evict_stale and _health_check(host, port, timeout=2.0):
                return True
            # Pidfile process is alive but identity doesn't match — fall through
            # to the identity-aware health check which will evict it.

    # Config is required
    if not CONFIG_FILE.is_file():
        _log(f"ERROR: No config.yaml found at {CONFIG_FILE}")
        return False

    # Find buffer runtime
    buffer_py = Path(__file__).parent / "codex_buffer.py"
    if CODEX_BUFFER_BIN.is_file() and os.access(CODEX_BUFFER_BIN, os.X_OK):
        cmd = [str(CODEX_BUFFER_BIN)]
    elif buffer_py.is_file():
        cmd = [sys.executable, str(buffer_py)]
    else:
        _log(f"Buffer runtime not found at {CODEX_BUFFER_BIN} or {buffer_py}")
        return False

    # Identity-aware health check — detect and evict stale daemons
    if _health_check(host, port, timeout=2.0):
        identity = _health_identity(host, port)
        expected = _expected_build_path()
        remote_bp = identity.get("build_path")

        if remote_bp and os.path.realpath(remote_bp) == os.path.realpath(expected):
            # Truly ours, current build
            return True

        if not evict_stale:
            # Preserve buffered events for hook-time drains.  The listener is
            # healthy enough to answer the buffer API, so prefer imperfect spans
            # over losing the turn's child events by restarting the daemon.
            return True

        # Stale or foreign: build_path missing, mismatched, or points to deleted file
        reason = "no identity (old buffer)" if not remote_bp else f"build_path mismatch: {remote_bp}"
        if remote_bp and not os.path.isfile(remote_bp):
            reason = f"build_path no longer exists: {remote_bp}"

        listener = _listener_pid(host, port)
        if listener is None:
            _log(f"WARNING: Cannot find PID for listener on {host}:{port}; cannot evict")
            return False

        if not _evict_stale(listener, host, port, reason):
            _log(f"ERROR: Failed to evict stale buffer at PID {listener}")
            return False
        # Fall through to spawn a fresh buffer

    # Port-in-use check (raw socket)
    try:
        sock = socket.create_connection((host, port), timeout=1)
        sock.close()
        # Port is open but health check failed — something else owns it
        _log(
            f"ERROR: Port {port} is already in use by another process. "
            f"Set harnesses.codex.collector.port in {CONFIG_FILE} to use a different port"
        )
        return False
    except (ConnectionRefusedError, socket.timeout, OSError):
        pass  # Port is free — proceed

    # Ensure directories
    PID_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Launch process
    log_fd = open(CODEX_BUFFER_LOG_FILE, "a")
    try:
        if _is_windows():
            proc = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW),  # type: ignore[attr-defined]
            )
        else:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as e:
        _log(f"Failed to launch buffer: {e}")
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
        _log("Failed to start buffer (process exited)")
        return False


def _kill_and_wait(pid: int) -> None:
    """Send SIGTERM, wait up to 5s, escalate to SIGKILL if needed."""
    # Safety: never kill PID 0, 1, negative, or ourselves
    if pid <= 1 or pid == os.getpid():
        _log(f"Refusing to kill PID {pid} (safety guard)")
        return

    try:
        if _is_windows():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                subprocess.run(
                    ["taskkill", "/PID", str(pid)],
                    capture_output=True,
                    timeout=5,
                )
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        pass

    # Wait for process to die (50 attempts × 0.1s = 5s)
    for _ in range(50):
        time.sleep(0.1)
        if not _is_process_alive(pid):
            return

    # Escalate to SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass

    for _ in range(10):
        time.sleep(0.1)
        if not _is_process_alive(pid):
            return


def buffer_stop(force: bool = False) -> str:
    """Stop the buffer service.

    Returns "stopped" on success, "refused" if a foreign listener is found
    and force is False.
    """
    pidfile_existed = CODEX_BUFFER_PID_FILE.is_file()
    if pidfile_existed:
        try:
            pid_text = CODEX_BUFFER_PID_FILE.read_text().strip()
            pid = int(pid_text)
        except (ValueError, OSError):
            pid = None

        if pid and _is_process_alive(pid):
            _kill_and_wait(pid)
            # Remove PID file and return — we killed our known process
            try:
                CODEX_BUFFER_PID_FILE.unlink()
            except OSError:
                pass
            return "stopped"

        # PID invalid or dead — clean up stale pidfile and fall through
        # to orphan listener check (something else may hold the port)
        try:
            CODEX_BUFFER_PID_FILE.unlink()
        except OSError:
            pass

    # No valid pidfile process — check for orphaned listener
    host, port = _resolve_host_port()
    listener = _listener_pid(host, port)
    if listener is None:
        return "stopped"

    identity = _health_identity(host, port)
    remote_bp = identity.get("build_path")
    expected = _expected_build_path()

    # Kill if: build_path matches ours, or the file no longer exists on disk
    if remote_bp and (os.path.realpath(remote_bp) == os.path.realpath(expected) or not os.path.isfile(remote_bp)):
        _kill_and_wait(listener)
        return "stopped"

    # Unknown/foreign listener
    if force:
        _kill_and_wait(listener)
        return "stopped"

    _log(f"Found unknown listener at PID {listener} " f"(build_path={remote_bp}). Pass --force to stop it.")
    return "refused"


def buffer_ensure() -> None:
    """Silent idempotent start. Never raises. Suitable for hooks.

    Hook invocations must not evict a healthy listener just because its
    build_path differs from this package. The buffer is in-memory, so a restart
    immediately before notify/drain loses the tool events accumulated earlier in
    the same turn.
    """
    try:
        buffer_start(evict_stale=False)
    except Exception:
        pass


def main() -> None:
    """CLI entrypoint for arize-codex-buffer."""
    if len(sys.argv) < 2 or sys.argv[1] not in ("start", "stop", "status"):
        sys.stderr.write("usage: arize-codex-buffer <start|stop|status>\n")
        sys.exit(1)

    command = sys.argv[1]

    if command == "status":
        status, pid, addr = buffer_status()
        if status == "running":
            host, port = _resolve_host_port()
            identity = _health_identity(host, port)
            bp = identity.get("build_path")
            if bp:
                print(f"running (PID {pid}, {addr}, build_path={bp})")
            else:
                print(f"running (PID {pid}, {addr})")
        else:
            print("stopped")

    elif command == "start":
        ok = buffer_start()
        if ok:
            status, pid, addr = buffer_status()
            if status == "running":
                print(f"running (PID {pid}, {addr})")
            else:
                print("started")
        else:
            print("failed to start buffer")
            sys.exit(1)

    elif command == "stop":
        force = "--force" in sys.argv[2:]
        result = buffer_stop(force=force)
        print(result)
        if result == "refused":
            sys.exit(1)


if __name__ == "__main__":
    main()
