#!/usr/bin/env python3
"""Shared library for arize-agent-kit: state management, file locking, and span building.

Provides FileLock (cross-platform file locking), StateManager (per-session
key-value state backed by YAML files), and OTLP span building functions.
Replaces the jq-based state functions in common.sh lines 46-109 and
build_span/build_multi_span from common.sh lines 277-317 / codex common.sh lines 110-145.
"""
import json as _json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error
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

    @property
    def collector_host(self) -> str:
        val = os.environ.get("ARIZE_COLLECTOR_HOST", "")
        if val:
            return val
        try:
            from core.config import load_config, get_value
            cfg = load_config()
            v = get_value(cfg, "collector.host")
            if v:
                return str(v)
        except Exception:
            pass
        from core.constants import DEFAULT_COLLECTOR_HOST
        return DEFAULT_COLLECTOR_HOST

    @property
    def collector_port(self) -> int:
        val = os.environ.get("ARIZE_COLLECTOR_PORT", "")
        if val:
            try:
                return int(val)
            except ValueError:
                pass
        try:
            from core.config import load_config, get_value
            cfg = load_config()
            v = get_value(cfg, "collector.port")
            if v is not None:
                return int(v)
        except Exception:
            pass
        from core.constants import DEFAULT_COLLECTOR_PORT
        return DEFAULT_COLLECTOR_PORT

    @property
    def collector_url(self) -> str:
        return f"http://{self.collector_host}:{self.collector_port}"

    @property
    def phoenix_endpoint(self) -> str:
        return os.environ.get("PHOENIX_ENDPOINT", "")

    @property
    def api_key(self) -> str:
        return os.environ.get("ARIZE_API_KEY", "")

    @property
    def space_id(self) -> str:
        return os.environ.get("ARIZE_SPACE_ID", "")

    @property
    def direct_send(self) -> bool:
        return os.environ.get("ARIZE_DIRECT_SEND", "").lower() == "true"


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


# ---------------------------------------------------------------------------
# Target detection and span sending
# ---------------------------------------------------------------------------

def get_target() -> str:
    """Detect backend target from env vars.

    Returns "phoenix", "arize", or "none".
    """
    if env.phoenix_endpoint:
        return "phoenix"
    if env.api_key and env.space_id:
        return "arize"
    return "none"


def _send_to_collector(span_dict: dict) -> bool:
    """POST span to the local collector. Returns True on success."""
    url = f"{env.collector_url}/v1/spans"
    try:
        body = _json.dumps(span_dict).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        log(f"Collector send failed ({url}): {e}")
        return False


def _extract_span_name(span_dict: dict) -> str:
    """Extract the first span name from an OTLP payload."""
    try:
        return span_dict["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"]
    except (KeyError, IndexError, TypeError):
        return "unknown"


def send_span(span_dict: dict) -> bool:
    """Send a span payload. Tries collector first, falls back to direct send.

    Never raises. Returns True on success, False on failure.
    """
    try:
        if env.dry_run:
            log(f"[dry-run] would send span: {_extract_span_name(span_dict)}")
            return True

        if env.verbose:
            log(f"span payload: {_json.dumps(span_dict)}")

        # Try collector first (unless direct send requested)
        if not env.direct_send:
            if _send_to_collector(span_dict):
                return True

        # Direct send fallback
        target = get_target()
        if target == "phoenix":
            # Phoenix send via urllib
            try:
                from core.config import load_config, get_value
                cfg = load_config()
                project = get_value(cfg, "project_name") or env.project_name or "default"
            except Exception:
                project = env.project_name or "default"
            url = f"{env.phoenix_endpoint}/v1/projects/{project}/spans"
            body = _json.dumps(span_dict).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if env.api_key:
                headers["Authorization"] = f"Bearer {env.api_key}"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return 200 <= resp.status < 300
            except Exception as e:
                error(f"Phoenix send failed: {e}")
                return False
        elif target == "arize":
            try:
                from core.send_arize import send_to_arize
                return send_to_arize(span_dict)
            except ImportError:
                error("send_arize not available (missing opentelemetry-proto/grpcio)")
                return False
            except Exception as e:
                error(f"Arize send failed: {e}")
                return False
        else:
            error("No backend configured (set PHOENIX_ENDPOINT or ARIZE_API_KEY+ARIZE_SPACE_ID)")
            return False
    except Exception as e:
        error(f"send_span failed: {e}")
        return False


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


# ── OTLP Span Building ────────────────────────────────────────────────────

