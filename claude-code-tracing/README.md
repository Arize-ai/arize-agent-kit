# Claude Code Tracing Plugin

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for **Claude Code CLI** and the **Claude Agent SDK**. Every prompt, tool call, model response, and session lifecycle event is captured as a span and exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) via a shared background collector.

## Features

- 9 hook-based span types covering the full session lifecycle
- Works with both Claude Code CLI and the Claude Agent SDK — same install, same hooks, same config
- Exports to Phoenix or Arize AX through the shared background collector -- no harness-specific exporter dependencies required
- PID-based session isolation with automatic garbage collection
- Lazy session initialization for Agent SDK environments (no `SessionStart` event)
- `ARIZE_USER_ID` support for team-level span attribution
- Dry-run mode for validating span output without sending data

## Architecture

Claude hooks build OpenInference spans locally and submit them to a shared background collector at `http://127.0.0.1:4318/v1/spans`. The collector handles all backend export (Phoenix REST or Arize AX gRPC), retries, and credential management. This means:

- No Python packages (`grpcio`, `opentelemetry-proto`) are needed in the user environment
- No backend-specific transport logic runs inside hook scripts
- All harnesses (Claude, Codex, future) share one export path

```text
Claude hooks --> POST http://127.0.0.1:4318/v1/spans --> Phoenix
                      (shared collector)              \-> Arize AX
```

The collector is installed and started automatically by `install.py`. See [COLLECTOR_ARCHITECTURE.md](../COLLECTOR_ARCHITECTURE.md) for the full design.

## Installation

### Claude Code Marketplace (recommended)

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

### Curl installer

```bash
python3 install.py claude
```

The installer:

1. Clones the repo to `~/.arize/harness/`
2. Writes hook entries directly into `~/.claude/settings.json` (one per lifecycle event)
3. Registers the plugin path in `settings.json` under `plugins`
4. Sets up and starts the shared background collector

Hooks are written as hardcoded commands in `settings.json` rather than relying on `plugin.json` — this is the format that Claude Code fires reliably across all environments.

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

The single source of truth for backend credentials, collector settings, and per-harness configuration is `~/.arize/harness/config.yaml`. Each harness (e.g. `claude-code`, `codex`) gets its own entry under `harnesses` with a dedicated `project_name`:

```yaml
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "phoenix"
  phoenix:
    endpoint: "..."
    api_key: "..."
harnesses:
  claude-code:
    project_name: "claude-code"
```

Environment variables (see below) still work as a fallback for the legacy direct-send path, but the config file is the recommended way to manage all settings.

Backend credentials and harness project names are stored in `~/.arize/harness/config.yaml` and read by the shared collector — not by hooks directly. No environment variables need to be set in Claude settings for tracing to work. Tracing is enabled by default (`ARIZE_TRACE_ENABLED` defaults to `true` in the hook scripts).

No Python packages needed in the user environment — the collector bundles its own gRPC dependencies for Arize AX.

## Hooks

The installer registers 9 Claude Code hooks directly in `~/.claude/settings.json`. Each hook creates one OpenInference span:

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

Spans are submitted locally to the shared collector at `http://127.0.0.1:4318/v1/spans`. The collector forwards them to the configured backend.

## Agent SDK Compatibility

The plugin works identically with both Claude Code CLI and the Claude Agent SDK. The same hooks, settings, and collector are shared — no separate installation or configuration is needed.

The one difference is that the Agent SDK does not fire a `SessionStart` event. The `UserPromptSubmit` hook performs lazy session initialization when it detects no prior session state, so tracing starts automatically on the first prompt.

Hook commands are written with absolute paths by `install.py` into `~/.claude/settings.json`. The `plugin.json` also declares hooks using `${CLAUDE_PLUGIN_ROOT}` for marketplace installs, but the `settings.json` entries are what fire reliably across all environments.

## Environment Variables (fallback)

The config file `~/.arize/harness/config.yaml` is the primary and recommended way to configure tracing. The environment variables below serve as a fallback for the legacy direct-send path or for overriding specific values at runtime.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Set to `false` to disable tracing (enabled by default) |
| `ARIZE_PROJECT_NAME` | No | Config file / working dir basename | Project name override (prefer `harnesses` config) |
| `ARIZE_USER_ID` | No | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-claude-code.log` | Log file path (empty to disable) |
| `ARIZE_COLLECTOR_HOST` | No | `127.0.0.1` | Shared collector listen address |
| `ARIZE_COLLECTOR_PORT` | No | `4318` | Shared collector listen port |

Backend credentials (`ARIZE_API_KEY`, `ARIZE_SPACE_ID`, `PHOENIX_ENDPOINT`, etc.) and project names are configured in the shared config file `~/.arize/harness/config.yaml` and read by the collector. They do not need to be set as environment variables in Claude settings.

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

Check the collector log for backend export diagnostics:

```bash
tail -f ~/.arize/harness/logs/collector.log
```

Verify the collector is running:

```bash
curl -sf http://127.0.0.1:4318/health
```

## Directory Structure

```
claude-code-tracing/
  .claude-plugin/plugin.json   Hook registrations (9 hooks)
  skills/                      Claude Code skill for guided setup
```

Shared logic lives in `core/` at the repository root:

```
core/
  hooks/claude/adapter.py    Adapter: PID-based state, session resolution, GC
  hooks/claude/handlers.py   9 hook entry points
  common.py                  Env vars, logging, state, span building, sending
  collector.py               Shared background collector/exporter
  collector_ctl.py           Collector lifecycle management
```

## Troubleshooting

**Spans not appearing**

1. Verify hooks are registered in `~/.claude/settings.json` under the `hooks` key (each event should have a command pointing to the corresponding hook script)
2. Verify the collector is running: `curl -sf http://127.0.0.1:4318/health`
3. If the collector is not running, start it: `arize-collector-ctl start`
4. Check the hook log: `tail -20 /tmp/arize-claude-code.log`
5. Check the collector log: `tail -20 ~/.arize/harness/logs/collector.log`
6. Test with dry run: `ARIZE_DRY_RUN=true ARIZE_VERBOSE=true claude`
7. To disable tracing, set `ARIZE_TRACE_ENABLED=false` in your environment

**Collector not running**

1. Verify the shared config exists: `cat ~/.arize/harness/config.yaml`
2. Start the collector: `arize-collector-ctl start`
3. Check collector logs for startup errors: `tail -20 ~/.arize/harness/logs/collector.log`

**Session state issues**

State files are stored in `~/.arize/harness/state/claude-code/`. To reset:

```bash
rm -rf ~/.arize/harness/state/claude-code/state_*.json
```

Stale PID-based state files are garbage-collected automatically.

**User ID not appearing on spans**

Verify `ARIZE_USER_ID` is set in `.claude/settings.local.json` under the `env` key, or export it in your shell before starting Claude Code. Run with `ARIZE_VERBOSE=true` to confirm the value is read during session initialization.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Collector Architecture](../COLLECTOR_ARCHITECTURE.md)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
