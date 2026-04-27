# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the **OpenAI Codex CLI**. Each agent turn is captured as an LLM span with tool calls, token usage, and API request details, then sent to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Architecture

This integration sends spans directly to the backend via `send_span()` and uses the Codex Buffer Service for native OTLP event buffering:

```
Codex CLI
  │
  ├─ notify hook ──► arize-hook-codex-notify ──► OpenInference LLM spans (per turn)
  │                          │
  │                          ├─ Drains buffered events from buffer service (GET /drain/{id})
  │                          └─ Sends built spans directly to backend via send_span()
  │                                   └─► Phoenix (REST) or Arize AX (HTTP)
  │
  └─ OTLP export ──► Codex Buffer Service (POST /v1/logs)
                      └─ Buffers native Codex events by thread-id
```

1. **Direct send** (`core/common.py`) -- spans are sent directly to Phoenix or Arize AX from the notify handler via `send_span()`. Per-harness backend credentials are read from `harnesses.codex.*` in config.

2. **Codex Buffer Service** (`codex_tracing/codex_buffer.py`, default port 4318) -- a lightweight HTTP server that only buffers Codex OTLP log events between hook invocations. No export logic. Accepts events (`POST /v1/logs`) and serves buffered events (`GET /drain/{id}`, `GET /flush/{id}`). Managed via `arize-codex-buffer`.

3. **`arize-hook-codex-notify`** -- Codex calls this after every agent turn. It builds an OpenInference LLM span from the turn payload, drains buffered events from the buffer service, assembles child spans (TOOL, CHAIN), and sends the complete span tree directly to the backend.

When both the notify hook and native OTLP export are enabled, the notify handler builds a parent LLM span and attaches child spans from buffered event data, producing a rich trace tree per turn.

## Codex Exec Tracing

Interactive Codex tracing uses `notify` and `[otel.exporter.otlp-http]` in
`~/.codex/config.toml`. The notify hook fires after each agent turn, drains
buffered OTLP events, and sends spans directly to the backend.

`codex exec` tracing requires the `arize-codex-proxy` entry point because the
proxy runs the real Codex binary and then drains buffered events after the
process exits. Without the proxy, `codex exec` bypasses the notify hook and
buffered events are never flushed.

The installer creates a `~/.arize/harness/bin/codex` shim that points to
`arize-codex-proxy`. Users must ensure `~/.arize/harness/bin` appears before the
real Codex binary on `PATH`; otherwise the installer prints a shadowing warning
and `codex exec` tracing is not active.

### Verifying exec tracing

Run:

```bash
command -v codex
```

The output should resolve to `~/.arize/harness/bin/codex` for exec tracing to be
active. If it resolves to a different path, `codex exec` invocations will not be
traced.

## Installation

### Pip installer (recommended)

```bash
pip install arize-agent-kit
python -m core.install codex
```

The installer detects Codex and guides you through configuration. If another harness is already installed using the same target, the installer offers to reuse its credentials.

### Dedicated installer

```bash
pip install arize-agent-kit
arize-setup-codex
```

### Manual setup

1. Set the notify hook in `~/.codex/config.toml`:

```toml
notify = ["~/.arize/harness/venv/bin/arize-hook-codex-notify"]
```

