---
name: setup-claude-code-tracing
description: Set up and configure Arize tracing for Claude Code sessions or Agent SDK applications. Use when users want to set up tracing, configure Arize AX or Phoenix, create a new Arize project, get an API key, enable/disable tracing, or troubleshoot tracing issues. Triggers on "set up tracing", "configure Arize", "configure Phoenix", "enable tracing", "setup-claude-code-tracing", "create Arize project", "get Arize API key", "agent sdk tracing", or any request about connecting Claude Code or the Agent SDK to Arize or Phoenix for observability.
---

# Setup Tracing

Configure OpenInference tracing for Claude Code sessions or Agent SDK applications to Arize AX (cloud) or Phoenix (self-hosted).

## How to Use This Skill

**This skill follows a decision tree workflow.** Start by asking the user where they are in the setup process:

1. **Are they using the Claude Code CLI or the Agent SDK?**
   - CLI → Continue to step 2
   - Agent SDK (Python or TypeScript) → Go to [Agent SDK Setup](#agent-sdk-setup)

2. **Do they already have credentials?**
   - Yes → Jump to [Configure Settings](#configure-settings)
   - No → Continue to step 3

3. **Which backend do they want to use?**
   - Phoenix (self-hosted) → Go to [Set Up Phoenix](#set-up-phoenix)
   - Arize AX (cloud) → Go to [Set Up Arize AX](#set-up-arize-ax)

4. **Are they troubleshooting?**
   - Yes → Jump to [Troubleshoot](#troubleshoot)

**Important:** Only follow the relevant path for the user's needs. Don't go through all sections.

## Set Up Phoenix

Phoenix is self-hosted and requires no Python dependencies for tracing.

### Install Phoenix

Ask if they already have Phoenix running. If not, walk through:

```bash
# Option A: pip
pip install arize-phoenix && phoenix serve

# Option B: Docker
docker run -p 6006:6006 arizephoenix/phoenix:latest
```

Phoenix UI will be available at `http://localhost:6006`. Confirm it's running:

```bash
curl -sf http://localhost:6006/v1/traces >/dev/null && echo "Phoenix is running" || echo "Phoenix not reachable"
```

Then proceed to [Configure Local Project](#configure-local-project) with `PHOENIX_ENDPOINT=http://localhost:6006`.

## Set Up Arize AX

Arize AX is available as a SaaS platform or as an on-prem deployment. Users need an account, a space, and an API key.

**First, ask the user: "Are you using the Arize SaaS platform or an on-prem instance?"**

- **SaaS** → Uses the default endpoint (`otlp.arize.com:443`). Continue below.
- **On-prem** → The user will need to provide their custom OTLP endpoint (e.g., `otlp.mycompany.arize.com:443`). Ask for it and note it for the [Configure Settings](#configure-settings) step where it will be set as `ARIZE_OTLP_ENDPOINT`.

### 1. Create an account

If the user doesn't have an Arize account:
- **SaaS**: Sign up at https://app.arize.com/auth/join
- **On-prem**: Contact their administrator for access to the on-prem instance

### 2. Get Space ID and API key

Walk the user through finding their credentials:
1. Log in to their Arize instance (https://app.arize.com for SaaS, or their on-prem URL)
2. Click **Settings** (gear icon) in the left sidebar
3. The **Space ID** is shown on the Space Settings page
4. Go to the **API Keys** tab
5. Click **Create API Key** or copy an existing one

Both `ARIZE_API_KEY` and `ARIZE_SPACE_ID` are required.

### 3. Install Python dependencies

Arize AX uses gRPC, which requires Python:

```bash
pip install opentelemetry-proto grpcio
```

Verify:
```bash
python3 -c "import opentelemetry; import grpc; print('OK')"
```

Then proceed to [Configure Settings](#configure-settings). If the user is on an on-prem instance, remind them to set `ARIZE_OTLP_ENDPOINT` to their custom endpoint.

## Configure Settings

Before configuring, ask the user:

**"Do you want to configure tracing globally or for this project only?"**
- **Globally** → `~/.claude/settings.json` (applies to all projects)
- **Project-local** → `.claude/settings.local.json` (applies only to this project)

**Recommendation**: Use project-local for different backends per project (e.g., dev Phoenix vs prod Arize).

### Ask the user for:

1. **Scope** (if not already determined): Global or project-local
2. **Backend choice**: Phoenix or Arize AX
3. **Credentials**:
   - Phoenix: endpoint URL (default: `http://localhost:6006`), optional API key
   - Arize AX: API key and Space ID
4. **OTLP Endpoint** (Arize AX only, optional): For hosted Arize instances using a custom endpoint. Defaults to `otlp.arize.com:443` if not set.
5. **Project name** (optional): defaults to workspace name

### Write the config

**Determine the config file:**
- Global: `~/.claude/settings.json`
- Project-local: `.claude/settings.local.json` (create directory if needed: `mkdir -p .claude`)

Read the file (or create `{}` if it doesn't exist), then merge env vars into the `"env"` object.

**Phoenix:**
```json
{
  "env": {
    "PHOENIX_ENDPOINT": "<endpoint>",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

If the user has a Phoenix API key, also set `"PHOENIX_API_KEY": "<key>"`.

**Arize AX:**
```json
{
  "env": {
    "ARIZE_API_KEY": "<key>",
    "ARIZE_SPACE_ID": "<space-id>",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

If the user has a custom OTLP endpoint (e.g., a hosted Arize instance), also set `"ARIZE_OTLP_ENDPOINT": "<host:port>"`. Defaults to `otlp.arize.com:443` if not set.

If a custom project name was provided, also set `"ARIZE_PROJECT_NAME": "<name>"`.

**Example workflow:**
```bash
# For project-local
mkdir -p .claude
echo '{}' > .claude/settings.local.json
# Then use jq or editor to add env vars
```

### Validate

**Phoenix**: Run `curl -sf <endpoint>/v1/traces >/dev/null` to check connectivity. Warn if unreachable but note it may just not be running yet.

**Arize AX**: Run `python3 -c "import opentelemetry; import grpc"` to check dependencies. If it fails, tell the user to run `pip install opentelemetry-proto grpcio`.

### Confirm

Tell the user:
- Configuration saved to the chosen file:
  - Global: `~/.claude/settings.json`
  - Project-local: `.claude/settings.local.json`
- Restart the Claude Code session for tracing to take effect
- After restarting, traces will appear in their Phoenix UI or Arize AX dashboard under the project name
- Mention `ARIZE_DRY_RUN=true` to test without sending data
- Mention `ARIZE_VERBOSE=true` for debug output
- Logs are written to `/tmp/arize-claude-code.log`

**Note**: Project-local settings override global settings for the same variables.

## Agent SDK Setup

For users building with the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) (Python or TypeScript), the tracing plugin loads as a local plugin. **This section provides code and configuration for the developer to add to their application** — the agent cannot set this up at runtime since plugin paths and settings must be configured before the SDK session starts.

**Important:** The user must use `ClaudeSDKClient` — the standalone `query()` function does **not** support hooks, so tracing will not work with it.

### How to guide the user

When a user asks about Agent SDK tracing setup, provide them with the steps below to integrate into their own code. Do NOT try to execute `export` commands or modify their application source — instead, give them the snippets to copy.

### 1. Choose a backend

Ask the user which backend they want. If they don't have credentials yet, walk them through [Set Up Phoenix](#set-up-phoenix) or [Set Up Arize AX](#set-up-arize-ax) first, then return here.

### 2. Get the plugin path

Ask the user: **"Have you already installed this plugin via the Claude Code CLI?"**

**If yes (already installed via CLI):** They can reference it from the CLI cache. Tell them to check `~/.claude/plugins/installed_plugins.json` for the exact path, or use:
```
~/.claude/plugins/cache/arize-claude-plugin/claude-code-tracing/1.0.0
```

**If no:** Tell them to clone the repo into their project:
```bash
git clone https://github.com/Arize-ai/arize-claude-code-plugin.git
```
The plugin path will be `./arize-claude-code-plugin/plugins/claude-code-tracing`

For Arize AX, they also need Python dependencies:
```bash
pip install opentelemetry-proto grpcio
```

### 3. Create a settings file

The Agent SDK spawns a Claude Code subprocess that does **not** inherit the user's shell environment variables. Tracing credentials must be passed via a settings file referenced in the `ClaudeAgentOptions`.

Tell the user to create a `settings.local.json` file (or similar) with their tracing credentials:

**Phoenix:**
```json
{
  "env": {
    "PHOENIX_ENDPOINT": "http://localhost:6006",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

If the user has a Phoenix API key, also include `"PHOENIX_API_KEY": "<key>"`.

**Arize AX:**
```json
{
  "env": {
    "ARIZE_API_KEY": "your-api-key",
    "ARIZE_SPACE_ID": "your-space-id",
    "ARIZE_TRACE_ENABLED": "true"
  }
}
```

Optional env vars that can also be added to the settings file:
- `ARIZE_OTLP_ENDPOINT`: Custom OTLP gRPC endpoint for hosted Arize instances (default: `otlp.arize.com:443`)
- `ARIZE_PROJECT_NAME`: Custom project name (default: workspace directory name)
- `ARIZE_DRY_RUN`: Set to `"true"` to test without sending data
- `ARIZE_VERBOSE`: Set to `"true"` for debug output

### 4. Add the plugin to their code

Give the user the appropriate snippet to add to their application. They must use `ClaudeSDKClient` and pass both the plugin path (from step 2) and the settings file (from step 3):

**Python:**
```python
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

PLUGIN_PATH = "./arize-claude-code-plugin/plugins/claude-code-tracing"  # or CLI cache path

options = ClaudeAgentOptions(
    plugins=[{"type": "local", "path": PLUGIN_PATH}],
    settings="./settings.local.json",
)
async with ClaudeSDKClient(options=options) as client:
    await client.query("Your prompt here")
    async for message in client.receive_response():
        print(message)
```

**TypeScript:**
```typescript
import { ClaudeSDKClient } from "@anthropic-ai/claude-agent-sdk";

const PLUGIN_PATH = "./arize-claude-code-plugin/plugins/claude-code-tracing"; // or CLI cache path

const client = new ClaudeSDKClient({
  plugins: [{ type: "local", path: PLUGIN_PATH }],
  settings: "./settings.local.json",
});

await client.connect();
await client.query("Your prompt here");
for await (const message of client.receiveResponse()) {
  console.log(message);
}
await client.close();
```

### 5. Validate

Tell the user to add `"ARIZE_DRY_RUN": "true"` to their settings file to verify hooks fire without sending data, and check `/tmp/arize-claude-code.log` for output.

### Agent SDK Compatibility

- **Important**: You must use `ClaudeSDKClient` — the standalone `query()` function does not support hooks and tracing will not work.
- **TypeScript SDK**: All 9 hooks are supported — full parity with the CLI.
- **Python SDK**: `SessionStart`, `SessionEnd`, `Notification`, and `PermissionRequest` hooks are not available. The plugin handles this automatically — session state is lazily initialized on the first `UserPromptSubmit`. Core tracing (LLM spans, tool spans, subagent spans) works fully.
- Tracing credentials must be passed via a settings file in `ClaudeAgentOptions` — the SDK subprocess does not inherit shell environment variables.
- If the user is **troubleshooting** an existing Agent SDK setup, you can help by checking log files (`/tmp/arize-claude-code.log`), verifying the settings file contains the correct env vars, or enabling dry-run mode.

## Troubleshoot

Common issues and fixes:

| Problem | Fix |
|---------|-----|
| Traces not appearing | Check `ARIZE_TRACE_ENABLED` is `"true"` in `~/.claude/settings.json` |
| Phoenix unreachable | Verify Phoenix is running: `curl -sf <endpoint>/v1/traces` |
| "Python with opentelemetry not found" | Run `pip install opentelemetry-proto grpcio` |
| No output in terminal | Hook stderr is discarded by Claude Code; check `/tmp/arize-claude-code.log` |
| Want to test without sending | Set `ARIZE_DRY_RUN` to `"true"` in env config |
| Want verbose logging | Set `ARIZE_VERBOSE` to `"true"` in env config |
| Wrong project name | Set `ARIZE_PROJECT_NAME` in env config (default: `claude-code`) |
