#!/usr/bin/env python3
"""
Codex-specific event buffer for child-span assembly.

Receives OTLP ExportLogsServiceRequest payloads on POST / or /v1/logs,
buffers events by conversation_id, and serves them via GET /flush/{id}
and GET /drain/{id}.

This is NOT the span exporter — it is a Codex-only input component that
buffers native Codex OTel events until notify.sh drains them to build
child spans.  The actual span export is handled by the shared collector
at 127.0.0.1:4318 (core/collector.py).

It accepts OTLP/HTTP JSON directly and will also decode protobuf OTLP payloads
when the protobuf runtime is available in the environment.
"""

import json
import os
import signal
import sys
import threading
import time
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

# --- Configuration ---
# Event buffer listens on port 4319 by default to avoid conflict with the
# shared span exporter on port 4318.  Override with CODEX_EVENT_PORT.
PORT = int(os.environ.get("CODEX_EVENT_PORT", os.environ.get("CODEX_COLLECTOR_PORT", "4319")))
HOST = "127.0.0.1"
TTL_SECONDS = 30 * 60  # 30 minutes
INACTIVITY_TIMEOUT = 30 * 60  # 30 minutes
PID_DIR = os.path.expanduser("~/.arize-codex")
PID_FILE = os.path.join(PID_DIR, "event_buffer.pid")
DEBUG_DIR = os.path.join(PID_DIR, "debug")

# --- Buffer ---
_lock = threading.Lock()
_buffers: Dict[str, List[dict]] = {}
_timestamps: Dict[str, float] = {}
_last_activity = time.time()


def _debug_write(name: str, data):
    if os.environ.get("ARIZE_TRACE_DEBUG") != "true":
        return
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        ts = int(time.time() * 1000)
        path = os.path.join(DEBUG_DIR, f"collector_{name}_{ts}.log")
        with open(path, "w") as f:
            if isinstance(data, (dict, list)):
                json.dump(data, f, indent=2)
            else:
                f.write(str(data))
    except Exception:
        pass


def _update_activity():
    global _last_activity
    _last_activity = time.time()


def _expire_old():
    """Remove buffers older than TTL."""
    now = time.time()
    with _lock:
        expired = [k for k, t in _timestamps.items() if now - t > TTL_SECONDS]
        for k in expired:
            del _buffers[k]
            del _timestamps[k]


def _buffer_event(conversation_id: str, event: dict):
    with _lock:
        if conversation_id not in _buffers:
            _buffers[conversation_id] = []
            _timestamps[conversation_id] = time.time()
        _buffers[conversation_id].append(event)
        _timestamps[conversation_id] = time.time()
    _update_activity()


def _flush_events(conversation_id: str) -> List[dict]:
    with _lock:
        events = _buffers.pop(conversation_id, [])
        _timestamps.pop(conversation_id, None)
    _update_activity()
    return events


