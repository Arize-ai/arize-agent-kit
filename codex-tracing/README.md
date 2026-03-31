# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the **OpenAI Codex CLI**. Each agent turn is captured as an LLM span with tool calls, token usage, and API request details, then sent to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Architecture

This integration has three components:

```
Codex CLI
  │
  ├─ notify hook ──► notify.sh ──► OpenInference LLM spans (per turn)
  │                     │
  │                     ├─ Reads events from collector (child spans)
  │                     └─ Sends to Phoenix (REST) or Arize AX (gRPC)
  │
  └─ OTLP export ──► collector.py ──► Buffers events by thread-id
                      (port 4318)       └─ Drained by notify.sh per turn
```

1. **`notify.sh`** -- Codex calls this after every agent turn. It builds an OpenInference LLM span from the turn payload (input messages, assistant response, tool calls, token usage).

2. **`collector.py`** -- A lightweight OTLP log receiver (stdlib Python, port 4318). Codex's native telemetry exports events here. The collector buffers them by thread-id until `notify.sh` drains them.

3. **`collector_ctl.sh`** -- Lifecycle management for the collector process (start, stop, status, ensure).

When both the notify hook and native OTLP export are enabled, `notify.sh` builds a parent LLM span and attaches child spans (TOOL, CHAIN) from collector events, producing a rich trace tree per turn.

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

## Configuration

All env vars go in `~/.codex/arize-env.sh`. The notify hook sources this file automatically.

**Phoenix** (self-hosted) -- requires `jq` and `curl`, no Python:

```bash
export PHOENIX_ENDPOINT="http://localhost:6006"
export ARIZE_TRACE_ENABLED="true"
```

**Arize AX** (cloud) -- also requires Python with `opentelemetry-proto` and `grpcio`:

```bash
export ARIZE_API_KEY="<your-api-key>"
export ARIZE_SPACE_ID="<your-space-id>"
export ARIZE_TRACE_ENABLED="true"
# pip install opentelemetry-proto grpcio
```

## How It Works

### Span Types

Each Codex agent turn produces a **parent LLM span** with optional child spans:

| Span | Kind | Source | Description |
|------|------|--------|-------------|
| Turn N | LLM | notify payload | Parent span with input/output, token counts, model name |
| Tool call | TOOL | collector events | One per `codex.tool_decision` + `codex.tool_result` pair |
| API Request | CHAIN | collector events | One per `codex.api_request` or `codex.websocket_request` |

### Parent Span Attributes

The parent LLM span includes:

- `session.id`, `trace.number`, `project.name` -- session tracking
- `input.value`, `output.value` -- user prompt and assistant response
- `llm.output_messages` -- structured assistant output
- `llm.model_name` -- model extracted from collector events
- `llm.token_count.prompt`, `llm.token_count.completion`, `llm.token_count.total` -- token usage
- `codex.thread_id`, `codex.turn_id` -- Codex identifiers
- `codex.sandbox_mode`, `codex.approval_mode` -- session settings
- `user.id` -- user identifier (when `ARIZE_USER_ID` is set)

### Multi-Span Assembly

When the collector is running, `notify.sh` drains buffered events for the current thread-id and builds child spans. These are merged with the parent span into a single OTLP `resourceSpans` payload via `build_multi_span()`, producing a hierarchical trace tree.

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
| `CODEX_COLLECTOR_PORT` | No | `4318` | Port for the OTLP event collector |

### User Identification

Set `ARIZE_USER_ID` to tag all spans with a `user.id` attribute:

```bash
export ARIZE_USER_ID="alice@example.com"
```

Add this to `~/.codex/arize-env.sh` so it persists across sessions.

## Collector Management

The event collector is managed via `collector_ctl.sh`:

```bash
source codex-tracing/scripts/collector_ctl.sh

collector_start    # Start the collector daemon
collector_stop     # Stop the collector
collector_status   # Check if running (exit code 0/1)
collector_ensure   # Start if not already running
```

The collector listens on `127.0.0.1:4318`, buffers events by thread ID, supports protobuf and JSON OTLP formats, and auto-exits after 30 minutes of inactivity. PID file: `~/.arize-codex/collector.pid`.

## Directory Structure

``` 
codex-tracing/
  hooks/common.sh              Adapter: thread-id state, debug dump, multi-span
  hooks/notify.sh              Notify hook (LLM spans with child span assembly)
  scripts/collector.py         OTLP event collector daemon
  scripts/collector_ctl.sh     Collector lifecycle management
  install.sh                   Interactive/non-interactive installer
  skills/                      Codex setup skill
```

Shared logic lives in `core/` at the repository root:

```
core/common.sh       Env vars, logging, state primitives, span building, sending
core/send_arize.py   Arize AX gRPC sender (Python)
```

## Troubleshooting

**Spans not appearing in Phoenix**

1. Verify Phoenix is running: `curl -s http://localhost:6006/healthz`
2. Check env vars in `~/.codex/arize-env.sh`
3. Check the log: `tail -20 /tmp/arize-codex.log`
4. Test with dry run: `ARIZE_DRY_RUN=true codex`

**Spans not appearing in Arize AX**

1. Verify `ARIZE_API_KEY` and `ARIZE_SPACE_ID` are set in `~/.codex/arize-env.sh`
2. Ensure Python dependencies: `python3 -c "import opentelemetry; import grpc"`
3. Check the log for gRPC errors: `grep ERROR /tmp/arize-codex.log`

**Collector not starting**

1. Check if port 4318 is in use: `lsof -i :4318`
2. Check collector status: `source scripts/collector_ctl.sh && collector_status`
3. Check PID file: `cat ~/.arize-codex/collector.pid`
4. Look for collector errors in `~/.arize-codex/debug/`

**Missing child spans (tool calls, API requests)**

1. Ensure native OTLP export is enabled in Codex config
2. Verify the collector is running: `curl -s http://127.0.0.1:4318/health`
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
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
