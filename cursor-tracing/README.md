# Cursor IDE Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for **Cursor IDE** sessions. Every prompt, agent response, thinking step, shell execution, MCP tool use, file operation, and stop event is captured as a span and exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) via a shared background collector.

## Features

- 12 hook-based span types covering the full Cursor session lifecycle
- Before/after event merging for shell execution and MCP tool use via disk-backed state stack
- Exports to Phoenix or Arize AX through the shared background collector — no Python dependencies required in hooks
- Deterministic trace IDs derived from Cursor's `generation_id`
- Single handler script dispatches all hook events via `hook_event_name`
- `ARIZE_USER_ID` support for team-level span attribution
- Dry-run mode for validating span output without sending data

## Prerequisites

- **`bash`** (4.0+)
- **`jq`** — JSON manipulation (`brew install jq` on macOS, `apt-get install jq` on Linux)
- **`curl`** — HTTP requests (pre-installed on most systems)

No Python installation is required. The shared collector (installed automatically) handles all backend export.

## Installation

### Curl installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor
```

The installer will:
1. Clone or update the arize-agent-kit repository
2. Run the Cursor setup script
3. Start the shared background collector
4. Guide you through backend configuration

### Manual

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
bash cursor-tracing/scripts/setup.sh
```

## Configuration

The single source of truth for backend credentials, collector settings, and per-harness configuration is `~/.arize/harness/config.json`. Each harness gets its own entry under `harnesses` with a dedicated `project_name`.

### Phoenix (self-hosted)

```json
{
  "collector": { "host": "127.0.0.1", "port": 4318 },
  "backend": {
    "target": "phoenix",
    "phoenix": { "endpoint": "http://localhost:6006", "api_key": "" }
  },
  "harnesses": {
    "cursor": { "project_name": "cursor" }
  }
}
```

### Arize AX (cloud)

```json
{
  "collector": { "host": "127.0.0.1", "port": 4318 },
  "backend": {
    "target": "arize",
    "arize": { "api_key": "<your-api-key>", "space_id": "<your-space-id>" }
  },
  "harnesses": {
    "cursor": { "project_name": "cursor" }
  }
}
```

### `.env` file support

