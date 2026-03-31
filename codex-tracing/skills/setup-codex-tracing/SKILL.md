---
name: setup-codex-tracing
description: Set up and configure Arize tracing for OpenAI Codex CLI sessions. Use when users want to set up Codex tracing, configure Arize AX or Phoenix for Codex, enable/disable tracing, or troubleshoot Codex tracing issues. Triggers on "set up codex tracing", "configure Arize for Codex", "configure Phoenix for Codex", "enable codex tracing", "setup-codex-tracing", or any request about connecting Codex to Arize or Phoenix for observability.
---

# Setup Codex Tracing

Configure OpenInference tracing for OpenAI Codex CLI sessions to Arize AX (cloud) or Phoenix (self-hosted).

## Architecture Overview

Codex tracing produces rich span trees using three components:

1. **OTel Collector** (`collector.py`) — A lightweight stdlib-only Python HTTP server running on `127.0.0.1:4318`. Receives Codex's native OpenTelemetry log events (`codex.tool_decision`, `codex.tool_result`, `codex.api_request`, `codex.sse_event`, etc.) via the `[otel]` config and buffers them by conversation ID.

2. **Notify hook** (`notify.sh`) — Fires on `agent-turn-complete` events. Flushes buffered events from the collector, transforms them into OpenInference child spans (TOOL spans for tool calls, LLM spans for API requests), enriches the parent Turn span with model name and token counts, and sends the complete span tree.

3. **Collector lifecycle** (`collector_ctl.sh`) — Shell functions for starting/stopping the collector. Auto-started from the shell profile on login and as a safety net from the notify hook.

```
Codex CLI
  |
  |-- [otel] otlp-http --> POST /v1/logs --> collector.py (buffers by conversation_id)
  |
  |-- notify hook (agent-turn-complete) --> notify.sh
        |
        |--> curl /flush/{conversation_id} --> get buffered events
        |--> Transform events into child spans
        |--> Build multi-span OTLP payload (Turn parent + children)
        |--> send_span() via existing Phoenix/Arize path
```

**Graceful degradation**: If the collector isn't running or returns no events, the notify hook falls back to the current behavior (single flat Turn span).

Environment variables are stored in `~/.codex/arize-env.sh` and auto-sourced by the notify script.

## How to Use This Skill

**This skill follows a decision tree workflow.** Start by asking the user where they are in the setup process:

