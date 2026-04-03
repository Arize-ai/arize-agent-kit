---
name: setup-cursor-tracing
description: Set up and configure Arize tracing for Cursor IDE sessions. Use when users want to set up tracing, configure Arize AX or Phoenix for Cursor, enable/disable tracing, or troubleshoot tracing issues. Triggers on "set up cursor tracing", "configure Arize for Cursor", "configure Phoenix for Cursor", "enable cursor tracing", "setup-cursor-tracing", or any request about connecting Cursor to Arize or Phoenix for observability.
---

# Setup Cursor Tracing

Configure OpenInference tracing for Cursor IDE sessions to Arize AX (cloud) or Phoenix (self-hosted). Spans are exported through a shared background collector -- no backend-specific dependencies are needed in the user's environment.

## How to Use This Skill

**This skill follows a decision tree workflow.** Start by asking the user where they are in the setup process:

1. **Do they already have credentials?**
   - Yes -> Jump to [Configure Settings](#configure-settings)
   - No -> Continue to step 2

2. **Which backend do they want to use?**
   - Phoenix (self-hosted) -> Go to [Set Up Phoenix](#set-up-phoenix)
   - Arize AX (cloud) -> Go to [Set Up Arize AX](#set-up-arize-ax)

3. **Are they troubleshooting?**
   - Yes -> Jump to [Troubleshoot](#troubleshoot)

**Important:** Only follow the relevant path for the user's needs. Don't go through all sections.

## Set Up Phoenix

Phoenix is self-hosted. No Python dependencies are needed for tracing -- the shared collector handles export.

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

Then proceed to [Configure Settings](#configure-settings) with the Phoenix endpoint.

## Set Up Arize AX

Arize AX is available as a SaaS platform or as an on-prem deployment. Users need an account, a space, and an API key.

**First, ask the user: "Are you using the Arize SaaS platform or an on-prem instance?"**

- **SaaS** -> Uses the default endpoint (`otlp.arize.com:443`). Continue below.
- **On-prem** -> The user will need to provide their custom OTLP endpoint (e.g., `otlp.mycompany.arize.com:443`). Ask for it and note it for the [Configure Settings](#configure-settings) step.

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

Both `api_key` and `space_id` are required for the shared config.

**No Python dependencies are needed.** The shared background collector bundles its own gRPC dependencies for Arize AX export. Users do not need to install `opentelemetry-proto` or `grpcio`.

Then proceed to [Configure Settings](#configure-settings). If the user is on an on-prem instance, remind them to provide their custom endpoint.

## Configure Settings

**Important:** Users must run this setup before tracing will work. The shared collector requires `~/.arize/harness/config.yaml` to exist -- it will not start without it.

### Ask the user for:

1. **Backend choice**: Phoenix or Arize AX
2. **Credentials** (only if no existing config):
   - Phoenix: endpoint URL (default: `http://localhost:6006`), optional API key
   - Arize AX: API key and Space ID
3. **OTLP Endpoint** (Arize AX only, optional): For hosted Arize instances using a custom endpoint. Defaults to `otlp.arize.com:443`.
4. **Project name** (optional): defaults to `"cursor"`, stored under `harnesses.cursor.project_name`
5. **User ID** (optional): Set `ARIZE_USER_ID` env var to identify spans by user (useful for teams)

### Write the shared collector config

The config file at `~/.arize/harness/config.yaml` is the single source of truth for backend credentials and per-harness project naming. Create the directory structure if needed: `mkdir -p ~/.arize/harness/{bin,run,logs,state/cursor}`

**Important: read-merge-write.** If `~/.arize/harness/config.yaml` already exists, read it first, then merge in the new or updated fields (e.g., add/update the `harnesses.cursor` entry) while preserving existing backend credentials. Only prompt for backend credentials if no existing config is found.

**Phoenix:**
```yaml
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "phoenix"
  phoenix:
    endpoint: "<endpoint>"
    api_key: ""
harnesses:
  cursor:
    project_name: "cursor"
```

**Arize AX:**
```yaml
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "arize"
  arize:
    endpoint: "otlp.arize.com:443"
    api_key: "<key>"
    space_id: "<id>"
harnesses:
  cursor:
    project_name: "cursor"
```

If the user has a custom OTLP endpoint, set it in `backend.arize.endpoint`.

### Activate Cursor hooks

Cursor uses a `.cursor/hooks.json` file in the project root to route hook events to the handler script. The handler lives in the arize-agent-kit installation at `~/.arize/harness/cursor-tracing/hooks/hook-handler.sh`.

Create `.cursor/hooks.json` in the user's project (or merge into it if it already exists):

```json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "afterAgentResponse": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "afterAgentThought": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "beforeShellExecution": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "afterShellExecution": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "beforeMCPExecution": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "afterMCPExecution": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "beforeReadFile": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "afterFileEdit": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "stop": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "beforeTabFileRead": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }],
    "afterTabFileEdit": [{ "command": "bash ~/.arize/harness/cursor-tracing/hooks/hook-handler.sh" }]
  }
}
```

If the user already has a `.cursor/hooks.json` with other hooks, merge the Arize entries into the existing arrays for each event.

### Validate

1. **Collector running**: Run `curl -sf http://127.0.0.1:4318/health` to check the shared collector. If not running, start it:
   ```bash
   source ~/.arize/harness/core/collector_ctl.sh && collector_start
   ```
2. **Phoenix** (if applicable): Run `curl -sf <endpoint>/v1/traces >/dev/null` to check connectivity.
3. **Hooks active**: Verify `.cursor/hooks.json` exists in the project root and contains the Arize hook entries.

### Confirm

Tell the user:
- Shared collector config saved to `~/.arize/harness/config.yaml`
- Cursor hooks activated via `.cursor/hooks.json`
- The shared collector must be running for spans to be exported (check with `curl -sf http://127.0.0.1:4318/health`)
- After saving, open a new Cursor session and traces will appear in their Phoenix UI or Arize AX dashboard under the project name
- Mention `ARIZE_DRY_RUN=true` to test without sending data (set as env var before launching Cursor)
- Mention `ARIZE_VERBOSE=true` for debug output
- Hook logs are written to `/tmp/arize-cursor.log`
- Collector logs are written to `~/.arize/harness/logs/collector.log`

## Hook Events

Cursor fires 12 hook events. Here's what each one traces:

| Event | Span Name | Kind | Description |
|-------|-----------|------|-------------|
| `beforeSubmitPrompt` | User Prompt | CHAIN | Root span for the turn; captures prompt text, model, attachments |
| `afterAgentResponse` | Agent Response | LLM | LLM response text and model name |
| `afterAgentThought` | Agent Thinking | CHAIN | Agent thinking/reasoning text |
| `beforeShellExecution` | (state push) | -- | Saves command and start time to disk state |
| `afterShellExecution` | Shell | TOOL | Merged span with command input and output |
| `beforeMCPExecution` | (state push) | -- | Saves tool name, input, and start time |
| `afterMCPExecution` | MCP: {tool} | TOOL | Merged span with tool input and result |
| `beforeReadFile` | Read File | TOOL | File path being read |
| `afterFileEdit` | File Edit | TOOL | File path and edit details |
| `beforeTabFileRead` | Tab Read File | TOOL | Tab file read (file path) |
| `afterTabFileEdit` | Tab File Edit | TOOL | Tab file edit (path and edits) |
| `stop` | Agent Stop | CHAIN | Turn completion status and loop count |

Shell and MCP events use a disk-backed state stack to merge before/after context into single spans with both input and output.

## Troubleshoot

Common issues and fixes:

| Problem | Fix |
|---------|-----|
| Traces not appearing | Verify collector is running: `curl -sf http://127.0.0.1:4318/health`. Check hook log: `tail -20 /tmp/arize-cursor.log` |
| Collector not running | Start it: `source ~/.arize/harness/core/collector_ctl.sh && collector_start`. Check logs: `~/.arize/harness/logs/collector.log` |
| Collector config missing | Run `install.sh cursor` or create `~/.arize/harness/config.yaml` manually (include `harnesses.cursor` section) |
| Phoenix unreachable | Verify Phoenix is running: `curl -sf <endpoint>/v1/traces` |
| Hooks not firing | Verify `.cursor/hooks.json` exists in the project root and paths are correct (use absolute paths) |
| Shell/MCP spans missing input | State push failed -- check that `~/.arize/harness/state/cursor/` is writable |
| Want to test without sending | Set `ARIZE_DRY_RUN=true` env var before launching Cursor |
| Want verbose logging | Set `ARIZE_VERBOSE=true` env var before launching Cursor |
| Wrong project name | Set `harnesses.cursor.project_name` in `~/.arize/harness/config.yaml` (default: `"cursor"`) |
| Spans missing user attribution | Set `ARIZE_USER_ID` env var before launching Cursor |
