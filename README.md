# Arize Agent Kit

Trace AI coding sessions to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) with [OpenInference](https://github.com/Arize-ai/openinference) spans. Each harness integration emits spans for prompts, tool calls, model responses, and session lifecycle events.

## Supported Harnesses

| Harness | Integration | Install Method | Guide |
|---------|-------------|----------------|-------|
| Claude Code CLI | `claude-code-tracing` | Marketplace or curl | [claude-code-tracing/README.md](claude-code-tracing/README.md) |
| Claude Agent SDK | `claude-code-tracing` | Local plugin path | [claude-code-tracing/README.md](claude-code-tracing/README.md) |
| OpenAI Codex CLI | `codex-tracing` | `install.sh` or curl | [codex-tracing/README.md](codex-tracing/README.md) |
| Cursor IDE | `cursor-tracing` | `install.sh` or curl | [cursor-tracing/README.md](cursor-tracing/README.md) |

## Quick Install

**Claude Code (marketplace):**

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

**Any harness (curl):**

```bash
# Claude Code
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude

# Codex
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex

# Cursor
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor
```

The installer does three things:

1. **Asks for your backend** — Phoenix endpoint or Arize AX credentials
2. **Starts a background collector** — a lightweight local process at `127.0.0.1:4318` that handles all backend export (HTTP for Phoenix, gRPC for Arize AX)
3. **Configures your harness** — sets up hooks so spans flow automatically

No Python packages, `grpcio`, or `opentelemetry-proto` need to be installed in your environment. The collector ships with everything it needs.

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall
```

This stops the background collector, removes the collector runtime, and cleans up harness-specific configuration. You will be prompted before any user-owned config (credentials, state files) is deleted.

## Configuration

All configuration lives in `~/.arize/harness/config.json`, written by the installer. This file is the single source of truth for backend credentials, collector settings, and per-harness project names.

### config.json Schema

```json
{
  "collector": { "host": "127.0.0.1", "port": 4318 },
  "backend": {
    "target": "phoenix|arize",
    "phoenix": { "endpoint": "...", "api_key": "..." },
    "arize": { "endpoint": "...", "api_key": "...", "space_id": "..." }
  },
  "harnesses": {
    "claude-code": { "project_name": "claude-code" },
    "codex": { "project_name": "codex" },
    "cursor": { "project_name": "cursor" }
  }
}
```

- **`collector`** — Host and port for the local OTLP collector. Default port is `4318`. To change it, set `collector.port` in `config.json` — this only needs to be done once and applies to all harnesses.
- **`backend.target`** — Which backend to export to (`phoenix` or `arize`).
- **`backend.phoenix` / `backend.arize`** — Credentials for the selected backend.
- **`harnesses.<name>.project_name`** — Per-harness project name used in Arize/Phoenix.

> **Port conflict?** If port 4318 is already in use, the collector will fail to start. Set `collector.port` to a different value (e.g. `4319`) in `~/.arize/harness/config.json`. The installer will also prompt for this during setup.

### Environment Variable Fallbacks

Environment variables are supported as fallbacks but are secondary to `config.json`. If a value is set in both `config.json` and the environment, `config.json` wins.

| Variable | Default | Description |
|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | `true` | Enable or disable tracing |
| `ARIZE_API_KEY` | - | Arize AX API key (fallback if not in config.json) |
| `ARIZE_SPACE_ID` | - | Arize AX space ID (fallback if not in config.json) |
| `ARIZE_OTLP_ENDPOINT` | `otlp.arize.com:443` | OTLP gRPC endpoint (on-prem Arize) |
| `PHOENIX_ENDPOINT` | `http://localhost:6006` | Phoenix collector URL (fallback if not in config.json) |
| `PHOENIX_API_KEY` | - | Phoenix API key (fallback if not in config.json) |
| `ARIZE_PROJECT_NAME` | `default` | Project name (fallback if not in `harnesses` config) |
| `ARIZE_USER_ID` | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | `/tmp/arize-<harness>.log` | Log file path (empty to disable) |

### Backend Requirements

| Backend | Auth (config.json) | Harness Dependencies | Latency |
|---------|---------------------|---------------------|---------|
| **Phoenix** (self-hosted) | `backend.phoenix.endpoint` | `jq`, `curl` | ~local |
| **Arize AX** (cloud) | `backend.arize.api_key` + `backend.arize.space_id` | `jq`, `curl` | ~remote |

Both backends are served by the shared collector. Harnesses only need `jq` and `curl` to build and submit spans locally. The collector handles all backend-specific transport (HTTP for Phoenix, gRPC for Arize AX) — no Python packages required in the user environment.

## Architecture

Harness integrations build OpenInference spans locally and submit them to a shared background collector at `http://127.0.0.1:4318`. The collector owns backend export to Phoenix or Arize AX, including credentials, retries, and logging. Harnesses do not export directly to backends.

```text
Claude Code hooks ─┐
Codex hooks       ─┼─> POST http://127.0.0.1:4318/v1/spans ──> Phoenix / Arize AX
Cursor hooks      ─┘         (shared background collector)
```

The installer writes all shared runtime files under `~/.arize/harness/`:

| Path | Purpose |
|------|---------|
| `config.json` | Collector settings, backend target/credentials, and per-harness project names (`harnesses`) |
| `bin/arize-collector` | Collector launcher script |
| `run/collector.pid` | PID of the running collector process |
| `logs/collector.log` | Collector log output |

The collector starts automatically during install and runs in the background. Check its status with:

```bash
curl -s http://127.0.0.1:4318/health | python3 -m json.tool
```

See [COLLECTOR_ARCHITECTURE.md](COLLECTOR_ARCHITECTURE.md) for the full collector contract.

## Repository Layout

```
core/                   Shared span building, state primitives, collector, and sending
claude-code-tracing/    Claude Code CLI and Agent SDK integration
codex-tracing/          OpenAI Codex CLI integration
cursor-tracing/         Cursor IDE integration
install.sh              Curl-pipe installer (shared collector + harness config)
DEVELOPMENT.md          Guide for adding new harness adapters
```

## Testing

Validate span output without sending data:

```bash
ARIZE_DRY_RUN=true <your-harness-command>
```

## Contributing

See [DEVELOPMENT.md](DEVELOPMENT.md) for how to add a new harness adapter.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)

## License

MIT
