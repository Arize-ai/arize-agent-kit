# Arize Agent Kit

Trace AI coding sessions to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) with [OpenInference](https://github.com/Arize-ai/openinference) spans. Each harness integration emits spans for prompts, tool calls, model responses, and session lifecycle events.

## Supported Harnesses

| Harness | Integration | Install Method |
|---------|-------------|----------------|
| [Claude Code CLI / Agent SDK](claude-code-tracing/README.md) | `claude-code-tracing` | Marketplace or `install.sh` |
| [OpenAI Codex CLI](codex-tracing/README.md) | `codex-tracing` | `install.sh` |
| [Cursor IDE](cursor-tracing/README.md) | `cursor-tracing` | `install.sh` |

Claude Code CLI and the Claude Agent SDK share the same plugin, hooks, and configuration — one install covers both.

## Quick Install

**Claude Code (marketplace):**

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

**Any harness (curl):**

```bash
INSTALL="https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh"

curl -fsSL $INSTALL | bash -s -- claude   # Claude Code / Agent SDK
curl -fsSL $INSTALL | bash -s -- codex    # OpenAI Codex
curl -fsSL $INSTALL | bash -s -- cursor   # Cursor IDE
```

The installer:

1. **Asks for your backend** — Phoenix endpoint or Arize AX credentials
2. **Writes config** — saves backend credentials and harness settings to `~/.arize/harness/config.json`
3. **Starts a background collector** — a lightweight local process at `127.0.0.1:4318` that handles all backend export (HTTP for Phoenix, gRPC for Arize AX)
4. **Configures your harness** — sets up hooks so spans flow automatically

### Uninstall

```bash
curl -fsSL $INSTALL | bash -s -- uninstall
```

This stops the background collector, removes the collector runtime, and cleans up harness-specific configuration. You will be prompted before any user-owned config (credentials, state files) is deleted.

## Configuration

All configuration lives in `~/.arize/harness/config.json`, written by the installer. This file is the single source of truth for backend credentials, collector settings, and per-harness project names.

### config.json Fields

**Collector**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `collector.host` | No | `127.0.0.1` | Collector listen address |
| `collector.port` | No | `4318` | Collector listen port |

**Backend**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `backend.target` | Yes | — | `phoenix` or `arize` |

**Phoenix backend** (`backend.target: "phoenix"`)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `backend.phoenix.endpoint` | Yes | `http://localhost:6006` | Phoenix server URL |
| `backend.phoenix.api_key` | No | — | Phoenix API key (if auth is enabled) |

**Arize AX backend** (`backend.target: "arize"`)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `backend.arize.api_key` | Yes | — | Arize AX API key |
| `backend.arize.space_id` | Yes | — | Arize AX space ID |
| `backend.arize.endpoint` | No | `otlp.arize.com:443` | Arize OTLP gRPC endpoint (for on-prem) |

**User**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `user_id` | No | — | User identifier added to all spans as `user.id` |

**Per-harness project names** (under `harnesses.<name>`) — sets the project name in Arize/Phoenix

| Name | Field | Default |
|------|-------|---------|
| `claude-code` | `project_name` | `claude-code` |
| `codex` | `project_name` | `codex` |
| `cursor` | `project_name` | `cursor` |

The collector handles all backend-specific transport (HTTP for Phoenix, gRPC for Arize AX). Harnesses only need `jq` and `curl`.

See [COLLECTOR_ARCHITECTURE.md](COLLECTOR_ARCHITECTURE.md) for the full collector contract.

## Contributing

See [DEVELOPMENT.md](DEVELOPMENT.md) for how to add a new harness adapter.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)

## License

MIT
