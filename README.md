# Arize Agent Kit

Trace AI coding sessions to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) with [OpenInference](https://github.com/Arize-ai/openinference) spans. Each harness integration emits spans for prompts, tool calls, model responses, and session lifecycle events.

## Supported Harnesses

| Harness | Integration | Install Method |
|---------|-------------|----------------|
| [Claude Code CLI / Agent SDK](claude-code-tracing/README.md) | `claude-code-tracing` | Marketplace or `install.sh` / `install.bat` |
| [OpenAI Codex CLI](codex-tracing/README.md) | `codex-tracing` | `install.sh` / `install.bat` |
| [Cursor IDE / CLI](cursor-tracing/README.md) | `cursor-tracing` | `install.sh` / `install.bat` |
| [GitHub Copilot (VS Code + CLI)](copilot_tracing/README.md) | `copilot-tracing` | `install.sh` / `install.bat` |

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

curl -sSL "$INSTALL_URL" | bash -s -- claude    # Claude Code / Agent SDK
curl -sSL "$INSTALL_URL" | bash -s -- codex     # OpenAI Codex
curl -sSL "$INSTALL_URL" | bash -s -- cursor    # Cursor IDE / CLI
curl -sSL "$INSTALL_URL" | bash -s -- copilot   # GitHub Copilot (VS Code + CLI)
```

**Or run locally:**

```bash
./install.sh claude    # Claude Code / Agent SDK
./install.sh codex     # OpenAI Codex
./install.sh cursor    # Cursor IDE / CLI
./install.sh copilot   # GitHub Copilot (VS Code + CLI)
```

The installer:

1. **Asks for your backend** — Phoenix endpoint or Arize AX credentials
2. **Offers to copy credentials** — if another harness is already installed using the same target, the installer offers to reuse its credentials
3. **Asks for a project name** — defaults to the harness name (e.g. `claude-code`, `codex`, `cursor`)
4. **Writes config** — saves backend credentials and harness settings to `~/.arize/harness/config.yaml`
5. **Configures your harness** — sets up hooks so spans flow automatically

Spans are sent directly to the backend from hooks — no background process is needed. (Codex additionally starts a lightweight buffer service for native OTLP event buffering.)

> **Codex exec:** the Codex installer creates the `arize-codex-proxy` shim at `~/.arize/harness/bin/codex` and adds the harness bin directory to supported shell profiles so it resolves ahead of the real Codex binary. Open a new shell after install. See [codex_tracing/README.md](codex_tracing/README.md) for details.

> **Cursor CLI:** Cursor CLI emits a subset of the IDE hook events. `afterAgentResponse` and `afterAgentThought` are not available through CLI hooks. See [cursor_tracing/README.md](cursor_tracing/README.md) for coverage details.

### Uninstall

```bash
./install.sh uninstall
```

This removes the harness configuration and cleans up runtime files. For Codex, the buffer service is stopped. You will be prompted before any user-owned config (credentials, state files) is deleted.

## Configuration

All configuration lives in `~/.arize/harness/config.yaml`, written by the installer. This file is the single source of truth for backend credentials and per-harness settings.

### config.yaml Fields

**Per-harness settings** (under `harnesses.<name>`)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `harnesses.<name>.project_name` | No | harness name | Project name in Arize/Phoenix |
| `harnesses.<name>.target` | Yes | — | `phoenix` or `arize` |
| `harnesses.<name>.endpoint` | Yes | — | Phoenix server URL or Arize OTLP gRPC endpoint |
| `harnesses.<name>.api_key` | Arize: Yes | — | Arize AX API key (or optional Phoenix API key) |
| `harnesses.<name>.space_id` | Arize: Yes | — | Arize AX space ID |

**Codex-only** (under `harnesses.codex.collector`)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `harnesses.codex.collector.host` | No | `127.0.0.1` | Codex buffer service listen address |
| `harnesses.codex.collector.port` | No | `4318` | Codex buffer service listen port |

**User**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `user_id` | No | — | User identifier added to all spans as `user.id` |

Each harness owns its full backend configuration directly — there is no shared global backend block. This allows different harnesses to use different backends or credentials:

```yaml
harnesses:
  claude-code:
    project_name: claude-code
    target: arize
    endpoint: otlp.arize.com:443
    api_key: ak-xxx
    space_id: U3Bh...
  codex:
    project_name: codex
    target: phoenix
    endpoint: http://localhost:6006
    api_key: ""
    collector:
      host: 127.0.0.1
      port: 4318
  copilot:
    project_name: copilot
    target: arize
    endpoint: otlp.arize.com:443
    api_key: ak-xxx
    space_id: U3Bh...
  cursor:
    project_name: cursor
    target: phoenix
    endpoint: http://localhost:6006
    api_key: ""
user_id: optional-global-user-id
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
