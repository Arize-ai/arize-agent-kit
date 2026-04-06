#!/usr/bin/env python3
"""
Shared background collector/exporter for Arize Agent Kit.

Accepts OTLP JSON span payloads on POST /v1/spans from any harness,
exports to the configured backend (Phoenix REST or Arize AX gRPC),
and reports health on GET /health.

Reads configuration from ~/.arize/harness/config.yaml.
Writes PID to ~/.arize/harness/run/collector.pid.
Logs to ~/.arize/harness/logs/collector.log.

This is a stdlib-only runtime for the HTTP server and Phoenix export path.
Arize AX gRPC export requires grpcio and opentelemetry-proto, which are
expected to be bundled with the collector — not in the user's environment.
"""

import base64
import json
import os
import yaml
import signal
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# --- Paths ---
BASE_DIR = os.path.expanduser("~/.arize/harness")
CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")
PID_DIR = os.path.join(BASE_DIR, "run")
PID_FILE = os.path.join(PID_DIR, "collector.pid")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "collector.log")

# --- Limits ---
MAX_BODY_BYTES = 4 * 1024 * 1024  # 4 MB
SHUTDOWN_FLUSH_TIMEOUT = 5  # seconds
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = [1, 2, 4]  # seconds
EVENT_BUFFER_TTL = 30 * 60  # 30 minutes

# --- Global state ---
_start_time = 0.0
_config = {}
_shutting_down = False
_last_backend_error = ""
_last_backend_error_lock = threading.Lock()
_log_lock = threading.Lock()
_inflight_exports = []  # list of threading.Thread
_inflight_lock = threading.Lock()

# --- Event buffer state (Codex OTLP log buffering) ---
_event_lock = threading.Lock()
_event_buffers = {}   # conversation_id -> [event, ...]
_event_timestamps = {}  # conversation_id -> last_update_time
_logged_conv_debug = 0


def _log(msg):
    """Append a timestamped line to the collector log file."""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with _log_lock:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line)
        except OSError:
            pass
    sys.stderr.write(f"[collector] {msg}\n")


def _set_last_error(err):
    global _last_backend_error
    with _last_backend_error_lock:
        _last_backend_error = str(err) if err else ""


def _get_last_error():
    with _last_backend_error_lock:
        return _last_backend_error


# --- Config ---

def load_config():
    """Load config from ~/.arize/harness/config.yaml.

    Config file is required — run install.py or the setup skill to create it.
    """
    if not os.path.isfile(CONFIG_FILE):
        raise ValueError(
            f"No config found at {CONFIG_FILE}. "
            "Run install.py or use the setup skill to create it."
        )

    with open(CONFIG_FILE, "r") as f:
        cfg = yaml.safe_load(f)

    backend = cfg.get("backend", {})
    target = backend.get("target", "")
    if target not in ("phoenix", "arize"):
        raise ValueError(
            f"Invalid or missing backend.target: '{target}'. Must be 'phoenix' or 'arize'."
        )
    if target == "arize":
        arize_cfg = backend.get("arize", {})
        if not arize_cfg.get("api_key"):
            raise ValueError("backend.arize.api_key is required when target is 'arize'")
        if not arize_cfg.get("space_id"):
            raise ValueError("backend.arize.space_id is required when target is 'arize'")

    return cfg


def _resolve_project_name(span_json, config):
    """Resolve the project name for a span payload.

    Priority:
    1. harnesses.<service_name>.project_name in config (explicit per-harness override)
    2. ARIZE_PROJECT_NAME env var
    3. service.name resource attribute from the span
    4. "default"
    """
    # Extract service.name from span resource attributes
    service_name = ""
    for rs in span_json.get("resourceSpans", []):
        for attr in rs.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                service_name = attr.get("value", {}).get("stringValue", "")
                break
        if service_name:
            break

    # Look up per-harness config
    harness_cfg = config.get("harnesses", {}).get(service_name, {})
    project_name = harness_cfg.get("project_name", "")

    if not project_name:
        project_name = os.environ.get("ARIZE_PROJECT_NAME", "")
    if not project_name:
        project_name = service_name
    if not project_name:
        project_name = "default"

    return project_name


# --- Backend export ---

