# Cursor IDE Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for **Cursor IDE** sessions. Every prompt, agent response, thinking step, shell execution, MCP tool use, file operation, and stop event is captured as a span and exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Features

- 12 hook-based span types covering the full Cursor session lifecycle
- Before/after event merging for shell execution and MCP tool use via disk-backed state stack
- Sends spans directly to Phoenix (REST) or Arize AX (HTTP) — no background process needed
- Per-harness backend credentials via `harnesses.cursor.*` in config
- Deterministic trace IDs derived from Cursor's `generation_id`
- Single Python CLI entry point dispatches all hook events via `hook_event_name`
- Cross-platform: works on macOS, Linux, and Windows (Python 3.9+)
- `ARIZE_USER_ID` support for team-level span attribution
- Dry-run mode for validating span output without sending data

## Prerequisites

- **Python 3.9+**

No additional dependencies are required. Spans are sent directly to the backend from hooks.

## Installation

### Pip installer (recommended)

```bash
pip install arize-agent-kit
python -m core.install cursor
```

The installer will:
1. Install the package and CLI entry points into the venv
2. Run the Cursor setup script
3. If another harness is already installed using the same target, offer to reuse its credentials
4. Guide you through backend configuration

### Manual

```bash
pip install arize-agent-kit
arize-setup-cursor
```

## Configuration

The single source of truth for backend credentials and per-harness configuration is `~/.arize/harness/config.yaml`. Each harness owns its full backend configuration directly.

### Phoenix (self-hosted)

```yaml
harnesses:
  cursor:
    project_name: cursor
    target: phoenix
    endpoint: http://localhost:6006
    api_key: ""
```

### Arize AX (cloud)

```yaml
harnesses:
  cursor:
    project_name: cursor
    target: arize
    endpoint: otlp.arize.com:443
    api_key: <your-api-key>
    space_id: <your-space-id>
```

See [TRACING_ARCHITECTURE.md](../docs/TRACING_ARCHITECTURE.md) for the full schema.

## Activating Hooks

Cursor uses a single `hooks.json` file in your project's `.cursor/` directory to route all hook events to one Python CLI entry point.

If you used the installer, hooks.json is generated automatically with the correct paths. For manual installs, create `.cursor/hooks.json` with the path to the handler:

```json
{
  "hooks": {
    "beforeSubmitPrompt": [{ "command": "~/.arize/harness/venv/bin/arize-hook-cursor" }],
    "afterAgentResponse": [{ "command": "~/.arize/harness/venv/bin/arize-hook-cursor" }]
  }
}
```

If your project already has a `.cursor/hooks.json`, merge the hook entries rather than overwriting the file. The setup script handles this automatically.

> **Note:** All 12 hook events route to the same `arize-hook-cursor` CLI entry point. The handler reads `hook_event_name` from the stdin JSON payload and dispatches to the appropriate logic.

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

All spans include `session.id` (from `conversation_id`), `project.name`, and `openinference.span.kind` attributes. Trace IDs are deterministically derived from `generation_id` using `hashlib.md5` (32 hex chars). Span IDs are 16 random hex chars from `os.urandom`.

## Architecture

Hooks build OTLP spans and send them directly to the configured backend via `send_span()` in `core/common.py`. Per-harness backend credentials are read from `harnesses.cursor.*` in config.

```text
Cursor IDE
  │
  └─ hooks.json ──► arize-hook-cursor ──► dispatch by hook_event_name
                          │
                          ├─ build span (OTLP format via core.common)
                          └─ send_span() ──► Phoenix (REST)
                                         \─► Arize AX (HTTP)
```

See [TRACING_ARCHITECTURE.md](../docs/TRACING_ARCHITECTURE.md) for the full design.

## Shell/MCP State Merging

Cursor fires separate `before` and `after` events for shell execution and MCP tool use. To produce a single span with both the input (command/tool name) and the result (output, duration), the handler uses a disk-backed LIFO state stack:

1. **`beforeShellExecution` / `beforeMCPExecution`** — Pushes the command/tool name and start timestamp to a state file in `~/.arize/harness/state/cursor/`.
2. **`afterShellExecution` / `afterMCPExecution`** — Pops the matching state, computes duration, and builds a complete TOOL span with both input and output.

State files are keyed by `conversation_id` to isolate concurrent sessions. Stale state files are garbage-collected automatically.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Spans not appearing** | 1. Check hook log: `tail -20 /tmp/arize-cursor.log` 2. Verify backend is reachable (Phoenix: `curl -s http://localhost:6006/healthz`) 3. Test with dry run: `ARIZE_DRY_RUN=true ARIZE_VERBOSE=true` |
| **Spans not appearing in Arize AX** | Verify `api_key` and `space_id` in `~/.arize/harness/config.yaml`. Check hook log: `grep ERROR /tmp/arize-cursor.log` |
| **Shell/MCP spans missing input** | State push failed — check that `~/.arize/harness/state/cursor/` is writable. Enable verbose logging: `ARIZE_VERBOSE=true` |
| **Hooks not firing** | Verify `.cursor/hooks.json` exists in your project root and the handler path is correct (absolute path) |
| **Duplicate or stale state files** | Reset state: `rm -rf ~/.arize/harness/state/cursor/state_*.yaml`. Stale files are normally garbage-collected automatically |

For more verbose output, enable debug logging:

```bash
ARIZE_VERBOSE=true  # set in your shell before running Cursor
tail -f /tmp/arize-cursor.log
```

## Environment Variables (fallback)

The config file `~/.arize/harness/config.yaml` is the primary and recommended way to configure tracing. The environment variables below serve as a fallback or for overriding specific values at runtime.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_PROJECT_NAME` | No | Config file / `cursor` | Project name override (prefer `harnesses` config) |
| `ARIZE_USER_ID` | No | — | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-cursor.log` | Log file path (empty to disable) |

Backend credentials are configured in `~/.arize/harness/config.yaml` under `harnesses.cursor.*`.

## Directory Structure

```
cursor-tracing/
  skills/               Cursor setup skill
  README.md
```

Setup is provided by the `arize-setup-cursor` CLI entry point (defined in `core/setup/cursor.py`).

Hook logic lives in `core/` at the repository root (installed as a Python package):

```
core/
  hooks/cursor/
    adapter.py       Cursor-specific state stack, ID generation, sanitize
    handlers.py      12-event dispatcher entry point
  common.py          Shared: span building, direct send, state, logging, IDs
  config.py          YAML config helper
  constants.py       Single source of truth for all paths
```

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Tracing Architecture](../docs/TRACING_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