# Map string kind names to OTLP SpanKind integer values.
# Case-insensitive lookup (caller passes "LLM", "TOOL", etc.)
SPAN_KIND_MAP: dict = {
    # kind 1 = SPAN_KIND_INTERNAL (used for LLM, CHAIN, TOOL, INTERNAL in OpenInference)
    "": 1, "llm": 1, "chain": 1, "tool": 1, "internal": 1,
    "span_kind_internal": 1,
    # kind 2 = SPAN_KIND_SERVER
    "server": 2, "span_kind_server": 2,
    # kind 3 = SPAN_KIND_CLIENT
    "client": 3, "span_kind_client": 3,
    # kind 4 = SPAN_KIND_PRODUCER
    "producer": 4, "span_kind_producer": 4,
    # kind 5 = SPAN_KIND_CONSUMER
    "consumer": 5, "span_kind_consumer": 5,
    # kind 0 = SPAN_KIND_UNSPECIFIED
    "unspecified": 0, "span_kind_unspecified": 0,
}


def _resolve_kind(kind: str) -> int:
    """Resolve a span kind string to an OTLP SpanKind integer.

    Case-insensitive lookup in SPAN_KIND_MAP. If not found and numeric, parse
    as int. Otherwise default to 1 (SPAN_KIND_INTERNAL).
    """
    lookup = SPAN_KIND_MAP.get(kind.lower())
    if lookup is not None:
        return lookup
    # Numeric string (matches bash: if [[ "$kind" =~ ^[0-9]+$ ]])
    try:
        return int(kind)
    except (ValueError, TypeError):
        return 1


def _to_otlp_attr_value(value) -> dict:
    """Convert a Python value to OTLP attribute value dict.

    Matches the jq type-detection logic in build_span:
    - bool → {"boolValue": v}          (check BEFORE int — bool is subclass of int)
    - int → {"intValue": v}
    - float with no fractional part → {"intValue": int(v)}   (matches jq: floor == value)
    - float with fractional part → {"doubleValue": v}
    - everything else → {"stringValue": str(v)}
    """
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        if value == int(value):
            return {"intValue": int(value)}
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _attrs_to_otlp(attrs: dict) -> list:
    """Convert a flat Python dict to OTLP attribute list.

    Input:  {"session.id": "abc", "llm.token_count.prompt": 100}
    Output: [{"key": "session.id", "value": {"stringValue": "abc"}},
             {"key": "llm.token_count.prompt", "value": {"intValue": 100}}]
    """
    return [{"key": k, "value": _to_otlp_attr_value(v)} for k, v in attrs.items()]


def build_span(
    name: str,
    kind: str,
    span_id: str,
    trace_id: str,
    parent_span_id: str = "",
    start_ms: "int | str" = 0,
    end_ms: "int | str" = 0,
    attrs: "dict | None" = None,
    service_name: str = "arize-agent-kit",
    scope_name: str = "arize-agent-kit",
) -> dict:
    """Build an OTLP JSON span payload.

    Returns a dict matching the exact structure produced by core/common.sh:build_span().

    Timestamp handling: start_ms and end_ms are in milliseconds. The OTLP format
    requires nanoseconds as strings. Bash appends "000000" (line 312):
        "startTimeUnixNano":"${start}000000"
    Python does the same: f"{int(start_ms)}000000"

    If end_ms is empty/None/0, defaults to start_ms (matches bash: end="${7:-$start}").
    """
    if attrs is None:
        attrs = {}

    start = int(start_ms) if start_ms else 0
    end = int(end_ms) if end_ms else start

    kind_value = _resolve_kind(kind or "")

    span_obj = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": kind_value,
        "startTimeUnixNano": f"{start}000000",
        "endTimeUnixNano": f"{end}000000",
        "attributes": _attrs_to_otlp(attrs),
        "status": {"code": 1},
    }

    # parentSpanId only included if non-empty (matches bash conditional)
    if parent_span_id:
        span_obj["parentSpanId"] = parent_span_id

    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}}
                ]
            },
            "scopeSpans": [{
                "scope": {"name": scope_name},
                "spans": [span_obj]
            }]
        }]
    }


def build_multi_span(
    span_payloads: list,
    service_name: str = "arize-agent-kit",
    scope_name: str = "arize-agent-kit",
) -> dict:
    """Merge multiple build_span() outputs into a single resourceSpans payload.

    Extracts the span object from each payload's
    resourceSpans[0].scopeSpans[0].spans[0] and combines them under
    one resource/scope envelope.

    Returns {} if no valid spans found (matches bash: echo "{}"; return 1).
    """
    spans = []
    for payload in span_payloads:
        try:
            span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            spans.append(span)
        except (KeyError, IndexError, TypeError):
            continue

    if not spans:
        return {}

    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}}
                ]
            },
            "scopeSpans": [{
                "scope": {"name": scope_name},
                "spans": spans
            }]
        }]
    }