def _export_to_phoenix(span_json, phoenix_cfg):
    """Forward spans to Phoenix via REST API with retries.

    Transforms the OTLP JSON payload into the Phoenix /v1/projects/<project>/spans
    format that the legacy direct sender used, so the collector sends the same
    payload format Phoenix expects.
    """
    endpoint = phoenix_cfg.get("endpoint", "http://localhost:6006")
    api_key = phoenix_cfg.get("api_key", "")
    project = phoenix_cfg.get("project_name", "default")
    url = f"{endpoint}/v1/projects/{project}/spans"

    # Transform OTLP JSON into Phoenix span format (matches legacy send_to_phoenix)
    phoenix_spans = []
    for rs in span_json.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            for s in ss.get("spans", []):
                attrs = {}
                for a in s.get("attributes", []):
                    key = a.get("key", "")
                    val = a.get("value", {})
                    if not key:
                        continue
                    for vtype in ("stringValue", "doubleValue", "intValue", "boolValue"):
                        if vtype in val:
                            attrs[key] = val[vtype]
                            break
                    else:
                        attrs[key] = ""

                start_nano = int(s.get("startTimeUnixNano", 0))
                end_nano = int(s.get("endTimeUnixNano", 0))

                phoenix_spans.append({
                    "name": s.get("name", ""),
                    "context": {
                        "trace_id": s.get("traceId", ""),
                        "span_id": s.get("spanId", ""),
                    },
                    "parent_id": s.get("parentSpanId", ""),
                    "span_kind": "CHAIN",
                    "start_time": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_nano / 1e9)
                    ) if start_nano else "",
                    "end_time": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_nano / 1e9)
                    ) if end_nano else "",
                    "status_code": "OK",
                    "attributes": attrs,
                })

    body = json.dumps({"data": phoenix_spans}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            _set_last_error("")
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF[attempt])

    _set_last_error(last_err)
    _log(f"Phoenix export failed after {RETRY_ATTEMPTS} attempts: {last_err}")
    return False


