# Tracing Architecture

Spans are sent directly from harness hooks to the configured backend (Phoenix REST or Arize AX gRPC) via `send_span()` in `core/common.py`. No shared background process is required for span export. Codex additionally uses a lightweight buffer service to hold native OTLP log events between hook invocations.

## Overview

```text
Claude hooks ──┐
Cursor hooks ──┤
Codex hooks  ──┴── send_span() ──► Phoenix (REST)
                        │              └──► Arize AX (gRPC)
                        │
                        └── per-harness credential resolution
                              (harnesses.<name>.backend → global backend → env vars)

Codex OTLP ────── POST /v1/logs ──► Codex Buffer Service (event buffer)
                                       │
Codex notify ──── GET /drain/{id} ◄────┘
```

Harness hooks build OTLP JSON span payloads using `core.common.build_span()` and send them directly to the backend via `core.common.send_span()`. Each harness can optionally override backend credentials under its own `harnesses.<name>.backend` block in `config.yaml`. If not set, the global `backend` section is used.

## Source Files

| File | Purpose |
|------|---------|
| `core/common.py` | Direct send (`send_span()`), per-harness credential resolution, span building |
| `core/codex_buffer.py` | Codex-only HTTP buffer service for OTLP log events |
| `core/codex_buffer_ctl.py` | Codex buffer lifecycle management: start, stop, status, ensure |

## Configuration

All settings live in `~/.arize/harness/config.yaml`:

```yaml
backend:                          # global defaults
  target: "phoenix"               # "phoenix" or "arize"
  phoenix:
    endpoint: "http://localhost:6006"
    api_key: ""                   # Optional, if Phoenix auth is enabled
  arize:
    api_key: "<key>"              # Required for Arize AX
    space_id: "<id>"              # Required for Arize AX
    endpoint: "otlp.arize.com:443"  # Default; override for on-prem

harnesses:
  claude-code:
    project_name: "my-claude-project"
    backend:                      # optional per-harness override
      target: "arize"
      arize:
        api_key: "different-key"
        space_id: "different-space"
        endpoint: "otlp.arize.com:443"
  codex:
    project_name: "codex"
    buffer:
      host: "127.0.0.1"          # Codex buffer listen address (default: 127.0.0.1)
      port: 4318                  # Codex buffer listen port (default: 4318)
  cursor:
    project_name: "cursor"
```

Per-harness `project_name` values are resolved from config, falling back to `ARIZE_PROJECT_NAME` env var, then the harness default name.

Per-harness `backend` blocks are optional. When present, they override the global `backend` section for that harness only. This allows different harnesses to send to different backends or use different credentials.

## Credential Resolution

`resolve_backend()` in `core/common.py` resolves backend config for each span:

1. `harnesses.<service_name>.backend.*` in config (per-harness override)
2. `backend.*` in config (global)
3. Environment variables (`ARIZE_API_KEY`, `PHOENIX_ENDPOINT`, etc.)

## Codex Buffer Service

The buffer service (`core/codex_buffer.py`) is a minimal HTTP server used only by Codex. It buffers native OTLP log events by thread ID so the notify handler can drain and assemble child spans.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/logs` | POST | Accept and buffer OTLP log events by thread ID |
| `/health` | GET | Health check with buffer stats |
| `/drain/{thread_id}` | GET | Return buffered events (supports `since_ns`, `wait_ms`, `quiet_ms` params) |
| `/flush/{thread_id}` | GET | Return and remove all buffered events for a thread |

### Lifecycle Management

The `arize-codex-buffer` CLI (or `core.codex_buffer_ctl` module) manages the buffer process:

```bash
arize-codex-buffer start    # Start if not running
arize-codex-buffer stop     # Send SIGTERM, wait up to 5s, clean up PID file
arize-codex-buffer status   # Print "running (PID N, host:port)" or "stopped"
```

Codex hooks call `buffer_ensure()` which silently starts the buffer if it's not already running. This is idempotent and never raises.

## File Locations

| Path | Purpose |
|------|---------|
| `~/.arize/harness/config.yaml` | Backend and harness configuration |
| `~/.arize/harness/run/codex-buffer.pid` | PID file for the running buffer service |
| `~/.arize/harness/logs/codex-buffer.log` | Buffer service log (timestamped, append-only) |

## Backend Export

**Phoenix:** POSTs OTLP JSON to `/v1/projects/<name>/spans` via `urllib`. Supports optional Bearer token auth.

**Arize AX:** POSTs OTLP JSON to `https://otlp.arize.com/v1/traces` via `urllib` with `authorization` and `space_id` headers. Injects `arize.project.name` into span attributes before sending. No gRPC or protobuf dependencies required.

## Shutdown (Codex Buffer)

On SIGTERM or SIGINT, the buffer service:

1. Stops accepting new requests
2. Waits up to 5 seconds for in-flight operations
3. Closes the server socket
4. Removes the PID file