2. Create the config at `~/.arize/harness/config.yaml` with your backend and harness settings (see [Configuration](#configuration) below and [TRACING_ARCHITECTURE.md](../docs/TRACING_ARCHITECTURE.md) for the full schema).

3. Optionally create `~/.codex/arize-env.sh` for env-var overrides (see [Environment Variables](#environment-variables)).

## Configuration

The single source of truth is `~/.arize/harness/config.yaml`. The notify hook and buffer service both read from this file. Environment variables in `~/.codex/arize-env.sh` are still supported as overrides but are no longer the primary configuration mechanism.

**Phoenix** (self-hosted):

```yaml
harnesses:
  codex:
    project_name: codex
    target: phoenix
    endpoint: http://localhost:6006
    api_key: ""
    collector:
      host: 127.0.0.1
      port: 4318
```

**Arize AX** (cloud):

```yaml
harnesses:
  codex:
    project_name: codex
    target: arize
    endpoint: otlp.arize.com:443
    api_key: <your-api-key>
    space_id: <your-space-id>
    collector:
      host: 127.0.0.1
      port: 4318
```

Each harness owns its full backend configuration directly under `harnesses.<name>`. See [TRACING_ARCHITECTURE.md](../docs/TRACING_ARCHITECTURE.md) for the full schema.

Env-var overrides (optional) can still be placed in `~/.codex/arize-env.sh`.

## How It Works

### Span Types

Each Codex agent turn produces a **parent LLM span** with optional child spans:

| Span | Kind | Source | Description |
|------|------|--------|-------------|
| Turn N | LLM | notify payload | Parent span with input/output, token counts, model name |
| Tool call | TOOL | event buffer events | One per `codex.tool_decision` + `codex.tool_result` pair |
| API Request | CHAIN | event buffer events | One per `codex.api_request` or `codex.websocket_request` |

### Parent Span Attributes

The parent LLM span includes:

- `session.id`, `trace.number`, `project.name` -- session tracking
- `input.value`, `output.value` -- user prompt and assistant response
- `llm.output_messages` -- structured assistant output
- `llm.model_name` -- model extracted from event buffer events
- `llm.token_count.prompt`, `llm.token_count.completion`, `llm.token_count.total` -- token usage
- `codex.thread_id`, `codex.turn_id` -- Codex identifiers
- `codex.sandbox_mode`, `codex.approval_mode` -- session settings
- `user.id` -- user identifier (when `ARIZE_USER_ID` is set)

### Multi-Span Assembly

When Codex OTLP export is enabled, the notify handler drains buffered events for the current thread-id from the buffer service and builds child spans. These are merged with the parent span into a single OTLP `resourceSpans` payload, producing a hierarchical trace tree.

## Environment Variables

These env vars are **optional overrides**. Prefer setting values in `~/.arize/harness/config.yaml` (see [Configuration](#configuration)). If set, env vars take precedence over the config file.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_API_KEY` | No | config.yaml | Arize AX API key (override) |
| `ARIZE_SPACE_ID` | No | config.yaml | Arize AX space ID (override) |
| `ARIZE_OTLP_ENDPOINT` | No | `otlp.arize.com:443` | OTLP endpoint (on-prem Arize) |
| `PHOENIX_ENDPOINT` | No | config.yaml | Phoenix collector URL (override) |
| `PHOENIX_API_KEY` | No | config.yaml | Phoenix API key (override) |
| `ARIZE_PROJECT_NAME` | No | config.yaml | Project name (override; defaults to harness `project_name`) |
| `ARIZE_USER_ID` | No | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_TRACE_DEBUG` | No | `false` | Write debug dumps to `~/.arize/harness/state/codex/debug/` |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-codex.log` | Log file path (empty to disable) |
| `ARIZE_CODEX_BUFFER_PORT` | No | `4318` | Port for the Codex buffer service |

### User Identification

Set `ARIZE_USER_ID` to tag all spans with a `user.id` attribute:

```bash
export ARIZE_USER_ID="alice@example.com"
```

Add this to `~/.codex/arize-env.sh` so it persists across sessions (this is one of the few settings that remains env-var only).

## Process Management

### Codex Buffer Service (port 4318)

The buffer service buffers native Codex OTLP log events between hook invocations. It is managed via the `arize-codex-buffer` CLI:

```bash
arize-codex-buffer start    # Start the buffer service
arize-codex-buffer stop     # Stop it
arize-codex-buffer status   # Check if running (exit code 0/1)
arize-codex-buffer ensure   # Start if not already running
```

Config: `~/.arize/harness/config.yaml`.  PID: `~/.arize/harness/run/codex-buffer.pid`.  Log: `~/.arize/harness/logs/codex-buffer.log`.

Span export is handled directly by the notify hook via `send_span()` — the buffer service only buffers events, it does not export spans.

## Directory Structure

```
codex-tracing/
  skills/                      Codex setup skill
  README.md
```

Setup is provided by the `arize-setup-codex` CLI entry point (defined in `core/setup/codex.py`).

Hook logic lives in `core/` at the repository root (installed as a Python package):

```
core/
  hooks/codex/
    adapter.py       Codex-specific session resolution, GC, event drain
    handlers.py      Notify handler entry point
    proxy.py         Codex proxy script
  common.py          Shared: span building, direct send, state, logging, IDs
  codex_buffer.py    Codex buffer service: OTLP event buffering only
  codex_buffer_ctl.py Buffer service lifecycle management
  config.py          YAML config helper
  constants.py       Single source of truth for all paths
```

## Troubleshooting

**Spans not appearing in Phoenix**

1. Verify Phoenix is running: `curl -s http://localhost:6006/healthz`
2. Check config: `cat ~/.arize/harness/config.yaml` (and `~/.codex/arize-env.sh` if using env-var overrides)
3. Check the harness log: `tail -20 /tmp/arize-codex.log`
4. Test with dry run: `ARIZE_DRY_RUN=true codex`

**Spans not appearing in Arize AX**

1. Verify `api_key` and `space_id` under `harnesses.codex` in `~/.arize/harness/config.yaml`
2. Check the harness log for errors: `grep ERROR /tmp/arize-codex.log`

**Buffer service not starting**

1. Check config exists: `cat ~/.arize/harness/config.yaml`
2. Check if port 4318 is in use: `arize-codex-buffer status`
3. Check PID file: `cat ~/.arize/harness/run/codex-buffer.pid`
4. Check log: `tail -20 ~/.arize/harness/logs/codex-buffer.log`

**Missing child spans (tool calls, API requests)**

1. Ensure native OTLP export is enabled in Codex config (`[otel]` section pointing to `127.0.0.1:4318`)
2. Verify the buffer service is running: `arize-codex-buffer status`
3. Enable debug dumps: `export ARIZE_TRACE_DEBUG=true` and check `~/.arize/harness/state/codex/debug/`

**Session state issues**

State files are stored in `~/.arize/harness/state/codex/`. To reset:

```bash
rm -rf ~/.arize/harness/state/codex/state_*.yaml
```

Stale state files older than 24 hours are garbage-collected automatically.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Tracing Architecture](../docs/TRACING_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
