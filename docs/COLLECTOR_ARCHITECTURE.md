# Collector Architecture

The shared background collector is a lightweight HTTP server that receives OpenInference spans from all harness hooks and exports them to Phoenix or Arize AX. It runs as a single process shared by Claude Code, Codex, and Cursor integrations.

## Overview

```text
Claude hooks ──┐
Codex hooks  ──┼── POST /v1/spans ──► Collector ──► Phoenix (REST)
Cursor hooks ──┘         │                    └──► Arize AX (gRPC)
                         │
Codex OTLP ────── POST /v1/logs ──► Event buffer
                                       │
Codex notify ──── GET /drain/{id} ◄────┘
```

Harness hooks build OTLP JSON span payloads using `core.common.build_span()` and submit them to the collector via `core.common.send_span()`. The collector handles backend-specific transport, credentials, retries, and logging. Hooks never talk directly to Phoenix or Arize AX.

## Source Files

| File | Purpose |
|------|---------|
| `core/collector.py` | HTTP server, backend export (Phoenix REST, Arize AX gRPC), event buffering |
| `core/collector_ctl.py` | Lifecycle management: start, stop, status, ensure |

## Configuration

All settings live in `~/.arize/harness/config.yaml`:

```yaml
collector:
  host: "127.0.0.1"    # Listen address (default: 127.0.0.1)
  port: 4318            # Listen port (default: 4318)

backend:
  target: "phoenix"     # "phoenix" or "arize"
  phoenix:
    endpoint: "http://localhost:6006"
    api_key: ""          # Optional, if Phoenix auth is enabled
  arize:
    api_key: "<key>"     # Required for Arize AX
    space_id: "<id>"     # Required for Arize AX
    endpoint: "otlp.arize.com:443"  # Default; override for on-prem

harnesses:
  claude-code:
    project_name: "claude-code"
  codex:
    project_name: "codex"
  cursor:
    project_name: "cursor"
```

Per-harness `project_name` values are resolved by the collector from the span's `service.name` resource attribute, falling back to `ARIZE_PROJECT_NAME` env var, then `"default"`.

## API Endpoints

### `POST /v1/spans` — Span ingestion

Accepts an OTLP JSON payload with a `resourceSpans` array. Returns `202 Accepted` immediately and exports to the configured backend in a background thread with up to 3 retries.

**Request:** OTLP JSON (`Content-Type: application/json`, max 4 MB)
**Response:** `{"status": "accepted"}`

### `POST /v1/logs` — OTLP log ingestion (Codex)

Accepts OTLP log events (JSON or protobuf) and buffers them by conversation/thread ID. Used by Codex's native OTLP export for tool decision and API request events.

**Response:** `{"status": "accepted", "buffered": <count>}`

### `GET /health` — Health check

Returns collector status, backend target, uptime, event buffer stats, and the last backend error (if any).

**Response (healthy):** `{"status": "healthy", "backend": "phoenix", "uptime_seconds": 3600, ...}`
**Response (unhealthy):** `{"status": "unhealthy", "error": "...", ...}` with HTTP 503

### `GET /drain/{thread_id}` — Drain buffered events

Returns buffered OTLP log events for a Codex thread ID. Supports query parameters for polling:

| Parameter | Description |
|-----------|-------------|
| `since_ns` | Only return events newer than this timestamp (nanoseconds) |
| `wait_ms` | Maximum time to wait for events before returning |
| `quiet_ms` | Return once no new events arrive for this duration |

### `GET /flush/{thread_id}` — Flush buffered events

Returns and removes all buffered events for a thread ID. Unlike `/drain`, this is destructive.

## Lifecycle Management

The `arize-collector-ctl` CLI (or `core.collector_ctl` module) manages the collector process:

```bash
arize-collector-ctl start    # Start if not running
arize-collector-ctl stop     # Send SIGTERM, wait up to 5s, clean up PID file
arize-collector-ctl status   # Print "running (PID N, host:port)" or "stopped"
```

Hooks call `collector_ensure()` which silently starts the collector if it's not already running. This is idempotent and never raises.

## File Locations

| Path | Purpose |
|------|---------|
| `~/.arize/harness/config.yaml` | Collector and backend configuration |
| `~/.arize/harness/run/collector.pid` | PID file for the running collector |
| `~/.arize/harness/logs/collector.log` | Collector log (timestamped, append-only) |

## Backend Export

**Phoenix:** Transforms OTLP spans into Phoenix's `/v1/projects/<name>/spans` format and POSTs via `urllib`. Supports optional Bearer token auth.

**Arize AX:** Converts OTLP JSON to protobuf and sends via gRPC with `authorization` and `space_id` metadata. Requires `grpcio` and `opentelemetry-proto` (bundled with the collector, not required in the user environment).

Both paths retry up to 3 times with exponential backoff (1s, 2s, 4s). Failed exports are logged and surfaced via the `/health` endpoint.

## Shutdown

On SIGTERM or SIGINT, the collector:

1. Stops accepting new requests
2. Waits up to 5 seconds for in-flight exports to complete
3. Closes the server socket
4. Removes the PID file
