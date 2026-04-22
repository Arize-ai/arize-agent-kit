---
name: manage-copilot-tracing
description: Set up and configure Arize tracing for GitHub Copilot sessions (VS Code Copilot and Copilot CLI). Use when users want to set up tracing, configure Arize AX or Phoenix for Copilot, enable/disable tracing, or troubleshoot tracing issues. Triggers on "set up copilot tracing", "configure Arize for Copilot", "configure Phoenix for Copilot", "enable copilot tracing", "setup-copilot-tracing", or any request about connecting GitHub Copilot (VS Code or CLI) to Arize or Phoenix for observability.
---

# Setup Copilot Tracing

Configure OpenInference tracing for **GitHub Copilot** sessions (VS Code Copilot and Copilot CLI) to Arize AX (cloud) or Phoenix (self-hosted). Spans are sent directly to the backend from hooks -- no background process or backend-specific dependencies are needed in the user's environment. A single handler auto-detects which platform is calling.

## How to Use This Skill

**This skill follows a decision tree workflow.** Start by asking the user where they are in the setup process:

1. **Which Copilot platform are they using?**
   - VS Code Copilot -> Note this for the [Activate Copilot hooks](#activate-copilot-hooks) step
   - Copilot CLI -> Note this for the [Activate Copilot hooks](#activate-copilot-hooks) step
   - Both -> Configure both hook registrations in the same step

2. **Do they already have credentials?**
   - Yes -> Jump to [Configure Settings](#configure-settings)
   - No -> Continue to step 3

3. **Which backend do they want to use?**
   - Phoenix (self-hosted) -> Go to [Set Up Phoenix](#set-up-phoenix)
   - Arize AX (cloud) -> Go to [Set Up Arize AX](#set-up-arize-ax)

4. **Are they troubleshooting?**
   - Yes -> Jump to [Troubleshoot](#troubleshoot)

**Important:** Only follow the relevant path for the user's needs. Don't go through all sections.

## Set Up Phoenix

Phoenix is self-hosted. No Python dependencies are needed for tracing -- spans are sent directly via `send_span()` using stdlib `urllib`.

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

**No Python dependencies are needed.** Both Phoenix and Arize AX use HTTP/JSON — no additional Python dependencies are needed.

Then proceed to [Configure Settings](#configure-settings). If the user is on an on-prem instance, remind them to provide their custom endpoint.

## Configure Settings

**Important:** Users must run this setup before tracing will work. The `send_span()` function requires `~/.arize/harness/config.yaml` to exist for backend credential resolution.

### Ask the user for:

1. **Platform**: VS Code Copilot, Copilot CLI, or both
2. **Backend choice**: Phoenix or Arize AX
3. **Credentials** (only if no existing config):
   - Phoenix: endpoint URL (default: `http://localhost:6006`), optional API key
   - Arize AX: API key and Space ID
4. **OTLP Endpoint** (Arize AX only, optional): For hosted Arize instances using a custom endpoint. Defaults to `otlp.arize.com:443`.
5. **Project name** (optional): defaults to `"copilot"`, stored under `harnesses.copilot.project_name`
6. **User ID** (optional): Set `ARIZE_USER_ID` env var to identify spans by user (useful for teams)

### Write the config

The config file at `~/.arize/harness/config.yaml` is the single source of truth for backend credentials and per-harness settings. Create the directory structure if needed: `mkdir -p ~/.arize/harness/{bin,run,logs,state/copilot}`

**Important: read-merge-write.** If `~/.arize/harness/config.yaml` already exists, read it first, then merge in the new or updated fields (e.g., add/update the `harnesses.copilot` entry) while preserving existing backend credentials. Only prompt for backend credentials if no existing config is found.

**Phoenix:**
```yaml
backend:
  target: "phoenix"
  phoenix:
    endpoint: "<endpoint>"
    api_key: ""
harnesses:
  copilot:
    project_name: "copilot"
```

**Arize AX:**
```yaml
backend:
  target: "arize"
  arize:
    endpoint: "otlp.arize.com:443"
    api_key: "<key>"
    space_id: "<id>"
harnesses:
  copilot:
    project_name: "copilot"
```

If the user has a custom OTLP endpoint, set it in `backend.arize.endpoint`.

### Activate Copilot hooks

Copilot has two hook registration formats depending on the platform. The handler auto-detects which platform is calling, so both can coexist in the same project.

#### VS Code Copilot

VS Code uses **individual JSON files** in `.github/hooks/`, one per event. Create six files (or merge Arize entries into them if they already exist):

**`.github/hooks/session-start.json`**
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

Register the remaining five events the same way, each in its own file:

| File | `event` | `command` |
|------|---------|-----------|
| `user-prompt.json` | `UserPromptSubmit` | `arize-hook-copilot-user-prompt` |
| `pre-tool.json` | `PreToolUse` | `arize-hook-copilot-pre-tool` |
| `post-tool.json` | `PostToolUse` | `arize-hook-copilot-post-tool` |
| `stop.json` | `Stop` | `arize-hook-copilot-stop` |
| `subagent-stop.json` | `SubagentStop` | `arize-hook-copilot-subagent-stop` |

All `command` values should be absolute paths to the venv binary (e.g. `~/.arize/harness/venv/bin/arize-hook-copilot-<event>`).

#### Copilot CLI

Copilot CLI uses a **single `.github/hooks/hooks.json`** file with version 1 format. Note the `bash` field (not `command`) and camelCase event names:

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

If the user already has a `.github/hooks/hooks.json` with other hooks, merge the Arize entries into the existing arrays for each event.

### Validate

1. **Config exists**: Run `cat ~/.arize/harness/config.yaml` to verify the config file exists and has correct backend credentials.
2. **Phoenix** (if applicable): Run `curl -sf <endpoint>/v1/traces >/dev/null` to check connectivity.
3. **VS Code hooks active**: Verify `.github/hooks/*.json` files exist in the project root (one per event) and each `command` path is the absolute venv binary path.
4. **CLI hooks active**: Verify `.github/hooks/hooks.json` exists with `version: 1`, uses the `bash` field, and camelCase event names.
5. **Quick dry-run test** (optional):
   ```bash
   echo '{"hookEventName":"PreToolUse","tool_name":"test"}' | ARIZE_DRY_RUN=true arize-hook-copilot-pre-tool
   ```

### Confirm

Tell the user:
- Config saved to `~/.arize/harness/config.yaml`
- Copilot hooks activated via `.github/hooks/` (individual files for VS Code, single `hooks.json` for CLI)
- Spans are sent directly to the backend from hooks — no background process needed
- After saving, open a new Copilot session and traces will appear in their Phoenix UI or Arize AX dashboard under the project name
- Mention `ARIZE_DRY_RUN=true` to test without sending data (set as env var before launching Copilot)
- Mention `ARIZE_VERBOSE=true` for debug output
- Hook logs are written to `/tmp/arize-copilot.log`
- CLI mode is "input-only" -- agent response text and token counts are not exposed by Copilot CLI, so those fields will be absent on CLI spans

## Hook Events

Copilot fires 6 events in VS Code mode and 6 events in CLI mode from a single handler. The handler auto-detects the platform by checking for VS Code-only base fields (`sessionId`, `hookEventName`).

| VS Code Event | CLI Event | Span Name | Kind | Description |
|---------------|-----------|-----------|------|-------------|
| `SessionStart` | `sessionStart` | Session Start | CHAIN | Session initialization |
| `UserPromptSubmit` | `userPromptSubmitted` | User Prompt | CHAIN | User prompt text; in CLI mode also flushes the previous deferred turn |
| `PreToolUse` | `preToolUse` | Tool: {name} | TOOL | Tool start; **must print permission response to stdout** |
| `PostToolUse` | `postToolUse` | Tool: {name} | TOOL | Tool result |
| `Stop` | -- | Agent Stop | LLM | VS Code only: per-turn completion; parses `transcript_path` for full input/output/tokens |
| `SubagentStop` | -- | Subagent: {id} | CHAIN | VS Code only: subagent completion |
| -- | `errorOccurred` | Error | CHAIN | CLI only: error event |
| -- | `sessionEnd` | Session End | CHAIN | CLI only: session termination; flushes the deferred turn |

**Key mode differences:**
- **VS Code mode** receives `sessionId` and a `transcript_path` at `Stop`, enabling full input/output/token extraction.
- **CLI mode** has no transcript access -- turns are deferred and flushed at the next `userPromptSubmitted` or `sessionEnd` with input only (no agent output, no tokens, no model name).

### `PreToolUse` / `preToolUse` permission response

The pre-tool handler must print a permission response to stdout. The format differs by mode:

- **VS Code**: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}`
- **CLI**: `{"permissionDecision": "allow"}`

All other handlers print `{"continue": true}` in VS Code mode and nothing in CLI mode.

## Troubleshoot

Common issues and fixes, split by platform:

### VS Code Copilot

| Problem | Fix |
|---------|-----|
| Traces not appearing | Verify config exists: `cat ~/.arize/harness/config.yaml`. Check hook log: `tail -20 /tmp/arize-copilot.log` |
| Spans missing output/tokens | Verify `.github/hooks/stop.json` is registered and `transcript_path` appears in the payload -- transcript parsing is required for full I/O capture |
| Hooks not firing | Verify each `.github/hooks/*.json` file exists in the project root and `command` uses the absolute venv binary path |
| `PreToolUse` blocking tools | Check the handler prints the correct permission JSON. Test: `echo '{"hookEventName":"PreToolUse","tool_name":"test"}' \| arize-hook-copilot-pre-tool` |
| Subagent spans missing | `SubagentStop` is VS Code only -- verify `.github/hooks/subagent-stop.json` is registered |

### Copilot CLI

| Problem | Fix |
|---------|-----|
| Traces not appearing | Verify `.github/hooks/hooks.json` exists with `version: 1`. Check hook log: `tail -20 /tmp/arize-copilot.log` |
| No output on spans | Expected -- Copilot CLI does not expose agent responses, so CLI spans have input only |
| No token counts | Expected -- CLI payloads do not include model name or token usage |
| Hooks not firing | Verify `.github/hooks/hooks.json` uses the `bash` field (not `command`) and camelCase event names |
| `preToolUse` blocking tools | Check the handler prints `{"permissionDecision": "allow"}`. Test: `echo '{"toolName":"test","toolArgs":"{}"}' \| arize-hook-copilot-pre-tool` |
| Deferred turns not flushing | Turns flush at the next `userPromptSubmitted` or `sessionEnd`. If the CLI exits abnormally, the last turn may be lost |

### General

| Problem | Fix |
|---------|-----|
| Config missing | Run the installer or create `~/.arize/harness/config.yaml` manually (include `harnesses.copilot` section) |
| Phoenix unreachable | Verify Phoenix is running: `curl -sf <endpoint>/v1/traces` |
| Want to test without sending | Set `ARIZE_DRY_RUN=true` env var before launching Copilot |
| Want verbose logging | Set `ARIZE_VERBOSE=true` env var before launching Copilot |
| Wrong project name | Set `harnesses.copilot.project_name` in `~/.arize/harness/config.yaml` (default: `"copilot"`) |
| Spans missing user attribution | Set `ARIZE_USER_ID` env var before launching Copilot |
