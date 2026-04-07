# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the **OpenAI Codex CLI**. Each agent turn is captured as an LLM span with tool calls, token usage, and API request details, then sent to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Architecture

This integration uses the shared collector at `127.0.0.1:4318` for both span export and Codex event buffering:

```
Codex CLI
  │
  ├─ notify hook ──► notify handler ──► OpenInference LLM spans (per turn)
  │                     │
  │                     ├─ Drains buffered events from collector (GET /drain/{id})
  │                     └─ Sends built spans to collector (POST /v1/spans)
  │                              └─► Phoenix (REST) or Arize AX (gRPC)
  │
  └─ OTLP export ──► collector (POST /v1/logs)
                      └─ Buffers native Codex events by thread-id
```

1. **Shared collector** (`core/collector.py`, port 4318) -- background process shared by all harnesses. Accepts span exports (`POST /v1/spans`), buffers Codex OTLP log events (`POST /v1/logs`), and serves buffered events (`GET /drain/{id}`, `GET /flush/{id}`). Exports to Phoenix or Arize AX. Managed via `core/collector_ctl.py` (`arize-collector-ctl`).

2. **`notify handler`** (`handlers.py`) -- Codex calls this after every agent turn. It builds an OpenInference LLM span from the turn payload, drains buffered events from the collector, assembles child spans (TOOL, CHAIN), and submits the complete span tree back to the collector for export.

When both the notify hook and native OTLP export are enabled, the notify handler builds a parent LLM span and attaches child spans from buffered event data, producing a rich trace tree per turn.

## Installation

### Curl installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.py | python3
```

The installer detects Codex and guides you through configuration.

### Dedicated installer

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit/codex-tracing
python3 install.py
```

The installer supports interactive and non-interactive modes:

```bash
# Interactive
python3 install.py

# Non-interactive: Phoenix
python3 install.py --target phoenix

# Non-interactive: Arize AX with native OTLP
python3 install.py --target arize --otlp

# Uninstall
python3 install.py uninstall
```

### Manual setup

1. Set the notify hook in `~/.codex/config.toml`:

```toml
notify = ["arize-hook-codex-notify"]
```

