---
name: setup-codex-tracing
description: Set up and configure Arize tracing for OpenAI Codex CLI sessions. Use when users want to set up Codex tracing, configure Arize AX or Phoenix for Codex, enable/disable tracing, or troubleshoot Codex tracing issues. Triggers on "set up codex tracing", "configure Arize for Codex", "configure Phoenix for Codex", "enable codex tracing", "setup-codex-tracing", or any request about connecting Codex to Arize or Phoenix for observability.
---

# Setup Codex Tracing

Configure OpenInference tracing for OpenAI Codex CLI sessions to Arize AX (cloud) or Phoenix (self-hosted).

## Architecture Overview

Codex tracing uses the shared collector at `127.0.0.1:4318` for both span export and event buffering:

1. **Shared collector** (`core/collector.py`, port 4318) — background process shared by all harnesses. Accepts span exports (`POST /v1/spans`), buffers Codex OTLP log events (`POST /v1/logs`), and serves buffered events (`GET /drain/{id}`, `GET /flush/{id}`). Exports to Phoenix (REST) or Arize AX (gRPC). Managed via `arize-collector-ctl`.

2. **Notify hook** (`arize-hook-codex-notify`) — Fires on `agent-turn-complete` events. Drains buffered events from the collector, transforms them into OpenInference child spans (TOOL spans for tool calls, LLM spans for API requests), enriches the parent Turn span with model name and token counts, and sends the complete span tree back to the collector for export.

```
Codex CLI
  |
  |-- [otel] otlp-http --> POST /v1/logs --> collector (port 4318, buffers by thread-id)
  |
  |-- notify hook (agent-turn-complete) --> arize-hook-codex-notify
        |
        |--> GET /drain/{thread_id} (port 4318) --> get buffered events
        |--> Transform events into child spans
        |--> Build multi-span OTLP payload (Turn parent + children)
        |--> POST /v1/spans (port 4318) --> collector --> Phoenix/Arize AX
```

**Graceful degradation**: If the collector isn't running or returns no buffered events, the notify hook falls back to a single flat Turn span.  If `ARIZE_DIRECT_SEND=true`, spans are sent directly to the backend instead.

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

Phoenix is self-hosted and requires no Python dependencies for tracing (the shared collector handles export using stdlib for Phoenix).

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

### 3. Python dependencies (handled by the shared collector)

Arize AX uses gRPC for export, but the gRPC dependencies are bundled with the shared collector — they are **not** required in the user's Python environment.  No `pip install` step is needed for basic tracing.

