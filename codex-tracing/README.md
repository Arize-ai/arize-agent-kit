# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the **OpenAI Codex CLI**. Each agent turn is captured as an LLM span with tool calls, token usage, and API request details, then sent to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Architecture

This integration uses the shared collector at `127.0.0.1:4318` for both span export and Codex event buffering:

```
Codex CLI
  │
  ├─ notify hook ──► notify.sh ──► OpenInference LLM spans (per turn)
  │                     │
  │                     ├─ Drains buffered events from collector (GET /drain/{id})
  │                     └─ Sends built spans to collector (POST /v1/spans)
  │                              └─► Phoenix (REST) or Arize AX (gRPC)
  │
  └─ OTLP export ──► collector (POST /v1/logs)
                      └─ Buffers native Codex events by thread-id
```

1. **Shared collector** (`core/collector.py`, port 4318) -- background process shared by all harnesses. Accepts span exports (`POST /v1/spans`), buffers Codex OTLP log events (`POST /v1/logs`), and serves buffered events (`GET /drain/{id}`, `GET /flush/{id}`). Exports to Phoenix or Arize AX. Managed via `core/collector_ctl.sh`.

2. **`notify.sh`** -- Codex calls this after every agent turn. It builds an OpenInference LLM span from the turn payload, drains buffered events from the collector, assembles child spans (TOOL, CHAIN), and submits the complete span tree back to the collector for export.

When both the notify hook and native OTLP export are enabled, `notify.sh` builds a parent LLM span and attaches child spans from buffered event data, producing a rich trace tree per turn.

## Installation

### Curl installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash
```

The installer detects Codex and guides you through configuration.

### Dedicated installer

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit/codex-tracing
bash install.sh
```

The installer supports interactive and non-interactive modes:

```bash
# Interactive
bash install.sh

# Non-interactive: Phoenix
bash install.sh --target phoenix

# Non-interactive: Arize AX with native OTLP
bash install.sh --target arize --otlp

# Uninstall
bash install.sh uninstall
```

### Manual setup

1. Set the notify hook in `~/.codex/config.toml`:

```toml
notify = ["bash", "/path/to/arize-agent-kit/codex-tracing/hooks/notify.sh"]
```

2. Create `~/.codex/arize-env.sh` with your backend configuration (see below).

3. Create the shared collector config at `~/.arize-agent-kit/config.json` (see [COLLECTOR_ARCHITECTURE.md](../COLLECTOR_ARCHITECTURE.md) for the schema).

## Configuration

All env vars go in `~/.codex/arize-env.sh`. The notify hook sources this file automatically.

**Phoenix** (self-hosted) -- requires `jq` and `curl`, no Python:

```bash
export PHOENIX_ENDPOINT="http://localhost:6006"
export ARIZE_TRACE_ENABLED="true"
```

**Arize AX** (cloud) -- backend export is handled by the shared collector (gRPC dependencies are bundled with the collector, not required in your Python environment):

```bash
export ARIZE_API_KEY="<your-api-key>"
export ARIZE_SPACE_ID="<your-space-id>"
export ARIZE_TRACE_ENABLED="true"
```

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

When Codex OTLP export is enabled, `notify.sh` drains buffered events for the current thread-id from the shared collector and builds child spans.  These are merged with the parent span into a single OTLP `resourceSpans` payload via `build_multi_span()`, producing a hierarchical trace tree.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_API_KEY` | For AX | - | Arize AX API key |
| `ARIZE_SPACE_ID` | For AX | - | Arize AX space ID |
| `ARIZE_OTLP_ENDPOINT` | No | `otlp.arize.com:443` | OTLP gRPC endpoint (on-prem Arize) |
| `PHOENIX_ENDPOINT` | For Phoenix | `http://localhost:6006` | Phoenix collector URL |
| `PHOENIX_API_KEY` | No | - | Phoenix API key (if auth enabled) |
| `ARIZE_PROJECT_NAME` | No | Working dir basename | Project name in Arize/Phoenix |
| `ARIZE_USER_ID` | No | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_TRACE_DEBUG` | No | `false` | Write debug dumps to `~/.arize-codex/debug/` |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-codex.log` | Log file path (empty to disable) |
| `ARIZE_COLLECTOR_PORT` | No | `4318` | Port for the shared collector |

