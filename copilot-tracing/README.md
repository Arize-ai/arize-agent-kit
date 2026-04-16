# GitHub Copilot Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for **GitHub Copilot** sessions. Supports both **VS Code Copilot** (8 hook events with full transcript parsing) and **Copilot CLI** (6 hook events with deferred turns). Every prompt, tool use, agent response, subagent lifecycle, and stop event is captured as a span and exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Implementation Status

> **Note:** This README documents the planned Copilot tracing integration. The hook handlers (`core/hooks/copilot/`), setup script (`core/setup/copilot.py`), CLI entry points (`arize-hook-copilot-*`), and `install.sh copilot` support are being added in subsequent changes. The plugin directory and documentation are provided first to define the interface contract.

## Features

- **Dual-mode support**: VS Code Copilot (8 events) and Copilot CLI (6 events) from a single handler
- Automatic mode detection — no configuration needed to switch between VS Code and CLI
- Separate CLI entry points per hook event for clean registration
- Direct span export to Phoenix (REST) or Arize AX (HTTP) — no background process needed
- Per-harness backend credential overrides via `harnesses.copilot.backend` in config
- VS Code mode: full input/output/token capture via transcript parsing at `Stop`
- VS Code mode: subagent lifecycle tracking (`SubagentStart`/`SubagentStop`)
- CLI mode: deferred turn completion — spans sent at next `userPromptSubmitted` or `sessionEnd`
- `ARIZE_USER_ID` support for team-level span attribution
- Cross-platform: works on macOS, Linux, and Windows (Python 3.9+)
- Dry-run mode for validating span output without sending data

## Prerequisites

- **Python 3.9+**

No additional dependencies are required. Spans are sent directly to the backend from hooks.

## Architecture

The handler auto-detects which platform is calling by checking for VS Code-specific fields (`sessionId`, `hookEventName`). Each mode follows a different path:

```text
VS Code Copilot
  │
  └─ .github/hooks/*.json ──► arize-hook-copilot-* ──► detect VS Code mode
                                     │
                                     ├─ SessionStart        → session init span
                                     ├─ UserPromptSubmit    → user prompt span
                                     ├─ PreToolUse          → tool start span + permission response
                                     ├─ PostToolUse         → tool result span
                                     ├─ SubagentStart       → subagent init span
                                     ├─ SubagentStop        → subagent completion span
                                     ├─ PreCompact          → context compaction span
                                     └─ Stop                → parse transcript → full I/O + tokens
                                            │
                                            └─ send_span() ──► Phoenix (REST)
                                                           \─► Arize AX (HTTP)

Copilot CLI
  │
  └─ .github/hooks/hooks.json ──► arize-hook-copilot-* ──► detect CLI mode
                                        │
                                        ├─ sessionStart          → session init span
                                        ├─ userPromptSubmitted   → flush deferred turn + new prompt span
                                        ├─ preToolUse            → tool start span + permission response
                                        ├─ postToolUse           → tool result span
                                        ├─ errorOccurred         → error span
                                        └─ sessionEnd            → flush deferred turn + session end span
                                               │
                                               └─ send_span() ──► Phoenix (REST)
                                                              \─► Arize AX (HTTP)
```

**Key difference:** VS Code mode receives `sessionId` and a `transcript_path` at `Stop`, enabling full input/output/token extraction. CLI mode has no transcript access — turns are deferred and flushed with input only (no agent output or token counts).

## Installation

### Automated installer (recommended)

Once Copilot support is fully implemented, the installer will accept `copilot` as a harness argument:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- copilot
```

The installer will:
1. Create a virtualenv at `~/.arize/harness/venv`
2. Install `arize-agent-kit` and CLI entry points
3. Run the Copilot setup script
4. Guide you through backend configuration

### Pip install

```bash
pip install arize-agent-kit
python -m core.install copilot
```

### Manual

```bash
pip install arize-agent-kit
arize-setup-copilot
```

## Configuration

The single source of truth for backend credentials and per-harness configuration is `~/.arize/harness/config.yaml`. Each harness gets its own entry under `harnesses` with a dedicated `project_name` and optional backend override.

### Phoenix (self-hosted)

```yaml
backend:
  target: "phoenix"
  phoenix:
    endpoint: "http://localhost:6006"
    api_key: ""
harnesses:
  copilot:
    project_name: "copilot"
```

### Arize AX (cloud)

```yaml
backend:
  target: "arize"
  arize:
    api_key: "<your-api-key>"
    space_id: "<your-space-id>"
harnesses:
  copilot:
    project_name: "copilot"