def _export_to_arize(span_json, arize_cfg):
    """Forward OTLP JSON spans to Arize AX via gRPC with retries."""
    api_key = arize_cfg.get("api_key", "")
    space_id = arize_cfg.get("space_id", "")
    endpoint = arize_cfg.get("endpoint", "otlp.arize.com:443")
    project_name = arize_cfg.get("project_name", "default")

    try:
        import grpc
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2_grpc
        from opentelemetry.proto.trace.v1 import trace_pb2
        from opentelemetry.proto.common.v1 import common_pb2
        from opentelemetry.proto.resource.v1 import resource_pb2
    except ImportError as e:
        err_msg = f"Arize gRPC dependencies not available: {e}"
        _set_last_error(err_msg)
        _log(err_msg)
        return False

    def any_value_from_json(value):
        if not isinstance(value, dict):
            return common_pb2.AnyValue(string_value=str(value))
        if "stringValue" in value:
            return common_pb2.AnyValue(string_value=str(value["stringValue"]))
        if "intValue" in value:
            try:
                return common_pb2.AnyValue(int_value=int(value["intValue"]))
            except (TypeError, ValueError):
                pass
        if "doubleValue" in value:
            try:
                return common_pb2.AnyValue(double_value=float(value["doubleValue"]))
            except (TypeError, ValueError):
                pass
        if "boolValue" in value:
            bool_val = value["boolValue"]
            if isinstance(bool_val, str):
                bool_val = bool_val.strip().lower() in ("true", "1", "yes")
            else:
                bool_val = bool(bool_val)
            return common_pb2.AnyValue(bool_value=bool_val)
        if "bytesValue" in value:
            raw = value["bytesValue"]
            try:
                data = base64.b64decode(raw)
            except Exception:
                data = str(raw).encode("utf-8", errors="ignore")
            return common_pb2.AnyValue(bytes_value=data)
        if "arrayValue" in value:
            serialized = json.dumps(value.get("arrayValue", {}).get("values", []))
            return common_pb2.AnyValue(string_value=serialized)
        if "kvlistValue" in value:
            serialized = json.dumps(value.get("kvlistValue", {}).get("values", []))
            return common_pb2.AnyValue(string_value=serialized)
        return common_pb2.AnyValue(string_value=json.dumps(value))

    # Build the protobuf request once (doesn't depend on the channel)
    resource_spans = []
    status_ok = 1
    try:
        status_ok = trace_pb2.Status.StatusCode.STATUS_CODE_OK
    except AttributeError:
        status_ok = getattr(trace_pb2.Status, "STATUS_CODE_OK", 1)
    status_error = 2
    try:
        status_error = trace_pb2.Status.StatusCode.STATUS_CODE_ERROR
    except AttributeError:
        status_error = getattr(trace_pb2.Status, "STATUS_CODE_ERROR", 2)

    for rs in span_json.get("resourceSpans", []):
        resource_attrs = [
            common_pb2.KeyValue(
                key="arize.project.name",
                value=common_pb2.AnyValue(string_value=project_name),
            ),
        ]
        for attr in rs.get("resource", {}).get("attributes", []):
            key = attr.get("key", "")
            value = attr.get("value", {})
            if not key:
                continue
            resource_attrs.append(
                common_pb2.KeyValue(key=key, value=any_value_from_json(value))
            )
        resource = resource_pb2.Resource(attributes=resource_attrs)

        scope_spans = []
        for ss in rs.get("scopeSpans", []):
            spans = []
            for s in ss.get("spans", []):
                trace_id = bytes.fromhex(s.get("traceId", "0" * 32))
                span_id = bytes.fromhex(s.get("spanId", "0" * 16))
                parent_span_id = (
                    bytes.fromhex(s["parentSpanId"])
                    if s.get("parentSpanId")
                    else b""
                )
                attrs = [
                    common_pb2.KeyValue(
                        key="arize.project.name",
                        value=common_pb2.AnyValue(string_value=project_name),
                    ),
                ]
                for attr in s.get("attributes", []):
                    key = attr.get("key", "")
                    value = attr.get("value", {})
                    if not key:
                        continue
                    attrs.append(
                        common_pb2.KeyValue(
                            key=key, value=any_value_from_json(value)
                        )
                    )
                kind_value = s.get("kind", 1)
                try:
                    kind_value = int(kind_value)
                except (TypeError, ValueError):
                    kind_value = 1

                # Preserve span status from payload instead of hardcoding OK
                span_status = s.get("status", {})
                span_status_code = span_status.get("code", status_ok)
                try:
                    span_status_code = int(span_status_code)
                except (TypeError, ValueError):
                    span_status_code = status_ok
                span_status_msg = span_status.get("message", "")
                status_kwargs = {"code": span_status_code}
                if span_status_msg:
                    status_kwargs["message"] = str(span_status_msg)

                span = trace_pb2.Span(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    name=s.get("name", "span"),
                    kind=kind_value,
                    start_time_unix_nano=int(s.get("startTimeUnixNano", 0)),
                    end_time_unix_nano=int(s.get("endTimeUnixNano", 0)),
                    attributes=attrs,
                    status=trace_pb2.Status(**status_kwargs),
                )
                spans.append(span)

            scope_info = ss.get("scope", {}) or {}
            scope_kwargs = {}
            scope_name = scope_info.get("name")
            scope_version = scope_info.get("version")
            if scope_name:
                scope_kwargs["name"] = scope_name
            if scope_version:
                scope_kwargs["version"] = scope_version
            scope_args = {"spans": spans}
            if scope_kwargs:
                scope_args["scope"] = common_pb2.InstrumentationScope(
                    **scope_kwargs
                )
            scope_spans.append(trace_pb2.ScopeSpans(**scope_args))

        resource_spans.append(
            trace_pb2.ResourceSpans(
                resource=resource, scope_spans=scope_spans
            )
        )

    request = trace_service_pb2.ExportTraceServiceRequest(
        resource_spans=resource_spans
    )
    metadata = [
        ("authorization", f"Bearer {api_key}"),
        ("space_id", space_id),
    ]

    # Retry loop with proper channel lifecycle
    credentials = grpc.ssl_channel_credentials()
    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        channel = grpc.secure_channel(endpoint, credentials)
        try:
            stub = trace_service_pb2_grpc.TraceServiceStub(channel)
            stub.Export(request, metadata=metadata, timeout=10)
            _set_last_error("")
            return True
        except Exception as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF[attempt])
        finally:
            channel.close()

    _set_last_error(last_err)
    _log(f"Arize export failed after {RETRY_ATTEMPTS} attempts: {last_err}")
    return False


def export_spans(span_json, config):
    """Route span payload to the configured backend."""
    backend = config.get("backend", {})
    target = backend.get("target", "")
    project_name = _resolve_project_name(span_json, config)

    if target == "phoenix":
        phoenix_cfg = dict(backend.get("phoenix", {}))
        phoenix_cfg["project_name"] = project_name
        return _export_to_phoenix(span_json, phoenix_cfg)
    elif target == "arize":
        arize_cfg = dict(backend.get("arize", {}))
        arize_cfg["project_name"] = project_name
        return _export_to_arize(span_json, arize_cfg)
    else:
        _set_last_error(f"Unknown backend target: {target}")
        return False


