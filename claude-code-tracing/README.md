# Claude Code Tracing Plugin

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for **Claude Code CLI** and the **Claude Agent SDK**. Every prompt, tool call, model response, and session lifecycle event is captured as a span and exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Features

- 9 hook-based span types covering the full session lifecycle
- Works with both Claude Code CLI and the Claude Agent SDK — same install, same hooks, same config
- Sends spans directly to Phoenix (REST) or Arize AX (gRPC) — no background process needed
- Per-harness backend credential overrides via `harnesses.claude-code.backend` in config
- PID-based session isolation with automatic garbage collection
- Lazy session initialization for Agent SDK environments (no `SessionStart` event)
- `ARIZE_USER_ID` support for team-level span attribution
- Dry-run mode for validating span output without sending data

## Architecture

Claude hooks build OpenInference spans locally and send them directly to the configured backend via `send_span()` in `core/common.py`. Backend credentials are resolved per-harness from `config.yaml`, with optional overrides under `harnesses.claude-code.backend`.

- No background process or collector needed
- No additional Python packages (`grpcio`, `opentelemetry-proto`) are needed in the user environment
- Cross-platform: works on macOS, Linux, and Windows (Python 3.9+)

```text
Claude hooks (Python CLI) --> send_span() --> Phoenix (REST)
                                          \-> Arize AX (gRPC)
```

See [TRACING_ARCHITECTURE.md](../docs/TRACING_ARCHITECTURE.md) for the full design.

## Installation

### Claude Code Marketplace (recommended)

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

### Pip installer

```bash
pip install arize-agent-kit
python -m core.install claude
```

The installer:

1. Installs the package and CLI entry points into the venv
2. Writes hook entries directly into `~/.claude/settings.json` (one per lifecycle event)
3. Registers the plugin path in `settings.json` under `plugins`

Hooks are Python CLI entry points (e.g. `arize-hook-session-start`) installed in the venv. Each hook event maps to a dedicated command.

### Claude Agent SDK

The same installer works for both Claude Code CLI and the Claude Agent SDK — they share the same hooks and settings. Run the curl installer above, then pass the plugin path when launching your agent:

```typescript
import { Agent } from '@anthropic-ai/agent-sdk';

const agent = new Agent({
  plugins: ['~/.arize/harness/claude-code-tracing'],
  // ... other options
});
```

Or clone the repository for manual setup:

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
# Point your SDK config at:
#   /path/to/arize-agent-kit/claude-code-tracing
```

## Configuration

Run the interactive setup after installation:

```bash
arize-setup-claude
```

The setup script will:

1. Ask which backend to configure: Phoenix or Arize AX
2. Write backend credentials and harness settings to the shared config at `~/.arize/harness/config.yaml`
3. Optionally add `ARIZE_USER_ID` for span attribution

### Shared Config File

The single source of truth for backend credentials and per-harness configuration is `~/.arize/harness/config.yaml`. Each harness gets its own entry under `harnesses` with a dedicated `project_name` and optional backend override:

```yaml
backend:
  target: "phoenix"
  phoenix:
    endpoint: "..."
    api_key: "..."
harnesses:
  claude-code:
    project_name: "claude-code"
    backend:                      # optional — overrides global backend
      target: "arize"
      arize:
        api_key: "different-key"
        space_id: "different-space"
        endpoint: "otlp.arize.com:443"
