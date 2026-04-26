# Tracing Architecture

Spans are sent directly from harness hooks to the configured backend (Phoenix REST or Arize AX gRPC) via `send_span()` in `core/common.py`. No shared background process is required for span export. Codex additionally uses a lightweight buffer service to hold native OTLP log events between hook invocations.

## Overview

```text
Claude hooks ──┐
Cursor hooks ──┤
Codex hooks  ──┴── send_span() ──► Phoenix (REST)
                        │              └──► Arize AX (gRPC)
                        │
                        └── harnesses.<service_name>.* in ~/.arize/harness/config.yaml
                              No fallback — if the entry is missing or incomplete,
                              the resolver logs an error and spans are dropped.

Codex OTLP ────── POST /v1/logs ──► Codex Buffer Service (event buffer)
                                       │
Codex notify ──── GET /drain/{id} ◄────┘
```

Harness hooks build OTLP JSON span payloads using `core.common.build_span()` and send them directly to the backend via `core.common.send_span()`. Each harness owns its full backend configuration directly under `harnesses.<name>` in `config.yaml`.

## Source Files

| File | Purpose |
|------|---------|
| `core/common.py` | Direct send (`send_span()`), per-harness credential resolution, span building |
| `codex_tracing/codex_buffer.py` | Codex-only HTTP buffer service for OTLP log events |
| `codex_tracing/codex_buffer_ctl.py` | Codex buffer lifecycle management: start, stop, status, ensure |

## Configuration

All settings live in `~/.arize/harness/config.yaml`:

```yaml
harnesses:
  claude-code:
    project_name: claude-code
    target: arize
    endpoint: otlp.arize.com:443
    api_key: ak-xxx
    space_id: U3Bh...
  codex:
    project_name: codex
    target: phoenix
    endpoint: http://localhost:6006
    api_key: ""
    collector:                    # codex only
      host: 127.0.0.1
      port: 4318
  copilot:
    project_name: copilot
    target: arize
    endpoint: otlp.arize.com:443
    api_key: ak-xxx
    space_id: U3Bh...
  cursor:
    project_name: cursor
    target: phoenix
    endpoint: http://localhost:6006
    api_key: ""
user_id: optional-global-user-id
```

Each harness owns its full backend configuration directly — `target`, `endpoint`, `api_key`, and (for Arize) `space_id`. There is no shared global backend block. This allows different harnesses to use different backends or credentials.

## Credential Resolution

`resolve_backend()` in `core/common.py` resolves backend config for each span from `harnesses.<service_name>.*` in `~/.arize/harness/config.yaml`. No fallback — if the entry is missing or incomplete, the resolver logs an error pointing the user at `install.sh <harness>` and spans are dropped.

## Codex Buffer Service

The buffer service (`codex_tracing/codex_buffer.py`) is a minimal HTTP server used only by Codex. It buffers native OTLP log events by thread ID so the notify handler can drain and assemble child spans.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/logs` | POST | Accept and buffer OTLP log events by thread ID |
| `/health` | GET | Health check with buffer stats |
| `/drain/{thread_id}` | GET | Return buffered events (supports `since_ns`, `wait_ms`, `quiet_ms` params) |
| `/flush/{thread_id}` | GET | Return and remove all buffered events for a thread |

### Lifecycle Management

The `arize-codex-buffer` CLI (or `codex_tracing.codex_buffer_ctl` module) manages the buffer process:

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
