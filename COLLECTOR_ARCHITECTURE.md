# Shared Background Collector Architecture

Implementation-ready contract for the shared local collector/exporter that replaces per-request Python package dependencies. Installed by `install.sh`, runs in the background, and owns all backend export logic.

## Problem

Today, harness hooks build spans locally and export them in one of two ways:

- Phoenix: direct HTTP from shell, lightweight and reliable
- Arize AX: shell -> Python -> gRPC, which depends on user-local `grpcio` and `opentelemetry-proto`

That Arize path creates three problems:

1. Package availability depends on the user's Python environment
2. Each send pays process startup and import cost
3. Failures are fragmented across hooks and can be easy to miss

The goal is to make setup effectively invisible:

- install once
- start automatically
- run in the background
- no extra package install steps
- no harness-specific exporter logic in user environments

## Target Architecture

```text
Claude hooks ─┐
Codex hooks  ─┼─> POST http://127.0.0.1:4318/v1/spans ──> Phoenix
Future       ─┘         (shared collector)              └─> Arize AX
```

### Harness Responsibilities

Harness adapters keep only harness-specific work:

- session/thread resolution
- payload parsing
- span construction
- local submission to the collector via `POST http://127.0.0.1:4318/v1/spans`

Harness adapters should not:

- import exporter SDKs
- discover Python environments
- manage backend-specific transport logic

### Collector Responsibilities

The shared collector/exporter owns:

- local HTTP listener on `127.0.0.1:4318`
- routing received payloads to the configured backend (Phoenix or Arize AX)
- retry policy and backoff for backend sends
- batching policy (Phase 2+)
- authentication headers / credentials for backends
- health endpoint at `GET http://127.0.0.1:4318/health`
- structured logging to `~/.arize-agent-kit/logs/collector.log`

---

## Phase 1 Runtime Contract

Phase 1 keeps all existing harness span-building logic unchanged. The only change is where spans are sent: harnesses submit to `127.0.0.1:4318` instead of exporting directly.

### Shared File Layout

| Path | Purpose |
|------|---------|
| `~/.arize-agent-kit/config.json` | Shared config: backend target, credentials, collector settings |
| `~/.arize-agent-kit/bin/arize-collector` | Collector runtime script or binary |
| `~/.arize-agent-kit/run/collector.pid` | PID file for the running collector process |
| `~/.arize-agent-kit/logs/collector.log` | Collector log output |

Harness-specific state remains in harness-specific directories:

- `~/.arize-claude-code/` — Claude Code adapter session state
- `~/.arize-codex/` — Codex adapter session state

### Config File: `~/.arize-agent-kit/config.json`

The shared config file is the single source of truth for collector behavior. Required keys for Phase 1:

```json
{
  "collector": {
    "host": "127.0.0.1",
    "port": 4318
  },
  "backend": {
    "target": "phoenix",
    "phoenix": {
      "endpoint": "http://localhost:6006",
      "api_key": ""
    },
    "arize": {
      "endpoint": "otlp.arize.com:443",
      "api_key": "",
      "space_id": ""
    }
  }
}
```

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `collector.host` | string | No | `"127.0.0.1"` | Collector listen address |
| `collector.port` | integer | No | `4318` | Collector listen port |
| `backend.target` | string | Yes | — | `"phoenix"` or `"arize"` |
| `backend.phoenix.endpoint` | string | When target=phoenix | `"http://localhost:6006"` | Phoenix REST API base URL |
| `backend.phoenix.api_key` | string | No | `""` | Phoenix API key (if auth enabled) |
| `backend.arize.endpoint` | string | When target=arize | `"otlp.arize.com:443"` | Arize OTLP gRPC endpoint |
| `backend.arize.api_key` | string | When target=arize | — | Arize AX API key |
| `backend.arize.space_id` | string | When target=arize | — | Arize AX space ID |

The installer writes this file. Harnesses do not read it — only the collector reads it at startup.

### Local API Endpoints

All responses use `Content-Type: application/json`. Requests to undefined routes receive `404 Not Found` with body `{"status": "error", "message": "not found"}`.

#### `POST http://127.0.0.1:4318/v1/spans`

Accept OTLP JSON span payloads from any harness. This is the same JSON format that `build_span()` and `build_multi_span()` already produce.

**Request:**

