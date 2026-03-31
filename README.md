# Arize Agent Kit

Trace AI coding sessions to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix) with [OpenInference](https://github.com/Arize-ai/openinference) spans. Each harness integration emits spans for prompts, tool calls, model responses, and session lifecycle events.

## Supported Harnesses

| Harness | Integration | Install Method | Guide |
|---------|-------------|----------------|-------|
| Claude Code CLI | `claude-code-tracing` | Marketplace or curl | [claude-code-tracing/README.md](claude-code-tracing/README.md) |
| Claude Agent SDK | `claude-code-tracing` | Local plugin path | [claude-code-tracing/README.md](claude-code-tracing/README.md) |
| OpenAI Codex CLI | `codex-tracing` | `install.sh` or curl | [codex-tracing/README.md](codex-tracing/README.md) |

## Quick Install

**Claude Code (marketplace):**

```bash
claude plugin marketplace add Arize-ai/arize-agent-kit
claude plugin install claude-code-tracing@arize-agent-kit
```

**Any harness (curl):**

```bash
curl -fsSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash
```

The installer detects available harnesses and prompts you to choose which integrations to set up.

## Configuration

All integrations share the same environment variables. Set them in your harness settings file or export them in your shell.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ARIZE_TRACE_ENABLED` | No | `true` | Enable or disable tracing |
| `ARIZE_API_KEY` | For AX | - | Arize AX API key |
| `ARIZE_SPACE_ID` | For AX | - | Arize AX space ID |
| `ARIZE_OTLP_ENDPOINT` | No | `otlp.arize.com:443` | OTLP gRPC endpoint (on-prem Arize) |
| `PHOENIX_ENDPOINT` | For Phoenix | `http://localhost:6006` | Phoenix collector URL |
| `PHOENIX_API_KEY` | No | - | Phoenix API key (if auth enabled) |
| `ARIZE_PROJECT_NAME` | No | `default` | Project name in Arize/Phoenix |
| `ARIZE_USER_ID` | No | - | User identifier added to all spans as `user.id` |
| `ARIZE_DRY_RUN` | No | `false` | Print spans to log instead of sending |
| `ARIZE_VERBOSE` | No | `false` | Enable verbose logging |
| `ARIZE_LOG_FILE` | No | `/tmp/arize-<harness>.log` | Log file path (empty to disable) |

### Backend Requirements

| Backend | Auth | Harness Dependencies | Latency |
|---------|------|---------------------|---------|
| **Phoenix** (self-hosted) | `PHOENIX_ENDPOINT` | `jq`, `curl` | ~local |
| **Arize AX** (cloud) | `ARIZE_API_KEY` + `ARIZE_SPACE_ID` | `jq`, `curl` | ~remote |

Both backends are served by the shared collector. Harnesses only need `jq` and `curl` to build and submit spans locally. The collector handles all backend-specific transport (HTTP for Phoenix, gRPC for Arize AX) — no Python, `grpcio`, or `opentelemetry-proto` required in the user environment.

## Architecture

Harness integrations build OpenInference spans locally and submit them to a shared background collector at `http://127.0.0.1:4318`. The collector owns backend export to Phoenix or Arize AX, including credentials, retries, and logging. Harnesses do not export directly to backends.

```text
Claude Code hooks ─┐
Codex hooks       ─┼─> localhost collector ──> Phoenix / Arize AX
Future harnesses  ─┘
```

See [COLLECTOR_ARCHITECTURE.md](COLLECTOR_ARCHITECTURE.md) for the full collector contract.

## Repository Layout

```
core/                   Shared span building, state primitives, and sending
claude-code-tracing/    Claude Code CLI and Agent SDK integration
codex-tracing/          OpenAI Codex CLI integration
install.sh              Curl-pipe installer for non-marketplace harnesses
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
