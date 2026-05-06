#!/usr/bin/env python3
"""
Codex event buffer service for Arize Harness Tracing.

Minimal HTTP server that buffers Codex OTLP log events between hook
invocations.  No export logic — the notify handler drains events and
assembles spans itself.

Reads configuration from ~/.arize/harness/config.yaml.
Writes PID to ~/.arize/harness/run/codex-buffer.pid.
Logs to ~/.arize/harness/logs/codex-buffer.log.
"""

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

# --- Identity ---
BUILD_PATH = os.path.abspath(__file__)

# --- Paths ---
BASE_DIR = os.path.expanduser("~/.arize/harness")
CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")
PID_DIR = os.path.join(BASE_DIR, "run")
PID_FILE = os.path.join(PID_DIR, "codex-buffer.pid")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "codex-buffer.log")

# --- Limits ---
MAX_BODY_BYTES = 4 * 1024 * 1024  # 4 MB
SHUTDOWN_FLUSH_TIMEOUT = 5  # seconds
EVENT_BUFFER_TTL = 30 * 60  # 30 minutes

# --- Global state ---
_start_time = 0.0
_config = {}
_shutting_down = False
_log_lock = threading.Lock()
_event_lock = threading.Lock()
_event_buffers: "dict[str, list[dict]]" = {}  # conversation_id -> [event, ...]
_event_timestamps: "dict[str, float]" = {}  # conversation_id -> last_update_time


def _log(msg):
    """Append a timestamped line to the buffer log file."""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with _log_lock:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line)
        except OSError:
            pass
    sys.stderr.write(f"[codex-buffer] {msg}\n")


# --- Event buffer ---


def _expire_old_events():
    """Remove event buffers older than TTL."""
    now = time.time()
    with _event_lock:
        expired = [k for k, t in _event_timestamps.items() if now - t > EVENT_BUFFER_TTL]
        for k in expired:
            del _event_buffers[k]
            del _event_timestamps[k]


def _buffer_event(conversation_id, event):
    with _event_lock:
        if conversation_id not in _event_buffers:
            _event_buffers[conversation_id] = []
            _event_timestamps[conversation_id] = time.time()
        _event_buffers[conversation_id].append(event)
        _event_timestamps[conversation_id] = time.time()


def _flush_events(conversation_id):
    """Remove and return all buffered events for a conversation."""
    with _event_lock:
        events = _event_buffers.pop(conversation_id, [])
        _event_timestamps.pop(conversation_id, None)
    return events


def _flush_idle(timeout_seconds=2.0):
    """Flush conversations with no new events for timeout_seconds.

    Returns dict of {conversation_id: [events, ...]} for all idle conversations.
    Active conversations (with recent events) are left in the buffer.
    """
    now = time.time()
    result = {}
    with _event_lock:
        idle = [k for k, t in _event_timestamps.items() if now - t >= timeout_seconds]
        for k in idle:
            result[k] = _event_buffers.pop(k, [])
            _event_timestamps.pop(k, None)
    return result


def _drain_events(conversation_id, since_ns=0, wait_ms=0, quiet_ms=0):
    """Return events newer than since_ns, optionally waiting for more to arrive.

    wait_ms: maximum time to wait for events (0 = return immediately)
    quiet_ms: stop waiting once no new events arrive for this duration
    """
    deadline = time.time() + max(wait_ms, 0) / 1000.0
    quiet_s = max(quiet_ms, 0) / 1000.0
    last_signature = None
    quiet_started_at = None

    while True:
        with _event_lock:
            events = list(_event_buffers.get(conversation_id, []))
        if since_ns > 0:
            events = [e for e in events if int(e.get("time_ns", 0)) > since_ns]

        if events:
            signature = (len(events), int(events[-1].get("time_ns", 0)))
            if signature != last_signature:
                last_signature = signature
                quiet_started_at = time.time()
            elif quiet_s <= 0 or (quiet_started_at is not None and time.time() - quiet_started_at >= quiet_s):
                return events

        if time.time() >= deadline:
            return events

        time.sleep(0.05)


def _extract_log_events(body):
    """Extract (conversation_id, normalized_event) pairs from OTLP logs JSON."""
    results = []
    for rl in body.get("resourceLogs", []):
        for sl in rl.get("scopeLogs", []):
            for record in sl.get("logRecords", []):
                attrs = {}
                for a in record.get("attributes", []):
                    key = a.get("key", "")
                    val = a.get("value", {})
                    for vtype in ("stringValue", "intValue", "doubleValue", "boolValue"):
                        if vtype in val:
                            attrs[key] = val[vtype]
                            break

                conv_id = (
                    attrs.get("thread_id")
                    or attrs.get("codex.thread_id")
                    or attrs.get("thread")
                    or attrs.get("codex.thread")
                    or attrs.get("threadId")
                    or attrs.get("codex.threadId")
                    or attrs.get("conversation.id")
                    or attrs.get("codex.conversation.id")
                    or attrs.get("conversation_id")
                    or attrs.get("codex.conversation_id")
                    or attrs.get("conversationId")
                    or attrs.get("codex.conversationId")
                    or "unknown"
                )

                body_val = record.get("body", {})
                if isinstance(body_val, dict):
                    event_name = body_val.get("stringValue", "")
                elif isinstance(body_val, str):
                    event_name = body_val
                else:
                    event_name = ""
                if not event_name:
                    event_name = attrs.get("event.name", attrs.get("event", "unknown"))

                time_ns = record.get("timeUnixNano", 0)
                try:
                    time_ns_int = int(time_ns)
                except (TypeError, ValueError):
                    time_ns_int = 0
                if time_ns_int <= 0:
                    observed = record.get("observedTimeUnixNano", 0)
                    try:
                        time_ns_int = int(observed)
                    except (TypeError, ValueError):
                        time_ns_int = 0

                results.append(
                    (
                        str(conv_id),
                        {
                            "event": event_name,
                            "time_ns": time_ns_int,
                            "attrs": attrs,
                        },
                    )
                )
    return results


