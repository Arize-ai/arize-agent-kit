# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the OpenAI Codex CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup

### Remote setup

macOS / Linux:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex
```

Windows (PowerShell):

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat codex
```

### Local setup

macOS / Linux:

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
./install.sh codex
```

Windows:

```powershell
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
install.bat codex
```

The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, registers the `notify` hook in `~/.codex/config.toml`, starts the Codex buffer service, and creates the `arize-codex-proxy` shim at `~/.arize/harness/bin/codex` so `codex exec` is traced. Open a new shell after install so the PATH update takes effect.

### Uninstall

```bash
./install.sh uninstall codex         # macOS / Linux
install.bat uninstall codex          # Windows
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `codex` |
| Project name | `codex` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook config file | `~/.codex/config.toml` (`notify` + `[otel.exporter.otlp-http]`) |
| Buffer service host / port | `127.0.0.1` / `4318` |
| Codex exec shim | `~/.arize/harness/bin/codex` (added to PATH) |
| Env override file | `~/.codex/arize-env.sh` |
| State directory | `~/.arize/harness/state/codex/` |
| Buffer PID / log | `~/.arize/harness/run/codex-buffer.pid` / `~/.arize/harness/logs/codex-buffer.log` |
| Log file | `/tmp/arize-codex.log` |
| Tracing enabled (`ARIZE_TRACE_ENABLED`) | `true` |

See the [root README](../README.md) for backend configuration details.
