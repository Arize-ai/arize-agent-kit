# Claude Code Tracing Plugin

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for **Claude Code CLI** and the **Claude Agent SDK**. Every prompt, tool call, model response, and session lifecycle event is captured as a span and sent to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Features

- 9 hook-based span types covering the full Claude Code session lifecycle
- Works with both Claude Code CLI and the Python Agent SDK
- Sends to Phoenix (bash + curl, no Python) or Arize AX (gRPC via Python)
- PID-based session isolation with automatic garbage collection
- Lazy session initialization for Agent SDK environments (no `SessionStart` event)
- `ARIZE_USER_ID` support for team-level span attribution
- Dry-run mode for validating span output without sending data

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

Or configure manually by adding environment variables to `.claude/settings.local.json`:

### Phoenix (self-hosted)

```json
{
  "env": {
    "PHOENIX_ENDPOINT": "http://localhost:6006",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

Requires: `jq`, `curl`. No Python needed.

### Arize AX (cloud)

```json
{
  "env": {
    "ARIZE_API_KEY": "<your-api-key>",
    "ARIZE_SPACE_ID": "<your-space-id>",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

Requires: `jq`, `curl`, Python 3 with `opentelemetry-proto` and `grpcio`:

```bash
pip install opentelemetry-proto grpcio
```

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

## Agent SDK Compatibility

The plugin works with the Claude Agent SDK (Python) with one difference: the SDK does not fire a `SessionStart` event. The `UserPromptSubmit` hook performs lazy session initialization when it detects no prior session state.

Hook commands in `plugin.json` use `${CLAUDE_PLUGIN_ROOT}` so the plugin directory can be located anywhere on disk.

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
| `ARIZE_LOG_FILE` | No | `/tmp/arize-claude-code.log` | Log file path (empty to disable) |

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

Check the log file for diagnostics:

```bash
tail -f /tmp/arize-claude-code.log
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
core/common.sh       Env vars, logging, state primitives, span building, sending
core/send_arize.py   Arize AX gRPC sender (Python)
```

## Troubleshooting

**Spans not appearing in Phoenix**

1. Verify Phoenix is running: `curl -s http://localhost:6006/healthz`
2. Check `PHOENIX_ENDPOINT` is set and `ARIZE_TRACE_ENABLED` is `true`
3. Check the log: `tail -20 /tmp/arize-claude-code.log`
4. Test with dry run: `ARIZE_DRY_RUN=true ARIZE_VERBOSE=true claude`

**Spans not appearing in Arize AX**

1. Verify `ARIZE_API_KEY` and `ARIZE_SPACE_ID` are set
2. Ensure Python dependencies are installed: `python3 -c "import opentelemetry; import grpc"`
3. Check `ARIZE_OTLP_ENDPOINT` if using an on-prem deployment
4. Check the log for gRPC errors: `grep ERROR /tmp/arize-claude-code.log`

**"jq required" error**

Install jq: `brew install jq` (macOS) or `apt-get install jq` (Linux).

**Session state issues**

State files are stored in `~/.arize-claude-code/`. To reset:

```bash
rm -rf ~/.arize-claude-code/state_*.json
```

Stale PID-based state files are garbage-collected automatically.

**User ID not appearing on spans**

Verify `ARIZE_USER_ID` is set in `.claude/settings.local.json` under the `env` key, or export it in your shell before starting Claude Code. Run with `ARIZE_VERBOSE=true` to confirm the value is read during session initialization.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Root README](../README.md)
- [Development Guide](../DEVELOPMENT.md)