- Method: `POST`
- Content-Type: `application/json`
- Body: OTLP JSON payload as produced by `build_span()` or `build_multi_span()` — a `resourceSpans` array containing resource, scope, and span objects.
- Max body size: 4 MB. Requests exceeding this limit receive `413 Payload Too Large`.

Example request body (single span, abbreviated):

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "claude-code" } }
        ]
      },
      "scopeSpans": [
        {
          "scope": { "name": "arize-claude-plugin" },
          "spans": [
            {
              "traceId": "abcdef0123456789abcdef0123456789",
              "spanId": "abcdef0123456789",
              "name": "tool_use",
              "kind": 1,
              "startTimeUnixNano": "1711900000000000000",
              "endTimeUnixNano": "1711900001000000000",
              "attributes": [],
              "status": {}
            }
          ]
        }
      ]
    }
  ]
}
```

**Response — success:**

- Status: `202 Accepted`
- Body: `{"status": "accepted"}`

The `202` status means the collector has received and queued the payload. It does not guarantee the backend accepted it.

**Response — error:**

| Status | Condition | Body |
|--------|-----------|------|
| `400 Bad Request` | Malformed JSON or missing `resourceSpans` | `{"status": "error", "message": "<description>"}` |
| `413 Payload Too Large` | Request body exceeds 4 MB | `{"status": "error", "message": "payload too large"}` |
| `503 Service Unavailable` | Collector is shutting down | `{"status": "error", "message": "shutting down"}` |

#### `GET http://127.0.0.1:4318/health`

Returns collector health and readiness.

**Response — healthy:**

- Status: `200 OK`
- Body:

```json
{
  "status": "healthy",
  "backend": "phoenix",
  "uptime_seconds": 3600
}
```

**Response — unhealthy:**

- Status: `503 Service Unavailable`
- Body:

```json
{
  "status": "unhealthy",
  "backend": "phoenix",
  "error": "<last backend error>"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"healthy"` or `"unhealthy"` |
| `backend` | string | Configured backend target: `"phoenix"` or `"arize"` |
| `uptime_seconds` | integer | Seconds since the collector started (present when healthy) |
| `error` | string | Last backend export error message (present when unhealthy) |

### Process Lifecycle

#### Start

1. Read `~/.arize-agent-kit/config.json`; exit non-zero with a logged error if the file is missing or unparseable
2. Bind to `127.0.0.1:<port>` (default `4318`)
3. Write PID to `~/.arize-agent-kit/run/collector.pid`
4. Begin accepting requests on `/v1/spans` and `/health`
5. Log startup to `~/.arize-agent-kit/logs/collector.log`

If the configured port is already in use, the collector must check whether the existing process is a running collector (via the PID file). If yes, exit cleanly — the collector is already running. If no, log an error and exit with a non-zero status.

#### Health Check

Any process can verify the collector is running:

```bash
curl -sf http://127.0.0.1:4318/health
```

Exit code 0 and a `200` response means the collector is healthy and ready to accept spans.

#### Stop

1. Send `SIGTERM` to the PID recorded in `~/.arize-agent-kit/run/collector.pid`
2. The collector stops accepting new requests
3. The collector attempts to flush any queued spans to the backend (best-effort, 5-second timeout)
4. The collector removes the PID file and exits

#### Restart

Restart is stop followed by start. There is no hot-reload of config in Phase 1 — config changes require a restart.

#### Crash Recovery

If the collector crashes:

- The PID file may be stale
- The start sequence detects stale PID files (process no longer running) and overwrites them
- Harness `send_span` calls that fail to connect to `127.0.0.1:4318` should log a warning and drop the span (same failure mode as a backend being unavailable today)

### Backend Export Behavior

#### Phoenix (target = `"phoenix"`)

The collector forwards spans to Phoenix using the same HTTP REST API that `send_to_phoenix` uses today:

- `POST <phoenix_endpoint>/v1/traces`
- Headers: `Content-Type: application/json`, plus `api_key: <key>` if configured
- Body: the OTLP JSON payload as received from the harness
- Retry: up to 3 attempts with 1s/2s/4s backoff on 5xx or connection errors

This is functionally identical to the current `send_to_phoenix` in `core/common.sh`, moved into the collector.

#### Arize AX (target = `"arize"`)