2. Create the shared collector config at `~/.arize/harness/config.yaml` with your backend and harness settings (see [Configuration](#configuration) below and [COLLECTOR_ARCHITECTURE.md](../COLLECTOR_ARCHITECTURE.md) for the full schema).

3. Optionally create `~/.codex/arize-env.sh` for env-var overrides (see [Environment Variables](#environment-variables)).

## Configuration

The single source of truth is `~/.arize/harness/config.yaml`. The notify hook and collector both read from this file. Environment variables in `~/.codex/arize-env.sh` are still supported as overrides but are no longer the primary configuration mechanism.

**Phoenix** (self-hosted):

```yaml
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "phoenix"
  phoenix:
    endpoint: "http://localhost:6006"
    api_key: ""
harnesses:
  codex:
    project_name: "codex"
```

**Arize AX** (cloud):

```yaml
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "arize"
  arize:
    api_key: "<your-api-key>"
    space_id: "<your-space-id>"
harnesses:
  codex:
    project_name: "codex"
```

Env-var overrides (optional) can still be placed in `~/.codex/arize-env.sh`, which the notify hook sources automatically.

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

When Codex OTLP export is enabled, the notify handler drains buffered events for the current thread-id from the shared collector and builds child spans.  These are merged with the parent span into a single OTLP `resourceSpans` payload via `build_multi_span()`, producing a hierarchical trace tree.

## Environment Variables

These env vars are **optional overrides**. Prefer setting values in `~/.arize/harness/config.yaml` (see [Configuration](#configuration)). If set, env vars take precedence over the config file.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_API_KEY` | No | config.yaml | Arize AX API key (override) |
| `ARIZE_SPACE_ID` | No | config.yaml | Arize AX space ID (override) |
| `ARIZE_OTLP_ENDPOINT` | No | `otlp.arize.com:443` | OTLP gRPC endpoint (on-prem Arize) |
| `PHOENIX_ENDPOINT` | No | config.yaml | Phoenix collector URL (override) |
| `PHOENIX_API_KEY` | No | config.yaml | Phoenix API key (override) |
| `ARIZE_PROJECT_NAME` | No | config.yaml | Project name (override; defaults to harness `project_name`) |
| `ARIZE_USER_ID` | No | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_TRACE_DEBUG` | No | `false` | Write debug dumps to `~/.arize/harness/state/codex/debug/` |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-codex.log` | Log file path (empty to disable) |
| `ARIZE_COLLECTOR_PORT` | No | `4318` | Port for the shared collector |

### User Identification

Set `ARIZE_USER_ID` to tag all spans with a `user.id` attribute:

```bash
export ARIZE_USER_ID="alice@example.com"
```

Add this to `~/.codex/arize-env.sh` so it persists across sessions (this is one of the few settings that remains env-var only).

## Process Management

### Shared Collector (port 4318)

The shared collector exports spans to the configured backend (Phoenix or Arize AX).  It is managed via `core/collector_ctl.py` (`arize-collector-ctl`):

```bash
arize-collector-ctl start    # Start the shared collector
arize-collector-ctl stop     # Stop it
arize-collector-ctl status   # Check if running (exit code 0/1)
arize-collector-ctl ensure   # Start if not already running
```

Config: `~/.arize/harness/config.yaml`.  PID: `~/.arize/harness/run/collector.pid`.  Log: `~/.arize/harness/logs/collector.log`.

The shared collector also buffers Codex's native OTLP log events (`POST /v1/logs`) by thread ID for child-span assembly. No separate event buffer process is needed.

## Directory Structure

```
codex-tracing/
  skills/                      Codex setup skill
```

Shared logic lives in `core/` at the repository root:

```
core/
  hooks/codex/adapter.py     Adapter: thread-id state, debug dump, multi-span
  hooks/codex/handlers.py    Notify hook handler
  hooks/codex/proxy.py       Proxy wrapper (ensures collector is running)
  common.py                  Env vars, logging, state, span building, sending
  collector.py               Shared collector: span export + event buffering
  collector_ctl.py           Collector lifecycle management
  send_arize.py              Arize AX gRPC sender (legacy fallback)
```

## Troubleshooting

**Spans not appearing in Phoenix**

1. Verify Phoenix is running: `curl -s http://localhost:6006/healthz`
2. Check the shared collector: `curl -s http://127.0.0.1:4318/health`
3. Check config: `cat ~/.arize/harness/config.yaml` (and `~/.codex/arize-env.sh` if using env-var overrides)
4. Check the shared collector log: `tail -20 ~/.arize/harness/logs/collector.log`
5. Check the harness log: `tail -20 /tmp/arize-codex.log`
6. Test with dry run: `ARIZE_DRY_RUN=true codex`

**Spans not appearing in Arize AX**

1. Verify `ARIZE_API_KEY` and `ARIZE_SPACE_ID` in `~/.arize/harness/config.yaml`
2. Check the shared collector: `curl -s http://127.0.0.1:4318/health`
3. Check the shared collector log for gRPC errors: `grep ERROR ~/.arize/harness/logs/collector.log`

**Shared collector not starting**

1. Check config exists: `cat ~/.arize/harness/config.yaml`
2. Check if port 4318 is in use: `lsof -i :4318`
3. Check PID file: `cat ~/.arize/harness/run/collector.pid`
4. Check log: `tail -20 ~/.arize/harness/logs/collector.log`

**Missing child spans (tool calls, API requests)**

1. Ensure native OTLP export is enabled in Codex config (`[otel]` section pointing to `127.0.0.1:4318`)
2. Verify the collector is running: `curl -s http://127.0.0.1:4318/health` (check `event_buffer` in response)
3. Enable debug dumps: `export ARIZE_TRACE_DEBUG=true` and check `~/.arize/harness/state/codex/debug/`

**Session state issues**

State files are stored in `~/.arize/harness/state/codex/`. To reset:

```bash
rm -rf ~/.arize/harness/state/codex/state_*.json
```

Stale state files older than 24 hours are garbage-collected automatically.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Collector Architecture](../COLLECTOR_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