def _event_time_ns(event: dict) -> int:
    value = event.get("time_ns", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _events_since(conversation_id: str, since_ns: int) -> List[dict]:
    with _lock:
        events = list(_buffers.get(conversation_id, []))
    return [event for event in events if _event_time_ns(event) > since_ns]


def _drain_events(conversation_id: str, since_ns: int, wait_ms: int = 0, quiet_ms: int = 0) -> List[dict]:
    deadline = time.time() + max(wait_ms, 0) / 1000.0
    quiet_s = max(quiet_ms, 0) / 1000.0
    last_signature = None
    quiet_started_at = None

    while True:
        events = _events_since(conversation_id, since_ns)
        signature = (
            len(events),
            _event_time_ns(events[-1]) if events else 0,
        )

        if events:
            if signature != last_signature:
                last_signature = signature
                quiet_started_at = time.time()
            elif quiet_s <= 0 or (quiet_started_at is not None and time.time() - quiet_started_at >= quiet_s):
                _update_activity()
                return events

        if time.time() >= deadline:
            _update_activity()
            return events

        time.sleep(0.05)


def _extract_events(body: dict) -> List[Tuple[str, dict]]:
    """Extract (conversation_id, normalized_event) pairs from OTLP logs JSON."""
    results = []
    for rl in body.get("resourceLogs", []):
        for sl in rl.get("scopeLogs", []):
            for record in sl.get("logRecords", []):
                attrs = {}
                for a in record.get("attributes", []):
                    key = a.get("key", "")
                    val = a.get("value", {})
                    # Extract typed value
                    for vtype in ("stringValue", "intValue", "doubleValue", "boolValue"):
                        if vtype in val:
                            attrs[key] = val[vtype]
                            break

                # Determine buffer key — prefer thread_id because notify flushes
                # by thread-id, then fall back to conversation_id variants.
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

                # Event name from body or attributes
                event_name = ""
                body_val = record.get("body", {})
                if isinstance(body_val, dict):
                    event_name = body_val.get("stringValue", "")
                elif isinstance(body_val, str):
                    event_name = body_val

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

                normalized = {
                    "event": event_name,
                    "time_ns": time_ns_int,
                    "attrs": attrs,
                }
                results.append((str(conv_id), normalized))
    if os.environ.get("ARIZE_TRACE_DEBUG") == "true":
        summary = [
            {
                "conversation_id": conv_id,
                "event": event.get("event"),
                "attr_keys": sorted(event.get("attrs", {}).keys()),
            }
            for conv_id, event in results[:50]
        ]
        _debug_write("extract_summary", summary)
    return results


def _decode_request_body(raw: bytes) -> dict:
    """Decode an OTLP ExportLogsServiceRequest into a Python dict."""
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
        raise ValueError(f"unsupported OTLP payload: {exc}") from exc


class CollectorHandler(BaseHTTPRequestHandler):
    """HTTP handler for the collector endpoints."""

    def log_message(self, format, *args):
        # Suppress default access logs unless debug
        if os.environ.get("ARIZE_TRACE_DEBUG") == "true":
            sys.stderr.write(f"[collector] {format % args}\n")

    def _send_json(self, code: int, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path in ("/", "/v1/logs", "/v1/logs/"):
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_json(400, {"error": "empty body"})
                return

            raw = self.rfile.read(content_length)
            try:
                body = _decode_request_body(raw)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return

            _debug_write("request_body", body)

            events = _extract_events(body)
            for conv_id, event in events:
                _buffer_event(conv_id, event)

            self._send_json(200, {"accepted": len(events)})
        else:
            self._send_json(404, {"error": "not found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            with _lock:
                buf_count = sum(len(v) for v in _buffers.values())
            self._send_json(200, {
                "status": "ok",
                "buffered_events": buf_count,
                "conversations": len(_buffers),
                "uptime_s": int(time.time() - _start_time),
            })
        elif path.startswith("/flush/"):
            conv_id = path[len("/flush/"):]
            if not conv_id:
                self._send_json(400, {"error": "missing conversation_id"})
                return
            events = _flush_events(conv_id)
            self._send_json(200, events)
        elif path.startswith("/drain/"):
            conv_id = path[len("/drain/"):]
            if not conv_id:
                self._send_json(400, {"error": "missing conversation_id"})
                return
            try:
                since_ns = int((query.get("since_ns", ["0"])[0] or "0"))
                wait_ms = int((query.get("wait_ms", ["0"])[0] or "0"))
                quiet_ms = int((query.get("quiet_ms", ["0"])[0] or "0"))
            except ValueError:
                self._send_json(400, {"error": "invalid query params"})
                return
            events = _drain_events(conv_id, since_ns=since_ns, wait_ms=wait_ms, quiet_ms=quiet_ms)
            self._send_json(200, events)
        else:
            self._send_json(404, {"error": "not found"})


def _write_pid():
    os.makedirs(PID_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def _inactivity_watchdog():
    """Exit if no activity for INACTIVITY_TIMEOUT seconds."""
    while True:
        time.sleep(60)  # Check every minute
        if time.time() - _last_activity > INACTIVITY_TIMEOUT:
            sys.stderr.write("[collector] Exiting after inactivity timeout\n")
            _remove_pid()
            os._exit(0)
        # Also expire old buffers
        _expire_old()


_start_time = time.time()


def main():
    global _start_time
    _start_time = time.time()

    _write_pid()

    def _shutdown(signum, frame):
        _remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Start inactivity watchdog
    watchdog = threading.Thread(target=_inactivity_watchdog, daemon=True)
    watchdog.start()

    server = ThreadingHTTPServer((HOST, PORT), CollectorHandler)
    sys.stderr.write(f"[collector] Listening on {HOST}:{PORT} (PID {os.getpid()})\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _remove_pid()


if __name__ == "__main__":
    main()
