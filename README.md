# Arize Claude Code Plugins

Official Claude Code plugins from Arize AI for enhanced observability and platform integration.

## What's Included

This repository contains the following plugins:

1. **[claude-code-tracing](#claude-code-tracing)** — Automatic tracing of Claude Code sessions to Arize AX or Phoenix
2. **[arize-platform](#arize-platform)** — Skills for managing projects, datasets, and working with the Arize AX CLI

## Installation

Add the marketplace from repo owner/name:

```bash
claude plugin marketplace add Arize-ai/arize-claude-code-plugin
```

Then install the plugins:

```bash
claude plugin install claude-code-tracing@arize-claude-plugin
claude plugin install arize-platform@arize-claude-plugin
```

### Claude Agent SDK

The tracing plugin works with the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) (Python and TypeScript). Load it as a local plugin by pointing to the plugin directory.

> **Important:** You must use `ClaudeSDKClient` — the standalone `query()` function does **not** support hooks, so tracing will not work with it.

#### Option A: Already installed via CLI (easiest)

If you already installed the plugin with `claude plugin add`, reference it from the CLI cache:

```python
# Python
plugins=[{"type": "local", "path": "~/.claude/plugins/cache/arize-claude-plugin/claude-code-tracing/1.0.0"}]
```

```typescript
// TypeScript
plugins: [{ type: "local", path: "~/.claude/plugins/cache/arize-claude-plugin/claude-code-tracing/1.0.0" }]
```

> **Tip:** Check `~/.claude/plugins/installed_plugins.json` for the exact path and version on your machine.

#### Option B: Clone the repo

If you haven't installed via the CLI, clone the repo into your project:

```bash
git clone https://github.com/Arize-ai/arize-claude-code-plugin.git
```

Then reference the plugin directory:

```python
# Python
plugins=[{"type": "local", "path": "./arize-claude-code-plugin/plugins/claude-code-tracing"}]
```

```typescript
// TypeScript
plugins: [{ type: "local", path: "./arize-claude-code-plugin/plugins/claude-code-tracing" }]
```
Make sure to also pass in the path to the `settings.json` file. 
```python
# Python
settings="./settings.local.json"
```

```typescript
// TypeScript
settingSources: ["local"] // only .claude/settings.local.json
```

#### Full example

**Python:**
```python
import asyncio
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient


async def main():
    options = ClaudeAgentOptions(
        plugins=[{"type": "local", "path": "./arize-claude-code-plugin/plugins/claude-code-tracing"}],
        settings="./settings.local.json"
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("PROMPT_GOES_HERE")
        async for message in client.receive_response():
            print(message)

asyncio.run(main())
```

**TypeScript:**
```typescript
import { ClaudeSDKClient } from "@anthropic-ai/claude-agent-sdk";

const client = new ClaudeSDKClient({
  plugins: [{ type: "local", path: "./arize-claude-code-plugin/plugins/claude-code-tracing" }],
  settingSources: ["local"],
});

await client.connect();
await client.query("PROMPT_GOES_HERE");
for await (const message of client.receiveResponse()) {
  console.log(message);
}
await client.close();
```

#### Agent SDK Compatibility Notes

The plugin is fully compatible with the Agent SDK with some caveats:

- **TypeScript SDK** — All 9 hooks are supported. Full feature parity with the CLI.
- **Python SDK** — `SessionStart`, `SessionEnd`, `Notification`, and `PermissionRequest` hooks are not fired by the Python SDK. The plugin handles this gracefully:
  - Session initialization happens lazily on the first `UserPromptSubmit` if `SessionStart` didn't fire
  - Stale state files are garbage-collected periodically by the `Stop` hook
  - Notification and permission request spans are simply not created (non-critical, informational only)

---

# Claude Code Tracing

Trace your Claude Code sessions to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) with OpenInference spans.

## Features

- **9 Hooks** — Most comprehensive tracing coverage available
  - SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStop, Notification, PermissionRequest, SessionEnd
- **Dual Target Support** — Send traces to Arize AX (cloud) or Phoenix (self-hosted)
- **OpenInference Format** — Standard span format compatible with any OpenInference tool
- **Guided Setup Skill** — `/setup-claude-code-tracing` walks you through configuration
- **DX Features** — Dry run mode, verbose output, session summaries
- **Automatic Cost Tracking** — Phoenix/Arize calculate costs from token counts automatically
- **Minimal Dependencies**
  - Phoenix: Pure bash (`jq` + `curl` only)
  - Arize AX: Requires Python with `opentelemetry-proto` and `grpcio`

## Configuration

### Quick Setup

Configure tracing from within Claude Code:

```
/setup-claude-code-tracing
```

This walks you through choosing a backend (Phoenix or Arize AX), collecting credentials, writing the config, and validating the setup.

### Manual Configuration

Add to your project's `.claude/settings.local.json`:

**For Phoenix (self-hosted) — No Python required:**