def _decode_otlp_logs(raw):
    """Decode an OTLP ExportLogsServiceRequest (JSON or protobuf) into a dict."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        from google.protobuf.json_format import MessageToDict
        from opentelemetry.proto.collector.logs.v1 import logs_service_pb2

        request = logs_service_pb2.ExportLogsServiceRequest()
        request.ParseFromString(raw)
        return MessageToDict(request)
    except Exception as exc:
        raise ValueError(f"unsupported OTLP log payload: {exc}") from exc


# --- HTTP Handler ---


class CodexBufferHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        _log(format % args)

    def _send_json(self, code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        """Read and validate request body. Returns raw bytes or None on error."""
        if _shutting_down:
            self._send_json(503, {"status": "error", "message": "shutting down"})
            return None
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json(400, {"status": "error", "message": "invalid Content-Length"})
            return None
        if content_length > MAX_BODY_BYTES:
            self._send_json(413, {"status": "error", "message": "payload too large"})
            return None
        if content_length == 0:
            self._send_json(400, {"status": "error", "message": "empty body"})
            return None
        return self.rfile.read(content_length)

    def do_POST(self):
        from urllib.parse import urlparse

        path = urlparse(self.path).path.rstrip("/")

        # POST /v1/logs or root (Codex sends to both)
        if path in ("/v1/logs", ""):
            self._handle_logs()
        else:
            self._send_json(404, {"status": "error", "message": f"unknown path: {path}"})

    def _handle_logs(self):
        """Accept OTLP log events and buffer by conversation ID."""
        raw = self._read_body()
        if raw is None:
            return

        try:
            body = _decode_otlp_logs(raw)
        except ValueError as e:
            self._send_json(400, {"status": "error", "message": str(e)})
            return

        events = _extract_log_events(body)
        for conv_id, event in events:
            _buffer_event(conv_id, event)

        self._send_json(200, {"status": "accepted", "buffered": len(events)})

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/health":
            self._handle_health()
        elif path.startswith("/flush/"):
            conv_id = path[len("/flush/") :]
            if not conv_id:
                self._send_json(400, {"status": "error", "message": "missing conversation_id"})
                return
            events = _flush_events(conv_id)
            self._send_json(200, events)
        elif path == "/flush-idle":
            query = parse_qs(parsed.query)
            raw_timeout = query.get("timeout_seconds", ["2"])[0]
            try:
                timeout = float(raw_timeout)
            except (TypeError, ValueError):
                self._send_json(
                    400,
                    {
                        "status": "error",
                        "message": f"invalid timeout_seconds: {raw_timeout!r}",
                    },
                )
                return
            result = _flush_idle(timeout)
            self._send_json(200, result)
        elif path.startswith("/drain/"):
            conv_id = path[len("/drain/") :]
            if not conv_id:
                self._send_json(400, {"status": "error", "message": "missing conversation_id"})
                return
            query = parse_qs(parsed.query)
            since_ns = int(query.get("since_ns", ["0"])[0] or "0")
            wait_ms = int(query.get("wait_ms", ["0"])[0] or "0")
            quiet_ms = int(query.get("quiet_ms", ["0"])[0] or "0")
            events = _drain_events(conv_id, since_ns=since_ns, wait_ms=wait_ms, quiet_ms=quiet_ms)
            self._send_json(200, events)
        else:
            self._send_json(404, {"status": "error", "message": "not found"})

    def _handle_health(self):
        with _event_lock:
            buffered_events = sum(len(v) for v in _event_buffers.values())
            conversations = len(_event_buffers)
        health = {
            "status": "ok",
            "pid": os.getpid(),
            "build_path": BUILD_PATH,
            "started_at": _start_time,
            "uptime_seconds": int(time.time() - _start_time),
            "event_buffer": {
                "buffered_events": buffered_events,
                "conversations": conversations,
            },
        }
        self._send_json(200, health)


# --- Process lifecycle ---


def _write_pid():
    os.makedirs(PID_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def main():
    global _start_time, _config, _shutting_down

    try:
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                _config = yaml.safe_load(f) or {}
        else:
            _config = {}
    except Exception:
        _config = {}

    # Read collector config from harnesses.codex.collector
    codex_cfg = _config.get("harnesses", {}).get("codex", {})
    collector_cfg = codex_cfg.get("collector", {})
    host = collector_cfg.get("host", "127.0.0.1")
    port = int(collector_cfg.get("port", 4318))

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(PID_DIR, exist_ok=True)

    _start_time = time.time()
    _write_pid()

    server = ThreadingHTTPServer((host, port), CodexBufferHandler)

    def _shutdown(signum, frame):
        global _shutting_down
        _shutting_down = True
        _log("Received shutdown signal, stopping...")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _log(f"Codex buffer listening on {host}:{port} (PID {os.getpid()})")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _remove_pid()
        _log("Codex buffer stopped")


if __name__ == "__main__":
    main()
