# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the OpenAI Codex CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, registers the `notify` hook in `~/.codex/config.toml`, starts the Codex buffer service, and creates the `arize-codex-proxy` shim at `~/.arize/harness/bin/codex` so `codex exec` is traced. Open a new shell after install so the PATH update takes effect.

### Remote setup

macOS / Linux:

```bash
# Install
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex

# Uninstall
curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall codex
```

Windows (PowerShell):

```powershell
# Install
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat codex

# Uninstall
iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall codex
```

### Local setup

```bash
git clone https://github.com/Arize-ai/arize-agent-kit.git
cd arize-agent-kit
```

macOS / Linux:

```bash
# Install
./install.sh codex

# Uninstall
./install.sh uninstall codex
```

Windows:

```powershell
# Install
install.bat codex

# Uninstall
install.bat uninstall codex
```

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `codex` |
| Project name | `codex` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook config file | `~/.codex/config.toml` |
| Hook events handled | `agent-turn-complete` (via `notify`); buffer drain on `codex exec` exit |
| Buffer service host:port | `127.0.0.1` : `4318` |
| Codex exec shim | `~/.arize/harness/bin/codex` (added to PATH) |
| Env override file | `~/.codex/arize-env.sh` |
| State directory | `~/.arize/harness/state/codex/` |
| Buffer PID | `~/.arize/harness/run/codex-buffer.pid` |
| Log file | `~/.arize/harness/logs/codex.log` |