```

Each harness can optionally override backend credentials under `harnesses.copilot.backend`. See [TRACING_ARCHITECTURE.md](../docs/TRACING_ARCHITECTURE.md) for the per-harness override schema.

## Activating Hooks

### VS Code Copilot

VS Code uses individual JSON files in `.github/hooks/` for each hook event. If you used the installer, these are generated automatically. For manual setup, create a JSON file per event:

**Example: `.github/hooks/session-start.json`**
```json
{
  "hooks": [
    {
      "event": "SessionStart",
      "command": "~/.arize/harness/venv/bin/arize-hook-copilot-session-start"
    }
  ]
}
```

Register all 8 events by creating a file for each: `session-start.json`, `user-prompt.json`, `pre-tool.json`, `post-tool.json`, `stop.json`, `subagent-start.json`, `subagent-stop.json`, `pre-compact.json`.

> **Note:** VS Code auto-converts CLI camelCase event names to PascalCase. Each event maps to its own CLI entry point.

### Copilot CLI

Copilot CLI uses a single `.github/hooks/hooks.json` file with version 1 format:

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      { "bash": "~/.arize/harness/venv/bin/arize-hook-copilot-session-start" }
    ],
    "userPromptSubmitted": [
      { "bash": "~/.arize/harness/venv/bin/arize-hook-copilot-user-prompt" }
    ],
    "preToolUse": [
      { "bash": "~/.arize/harness/venv/bin/arize-hook-copilot-pre-tool" }
    ],
    "postToolUse": [
      { "bash": "~/.arize/harness/venv/bin/arize-hook-copilot-post-tool" }
    ],
    "errorOccurred": [
      { "bash": "~/.arize/harness/venv/bin/arize-hook-copilot-error" }
    ],
    "sessionEnd": [
      { "bash": "~/.arize/harness/venv/bin/arize-hook-copilot-session-end" }
    ]
  }
}
```

> **Note:** CLI hooks use the `bash` field (not `command`) and camelCase event names.

## Hook Events

| Hook Event | Platform | Span Name | Span Kind | Description |
|------------|----------|-----------|-----------|-------------|
| `SessionStart` / `sessionStart` | Both | Session Start | CHAIN | Session initialization; VS Code provides `sessionId`, CLI provides `source` and `initialPrompt` |
| `UserPromptSubmit` / `userPromptSubmitted` | Both | User Prompt | CHAIN | User prompt text; CLI mode also flushes the previous deferred turn |
| `PreToolUse` / `preToolUse` | Both | Tool: {name} | TOOL | Tool invocation start; **must print permission response to stdout** |
| `PostToolUse` / `postToolUse` | Both | Tool: {name} | TOOL | Tool result; VS Code uses `tool_response`, CLI uses `toolResult.textResultForLlm` |
| `Stop` | VS Code only | Agent Stop | LLM | Per-turn completion with `transcript_path` — parses full input/output/tokens |
| `SubagentStart` | VS Code only | Subagent: {id} | CHAIN | Subagent lifecycle start with `agent_id` and `agent_type` |
| `SubagentStop` | VS Code only | Subagent: {id} | CHAIN | Subagent lifecycle end with completion status |
| `PreCompact` | VS Code only | Context Compact | CHAIN | Context window compaction triggered by `trigger` field |
| `errorOccurred` | CLI only | Error | CHAIN | Error event with `message`, `name`, and `stack` |
| `sessionEnd` | CLI only | Session End | CHAIN | Session termination; flushes deferred turn; includes `reason` |

### PreToolUse Permission Response

The `PreToolUse`/`preToolUse` handler must print a permission response to stdout. The format differs by mode:

**VS Code mode:**
```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
```

**CLI mode:**
```json
{"permissionDecision": "allow"}
```

All other handlers print `{"continue": true}` in VS Code mode and nothing in CLI mode.

## Dual-Mode Detection

The handler automatically detects VS Code vs CLI by checking for VS Code-specific base fields:

```python
def _is_vscode(input_json: dict) -> bool:
    return bool(input_json.get("sessionId") or input_json.get("hookEventName"))
```

VS Code payloads always include `sessionId`, `hookEventName`, `timestamp`, `cwd`, and `transcript_path`. CLI payloads omit these fields entirely.