### User Identification

Set `ARIZE_USER_ID` to tag all spans with a `user.id` attribute:

```bash
export ARIZE_USER_ID="alice@example.com"
```

Add this to `~/.codex/arize-env.sh` so it persists across sessions.

## Process Management

### Shared Collector (port 4318)

The shared collector exports spans to the configured backend (Phoenix or Arize AX).  It is managed via `core/collector_ctl.sh`:

```bash
source core/collector_ctl.sh

collector_start    # Start the shared collector
collector_stop     # Stop it
collector_status   # Check if running (exit code 0/1)
collector_ensure   # Start if not already running
```

Config: `~/.arize-agent-kit/config.json`.  PID: `~/.arize-agent-kit/run/collector.pid`.  Log: `~/.arize-agent-kit/logs/collector.log`.

The shared collector also buffers Codex's native OTLP log events (`POST /v1/logs`) by thread ID for child-span assembly. No separate event buffer process is needed.

## Directory Structure

```
codex-tracing/
  hooks/common.sh              Adapter: thread-id state, debug dump, multi-span
  hooks/notify.sh              Notify hook (LLM spans with child span assembly)
  scripts/codex_proxy.sh       Proxy wrapper (ensures collector is running)
  install.sh                   Interactive/non-interactive installer
  skills/                      Codex setup skill
```

Shared logic lives in `core/` at the repository root:

```
core/common.sh        Env vars, logging, state primitives, span building, sending
core/collector.py     Shared collector: span export + event buffering
core/collector_ctl.sh Collector lifecycle management
core/send_arize.py    Arize AX gRPC sender (legacy fallback)
```

## Troubleshooting

**Spans not appearing in Phoenix**

1. Verify Phoenix is running: `curl -s http://localhost:6006/healthz`
2. Check the shared collector: `curl -s http://127.0.0.1:4318/health`
3. Check env vars in `~/.codex/arize-env.sh`
4. Check the shared collector log: `tail -20 ~/.arize-agent-kit/logs/collector.log`
5. Check the harness log: `tail -20 /tmp/arize-codex.log`
6. Test with dry run: `ARIZE_DRY_RUN=true codex`

**Spans not appearing in Arize AX**

1. Verify `ARIZE_API_KEY` and `ARIZE_SPACE_ID` in `~/.arize-agent-kit/config.json`
2. Check the shared collector: `curl -s http://127.0.0.1:4318/health`
3. Check the shared collector log for gRPC errors: `grep ERROR ~/.arize-agent-kit/logs/collector.log`

**Shared collector not starting**

1. Check config exists: `cat ~/.arize-agent-kit/config.json`
2. Check if port 4318 is in use: `lsof -i :4318`
3. Check PID file: `cat ~/.arize-agent-kit/run/collector.pid`
4. Check log: `tail -20 ~/.arize-agent-kit/logs/collector.log`

**Missing child spans (tool calls, API requests)**

1. Ensure native OTLP export is enabled in Codex config (`[otel]` section pointing to `127.0.0.1:4318`)
2. Verify the collector is running: `curl -s http://127.0.0.1:4318/health` (check `event_buffer` in response)
3. Enable debug dumps: `export ARIZE_TRACE_DEBUG=true` and check `~/.arize-codex/debug/`

**"jq required" error**

Install jq: `brew install jq` (macOS) or `apt-get install jq` (Linux).

**Session state issues**

State files are stored in `~/.arize-codex/`. To reset:

```bash
rm -rf ~/.arize-codex/state_*.json
```

Stale state files older than 24 hours are garbage-collected automatically.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Collector Architecture](../COLLECTOR_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