For backwards compatibility with the standalone `arize-cursor` repo, a `.env` file in the project root is also supported. Environment variables defined there override values from `config.json`. However, the config file is the recommended approach — see [Environment Variables](#environment-variables-fallback) for the full list.

## Activating Hooks

Cursor uses a single `hooks.json` file in your project's `.cursor/` directory to route all hook events to one handler script. Copy the provided hooks file:

```bash
cp cursor-tracing/hooks.json .cursor/hooks.json
```

The hooks file references the handler script via absolute path. If you installed to a non-default location, update the path in `.cursor/hooks.json`:

```json
{
  "hooks": {
    "beforeSubmitPrompt": [{ "command": "bash /path/to/arize-agent-kit/cursor-tracing/hooks/handler.sh" }],
    "afterAgentResponse": [{ "command": "bash /path/to/arize-agent-kit/cursor-tracing/hooks/handler.sh" }]
  }
}
```

If your project already has a `.cursor/hooks.json`, merge the hook entries rather than overwriting the file. The setup script (`scripts/setup.sh`) handles this automatically.

> **Note:** All 12 hook events route to the same `handler.sh` script. The handler reads `hook_event_name` from the stdin JSON payload and dispatches to the appropriate logic via a `case` statement.

## Hook Events

Each Cursor hook event produces one OpenInference span (or pushes state for later merging):

| Hook Event | Span Name | Span Kind | Description |
|------------|-----------|-----------|-------------|
| `beforeSubmitPrompt` | User Prompt | CHAIN | Root span for the turn; captures user prompt text |
| `afterAgentResponse` | Agent Response | LLM | Agent's response with input/output values |
| `afterAgentThought` | Agent Thinking | CHAIN | Agent's intermediate reasoning step |
| `beforeShellExecution` | *(state push)* | — | Pushes command and start time to disk state |
| `afterShellExecution` | Shell | TOOL | Merges with pushed state; captures command, output, duration |
| `beforeMCPExecution` | *(state push)* | — | Pushes MCP tool name and start time to disk state |
| `afterMCPExecution` | MCP: {tool} | TOOL | Merges with pushed state; captures tool name, input, output, duration |
| `beforeReadFile` | Read File | TOOL | File path read by the agent |
| `afterFileEdit` | File Edit | TOOL | File path and edit details |
| `beforeTabFileRead` | Tab Read File | TOOL | File read from a tab context |
| `afterTabFileEdit` | Tab File Edit | TOOL | File edit from a tab context |
| `stop` | Agent Stop | CHAIN | Session or conversation stop event |

All spans include `session.id` (from `conversation_id`), `project.name`, and `openinference.span.kind` attributes. Trace IDs are deterministically derived from `generation_id` using MD5/SHA hashing (32 hex chars). Span IDs are 16 random hex chars from `/dev/urandom`.

## Architecture

Hooks build OTLP spans and POST them to the shared background collector at `http://127.0.0.1:4318/v1/spans`. The collector handles all backend export (Phoenix REST or Arize AX gRPC), retries, and credential management.

```text
Cursor IDE
  │
  └─ hooks.json ──► handler.sh ──► case $hook_event_name
                        │
                        ├─ build_span() (OTLP format via core/common.sh)
                        └─ send_span()  ──► POST http://127.0.0.1:4318/v1/spans
                                                  (shared collector)
                                                        ├──► Phoenix (REST)
                                                        └──► Arize AX (gRPC)
```

The collector is installed and started automatically by `install.sh`. See [COLLECTOR_ARCHITECTURE.md](../COLLECTOR_ARCHITECTURE.md) for the full design.

## Shell/MCP State Merging

Cursor fires separate `before` and `after` events for shell execution and MCP tool use. To produce a single span with both the input (command/tool name) and the result (output, duration), the handler uses a disk-backed FIFO state stack:

1. **`beforeShellExecution` / `beforeMCPExecution`** — Pushes the command/tool name and start timestamp to a state file in `~/.arize-cursor/`.
2. **`afterShellExecution` / `afterMCPExecution`** — Pops the matching state, computes duration, and builds a complete TOOL span with both input and output.

State files are keyed by `conversation_id` to isolate concurrent sessions. Stale state files are garbage-collected automatically.

## Migrating from arize-cursor

If you are using the standalone [arize-cursor](https://github.com/Arize-ai/arize-cursor) repository, here is what changed in the arize-agent-kit port:

### What changed

| Aspect | arize-cursor (standalone) | arize-agent-kit (this) |
|--------|--------------------------|------------------------|
| **Backend export** | Python gRPC sender in hooks; requires `grpcio`, `opentelemetry-proto` | Shared collector handles all export; no Python deps in hooks |
| **Span format** | Two formats: `build_phoenix_span` + `build_otlp_span` | Single OTLP format via `build_span()` from `core/common.sh` |
| **Configuration** | `.env` file with `PHOENIX_ENDPOINT`, `ARIZE_API_KEY`, etc. | `~/.arize/harness/config.json` (`.env` still works as fallback) |
| **State directory** | `~/.cursor/cursor-phoenix-state/` | `~/.arize-cursor/` |
| **Collector** | None (direct export from hooks) | Shared background collector at `127.0.0.1:4318` |
| **Installation** | Standalone clone + manual setup | `install.sh` with `cursor` flag, or root curl installer |

### What stayed the same

- All 12 hook events and their span semantics
- Disk-backed state stack for before/after event merging
- `.env` file support (now as a fallback, not primary)
- `conversation_id`-based session tracking
- Deterministic trace ID derivation from `generation_id`

### Migration steps

1. Run the arize-agent-kit installer: `curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor`
2. Your existing `.env` settings will be read as fallback. Optionally migrate them to `~/.arize/harness/config.json`.
3. Update `.cursor/hooks.json` to point to the new handler path.
4. Remove the old `arize-cursor` clone if no longer needed.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Spans not appearing** | 1. Verify collector is running: `curl -sf http://127.0.0.1:4318/health` 2. Check hook log: `tail -20 /tmp/arize-cursor.log` 3. Check collector log: `tail -20 ~/.arize/harness/logs/collector.log` |
| **Collector not running** | Verify config exists: `cat ~/.arize/harness/config.json`. Start it: `source core/collector_ctl.sh && collector_start`. Check log: `tail -20 ~/.arize/harness/logs/collector.log` |
| **"jq required" error** | Install jq: `brew install jq` (macOS) or `apt-get install jq` (Linux) |
| **Shell/MCP spans missing input** | State push failed — check that `~/.arize-cursor/` is writable. Enable verbose logging: `ARIZE_VERBOSE=true` |
| **Hooks not firing** | Verify `.cursor/hooks.json` exists in your project root and the handler path is correct (absolute path) |
| **Duplicate or stale state files** | Reset state: `rm -rf ~/.arize-cursor/state_*.json`. Stale files are normally garbage-collected automatically |
| **Spans not appearing in Arize AX** | Verify `api_key` and `space_id` in `~/.arize/harness/config.json`. Check collector log: `grep ERROR ~/.arize/harness/logs/collector.log` |

For more verbose output, enable debug logging:

```bash
ARIZE_VERBOSE=true  # in your shell or .env file
tail -f /tmp/arize-cursor.log
```

## Environment Variables (fallback)

The config file `~/.arize/harness/config.json` is the primary and recommended way to configure tracing. The environment variables below serve as a fallback or for overriding specific values at runtime.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_PROJECT_NAME` | No | Config file / `cursor` | Project name override (prefer `harnesses` config) |
| `ARIZE_USER_ID` | No | — | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-cursor.log` | Log file path (empty to disable) |
| `ARIZE_COLLECTOR_HOST` | No | `127.0.0.1` | Shared collector listen address |
| `ARIZE_COLLECTOR_PORT` | No | `4318` | Shared collector listen port |

Backend credentials (`ARIZE_API_KEY`, `ARIZE_SPACE_ID`, `PHOENIX_ENDPOINT`, etc.) are configured in `~/.arize/harness/config.json` and read by the collector. They do not need to be set as environment variables.

## Directory Structure

```
cursor-tracing/
  hooks/common.sh       Adapter: sets ARIZE_SERVICE_NAME, sources core/common.sh
  hooks/handler.sh      Single handler for all 12 hook events (case dispatch)
  hooks.json            Cursor hooks configuration (copy to .cursor/hooks.json)
  scripts/setup.sh      Interactive configuration and hooks installation
```

Shared logic lives in `core/` at the repository root:

```
core/common.sh         Env vars, logging, state primitives, span building, local submission
core/collector.py      Shared background collector/exporter
core/collector_ctl.sh  Collector lifecycle management (start/stop/status/ensure)
```

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Collector Architecture](../COLLECTOR_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