| Behavior | VS Code mode | CLI mode |
|----------|-------------|----------|
| Session key | `sessionId` from payload | PID-based (like Claude Code) |
| Turn completion | `Stop` event with `transcript_path` | Deferred — sent at next `userPromptSubmitted` or `sessionEnd` |
| Root span output | Parsed from transcript | No output (CLI doesn't expose agent response) |
| Tool input format | `tool_input` (dict) | `toolArgs` (JSON string, needs `json.loads()`) |
| Tool output format | `tool_response` (string) | `toolResult.textResultForLlm` (nested object) |
| Subagent spans | Yes (`SubagentStart`/`SubagentStop`) | Not available |
| Field naming | snake_case (`tool_name`) | camelCase (`toolName`) |
| Model/token info | Available via transcript | Not available |

## Environment Variables (fallback)

The config file `~/.arize/harness/config.yaml` is the primary and recommended way to configure tracing. The environment variables below serve as a fallback or for overriding specific values at runtime.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_PROJECT_NAME` | No | Config file / `copilot` | Project name override (prefer `harnesses` config) |
| `ARIZE_USER_ID` | No | -- | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-copilot.log` | Log file path (empty to disable) |

Backend credentials (`ARIZE_API_KEY`, `ARIZE_SPACE_ID`, `PHOENIX_ENDPOINT`, etc.) can also be set as environment variables and will be used as fallbacks if not configured in `config.yaml`.

## Troubleshooting

### VS Code Copilot

| Problem | Solution |
|---------|----------|
| **Spans not appearing** | 1. Check hook log: `tail -20 /tmp/arize-copilot.log` 2. Verify backend is reachable (Phoenix: `curl -s http://localhost:6006/healthz`) 3. Test with dry run: `ARIZE_DRY_RUN=true ARIZE_VERBOSE=true` |
| **Spans missing output/tokens** | Verify `Stop` hook is registered and `transcript_path` is present in the payload. Transcript parsing is required for full I/O capture |
| **Hooks not firing** | Verify `.github/hooks/*.json` files exist in your project root and the `command` paths are correct (absolute path to venv binary) |
| **PreToolUse blocking tools** | Check that the handler prints the correct permission JSON to stdout. Verify with: `echo '{"hookEventName":"PreToolUse","tool_name":"test"}' \| arize-hook-copilot-pre-tool` |
| **Subagent spans missing** | `SubagentStart`/`SubagentStop` are VS Code only. Verify both hooks are registered in `.github/hooks/` |

### Copilot CLI

| Problem | Solution |
|---------|----------|
| **Spans not appearing** | 1. Check hook log: `tail -20 /tmp/arize-copilot.log` 2. Verify `.github/hooks/hooks.json` exists with `version: 1` 3. Test with dry run: `ARIZE_DRY_RUN=true ARIZE_VERBOSE=true` |
| **No output on spans** | Expected behavior. Copilot CLI does not expose agent responses — spans will have input only |
| **No token counts** | Expected behavior. Copilot CLI payloads do not include model name or token usage |
| **Hooks not firing** | Verify `.github/hooks/hooks.json` uses the `bash` field (not `command`) and camelCase event names |
| **preToolUse blocking tools** | Check that the handler prints `{"permissionDecision": "allow"}` to stdout. Verify with: `echo '{"toolName":"test","toolArgs":"{}"}' \| arize-hook-copilot-pre-tool` |
| **Deferred turns not flushing** | Turns flush at the next `userPromptSubmitted` or `sessionEnd`. If the CLI exits abnormally, the last turn may be lost |

For more verbose output, enable debug logging:

```bash
ARIZE_VERBOSE=true  # set in your shell before running Copilot
tail -f /tmp/arize-copilot.log
```

## Directory Structure

```
copilot-tracing/
  README.md
```

Setup will be provided by the `arize-setup-copilot` CLI entry point (defined in `core/setup/copilot.py`, not yet implemented).

Hook logic will live in `core/` at the repository root (installed as a Python package):

```
core/
  hooks/copilot/
    adapter.py       Copilot-specific session resolution, dual-mode detection
    handlers.py      Per-event handler functions for all 8 VS Code + 6 CLI events
  common.py          Shared: span building, direct send, state, logging, IDs
  config.py          YAML config helper
  constants.py       Single source of truth for all paths
```

## CLI Entry Points

Each hook event has a dedicated CLI entry point:

| Entry Point | VS Code Event | CLI Event |
|-------------|---------------|-----------|
| `arize-hook-copilot-session-start` | `SessionStart` | `sessionStart` |
| `arize-hook-copilot-user-prompt` | `UserPromptSubmit` | `userPromptSubmitted` |
| `arize-hook-copilot-pre-tool` | `PreToolUse` | `preToolUse` |
| `arize-hook-copilot-post-tool` | `PostToolUse` | `postToolUse` |
| `arize-hook-copilot-stop` | `Stop` | -- |
| `arize-hook-copilot-subagent-start` | `SubagentStart` | -- |
| `arize-hook-copilot-subagent-stop` | `SubagentStop` | -- |
| `arize-hook-copilot-pre-compact` | `PreCompact` | -- |
| `arize-hook-copilot-error` | -- | `errorOccurred` |
| `arize-hook-copilot-session-end` | -- | `sessionEnd` |

## Links

- [VS Code Copilot Hooks Reference](https://code.visualstudio.com/docs/copilot/customization/hooks)
- [Copilot CLI Hooks Reference](https://docs.github.com/en/copilot/reference/hooks-configuration#hook-types)
- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Tracing Architecture](../docs/TRACING_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