```

Backend credentials and harness project names are stored in `~/.arize/harness/config.yaml` and read by `send_span()` directly. No environment variables need to be set in Claude settings for tracing to work. Tracing is enabled by default (`ARIZE_TRACE_ENABLED` defaults to `true`).

Requires: Python 3.9+. No additional packages needed in the user environment.

## Hooks

The installer registers 9 Claude Code hooks as Python CLI entry points in `~/.claude/settings.json`. Each hook creates one OpenInference span:

| Hook | Span Kind | Description |
|------|-----------|-------------|
| `SessionStart` | CHAIN | Session initialized, trace/tool counters reset |
| `UserPromptSubmit` | CHAIN | User prompt captured (also lazy-inits session for SDK) |
| `PreToolUse` | TOOL | Tool invocation started, records tool name and input |
| `PostToolUse` | TOOL | Tool invocation completed, records output and duration |
| `Stop` | LLM | Model response completed with input/output values |
| `SubagentStop` | LLM | Subagent response completed |
| `Notification` | CHAIN | System notification event |
| `PermissionRequest` | CHAIN | Permission prompt for tool use |
| `SessionEnd` | CHAIN | Session teardown, state file cleanup |

All spans include `session.id`, `project.name`, `trace.number`, and `openinference.span.kind` attributes.

Spans are sent directly to the configured backend via `send_span()`.

## Agent SDK Compatibility

The plugin works identically with both Claude Code CLI and the Claude Agent SDK. The same hooks and settings are shared — no separate installation or configuration is needed.

The one difference is that the Agent SDK does not fire a `SessionStart` event. The `UserPromptSubmit` hook performs lazy session initialization when it detects no prior session state, so tracing starts automatically on the first prompt.

Hook commands use Python CLI entry points (e.g. `~/.arize/harness/venv/bin/arize-hook-session-start`) written into `~/.claude/settings.json` by the installer. The `plugin.json` also declares hooks for marketplace installs.

## Environment Variables (fallback)

The config file `~/.arize/harness/config.yaml` is the primary and recommended way to configure tracing. The environment variables below serve as a fallback or for overriding specific values at runtime.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Set to `false` to disable tracing (enabled by default) |
| `ARIZE_PROJECT_NAME` | No | Config file / working dir basename | Project name override (prefer `harnesses` config) |
| `ARIZE_USER_ID` | No | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-claude-code.log` | Log file path (empty to disable) |

Backend credentials (`ARIZE_API_KEY`, `ARIZE_SPACE_ID`, `PHOENIX_ENDPOINT`, etc.) can also be set as environment variables and will be used as fallbacks if not configured in `config.yaml`.

### User Identification

Set `user_id` in `~/.arize/harness/config.yaml` to tag all spans with a `user.id` attribute. This is useful for team environments where multiple users share a project:

```yaml
user_id: "alice@example.com"
```

The `ARIZE_USER_ID` environment variable can also be used and takes precedence over the config file. The hook input JSON `user_id` field is used as a final fallback.

## Usage

Once configured, start a Claude Code session. Spans are sent automatically:

```bash
# Validate output without sending
ARIZE_DRY_RUN=true claude

# Enable verbose logging
ARIZE_VERBOSE=true claude
```

Check the hook log file for diagnostics:

```bash
tail -f /tmp/arize-claude-code.log
```

## Directory Structure

```
claude-code-tracing/
  .claude-plugin/plugin.json   Hook registrations (9 hooks, CLI entry points)
  skills/                      Claude Code skill for guided setup
  README.md
```

Setup is provided by the `arize-setup-claude` CLI entry point (defined in `core/setup/claude.py`).

Hook logic lives in `core/` at the repository root (installed as a Python package):

```
core/
  hooks/claude/
    adapter.py       Claude-specific session resolution, GC, init
    handlers.py      One exported function per Claude Code hook event
  common.py          Shared: span building, direct send, state, logging, IDs
  config.py          YAML config helper
  constants.py       Single source of truth for all paths
  send_arize.py      Arize AX gRPC sender (used by send_span)
```

## Troubleshooting

**Spans not appearing**

1. Verify hooks are registered in `~/.claude/settings.json` under the `hooks` key (each event should have a command pointing to the corresponding CLI entry point)
2. Check the hook log: `tail -20 /tmp/arize-claude-code.log`
3. Test with dry run: `ARIZE_DRY_RUN=true ARIZE_VERBOSE=true claude`
4. Verify backend is reachable (Phoenix: `curl -s http://localhost:6006/healthz`)
5. To disable tracing, set `ARIZE_TRACE_ENABLED=false` in your environment

**Session state issues**

State files are stored in `~/.arize/harness/state/claude-code/`. To reset:

```bash
rm -rf ~/.arize/harness/state/claude-code/state_*.yaml
```

Stale PID-based state files are garbage-collected automatically.

**User ID not appearing on spans**

Verify `ARIZE_USER_ID` is set in `.claude/settings.local.json` under the `env` key, or export it in your shell before starting Claude Code. Run with `ARIZE_VERBOSE=true` to confirm the value is read during session initialization.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Tracing Architecture](../docs/TRACING_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
