# Claude Code Tracing Plugin

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for **Claude Code CLI** and the **Claude Agent SDK**. Every prompt, tool call, model response, and session lifecycle event is captured as a span and exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) via a shared background collector.

## Features

- 9 hook-based span types covering the full Claude Code session lifecycle
- Works with both Claude Code CLI and the Python Agent SDK
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

The collector is installed and started automatically by `install.sh`. See [COLLECTOR_ARCHITECTURE.md](../COLLECTOR_ARCHITECTURE.md) for the full design.

## Installation

### Claude Code Marketplace (recommended)

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

### Curl installer

```bash
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash
```

### Manual (Agent SDK)

Clone the repository and point your Agent SDK project at the plugin directory:

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
# In your SDK config, set the plugin path to:
#   /path/to/arize-agent-kit/claude-code-tracing
```

## Configuration

Run the interactive setup after installation:

```bash
bash claude-code-tracing/scripts/setup.sh
```

The setup script will:

1. Ask whether to store tracing env vars globally in `~/.claude/settings.json` or project-locally in `.claude/settings.local.json`
2. Ask which backend to configure: Phoenix or Arize AX
3. Write backend credentials and harness settings to the shared config at `~/.arize/harness/config.json`
4. Write the required env vars into the selected Claude settings file
5. Optionally add `ARIZE_USER_ID` for span attribution

### Shared Config File

The single source of truth for backend credentials, collector settings, and per-harness configuration is `~/.arize/harness/config.json`. Each harness (e.g. `claude-code`, `codex`) gets its own entry under `harnesses` with a dedicated `project_name`:

```json
{
  "collector": { "host": "127.0.0.1", "port": 4318 },
  "backend": {
    "target": "phoenix",
    "phoenix": { "endpoint": "...", "api_key": "..." }
  },
  "harnesses": {
    "claude-code": { "project_name": "claude-code" }
  }
}
```

Environment variables (see below) still work as a fallback for the legacy direct-send path, but the config file is the recommended way to manage all settings.

Or configure manually by adding environment variables to either `~/.claude/settings.json` or `.claude/settings.local.json`:

### Phoenix (self-hosted)

```json
{
  "env": {
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

Backend credentials and harness project names are stored in `~/.arize/harness/config.json` and read by the shared collector -- not by hooks directly.

Requires: `jq`, `curl`. No Python packages needed in the user environment.

### Arize AX (cloud)

```json
{
  "env": {
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

Backend credentials (`api_key`, `space_id`) and harness project names are stored in `~/.arize/harness/config.json` and read by the shared collector.

Requires: `jq`, `curl`. No Python packages needed in the user environment -- the collector bundles its own gRPC dependencies.

## Hooks

The plugin registers 9 Claude Code hooks. Each hook creates one OpenInference span:

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

The plugin works with the Claude Agent SDK (Python) with one difference: the SDK does not fire a `SessionStart` event. The `UserPromptSubmit` hook performs lazy session initialization when it detects no prior session state.

Hook commands in `plugin.json` use `${CLAUDE_PLUGIN_ROOT}` so the plugin directory can be located anywhere on disk.

## Environment Variables (fallback)

The config file `~/.arize/harness/config.json` is the primary and recommended way to configure tracing. The environment variables below serve as a fallback for the legacy direct-send path or for overriding specific values at runtime.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_PROJECT_NAME` | No | Config file / working dir basename | Project name override (prefer `harnesses` config) |
| `ARIZE_USER_ID` | No | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-claude-code.log` | Log file path (empty to disable) |
| `ARIZE_COLLECTOR_HOST` | No | `127.0.0.1` | Shared collector listen address |
| `ARIZE_COLLECTOR_PORT` | No | `4318` | Shared collector listen port |

Backend credentials (`ARIZE_API_KEY`, `ARIZE_SPACE_ID`, `PHOENIX_ENDPOINT`, etc.) and project names are configured in the shared config file `~/.arize/harness/config.json` and read by the collector. They do not need to be set as environment variables in Claude settings.

### User Identification

Set `ARIZE_USER_ID` to tag all spans with a `user.id` attribute. This is useful for team environments where multiple users share a project:

```json
{
  "env": {
    "ARIZE_USER_ID": "alice@example.com"
  }
}
```

The interactive setup (`scripts/setup.sh`) prompts for this value. If not set via the environment variable, the plugin also checks for a `user_id` field in the hook input JSON.

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
  hooks/common.sh              Adapter: PID-based state, session resolution, GC
  hooks/session_start.sh       SessionStart hook
  hooks/user_prompt_submit.sh  UserPromptSubmit hook (with lazy init)
  hooks/pre_tool_use.sh        PreToolUse hook
  hooks/post_tool_use.sh       PostToolUse hook
  hooks/stop.sh                Stop hook
  hooks/subagent_stop.sh       SubagentStop hook
  hooks/notification.sh        Notification hook
  hooks/permission_request.sh  PermissionRequest hook
  hooks/session_end.sh         SessionEnd hook
  scripts/setup.sh             Interactive configuration wizard
  skills/                      Claude Code skill for guided setup
```

Shared logic lives in `core/` at the repository root:

```
core/common.sh         Env vars, logging, state primitives, span building, local submission
core/collector.py      Shared background collector/exporter
core/collector_ctl.sh  Collector lifecycle management (start/stop/status/ensure)
```

## Troubleshooting

**Spans not appearing**

1. Check that `ARIZE_TRACE_ENABLED` is `true` in your Claude settings
2. Verify the collector is running: `curl -sf http://127.0.0.1:4318/health`
3. If the collector is not running, start it: `source core/collector_ctl.sh && collector_start`
4. Check the hook log: `tail -20 /tmp/arize-claude-code.log`
5. Check the collector log: `tail -20 ~/.arize/harness/logs/collector.log`
6. Test with dry run: `ARIZE_DRY_RUN=true ARIZE_VERBOSE=true claude`

**Collector not running**

1. Verify the shared config exists: `cat ~/.arize/harness/config.json`
2. Start the collector: `source core/collector_ctl.sh && collector_start`
3. Check collector logs for startup errors: `tail -20 ~/.arize/harness/logs/collector.log`

**"jq required" error**

Install jq: `brew install jq` (macOS) or `apt-get install jq` (Linux).

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