The collector forwards spans to Arize using OTLP gRPC:

- Endpoint: `backend.arize.endpoint` (default `otlp.arize.com:443`)
- Headers: `authorization: <api_key>`, `space_id: <space_id>`
- Payload: OTLP protobuf (converted from JSON internally)
- Retry: up to 3 attempts with 1s/2s/4s backoff on transient errors

This replaces the current `send_to_arize` / `core/send_arize.py` path. The gRPC dependencies (`grpcio`, `opentelemetry-proto`) are bundled with or embedded in the collector runtime — they are not required in the user's Python environment.

### What Stays Unchanged in Phase 1

| Component | Status | Notes |
|-----------|--------|-------|
| Harness span-building logic (`build_span`, `build_multi_span`) | **Unchanged** | Harnesses still construct OTLP JSON |
| Harness session/state management | **Unchanged** | Per-harness state dirs remain |
| Harness hook scripts | **Unchanged** (except send target) | Only the destination of `send_span` changes |
| `core/common.sh` span-building functions | **Unchanged** | Still used by all harnesses |
| Harness-specific environment variables | **Unchanged** | `ARIZE_SERVICE_NAME`, `STATE_DIR`, etc. |

### What Moves Into the Collector in Phase 1

| Component | Current Location | New Location |
|-----------|-----------------|--------------|
| Phoenix HTTP export | `send_to_phoenix` in `core/common.sh` | Collector |
| Arize gRPC export | `send_to_arize` in `core/common.sh` + `core/send_arize.py` | Collector |
| Backend target detection | `get_target` in `core/common.sh` | Collector reads `config.json` |
| Backend credentials | Per-harness env vars | `~/.arize-agent-kit/config.json` |

After Phase 1, `send_span` in `core/common.sh` becomes a `curl POST` to `http://127.0.0.1:4318/v1/spans` instead of calling `send_to_phoenix` or `send_to_arize` directly.

---

## Runtime Model

The collector should be installed automatically by `install.sh` and run in the background without user action.

Preferred runtime model:

- ship a self-contained binary per platform

Acceptable fallback:

- ship a controlled embedded runtime

Not recommended:

- depend on arbitrary user Python environments

The design only delivers the intended UX if the runtime is owned by the project.

## Install Flow

Desired install experience:

1. User runs `install.sh`
2. Installer asks only for backend-specific credentials or endpoint
3. Installer writes `~/.arize-agent-kit/config.json`
4. Installer installs the collector runtime to `~/.arize-agent-kit/bin/arize-collector`
5. Installer configures harness-specific local hooks/wrappers
6. Installer starts the collector automatically
7. Harnesses submit to `http://127.0.0.1:4318/v1/spans` with no further setup

## Future Phases

### Phase 2: Normalize install/runtime around one service

- Shared installer/service management
- Remove Arize Python dependency checks from hooks
- Remove `core/send_arize.py` and direct `send_to_arize` path

### Phase 3: Optional deeper collector responsibilities

- Batching
- Disk-backed retry queue
- Offline buffering
- Collector-side child-span assembly where useful

## Risks

### Packaging

If the collector still depends on user-managed Python, the main UX problem remains.

### Process management

Background daemons need clear lifecycle handling — the start/health/stop/restart contract above addresses this.

### Backward compatibility

Existing Codex behavior includes collector-specific event draining. That should be preserved during migration, then simplified later.

## Resolved Questions (Phase 1)

| Question | Decision |
|----------|----------|
| What payload format does the collector accept? | OTLP JSON as produced by `build_span()` / `build_multi_span()` — the same format harnesses already produce |
| Should both Phoenix and Arize go through the collector? | Yes, both backends are served by the collector in Phase 1 |
| What does the collector listen on? | `127.0.0.1:4318` (localhost only, no network exposure) |
| Should failure to start the collector block install? | No — install completes with a warning; harness spans are dropped until the collector starts |
| Should the collector accept raw harness events? | No — Phase 1 accepts only fully-built OTLP JSON spans |
| What is the max request body size? | 4 MB — sufficient for any realistic batch of spans |
| What is the graceful shutdown timeout? | 5 seconds — long enough to flush a small queue, short enough to not hang |
| How does the collector handle unknown routes? | `404 Not Found` with `{"status": "error", "message": "not found"}` |
