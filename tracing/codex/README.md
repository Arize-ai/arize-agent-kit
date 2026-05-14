# Codex CLI Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for the OpenAI Codex CLI. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## Setup
The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.yaml`, registers the `notify` hook in `~/.codex/config.toml`, starts the Codex buffer service, and creates the `arize-codex-proxy` shim at `~/.arize/harness/bin/codex` so `codex exec` is traced. Open a new shell after install so the PATH update takes effect.

Pass `--with-skills` to also symlink the `manage-codex-tracing` skill into the current directory's `.agents/skills/` so coding agents in this workspace can help manage Codex tracing configuration.

### Remote setup

macOS / Linux:

```bash
# Install
curl -sSL https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.sh | bash -s -- codex

# Uninstall
curl -sSL https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.sh | bash -s -- uninstall codex
```

Windows (PowerShell):

```powershell
# Install
iwr -useb https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat codex

# Uninstall
iwr -useb https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall codex
```

### Local setup

```bash
git clone https://github.com/Arize-ai/coding-harness-tracing.git
cd coding-harness-tracing
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

## Verifying tracing

After opening a new shell (so the updated PATH picks up the proxy shim):

```bash
# Run any Codex command — both interactive (`codex`) and one-shot (`codex exec`)
# routes are traced.
codex exec "explain what this file does" path/to/file.py
```

Then check:

- The buffer service is running: `ps aux | grep arize-codex-buffer` (PID is also stored in `~/.arize/harness/run/codex-buffer.pid`).
- Hook activity in `~/.arize/harness/logs/codex.log` and buffer activity in `~/.arize/harness/logs/codex-buffer.log`.
- Spans appear in your configured project in Arize AX or Phoenix.

## Troubleshooting

**`codex` is not running through the shim.** Confirm `which codex` returns `~/.arize/harness/bin/codex`. If a system Codex install is shadowing the shim, ensure `~/.arize/harness/bin` is earlier on your `PATH`, or open a new shell so the installer-applied PATH update takes effect.

**Buffer service won't start.** Port `4318` may be in use. Check `lsof -iTCP:4318 -sTCP:LISTEN`. Stop the conflicting process or change the port under `harnesses.codex.collector.port` in `~/.arize/harness/config.yaml`, then re-run `./install.sh codex`.

**No spans appear.** Re-source your shell profile (or open a new terminal) so `~/.codex/arize-env.sh` is loaded into the environment. Check `~/.arize/harness/logs/codex.log` for backend/auth errors.

**Disable temporarily.** Remove the `notify` entry from `~/.codex/config.toml` to pause hook execution without uninstalling, or uninstall fully with `./install.sh uninstall codex`.