```json
{
  "env": {
    "PHOENIX_ENDPOINT": "http://localhost:6006",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

If your Phoenix instance requires authentication, add the API key:

```json
{
  "env": {
    "PHOENIX_ENDPOINT": "http://localhost:6006",
    "PHOENIX_API_KEY": "your-phoenix-api-key",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

**For Arize AX (cloud) — Requires Python:**

First install dependencies:
```bash
pip install opentelemetry-proto grpcio
```

Then configure:
```json
{
  "env": {
    "ARIZE_API_KEY": "your-api-key",
    "ARIZE_SPACE_ID": "your-space-id",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

For on-prem Arize instances, also set the OTLP endpoint:
```json
{
  "env": {
    "ARIZE_API_KEY": "your-api-key",
    "ARIZE_SPACE_ID": "your-space-id",
    "ARIZE_OTLP_ENDPOINT": "otlp.your-instance.arize.com:443",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_API_KEY` | For AX | - | Arize AX API key |
| `ARIZE_SPACE_ID` | For AX | - | Arize AX space ID |
| `ARIZE_OTLP_ENDPOINT` | No | `otlp.arize.com:443` | OTLP gRPC endpoint (for on-prem Arize instances) |
| `PHOENIX_ENDPOINT` | For Phoenix | `http://localhost:6006` | Phoenix collector URL |
| `PHOENIX_API_KEY` | No | - | Phoenix API key for authentication |
| `ARIZE_PROJECT_NAME` | No | `claude-code` | Project name in Arize/Phoenix |
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable/disable tracing |
| `ARIZE_DRY_RUN` | No | `false` | Print spans instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-claude-code.log` | Log file path (set empty to disable) |

## Usage

Once installed and configured, tracing happens automatically. After each session, you'll see:

```
[arize] Session complete: 3 traces, 12 tools
[arize] View in Arize/Phoenix: session.id = abc123-def456-...
```

### Dry Run Mode

Test without sending data:

```bash
ARIZE_DRY_RUN=true claude
```

### Verbose Mode

See what's being captured:

```bash
ARIZE_VERBOSE=true claude
```

## Hooks Supported

| Hook | Description | Captured Data | SDK Support |
|------|-------------|---------------|-------------|
| `SessionStart` | Session begins | Session ID, project name, timestamps | CLI, TS |
| `UserPromptSubmit` | User sends prompt | Trace ID, prompt preview, transcript position | CLI, TS, Python |
| `PreToolUse` | Before tool executes | Tool ID, start time | CLI, TS, Python |
| `PostToolUse` | After tool executes | Tool name, input, output, duration, tool-specific metadata | CLI, TS, Python |
| `Stop` | Claude finishes responding | Model, token counts, input/output text | CLI, TS, Python |
| `SubagentStop` | Subagent completes | Agent type, model, token counts, output | CLI, TS, Python |
| `Notification` | System notification | Title, message, notification type | CLI, TS |
| `PermissionRequest` | Permission requested | Permission type, tool name | CLI, TS |
| `SessionEnd` | Session closes | Trace count, tool count | CLI, TS |

**SDK Support key:** CLI = Claude Code CLI, TS = TypeScript Agent SDK, Python = Python Agent SDK

## Troubleshooting

### Traces not appearing

1. Check `ARIZE_TRACE_ENABLED` is `true`
2. Verify API key/endpoint is correct
3. Check the log file: `tail -f /tmp/arize-claude-code.log`
4. Run with `ARIZE_VERBOSE=true` to enable verbose logging
5. Run with `ARIZE_DRY_RUN=true` to test locally

### Viewing hook logs

Claude Code discards hook stderr, so verbose output isn't visible in the terminal. Logs are written to `/tmp/arize-claude-code.log` by default:

```bash
tail -f /tmp/arize-claude-code.log
```

To change the log location, set `ARIZE_LOG_FILE` in your settings. Set to empty string to disable file logging.

### Arize AX: "Python with opentelemetry not found"

Install the required Python packages:
```bash
pip install opentelemetry-proto grpcio
```

Note: Phoenix does not require Python — it uses the REST API directly.

---

# Arize Platform

Skills for working with the Arize AX platform, including CLI setup, project management, and dataset management.

## Features

- **CLI Setup** — Install and configure the Arize AX CLI
- **Project Management** — Create, list, get, and delete projects
- **Dataset Management** — Create, list, export, and delete datasets
- **Multiple Profiles** — Support for dev/staging/prod environments
- **Environment Variable Management** — Persist credentials securely
- **ID Extraction** — Find and use project/dataset IDs programmatically

## Skills

### `/setup-arize-cli`

Install and configure the Arize AX CLI for interacting with the Arize AI platform.

**Use when:**
- Installing the `ax` CLI for the first time
- Setting up authentication and API keys
- Creating configuration profiles
- Switching between environments
- Troubleshooting CLI setup issues

**Key capabilities:**
- Interactive installation guide
- Simple and advanced configuration modes
- Environment variable persistence
- Shell completion setup
- Multi-profile management

### `/arize-projects`

Manage projects in Arize AI using the `ax` CLI.

**Use when:**
- Listing all projects in a space
- Getting project details by name or ID
- Creating new projects
- Deleting projects
- Working with projects across multiple environments

**Key capabilities:**
- Project CRUD operations
- Name-to-ID resolution (find project IDs by name)
- Cursor-based pagination
- Profile-specific operations

### `/arize-datasets`

Manage datasets in Arize AI using the `ax` CLI.

**Use when:**
- Listing all datasets
- Getting dataset details by name or ID
- Creating datasets from CSV/JSON/Parquet files
- Exporting dataset data
- Deleting datasets
- Working with datasets across multiple environments

**Key capabilities:**
- Dataset CRUD operations
- Format conversion (JSON, CSV, Parquet)
- ID extraction by name
- Pagination for large result sets
- Profile-specific operations

## Uninstall

**Plugin marketplace:**

```bash
# Uninstall tracing plugin
/plugin uninstall claude-code-tracing@arize-claude-plugin

# Uninstall platform plugin
/plugin uninstall arize-platform@arize-claude-plugin

# Or uninstall all
claude plugin remove arize-claude-plugin
```

**Alternative: Manual uninstall (tracing only):**

For plugins installed with `./install.sh`:

```bash
cd arize-claude-code-plugin
./install.sh uninstall
```

## License

MIT

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)
- [Arize AX CLI](https://github.com/Arize-ai/arize-ax-cli)