Then proceed to [Configure Codex](#configure-codex).

## Configure Codex

This section configures:
1. **Shared collector config** at `~/.arize/harness/config.yaml`
2. **Environment variables** in `~/.codex/arize-env.sh`
3. **Notify hook** in `~/.codex/config.toml`
4. **Event buffer** (auto-configured) — captures Codex events for rich span trees
5. **Native OTLP export** in `~/.codex/config.toml` — routes to shared collector

### Determine the integration path

Ask the user: **"Where is the codex-tracing directory located?"**

Common locations:
- If cloned: `./arize-agent-kit/codex-tracing`
- If installed via the curl installer: `~/.arize/harness/codex-tracing`

Store this as `INTEGRATION_PATH` for the notify hook config.

### Step 1: Write the shared collector config

Write `~/.arize/harness/config.yaml` with the backend credentials. The config file is the single source of truth for collector and backend settings.

**Important: read-merge-write.** If `~/.arize/harness/config.yaml` already exists, read it first, add or update the `harnesses.codex` entry, and preserve existing backend credentials. Only prompt the user for backend credentials if there is no existing config.

**Phoenix:**
```bash
mkdir -p ~/.arize/harness/{bin,run,logs}
# Merge: add/update harnesses.codex, preserve existing backend settings
arize-config set harnesses.codex.project_name codex
```

If no config exists yet, create it:
```yaml
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "phoenix"
  phoenix:
    endpoint: "http://localhost:6006"
    api_key: ""
harnesses:
  codex:
    project_name: "codex"
```

**Arize AX:**
```bash
mkdir -p ~/.arize/harness/{bin,run,logs}
arize-config set harnesses.codex.project_name codex
```

If no config exists yet, create it:
```yaml
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "arize"
  arize:
    endpoint: "otlp.arize.com:443"
    api_key: "<key>"
    space_id: "<space-id>"
harnesses:
  codex:
    project_name: "codex"
```

### Step 2: Write the environment file (optional)

Environment variables are optional overrides — all backend credentials are in `~/.arize/harness/config.yaml`. If the user needs env-var overrides, create `~/.codex/arize-env.sh`:

**Phoenix:**
```bash
cat > ~/.codex/arize-env.sh << 'EOF'
export ARIZE_TRACE_ENABLED=true
export ARIZE_COLLECTOR_PORT=4318
EOF
chmod 600 ~/.codex/arize-env.sh
```

If the user wants to associate spans with a user ID, add `export ARIZE_USER_ID="<user-id>"`.

**Arize AX:**
```bash
cat > ~/.codex/arize-env.sh << 'EOF'
export ARIZE_TRACE_ENABLED=true
export ARIZE_COLLECTOR_PORT=4318
EOF
chmod 600 ~/.codex/arize-env.sh
```

If the user wants to associate spans with a user ID, add `export ARIZE_USER_ID="<user-id>"`.

### Step 3: Add the notify hook to config.toml

Read `~/.codex/config.toml`. Add the `notify` line at the top level (NOT inside any `[section]`):

```toml
notify = ["~/.arize/harness/venv/bin/arize-hook-codex-notify"]
```

**Important:** If `notify` already exists in the config, update the existing line.

### Step 4: Configure OTLP export to shared collector

Add an `[otel]` section that routes Codex's native events to the shared collector (port 4318):

```toml
[otel]
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:4318/v1/logs"
protocol = "json"
```

This routes Codex native telemetry to the shared collector, which buffers events until the notify hook drains them for child-span assembly.

### Step 5: Start the shared collector

Start the shared collector:
```bash
arize-collector-ctl start
```

Or ensure it is running (starts only if not already up):
```bash
arize-collector-ctl ensure
```

The collector is a single lightweight process (~5MB RSS, stdlib Python, zero CPU when idle).

**Note:** The installer handles Steps 1-5 automatically.  The manual steps above are for users who prefer to configure things themselves or need to troubleshoot.

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

3. **Check shared collector is running:**
```bash
curl -sf http://127.0.0.1:4318/health
```

4. **Check collector is running:**
```bash
curl -sf http://127.0.0.1:4318/health
```

5. **Phoenix connectivity** (if using Phoenix):
```bash
curl -sf ${PHOENIX_ENDPOINT}/v1/traces >/dev/null && echo "Phoenix reachable" || echo "Phoenix not reachable"
```

6. **Dry run test:**
```bash
ARIZE_DRY_RUN=true arize-hook-codex-notify '{"type":"agent-turn-complete","thread-id":"test-123","turn-id":"turn-1","cwd":"/tmp","input-messages":"hello","last-assistant-message":"hi there"}'
```
Should print: `[arize] DRY RUN:` followed by the span name.

### Confirm

Tell the user:
- Configuration saved to `~/.codex/config.toml`, `~/.codex/arize-env.sh`, and `~/.arize/harness/config.yaml`
- The shared collector (port 4318) exports spans to the configured backend
- The shared collector (port 4318) captures Codex native events for child-span assembly
- Traces will appear as rich span trees with child spans for tool calls and API requests
- Token totals live on the parent Turn LLM span, not on request child spans
- If the collector has no buffered events, tracing still works with flat Turn spans (graceful degradation)
- Mention `ARIZE_DRY_RUN=true` to test without sending data
- Mention `ARIZE_VERBOSE=true` and `ARIZE_TRACE_DEBUG=true` for debug output
- Logs: shared collector at `~/.arize/harness/logs/collector.log`, harness at `/tmp/arize-codex.log`

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
| `ARIZE_TRACE_DEBUG` | No | `false` | Write debug JSON to `~/.arize/harness/state/codex/debug/` |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-codex.log` | Log file path |
| `ARIZE_COLLECTOR_PORT` | No | `4318` | Port for the shared collector |

## Troubleshoot

Common issues and fixes:

| Problem | Fix |
|---------|-----|
| Traces not appearing | Check `ARIZE_TRACE_ENABLED` is `true` in `~/.codex/arize-env.sh` |
| Notify hook not firing | Verify `notify` line in `~/.codex/config.toml` points to correct path |
| Phoenix unreachable | Verify Phoenix is running: `curl -sf <endpoint>/v1/traces` |
| Shared collector not running | Check config: `cat ~/.arize/harness/config.yaml`. Start: `arize-collector-ctl start` |
| No output in terminal | Notify runs in background; check `/tmp/arize-codex.log` and `~/.arize/harness/logs/collector.log` |
| Want to test without sending | Set `ARIZE_DRY_RUN=true` in env or `export ARIZE_DRY_RUN=true` |
| Want verbose logging | Set `ARIZE_VERBOSE=true` in env or `export ARIZE_VERBOSE=true` |
| Wrong project name | Set `ARIZE_PROJECT_NAME` in `~/.codex/arize-env.sh` (default: `codex`) |
| Existing notify hook | Codex supports only one `notify` — create a wrapper script that calls both |
| Stale state files | Run: `rm -rf ~/.arize/harness/state/codex/state_*.yaml` |
| Flat spans only (no children) | Check collector health: `curl http://127.0.0.1:4318/health`. Verify `[otel]` in config.toml points to `127.0.0.1:4318` |
| Collector not starting | Check Python 3.9+ is available. Check port 4318 isn't in use. See `~/.arize/harness/logs/collector.log` |
| User ID not appearing on spans | Set `ARIZE_USER_ID` in `~/.codex/arize-env.sh` or export before running Codex |
