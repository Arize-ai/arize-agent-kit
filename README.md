# Arize Agent Kit

Trace AI coding sessions to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) with [OpenInference](https://github.com/Arize-ai/openinference) spans. Each harness integration emits spans for prompts, tool calls, model responses, and session lifecycle events.

## Supported Harnesses

| Harness | Integration | Install Method |
|---------|-------------|----------------|
| [Claude Code CLI / Agent SDK](claude-code-tracing/README.md) | `claude-code-tracing` | Marketplace or `install.sh` / `install.bat` |
| [OpenAI Codex CLI](codex-tracing/README.md) | `codex-tracing` | `install.sh` / `install.bat` |
| [Cursor IDE](cursor-tracing/README.md) | `cursor-tracing` | `install.sh` / `install.bat` |

Claude Code CLI and the Claude Agent SDK share the same plugin, hooks, and configuration — one install covers both.

## Quick Install

**Claude Code (marketplace):**

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

Then add your backend credentials to `~/.claude/settings.json` (or `.claude/settings.local.json` for per-project):

```json
{
  "env": {
    "ARIZE_TRACE_ENABLED": "true",
    "ARIZE_API_KEY": "<your-arize-api-key>",
    "ARIZE_SPACE_ID": "<your-arize-space-id>",
    "ARIZE_PROJECT_NAME": "claude-code"
  }
}
```

For Phoenix, use `"PHOENIX_ENDPOINT": "http://localhost:6006"` instead of the Arize keys.

**Any harness (curl-pipe):**

```bash
INSTALL_URL="https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh"

curl -sSL "$INSTALL_URL" | bash -s -- claude   # Claude Code / Agent SDK
curl -sSL "$INSTALL_URL" | bash -s -- codex    # OpenAI Codex
curl -sSL "$INSTALL_URL" | bash -s -- cursor   # Cursor IDE
```

**Or run locally:**

```bash
./install.sh claude   # Claude Code / Agent SDK
./install.sh codex    # OpenAI Codex
./install.sh cursor   # Cursor IDE
```

The installer:

1. **Asks for your backend** — Phoenix endpoint or Arize AX credentials
2. **Asks for a project name** — defaults to the harness name (e.g. `claude-code`, `codex`, `cursor`)
3. **Writes config** — saves backend credentials and harness settings to `~/.arize/harness/config.yaml`
4. **Configures your harness** — sets up hooks so spans flow automatically

Spans are sent directly to the backend from hooks — no background process is needed. (Codex additionally starts a lightweight buffer service for native OTLP event buffering.)

### Uninstall

```bash
./install.sh uninstall
```

This removes the harness configuration and cleans up runtime files. For Codex, the buffer service is stopped. You will be prompted before any user-owned config (credentials, state files) is deleted.

## Configuration

All configuration lives in `~/.arize/harness/config.yaml`, written by the installer. This file is the single source of truth for backend credentials and per-harness settings.

### config.yaml Fields

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

**Per-harness settings** (under `harnesses.<name>`)

| Name | Field | Default |
|------|-------|---------|
| `claude-code` | `project_name` | `claude-code` |
| `codex` | `project_name` | `codex` |
| `cursor` | `project_name` | `cursor` |

Each harness can optionally override backend credentials under `harnesses.<name>.backend`. When present, these override the global `backend` section for that harness only. This allows different harnesses to use different backends or credentials:

```yaml
harnesses:
  claude-code:
    project_name: "my-project"
    backend:                      # optional per-harness override
      target: "arize"
      arize:
        api_key: "different-key"
        space_id: "different-space"
        endpoint: "otlp.arize.com:443"
```

Harnesses send spans directly to the backend via `send_span()` in `core/common.py`. Python CLI entry points handle all hook events — no external dependencies (`curl`, `jq`, `bash`) are required.

See [TRACING_ARCHITECTURE.md](docs/TRACING_ARCHITECTURE.md) for the full architecture.

## Contributing

See [DEVELOPMENT.md](DEVELOPMENT.md) for how to add a new harness adapter.

## Links

- [Arize AX](https://arize.com)
- [Phoenix](https://github.com/Arize-ai/phoenix)
- [OpenInference](https://github.com/Arize-ai/openinference)

## License

MIT