# --- Event buffer (Codex OTLP log ingestion) ---
# Codex emits native OTLP log events (codex.tool_decision, codex.sse_event, etc.)
# which need to be buffered by conversation/thread ID until the notify hook drains them
# to assemble child spans.

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
    global _logged_conv_debug
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

                if _logged_conv_debug < 20:
                    interesting = {
                        k: attrs.get(k)
                        for k in (
                            "thread_id",
                            "codex.thread_id",
                            "thread",
                            "codex.thread",
                            "threadId",
                            "codex.threadId",
                            "conversation.id",
                            "codex.conversation.id",
                            "conversation_id",
                            "codex.conversation_id",
                            "conversationId",
                            "codex.conversationId",
                        )
                        if k in attrs
                    }
                    _log(
                        "OTLP log identity debug: "
                        f"event={event_name} conv_id={conv_id} "
                        f"interesting={interesting} "
                        f"attr_keys={sorted(attrs.keys())[:40]}"
                    )
                    _logged_conv_debug += 1

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

                results.append((str(conv_id), {
                    "event": event_name,
                    "time_ns": time_ns_int,
                    "attrs": attrs,
                }))
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

class CollectorHandler(BaseHTTPRequestHandler):

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

        if path == "/v1/spans":
            self._handle_spans()
        elif path in ("/v1/logs", ""):
            self._handle_logs()
        else:
            self._send_json(404, {"status": "error", "message": "not found"})

    def _handle_spans(self):
        """Accept OTLP span JSON and export to backend."""
        raw = self._read_body()
        if raw is None:
            return

        try:
            span_json = json.loads(raw)
        except json.JSONDecodeError as e:
            self._send_json(400, {"status": "error", "message": f"malformed JSON: {e}"})
            return

        if "resourceSpans" not in span_json:
            self._send_json(400, {"status": "error", "message": "missing resourceSpans"})
            return

        self._send_json(202, {"status": "accepted"})

        t = threading.Thread(target=_background_export, args=(span_json,), daemon=True)
        with _inflight_lock:
            _inflight_exports[:] = [th for th in _inflight_exports if th.is_alive()]
            _inflight_exports.append(t)
        t.start()

    def _handle_logs(self):
        """Accept OTLP log events and buffer by conversation ID (Codex)."""
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
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/health":
            self._handle_health()
        elif path.startswith("/flush/"):
            conv_id = path[len("/flush/"):]
            if not conv_id:
                self._send_json(400, {"status": "error", "message": "missing conversation_id"})
                return
            events = _flush_events(conv_id)
            self._send_json(200, events)
        elif path.startswith("/drain/"):
            conv_id = path[len("/drain/"):]
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
        last_err = _get_last_error()
        backend_target = _config.get("backend", {}).get("target", "unknown")
        with _event_lock:
            buffered_events = sum(len(v) for v in _event_buffers.values())
            conversations = len(_event_buffers)
        health = {
            "status": "unhealthy" if last_err else "healthy",
            "backend": backend_target,
            "uptime_seconds": int(time.time() - _start_time),
            "event_buffer": {
                "buffered_events": buffered_events,
                "conversations": conversations,
            },
        }
        if last_err:
            health["error"] = last_err
        self._send_json(503 if last_err else 200, health)


def _background_export(span_json):
    """Export spans in a background thread."""
    try:
        export_spans(span_json, _config)
    except Exception as e:
        _set_last_error(e)
        _log(f"Background export error: {e}")


def _flush_inflight():
    """Wait for in-flight export threads to finish (best-effort, bounded)."""
    with _inflight_lock:
        threads = list(_inflight_exports)
    if not threads:
        return
    _log(f"Flushing {len(threads)} in-flight export(s) (timeout={SHUTDOWN_FLUSH_TIMEOUT}s)...")
    deadline = time.time() + SHUTDOWN_FLUSH_TIMEOUT
    for t in threads:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        t.join(timeout=remaining)
    still_alive = sum(1 for t in threads if t.is_alive())
    if still_alive:
        _log(f"Shutdown flush: {still_alive} export(s) did not finish in time")


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

    # Load config
    try:
        _config = load_config()
    except (FileNotFoundError, ValueError, yaml.YAMLError) as e:
        sys.stderr.write(f"[collector] Config error: {e}\n")
        sys.exit(1)

    host = _config.get("collector", {}).get("host", "127.0.0.1")
    port = _config.get("collector", {}).get("port", 4318)

    # Ensure log directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    _start_time = time.time()
    _write_pid()

    server = ThreadingHTTPServer((host, port), CollectorHandler)

    def _shutdown(signum, frame):
        global _shutting_down
        _shutting_down = True
        _log("Received shutdown signal, stopping...")
        # Stop accepting new requests
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    backend_target = _config.get("backend", {}).get("target", "unknown")
    _log(f"Listening on {host}:{port} (PID {os.getpid()}, backend={backend_target})")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _flush_inflight()
        server.server_close()
        _remove_pid()
        _log("Collector stopped")


if __name__ == "__main__":
    main()
