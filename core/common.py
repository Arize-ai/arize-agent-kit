#!/usr/bin/env python3
"""Shared library for arize-agent-kit: state management and file locking.

Provides FileLock (cross-platform file locking) and StateManager (per-session
key-value state backed by YAML files). Replaces the jq-based state functions
in common.sh lines 46-109.
"""
import os
import shutil
import sys
import time
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Environment helper — reads tracing-related env vars with defaults
# ---------------------------------------------------------------------------

class _Env:
    """Lazy accessor for tracing-related environment variables.

    Property reads are live (not cached) so tests can monkeypatch os.environ.
    """

    @property
    def trace_enabled(self) -> bool:
        return os.environ.get("ARIZE_TRACE_ENABLED", "true").lower() == "true"

    @property
    def project_name(self) -> str:
        return os.environ.get("ARIZE_PROJECT_NAME", "")

    @property
    def user_id(self) -> str:
        return os.environ.get("ARIZE_USER_ID", "")

    @property
    def verbose(self) -> bool:
        return os.environ.get("ARIZE_VERBOSE", "").lower() == "true"

    @property
    def dry_run(self) -> bool:
        return os.environ.get("ARIZE_DRY_RUN", "false").lower() == "true"

    @property
    def log_file(self) -> str:
        return os.environ.get("ARIZE_LOG_FILE", "/tmp/arize-agent-kit.log")


env = _Env()


# ---------------------------------------------------------------------------
# ID and timestamp generation
# ---------------------------------------------------------------------------

def generate_trace_id() -> str:
    """Generate a 32-hex-char trace ID (replaces uuidgen | tr -d '-')."""
    return os.urandom(16).hex()


def generate_span_id() -> str:
    """Generate a 16-hex-char span ID (replaces uuidgen | tr -d '-' | cut -c1-16)."""
    return os.urandom(8).hex()


def get_timestamp_ms() -> int:
    """Current time in milliseconds since epoch (replaces date +%s%3N)."""
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _is_verbose() -> bool:
    return os.environ.get("ARIZE_VERBOSE", "").lower() == "true"


def log(msg: str) -> None:
    """Verbose log — only written when ARIZE_VERBOSE=true. Goes to stderr."""
    if _is_verbose():
        print(f"[arize] {msg}", file=sys.stderr, flush=True)


def error(msg: str) -> None:
    """Error log — always written. Goes to stderr."""
    print(f"[arize:error] {msg}", file=sys.stderr, flush=True)


def debug_dump(label: str, data: object) -> None:
    """Trace-level debug dump — only when ARIZE_TRACE_DEBUG=true.

    Writes YAML files to {STATE_DIR}/debug/{label}_{timestamp}.yaml.
    Used by Codex hooks for detailed payload inspection.
    """
    if os.environ.get("ARIZE_TRACE_DEBUG", "").lower() != "true":
        return
    try:
        from core.constants import STATE_BASE_DIR
        debug_dir = STATE_BASE_DIR / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        dump_file = debug_dir / f"{label}_{ts}.yaml"
        dump_file.write_text(yaml.safe_dump(data, default_flow_style=False), encoding="utf-8")
    except Exception:
        pass  # debug dumps must never cause failures


# --- Platform-specific lock implementation detection ---
try:
    import fcntl
    _LOCK_IMPL = "fcntl"
except ImportError:
    try:
        import msvcrt
        _LOCK_IMPL = "msvcrt"
    except ImportError:
        _LOCK_IMPL = "mkdir"


class FileLock:
    """Cross-platform file lock.

    Uses fcntl.flock on Unix, msvcrt.locking on Windows.
    Falls back to mkdir-based locking if neither is available.

    Usage:
        with FileLock(Path("/path/to/.lock"), timeout=3.0):
            # exclusive access

    The lock_path can be a file or directory path:
    - fcntl/msvcrt mode: creates/opens lock_path as a file
    - mkdir fallback: creates lock_path as a directory (matches bash behavior)
    """

    def __init__(self, lock_path: Path, timeout: float = 3.0) -> None:
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self._fd = None
        self._method = _LOCK_IMPL

    def __enter__(self) -> "FileLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        if self._method == "fcntl":
            self._acquire_fcntl()
        elif self._method == "msvcrt":
            self._acquire_msvcrt()
        else:
            self._acquire_mkdir()
        return self

    def __exit__(self, *args) -> None:
        if self._method == "fcntl":
            self._release_fcntl()
        elif self._method == "msvcrt":
            self._release_msvcrt()
        else:
            self._release_mkdir()

    def _acquire_fcntl(self) -> None:
        self._fd = open(self.lock_path, "w")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    # Force-acquire: close, remove, reopen
                    self._fd.close()
                    try:
                        self.lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    self._fd = open(self.lock_path, "w")
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return
                time.sleep(0.1)

    def _release_fcntl(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                self._fd.close()
            except OSError:
                pass
            self._fd = None

    def _acquire_msvcrt(self) -> None:
        self._fd = open(self.lock_path, "w")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    self._fd.close()
                    try:
                        self.lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    self._fd = open(self.lock_path, "w")
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                    return
                time.sleep(0.1)

    def _release_msvcrt(self) -> None:
        if self._fd is not None:
            try:
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLOCK, 1)
            except OSError:
                pass
            try:
                self._fd.close()
            except OSError:
                pass
            self._fd = None

    def _acquire_mkdir(self) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.lock_path.mkdir()
                return
            except FileExistsError:
                if time.monotonic() >= deadline:
                    # Force-acquire: remove and recreate (matches bash lines 67-70)
                    try:
                        shutil.rmtree(self.lock_path)
                    except OSError:
                        pass
                    try:
                        self.lock_path.mkdir()
                    except FileExistsError:
                        pass
                    return
                time.sleep(0.1)

    def _release_mkdir(self) -> None:
        try:
            self.lock_path.rmdir()
        except OSError:
            pass