1. **Do they already have credentials?**
   - Yes → Jump to [Configure Codex](#configure-codex)
   - No → Continue to step 2

2. **Which backend do they want to use?**
   - Phoenix (self-hosted) → Go to [Set Up Phoenix](#set-up-phoenix)
   - Arize AX (cloud) → Go to [Set Up Arize AX](#set-up-arize-ax)

3. **Are they troubleshooting?**
   - Yes → Jump to [Troubleshoot](#troubleshoot)

**Important:** Only follow the relevant path for the user's needs. Don't go through all sections.

## Set Up Phoenix

Phoenix is self-hosted and requires no Python dependencies for tracing (the collector uses stdlib only).

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

Then proceed to [Configure Codex](#configure-codex) with `PHOENIX_ENDPOINT=http://localhost:6006`.

## Set Up Arize AX

Arize AX is available as a SaaS platform or as an on-prem deployment. Users need an account, a space, and an API key.

**First, ask the user: "Are you using the Arize SaaS platform or an on-prem instance?"**

- **SaaS** → Uses the default endpoint (`otlp.arize.com:443`). Continue below.
- **On-prem** → The user will need to provide their custom OTLP endpoint (e.g., `otlp.mycompany.arize.com:443`). Ask for it and note it for the configure step where it will be set as `ARIZE_OTLP_ENDPOINT`.

### 1. Create an account

If the user doesn't have an Arize account:
- **SaaS**: Sign up at https://app.arize.com/auth/join
- **On-prem**: Contact their administrator for access

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

Then proceed to [Configure Codex](#configure-codex).

## Configure Codex

This section configures:
1. **Environment variables** in `~/.codex/arize-env.sh`
2. **Notify hook** in `~/.codex/config.toml`
3. **OTel collector** (auto-configured) — captures Codex events for rich span trees
4. **Native OTLP export** in `~/.codex/config.toml` — routes to local collector

### Determine the integration path

Ask the user: **"Where is the codex-tracing directory located?"**

Common locations:
- If cloned: `./arize-agent-kit/codex-tracing`
- If installed via the curl installer: `~/.arize-agent-kit/codex-tracing`

Store this as `INTEGRATION_PATH` for the notify hook config.

### Step 1: Write the environment file

Create `~/.codex/arize-env.sh` with the user's credentials. The notify script auto-sources this file on each invocation.

**Phoenix:**
```bash
cat > ~/.codex/arize-env.sh << 'EOF'
export ARIZE_TRACE_ENABLED=true
export PHOENIX_ENDPOINT=http://localhost:6006
export ARIZE_PROJECT_NAME=codex
export CODEX_COLLECTOR_PORT=4318
EOF
chmod 600 ~/.codex/arize-env.sh
```

If the user has a Phoenix API key, also add `export PHOENIX_API_KEY="<key>"`.
If the user wants to associate spans with a user ID, add `export ARIZE_USER_ID="<user-id>"`.

**Arize AX:**
```bash
cat > ~/.codex/arize-env.sh << 'EOF'
export ARIZE_TRACE_ENABLED=true
export ARIZE_API_KEY=<user's key>
export ARIZE_SPACE_ID=<user's space id>
export ARIZE_PROJECT_NAME=codex
export CODEX_COLLECTOR_PORT=4318
EOF
chmod 600 ~/.codex/arize-env.sh
```

If the user has a custom OTLP endpoint (on-prem), also add `export ARIZE_OTLP_ENDPOINT="<host:port>"`.
If the user wants to associate spans with a user ID, add `export ARIZE_USER_ID="<user-id>"`.

### Step 2: Add the notify hook to config.toml

Read `~/.codex/config.toml`. Add the `notify` line at the top level (NOT inside any `[section]`):

```toml
notify = ["bash", "<PLUGIN_PATH>/hooks/notify.sh"]
```

**Important:** If `notify` already exists in the config, update the existing line.

### Step 3: Configure OTLP export to local collector

Add an `[otel]` section that routes Codex's native events to the local collector:

```toml
[otel]
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:4318/v1/logs"
protocol = "json"
```

This replaces any previous `[otel]` config that pointed directly at Phoenix or Arize. The collector buffers these events and the notify hook flushes them to build rich span trees.

### Step 4: Start the collector

Add the collector auto-start to the user's shell profile:

```bash
# Add to .zshrc or .bashrc:
[ -f ~/.codex/arize-env.sh ] && source ~/.codex/arize-env.sh && source "<PLUGIN_PATH>/scripts/collector_ctl.sh" && collector_ensure
```

Or start it manually:
```bash
source <PLUGIN_PATH>/scripts/collector_ctl.sh
collector_start
```

The collector is a tiny process (~5MB RSS, stdlib Python, zero CPU when idle) that auto-exits after 30 minutes of inactivity.

**Note:** The interactive installer (`./install.sh`) handles Steps 1-4 automatically. The manual steps above are for users who prefer to configure things themselves or need to troubleshoot.

### Validate

After writing the config, validate:

1. **Check config.toml is valid:**
```bash
cat ~/.codex/config.toml
```
Visually confirm the `notify` line is at the top level and the `[otel]` section points to `127.0.0.1:4318`.

2. **Check env file:**
```bash
source ~/.codex/arize-env.sh && echo "ARIZE_TRACE_ENABLED=$ARIZE_TRACE_ENABLED"
```

3. **Check collector is running:**
```bash
source <PLUGIN_PATH>/scripts/collector_ctl.sh && collector_status
curl -sf http://127.0.0.1:4318/health | jq .
```

4. **Phoenix connectivity** (if using Phoenix):
```bash
source ~/.codex/arize-env.sh && curl -sf ${PHOENIX_ENDPOINT}/v1/traces >/dev/null && echo "Phoenix reachable" || echo "Phoenix not reachable"
```

5. **Arize AX dependencies** (if using Arize):
```bash
python3 -c "import opentelemetry; import grpc; print('Dependencies OK')"
```

6. **Dry run test:**
```bash
source ~/.codex/arize-env.sh && ARIZE_DRY_RUN=true bash <PLUGIN_PATH>/hooks/notify.sh '{"type":"agent-turn-complete","thread-id":"test-123","turn-id":"turn-1","cwd":"/tmp","input-messages":"hello","last-assistant-message":"hi there"}'
```
Should print: `[arize] DRY RUN:` followed by the span name.

### Confirm

Tell the user:
- Configuration saved to `~/.codex/config.toml` and `~/.codex/arize-env.sh`
- The OTel collector runs in the background on port 4318 (auto-starts with shell)
- Traces will appear as rich span trees with child spans for tool calls and API requests
- Token totals live on the parent Turn LLM span, not on request child spans
- If the collector isn't running, tracing still works with flat Turn spans (graceful degradation)
- Mention `ARIZE_DRY_RUN=true` to test without sending data
- Mention `ARIZE_VERBOSE=true` and `ARIZE_TRACE_DEBUG=true` for debug output
- Logs are written to `/tmp/arize-codex.log`

### Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_API_KEY` | For AX | - | Arize AX API key |
| `ARIZE_SPACE_ID` | For AX | - | Arize AX space ID |
| `ARIZE_OTLP_ENDPOINT` | No | `otlp.arize.com:443` | OTLP gRPC endpoint (on-prem Arize) |
| `PHOENIX_ENDPOINT` | For Phoenix | `http://localhost:6006` | Phoenix collector URL |
| `PHOENIX_API_KEY` | No | - | Phoenix API key for auth |
| `ARIZE_PROJECT_NAME` | No | `codex` | Project name in Arize/Phoenix |
| `ARIZE_USER_ID` | No | - | User ID to attach to all spans as `user.id` attribute |
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable/disable tracing |
| `ARIZE_DRY_RUN` | No | `false` | Print spans instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_TRACE_DEBUG` | No | `false` | Write debug JSON to `~/.arize-codex/debug/` |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-codex.log` | Log file path |
| `CODEX_COLLECTOR_PORT` | No | `4318` | Port for the local OTel collector |

## Troubleshoot

Common issues and fixes:

| Problem | Fix |
|---------|-----|
| Traces not appearing | Check `ARIZE_TRACE_ENABLED` is `true` in `~/.codex/arize-env.sh` |
| Notify hook not firing | Verify `notify` line in `~/.codex/config.toml` points to correct path |
| "jq required" error | Install jq: `brew install jq` (macOS) or `apt install jq` (Linux) |
| Phoenix unreachable | Verify Phoenix is running: `curl -sf <endpoint>/v1/traces` |
| "Python with opentelemetry not found" | Run `pip install opentelemetry-proto grpcio` |
| No output in terminal | Notify runs in background; check `/tmp/arize-codex.log` |
| Want to test without sending | Set `ARIZE_DRY_RUN=true` in env or `export ARIZE_DRY_RUN=true` |
| Want verbose logging | Set `ARIZE_VERBOSE=true` in env or `export ARIZE_VERBOSE=true` |
| Wrong project name | Set `ARIZE_PROJECT_NAME` in `~/.codex/arize-env.sh` (default: `codex`) |
| Existing notify hook | Codex supports only one `notify` — create a wrapper script that calls both |
| Stale state files | Run: `rm -rf ~/.arize-codex/state_*.json` |
| Flat spans only (no children) | Check collector: `curl http://127.0.0.1:4318/health`. Verify `[otel]` in config.toml points to `127.0.0.1:4318` |
| Collector not starting | Check `python3` is available. Check port 4318 isn't in use. See `~/.arize-codex/collector.log` |
| Collector auto-exit | Normal — auto-exits after 30min of inactivity. `collector_ensure` restarts it |
| Port conflict | Set `CODEX_COLLECTOR_PORT=<other_port>` in `~/.codex/arize-env.sh` and update `[otel]` endpoint in config.toml |
| User ID not appearing on spans | Set `ARIZE_USER_ID` in `~/.codex/arize-env.sh` or export before running Codex |