class StateManager:
    """Per-session key-value state backed by a YAML file.

    All values are stored as strings (matching bash behavior where jq
    reads/writes everything as string arguments via --arg).

    The state_file and lock_path are set by the adapter when resolving
    the session (e.g., state_<session_id>.yaml with .lock_<session_id>).
    """

    def __init__(
        self,
        state_dir: Path,
        state_file: "Path | None" = None,
        lock_path: "Path | None" = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_file = Path(state_file) if state_file is not None else None
        self._lock_path = Path(lock_path) if lock_path is not None else None

    def init_state(self) -> None:
        """Create state directory and file.

        If file doesn't exist, create with empty dict.
        If file exists but is corrupted, overwrite with empty dict.
        Matches bash init_state() at common.sh:49-59.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.state_file is None:
            return
        if not self.state_file.exists():
            self._write({})
        else:
            # Validate existing file; overwrite if corrupted
            try:
                data = self._read()
                if not isinstance(data, dict):
                    self._write({})
            except Exception:
                self._write({})

    def get(self, key: str) -> "str | None":
        """Read a value by key. Returns None if key missing or file missing.

        Does NOT acquire lock (read-only, matches bash get_state which
        doesn't call _lock_state).
        """
        data = self._read_safe()
        val = data.get(key)
        if val is None:
            return None
        return str(val)

    def set(self, key: str, value: str) -> None:
        """Set a key-value pair. Acquires lock.

        Value is always stored as string (matches bash: jq --arg v "$2").
        Uses atomic write: write to .tmp.{pid} then rename.
        """
        if self.state_file is None:
            return
        try:
            with self._lock():
                data = self._read_safe()
                data[key] = str(value)
                self._write(data)
        except Exception as e:
            error(f"set_state failed for key={key}: {e}")

    def delete(self, key: str) -> None:
        """Remove a key. No-op if missing. Acquires lock."""
        if self.state_file is None:
            return
        try:
            with self._lock():
                data = self._read_safe()
                data.pop(key, None)
                self._write(data)
        except Exception as e:
            error(f"del_state failed for key={key}: {e}")

    def increment(self, key: str) -> None:
        """Increment a numeric string value. Acquires lock.

        Missing key treated as "0" -> becomes "1".
        Non-numeric value treated as 0 -> becomes "1".
        Matches bash inc_state() at common.sh:101-108.
        """
        if self.state_file is None:
            return
        try:
            with self._lock():
                data = self._read_safe()
                current = data.get(key, "0")
                try:
                    num = int(current)
                except (ValueError, TypeError):
                    num = 0
                data[key] = str(num + 1)
                self._write(data)
        except Exception as e:
            error(f"inc_state failed for key={key}: {e}")

    def _lock(self) -> FileLock:
        """Return a FileLock for this state file."""
        if self._lock_path is not None:
            return FileLock(self._lock_path)
        # Default lock path next to state file
        return FileLock(self.state_file.with_suffix(".lock"))

    def _read_safe(self) -> dict:
        """Read state file, return {} on any error (missing, corrupt, permission)."""
        try:
            return self._read()
        except Exception:
            return {}

    def _read(self) -> dict:
        """Read state file, raise on error."""
        if self.state_file is None:
            return {}
        text = self.state_file.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"State file is not a mapping: {type(data)}")
        return data

    def _write(self, data: dict) -> None:
        """Write dict to state file atomically via tmp+rename."""
        if self.state_file is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(f".tmp.{os.getpid()}")
        try:
            tmp.write_text(yaml.safe_dump(data, default_flow_style=False), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
