#!/bin/bash
# Arize Agent Kit — Cross-platform installer (native bash)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- update
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall
#
# Installs the arize-agent-kit repo, sets up a shared venv and config,
# and configures tracing for the specified harness.
# Idempotent — safe to run multiple times.

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_URL="https://github.com/Arize-ai/arize-agent-kit.git"
INSTALL_BRANCH="${ARIZE_INSTALL_BRANCH:-main}"
TARBALL_URL="https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/${INSTALL_BRANCH}.tar.gz"
INSTALL_DIR="${HOME}/.arize/harness"

# Shared runtime layout
CONFIG_FILE="${INSTALL_DIR}/config.yaml"
BIN_DIR="${INSTALL_DIR}/bin"
PID_DIR="${INSTALL_DIR}/run"
LOG_DIR="${INSTALL_DIR}/logs"
VENV_DIR="${INSTALL_DIR}/venv"
STATE_BASE_DIR="${INSTALL_DIR}/state"

# Codex buffer service
BUFFER_BIN="${BIN_DIR}/arize-codex-buffer"
BUFFER_PID_FILE="${PID_DIR}/codex-buffer.pid"
BUFFER_LOG_FILE="${LOG_DIR}/codex-buffer.log"

# Legacy collector paths (for cleanup of existing installs)
COLLECTOR_BIN="${BIN_DIR}/arize-collector"
PID_FILE="${PID_DIR}/collector.pid"
COLLECTOR_LOG_FILE="${LOG_DIR}/collector.log"

# Hook entry point names are defined in the Python heredoc in setup_claude()
# (matches pyproject.toml [project.scripts])

CURSOR_HOOK_EVENTS=(
    "beforeSubmitPrompt"
    "afterAgentResponse"
    "afterAgentThought"
    "beforeShellExecution"
    "afterShellExecution"
    "beforeMCPExecution"
    "afterMCPExecution"
    "beforeReadFile"
    "afterFileEdit"
    "stop"
    "beforeTabFileRead"
    "afterTabFileEdit"
)

ARIZE_ENV_KEYS=(
    "ARIZE_TRACE_ENABLED"
    "PHOENIX_ENDPOINT"
    "PHOENIX_API_KEY"
    "ARIZE_API_KEY"
    "ARIZE_SPACE_ID"
    "ARIZE_OTLP_ENDPOINT"
    "ARIZE_PROJECT_NAME"
    "ARIZE_USER_ID"
    "ARIZE_DRY_RUN"
    "ARIZE_VERBOSE"
    "ARIZE_LOG_FILE"
)

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

if [[ -n "${NO_COLOR:-}" ]] || [[ ! -t 1 ]]; then
    RED="" GREEN="" YELLOW="" BLUE="" BOLD="" NC=""
fi

info()   { echo -e "${GREEN}[arize]${NC} $*"; }
warn()   { echo -e "${YELLOW}[arize]${NC} $*"; }
err()    { echo -e "${RED}[arize]${NC} $*" >&2; }
header() { echo -e "\n${BOLD}${BLUE}$*${NC}\n"; }

command_exists() { command -v "$1" &>/dev/null; }

# Read input, trying /dev/tty if stdin is piped (e.g. curl | bash)
_tty_in=""
if [[ -t 0 ]]; then
    _tty_in="/dev/stdin"
else
    # Check if /dev/tty is available (for curl | bash scenarios)
    if (exec 3< /dev/tty) 2>/dev/null; then
        exec 3<&-
        _tty_in="/dev/tty"
    fi
fi

tty_input() {
    local prompt="$1" reply=""
    if [[ -n "$_tty_in" ]]; then
        read -rp "$prompt" reply < "$_tty_in"
    fi
    echo "$reply"
}

confirm() {
    local prompt="$1" default="${2:-n}" reply
    reply=$(tty_input "$prompt")
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[Yy] ]]
}

# Read one line from $_tty_in; print '*' for each character (stderr). Sets REPLY.
tty_read_masked_line() {
    REPLY=""
    [[ -n "${_tty_in:-}" ]] || return 1
    local prompt="$1"
    local char
    printf '%s' "$prompt" >&2
    while IFS= read -rs -n 1 char < "$_tty_in"; do
        # read -n 1 uses newline as delimiter, so Enter yields an empty string
        if [[ -z "$char" || "$char" == $'\n' || "$char" == $'\r' ]]; then
            printf '\n' >&2
            return 0
        fi
        if [[ "$char" == $'\177' || "$char" == $'\b' ]]; then
            if [[ -n "$REPLY" ]]; then
                REPLY="${REPLY%?}"
                printf '\b \b' >&2
            fi
            continue
        fi
        # Skip other control characters (e.g. Ctrl+C still raises SIGINT)
        [[ "$char" =~ [[:cntrl:]] ]] && continue
        REPLY+="$char"
        printf '*' >&2
    done
    printf '\n' >&2
    return 0
}

# ---------------------------------------------------------------------------
# Python discovery
# ---------------------------------------------------------------------------
find_python() {
    local candidates=(python3 python /usr/bin/python3 /usr/local/bin/python3 "$HOME/.local/bin/python3")
    # pyenv
    [[ -d "$HOME/.pyenv/shims" ]] && candidates+=("$HOME/.pyenv/shims/python3")
    # Homebrew (macOS)
    [[ -x "/opt/homebrew/bin/python3" ]] && candidates+=("/opt/homebrew/bin/python3")
    # Conda
    local conda_base
    conda_base=$(conda info --base 2>/dev/null) && [[ -n "$conda_base" ]] && candidates+=("${conda_base}/bin/python3")

    for p in "${candidates[@]}"; do
        local resolved
        if [[ "$p" == /* ]]; then
            resolved="$p"
        else
            resolved=$(command -v "$p" 2>/dev/null || true)
        fi
        [[ -z "$resolved" || ! -f "$resolved" ]] && continue
        if "$resolved" -c "import sys; assert sys.version_info >= (3, 9)" 2>/dev/null; then
            echo "$resolved"
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# Venv helpers
# ---------------------------------------------------------------------------
venv_python() {
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        echo "${VENV_DIR}/bin/python"
    elif [[ -x "${VENV_DIR}/Scripts/python.exe" ]]; then
        echo "${VENV_DIR}/Scripts/python.exe"
    else
        return 1
    fi
}

venv_pip() {
    if [[ -x "${VENV_DIR}/bin/pip" ]]; then
        echo "${VENV_DIR}/bin/pip"
    elif [[ -x "${VENV_DIR}/Scripts/pip.exe" ]]; then
        echo "${VENV_DIR}/Scripts/pip.exe"
    else
        return 1
    fi
}

venv_bin() {
    local name="$1"
    echo "${VENV_DIR}/bin/${name}"
}

# ---------------------------------------------------------------------------
# Config helpers (use core/config.py via venv python)
# ---------------------------------------------------------------------------
cfg_get() {
    local vp
    vp=$(venv_python 2>/dev/null) || return 0
    [[ -f "$CONFIG_FILE" ]] || return 0
    "$vp" "${INSTALL_DIR}/core/config.py" get "$1" 2>/dev/null || true
}

cfg_set() {
    local vp
    vp=$(venv_python 2>/dev/null) || return 0
    "$vp" "${INSTALL_DIR}/core/config.py" set "$1" "$2" 2>/dev/null || true
}

cfg_delete() {
    local vp
    vp=$(venv_python 2>/dev/null) || return 0
    "$vp" "${INSTALL_DIR}/core/config.py" delete "$1" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Repository download
# ---------------------------------------------------------------------------
# Point ${INSTALL_DIR} at origin/$1 (handles ARIZE_INSTALL_BRANCH / --branch). Returns 0 on success.
git_sync_harness_repo() {
    local branch="$1"
    [[ -d "${INSTALL_DIR}/.git" ]] || return 1
    info "Syncing with origin/${branch}..."
    if git -C "$INSTALL_DIR" fetch --depth 1 origin "$branch" 2>/dev/null \
        && git -C "$INSTALL_DIR" checkout -B "$branch" FETCH_HEAD 2>/dev/null; then
        return 0
    fi
    if git -C "$INSTALL_DIR" fetch origin "$branch" 2>/dev/null \
        && git -C "$INSTALL_DIR" checkout -B "$branch" FETCH_HEAD 2>/dev/null; then
        return 0
    fi
    warn "git fetch/checkout failed — trying pull --ff-only"
    if git -C "$INSTALL_DIR" pull --ff-only origin "$branch" 2>/dev/null; then
        return 0
    fi
    if git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null; then
        return 0
    fi
    return 1
}

install_repo() {
    local branch="${1:-$INSTALL_BRANCH}"
    local tarball_url="${2:-$TARBALL_URL}"

    if [[ -d "${INSTALL_DIR}/.git" ]]; then
        info "Repository already installed at ${INSTALL_DIR}"
        if git_sync_harness_repo "$branch"; then
            return 0
        fi
        warn "git update failed — re-cloning"
        rm -rf "$INSTALL_DIR"
    fi

    if [[ -d "$INSTALL_DIR" && ! -d "${INSTALL_DIR}/.git" ]]; then
        info "Existing non-git install found — removing for fresh clone"
        rm -rf "$INSTALL_DIR"
    fi

    if command_exists git; then
        info "Cloning arize-agent-kit..."
        if git clone --depth 1 --branch "$branch" "$REPO_URL" "$INSTALL_DIR" 2>/dev/null; then
            return 0
        fi
        warn "git clone failed — falling back to tarball"
    fi

    install_repo_tarball "$tarball_url"
}

install_repo_tarball() {
    local tarball_url="${1:-$TARBALL_URL}"
    info "Downloading arize-agent-kit tarball..."

    local tmp_tar
    tmp_tar="$(mktemp)"
    trap 'rm -f "$tmp_tar"' RETURN

    if command_exists curl; then
        curl -sSfL "$tarball_url" -o "$tmp_tar"
    elif command_exists wget; then
        wget -qO "$tmp_tar" "$tarball_url"
    else
        err "Neither curl nor wget found — cannot download"
        exit 1
    fi

    mkdir -p "$INSTALL_DIR"
    tar xzf "$tmp_tar" --strip-components=1 -C "$INSTALL_DIR"
    info "Extracted to ${INSTALL_DIR}"
}

# ---------------------------------------------------------------------------
# Venv setup
# ---------------------------------------------------------------------------
setup_venv() {
    local python_cmd="$1"
    local backend_target="$2"

    # Check if existing venv already has required packages
    local vp
    vp=$(venv_python 2>/dev/null) || true
    if [[ -n "$vp" ]]; then
        local check_cmd="import yaml"
        [[ "$backend_target" == "arize" ]] && check_cmd="import yaml; import grpc; import opentelemetry"
        # yaml alone is not enough: an old/partial venv may have skipped pip install of
        # arize-agent-kit, leaving ~/.claude/settings.json pointing at missing hook scripts.
        if "$vp" -c "$check_cmd" 2>/dev/null \
            && "$vp" -c "import core" 2>/dev/null \
            && [[ -x "${VENV_DIR}/bin/arize-codex-buffer" ]]; then
            info "Venv already has required packages"
            return 0
        fi
    fi

    info "Creating venv..."
    if ! "$python_cmd" -m venv "$VENV_DIR" 2>/dev/null; then
        err "Failed to create venv with $python_cmd"
        err "You may need to install the venv module: apt install python3-venv (Debian/Ubuntu)"
        return 1
    fi

    local pip
    pip=$(venv_pip) || { err "pip not found in venv"; return 1; }

    # Install the package (core + pyyaml + CLI entry points)
    info "Installing arize-agent-kit into venv..."
    if ! "$pip" install --quiet "$INSTALL_DIR" 2>/dev/null; then
        err "Failed to install arize-agent-kit package"
        return 1
    fi

    # Install Arize AX extras if needed
    if [[ "$backend_target" == "arize" ]]; then
        info "Installing Arize AX dependencies (opentelemetry-proto, grpcio)..."
        "$pip" install --quiet opentelemetry-proto grpcio 2>/dev/null || \
            warn "Failed to install Arize AX dependencies — gRPC export may not work"
    fi

    info "Venv ready at ${VENV_DIR}"
}

# ---------------------------------------------------------------------------
# Config writing
# ---------------------------------------------------------------------------
write_config() {
    local backend_target="$1"
    local harness_name="$2"
    local phoenix_endpoint="$3"
    local phoenix_api_key="$4"
    local arize_api_key="$5"
    local arize_space_id="$6"
    local arize_endpoint="$7"
    local project_name="${8:-$harness_name}"
    local per_harness="${9:-false}"

    # If config already exists and venv has yaml, just add/update harness entry
    local vp
    vp=$(venv_python 2>/dev/null) || true
    if [[ -f "$CONFIG_FILE" && -n "$vp" && -n "$harness_name" ]]; then
        if "$vp" -c "
import yaml, os, sys

config_file = '${CONFIG_FILE}'
harness_name = '${harness_name}'
project_name = '${project_name}'
per_harness = '${per_harness}' == 'true'

with open(config_file) as f:
    config = yaml.safe_load(f) or {}

harness_entry = config.setdefault('harnesses', {}).setdefault(harness_name, {})
harness_entry['project_name'] = project_name

if per_harness:
    backend_target = '${backend_target}'
    harness_backend = harness_entry.setdefault('backend', {})
    harness_backend['target'] = backend_target
    if backend_target == 'phoenix':
        harness_backend['phoenix'] = {
            'endpoint': '${phoenix_endpoint}',
            'api_key': '${phoenix_api_key}',
        }
    elif backend_target == 'arize':
        harness_backend['arize'] = {
            'endpoint': '${arize_endpoint}',
            'api_key': '${arize_api_key}',
            'space_id': '${arize_space_id}',
        }

fd = os.open(config_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as f:
    yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
" 2>/dev/null; then
            info "Added harness '${harness_name}' to ${CONFIG_FILE}"
            return 0
        fi
    fi

    # Fresh config — write YAML
    mkdir -p "$(dirname "$CONFIG_FILE")"

    local harnesses_yaml="harnesses: {}"
    if [[ -n "$harness_name" ]]; then
        if [[ "$per_harness" == true ]]; then
            if [[ "$backend_target" == "phoenix" ]]; then
                harnesses_yaml="harnesses:
  ${harness_name}:
    project_name: \"${project_name}\"
    backend:
      target: \"phoenix\"
      phoenix:
        endpoint: \"${phoenix_endpoint}\"
        api_key: \"${phoenix_api_key}\""
            else
                harnesses_yaml="harnesses:
  ${harness_name}:
    project_name: \"${project_name}\"
    backend:
      target: \"arize\"
      arize:
        endpoint: \"${arize_endpoint}\"
        api_key: \"${arize_api_key}\"
        space_id: \"${arize_space_id}\""
            fi
        else
            harnesses_yaml="harnesses:
  ${harness_name}:
    project_name: \"${project_name}\""
        fi
    fi

    cat > "$CONFIG_FILE" <<CFGEOF
backend:
  target: "${backend_target}"
  phoenix:
    endpoint: "${phoenix_endpoint}"
    api_key: "${phoenix_api_key}"
  arize:
    endpoint: "${arize_endpoint}"
    api_key: "${arize_api_key}"
    space_id: "${arize_space_id}"
${harnesses_yaml}
CFGEOF
    chmod 600 "$CONFIG_FILE"
    info "Wrote shared config to ${CONFIG_FILE} (backend=${backend_target}, harness=${harness_name:-none})"
}

# ---------------------------------------------------------------------------
# Codex buffer service lifecycle
# ---------------------------------------------------------------------------
health_check() {
    local port="${1:-4318}"
    curl -sf --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null 2>&1
}

_stop_pid_file() {
    local pid_file="$1"
    local label="$2"
    [[ -f "$pid_file" ]] || return 0
    local pid
    pid=$(cat "$pid_file" 2>/dev/null) || { rm -f "$pid_file"; return 0; }
    [[ "$pid" =~ ^[0-9]+$ ]] || { rm -f "$pid_file"; return 0; }

    if kill -0 "$pid" 2>/dev/null; then
        info "Stopping ${label} (PID ${pid})..."
        kill "$pid" 2>/dev/null || true
        local attempts=0
        while kill -0 "$pid" 2>/dev/null && [[ $attempts -lt 50 ]]; do
            sleep 0.1
            attempts=$((attempts + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            warn "${label} did not exit gracefully — sending SIGKILL"
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    rm -f "$pid_file"
}

stop_codex_buffer() {
    # Stop legacy collector PID (handles upgrades from old installs)
    _stop_pid_file "$PID_FILE" "legacy collector"
    # Stop new buffer service PID
    _stop_pid_file "$BUFFER_PID_FILE" "buffer service"
}

start_codex_buffer() {
    local buffer_port="4318"
    # Legacy installs may still have collector.port in config
    local cfg_port
    cfg_port=$(cfg_get "collector.port") || true
    [[ -n "$cfg_port" ]] && buffer_port="$cfg_port"

    # Check if already running
    if health_check "$buffer_port"; then
        info "Codex buffer service is already running"
        return 0
    fi

    # Clean stale PID file
    if [[ -f "$BUFFER_PID_FILE" ]]; then
        local old_pid
        old_pid=$(cat "$BUFFER_PID_FILE" 2>/dev/null) || true
        if [[ -n "$old_pid" ]] && ! kill -0 "$old_pid" 2>/dev/null; then
            rm -f "$BUFFER_PID_FILE"
        fi
    fi

    # Try the venv entry point first
    local ctl
    ctl=$(venv_bin "arize-codex-buffer")
    if [[ -f "$ctl" ]]; then
        if "$ctl" start >/dev/null 2>&1; then
            info "Codex buffer service started (listening on 127.0.0.1:${buffer_port})"
            return 0
        fi
    fi

    # Fallback: launch codex_buffer.py directly
    local buffer_py="${INSTALL_DIR}/core/codex_buffer.py"
    local vp
    vp=$(venv_python 2>/dev/null) || true
    if [[ -z "$vp" || ! -f "$buffer_py" ]]; then
        warn "Could not find buffer service runtime — buffer service will not start"
        return 1
    fi

    mkdir -p "$PID_DIR" "$LOG_DIR"
    info "Starting Codex buffer service..."
    nohup "$vp" "$buffer_py" >> "$BUFFER_LOG_FILE" 2>&1 &
    local bg_pid=$!

    # Wait for health (up to 3 seconds)
    local attempts=0
    while [[ $attempts -lt 30 ]]; do
        if health_check "$buffer_port"; then
            info "Codex buffer service started (listening on 127.0.0.1:${buffer_port})"
            return 0
        fi
        sleep 0.1
        attempts=$((attempts + 1))
    done

    if kill -0 "$bg_pid" 2>/dev/null; then
        warn "Buffer service did not become healthy within 3 seconds"
        warn "Check logs at ${BUFFER_LOG_FILE} for details"
        return 0
    fi

    warn "Failed to start buffer service (process exited)"
    return 1
}

# ---------------------------------------------------------------------------
# Codex buffer launcher script
# ---------------------------------------------------------------------------
write_buffer_launcher() {
    local python_cmd="$1"
    mkdir -p "$BIN_DIR"

    local launcher_python
    launcher_python=$(venv_python 2>/dev/null) || launcher_python="$python_cmd"
    local buffer_src="${INSTALL_DIR}/core/codex_buffer.py"

    cat > "$BUFFER_BIN" <<BINEOF
#!${launcher_python}
# Arize Agent Kit — Codex buffer service launcher
# Auto-generated by install.sh. Do not edit manually.
import runpy, sys
sys.argv[0] = '${buffer_src}'
runpy.run_path('${buffer_src}', run_name="__main__")
BINEOF
    chmod +x "$BUFFER_BIN"
    info "Installed buffer launcher at ${BUFFER_BIN}"
}

# ---------------------------------------------------------------------------
# Backend credential collection
# ---------------------------------------------------------------------------
collect_backend_credentials() {
    local harness_name="${1:-}"

    # Defaults — set as globals so caller can read them
    CRED_PHOENIX_ENDPOINT="http://localhost:6006"
    CRED_PHOENIX_API_KEY=""
    CRED_ARIZE_API_KEY=""
    CRED_ARIZE_SPACE_ID=""
    CRED_ARIZE_ENDPOINT="otlp.arize.com:443"
    CRED_BUFFER_PORT=4318
    CRED_BACKEND_TARGET=""
    CRED_PER_HARNESS=false

    # Detect from environment
    if [[ -n "${ARIZE_API_KEY:-}" && -n "${ARIZE_SPACE_ID:-}" ]]; then
        CRED_BACKEND_TARGET="arize"
        CRED_ARIZE_API_KEY="$ARIZE_API_KEY"
        CRED_ARIZE_SPACE_ID="$ARIZE_SPACE_ID"
        [[ -n "${ARIZE_OTLP_ENDPOINT:-}" ]] && CRED_ARIZE_ENDPOINT="$ARIZE_OTLP_ENDPOINT"
    elif [[ -n "${PHOENIX_ENDPOINT:-}" ]]; then
        CRED_BACKEND_TARGET="phoenix"
        CRED_PHOENIX_ENDPOINT="$PHOENIX_ENDPOINT"
        [[ -n "${PHOENIX_API_KEY:-}" ]] && CRED_PHOENIX_API_KEY="$PHOENIX_API_KEY"
    fi

    # If global backend already configured, offer reuse
    local existing_backend=""
    existing_backend=$(cfg_get "backend.target") || true
    if [[ -n "$existing_backend" && -n "$_tty_in" && -z "$CRED_BACKEND_TARGET" ]]; then
        echo ""
        info "Existing backend: ${existing_backend}"
        local override
        read -rp "  Use different backend for ${harness_name}? [y/N]: " override < "$_tty_in"
        if [[ "$override" =~ ^[Yy] ]]; then
            CRED_PER_HARNESS=true
            # Fall through to interactive prompt below
        else
            CRED_PER_HARNESS=false
            CRED_BACKEND_TARGET="$existing_backend"
            return 0
        fi
    fi

    # Interactive prompt if not detected
    if [[ -z "$CRED_BACKEND_TARGET" && -n "$_tty_in" ]]; then
        echo ""
        echo "  Choose a tracing backend:"
        echo ""
        echo "    1) Phoenix (self-hosted)"
        echo "    2) Arize AX (cloud)"
        echo ""
        local choice
        read -rp "  Backend [1/2]: " choice < "$_tty_in"
        case "$choice" in
            1|phoenix)
                CRED_BACKEND_TARGET="phoenix"
                local ep
                read -rp "  Phoenix endpoint [${CRED_PHOENIX_ENDPOINT}]: " ep < "$_tty_in"
                [[ -n "$ep" ]] && CRED_PHOENIX_ENDPOINT="$ep"
                tty_read_masked_line "  Phoenix API key (blank if none): "
                CRED_PHOENIX_API_KEY="$REPLY"
                ;;
            2|arize)
                CRED_BACKEND_TARGET="arize"
                tty_read_masked_line "  Arize API key: "
                CRED_ARIZE_API_KEY="$REPLY"
                if [[ -z "$CRED_ARIZE_API_KEY" ]]; then
                    err "Arize API key is required"
                    exit 1
                fi
                read -rp "  Arize space ID: " CRED_ARIZE_SPACE_ID < "$_tty_in"
                if [[ -z "$CRED_ARIZE_SPACE_ID" ]]; then
                    err "Arize space ID is required"
                    exit 1
                fi
                local ep
                read -rp "  Arize OTLP endpoint [${CRED_ARIZE_ENDPOINT}]: " ep < "$_tty_in"
                [[ -n "$ep" ]] && CRED_ARIZE_ENDPOINT="$ep"
                ;;
            *)
                err "Invalid choice: $choice"
                exit 1
                ;;
        esac

        # Buffer port prompt only for Codex
        if [[ "$harness_name" == "codex" ]]; then
            echo ""
            local port_str
            read -rp "  Buffer service port [${CRED_BUFFER_PORT}]: " port_str < "$_tty_in"
            if [[ -n "$port_str" ]]; then
                if [[ "$port_str" =~ ^[0-9]+$ ]]; then
                    CRED_BUFFER_PORT="$port_str"
                else
                    warn "Invalid port '${port_str}', using default ${CRED_BUFFER_PORT}"
                fi
            fi
        fi
    fi

    # Non-interactive fallback
    if [[ -z "$CRED_BACKEND_TARGET" ]]; then
        if [[ -z "$_tty_in" ]]; then
            echo ""
            warn "No backend credentials detected and no interactive terminal available."
            warn "To configure Arize AX, re-run with env vars:"
            warn "  ARIZE_API_KEY=... ARIZE_SPACE_ID=... curl -fsSL ... | bash -s -- claude"
            warn "Defaulting to Phoenix at ${CRED_PHOENIX_ENDPOINT}"
            echo ""
        fi
        CRED_BACKEND_TARGET="phoenix"
        info "Backend: Phoenix at ${CRED_PHOENIX_ENDPOINT}"
    fi
}

collect_project_name() {
    local harness_name="$1"
    local default_name="$harness_name"
    CRED_PROJECT_NAME="$default_name"

    if [[ -n "$_tty_in" ]]; then
        local name
        read -rp "  Set project name (default: ${default_name}): " name < "$_tty_in"
        [[ -n "$name" ]] && CRED_PROJECT_NAME="$name"
    fi
}

# ---------------------------------------------------------------------------
# Shared runtime setup (orchestrates venv, config, and optionally buffer service)
# ---------------------------------------------------------------------------
setup_shared_runtime() {
    local harness_name="${1:-}"
    header "Setting up shared runtime"

    mkdir -p "$BIN_DIR" "$PID_DIR" "$LOG_DIR"

    # Check for existing backend config
    local existing_backend=""
    local defer_harness_merge=false
    if [[ -f "$CONFIG_FILE" ]]; then
        # Try venv python first (if available from prior install)
        if [[ -x "${VENV_DIR}/bin/python3" ]] || [[ -x "${VENV_DIR}/bin/python" ]]; then
            existing_backend=$(cfg_get "backend.target") || true
        fi
        # If venv not available yet, peek at the YAML with grep
        if [[ -z "$existing_backend" ]]; then
            existing_backend=$(grep -A1 '^backend:' "$CONFIG_FILE" 2>/dev/null \
                | grep 'target:' | sed 's/.*target:[[:space:]]*//' | tr -d '"'"'" | head -1) || true
        fi
    fi

    # Always call collect_backend_credentials so the user gets the
    # per-harness override prompt when a global backend already exists.
    collect_backend_credentials "$harness_name"

    if [[ -n "$existing_backend" && "$CRED_PER_HARNESS" != true ]]; then
        info "Existing backend config found (${existing_backend}) — adding harness entry"
        if [[ -n "$harness_name" ]]; then
            defer_harness_merge=true
        fi
    fi

    # Collect project name for this harness
    collect_project_name "$harness_name"

    # Find Python
    local python_cmd
    python_cmd=$(find_python) || {
        warn "No Python 3.9+ interpreter found"
        warn "Install Python 3 and re-run the installer"
        if [[ -z "$existing_backend" ]]; then
            write_config "$CRED_BACKEND_TARGET" "$harness_name" \
                "$CRED_PHOENIX_ENDPOINT" "$CRED_PHOENIX_API_KEY" \
                "$CRED_ARIZE_API_KEY" "$CRED_ARIZE_SPACE_ID" "$CRED_ARIZE_ENDPOINT" \
                "$CRED_PROJECT_NAME" "$CRED_PER_HARNESS"
        fi
        return 0
    }
    info "Found Python: ${python_cmd} ($("$python_cmd" --version 2>&1))"

    local buffer_src="${INSTALL_DIR}/core/codex_buffer.py"
    local pyproject="${INSTALL_DIR}/pyproject.toml"

    # Venv + package install are required for Claude/Codex/Cursor hooks even when the
    # buffer module is absent from this checkout.
    if [[ -f "$pyproject" ]]; then
        setup_venv "$python_cmd" "$CRED_BACKEND_TARGET" || {
            warn "Venv setup failed — hooks and config CLI may not work"
        }
    else
        warn "No pyproject.toml at ${INSTALL_DIR} — cannot install Python hook entry points"
        warn "Use a full repo checkout here, or ./install.sh claude --branch <branch> (or ARIZE_INSTALL_BRANCH)"
    fi

    # Write/update config
    if [[ "$defer_harness_merge" == true ]]; then
        # Existing global config — merge harness entry (now that venv with pyyaml exists)
        local vp
        vp=$(venv_python 2>/dev/null) || true
        if [[ -n "$vp" ]]; then
            cfg_set "harnesses.${harness_name}.project_name" "${CRED_PROJECT_NAME}"
            info "Added harness '${harness_name}' to ${CONFIG_FILE}"
        else
            warn "Could not add harness '${harness_name}' to config — venv not available"
        fi
    elif [[ "$CRED_PER_HARNESS" == true && -n "$existing_backend" ]]; then
        # User chose per-harness override — write per-harness backend block
        local vp
        vp=$(venv_python 2>/dev/null) || true
        if [[ -n "$vp" ]]; then
            cfg_set "harnesses.${harness_name}.project_name" "${CRED_PROJECT_NAME}"
            cfg_set "harnesses.${harness_name}.backend.target" "${CRED_BACKEND_TARGET}"
            if [[ "$CRED_BACKEND_TARGET" == "phoenix" ]]; then
                cfg_set "harnesses.${harness_name}.backend.phoenix.endpoint" "${CRED_PHOENIX_ENDPOINT}"
                cfg_set "harnesses.${harness_name}.backend.phoenix.api_key" "${CRED_PHOENIX_API_KEY}"
            elif [[ "$CRED_BACKEND_TARGET" == "arize" ]]; then
                cfg_set "harnesses.${harness_name}.backend.arize.endpoint" "${CRED_ARIZE_ENDPOINT}"
                cfg_set "harnesses.${harness_name}.backend.arize.api_key" "${CRED_ARIZE_API_KEY}"
                cfg_set "harnesses.${harness_name}.backend.arize.space_id" "${CRED_ARIZE_SPACE_ID}"
            fi
            info "Added harness '${harness_name}' with per-harness backend to ${CONFIG_FILE}"
        else
            warn "Could not add harness '${harness_name}' to config — venv not available"
        fi
    else
        write_config "$CRED_BACKEND_TARGET" "$harness_name" \
            "${CRED_PHOENIX_ENDPOINT:-http://localhost:6006}" "${CRED_PHOENIX_API_KEY:-}" \
            "${CRED_ARIZE_API_KEY:-}" "${CRED_ARIZE_SPACE_ID:-}" "${CRED_ARIZE_ENDPOINT:-otlp.arize.com:443}" \
            "${CRED_PROJECT_NAME}" "${CRED_PER_HARNESS:-false}"
    fi

    # Only start buffer service for Codex
    if [[ "$harness_name" == "codex" ]]; then
        if [[ -f "$buffer_src" ]]; then
            write_buffer_launcher "$python_cmd"
            start_codex_buffer
        else
            warn "Buffer source not found at ${buffer_src} — buffer service will not start"
            warn "Use a checkout that includes core/codex_buffer.py, or reinstall with --branch / ARIZE_INSTALL_BRANCH"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Claude Code harness setup
# ---------------------------------------------------------------------------
setup_claude() {
    header "Setting up Arize tracing for Claude Code"

    local plugin_dir="${INSTALL_DIR}/claude-code-tracing"
    [[ -d "$plugin_dir" ]] || plugin_dir="${INSTALL_DIR}/plugins/claude-code-tracing"
    if [[ ! -d "$plugin_dir" ]]; then
        err "Claude Code tracing plugin not found in ${INSTALL_DIR}"
        exit 1
    fi
    info "Plugin installed at: ${plugin_dir}"

    # Register plugin and hooks in ~/.claude/settings.json
    local settings_file="${HOME}/.claude/settings.json"
    mkdir -p "$(dirname "$settings_file")"

    # Use Python for reliable JSON manipulation (no jq dependency)
    local vp
    vp=$(venv_python 2>/dev/null) || vp=$(find_python 2>/dev/null) || true
    if [[ -z "$vp" ]]; then
        err "Python is required for JSON manipulation but was not found"
        exit 1
    fi

    local venv_bin_dir="${VENV_DIR}/bin"
    local hook_smoke="${venv_bin_dir}/arize-hook-session-start"
    if [[ ! -x "$hook_smoke" ]]; then
        err "Cannot register Claude hooks — missing ${hook_smoke}"
        err "Install the package into the harness venv, then re-run: ./install.sh claude"
        err "  ${VENV_DIR}/bin/pip install ${INSTALL_DIR}"
        err "Or reinstall with a checkout that includes pyproject.toml, core/, and hook entry points."
        exit 1
    fi

    "$vp" -c "
import json, os, sys

plugin_dir = '${plugin_dir}'
settings_file = '${settings_file}'
venv_bin_dir = '${venv_bin_dir}'

CLAUDE_HOOK_EVENTS = {
    'SessionStart': 'arize-hook-session-start',
    'UserPromptSubmit': 'arize-hook-user-prompt-submit',
    'PreToolUse': 'arize-hook-pre-tool-use',
    'PostToolUse': 'arize-hook-post-tool-use',
    'Stop': 'arize-hook-stop',
    'SubagentStop': 'arize-hook-subagent-stop',
    'Notification': 'arize-hook-notification',
    'PermissionRequest': 'arize-hook-permission-request',
    'SessionEnd': 'arize-hook-session-end',
}

# Load existing settings
if os.path.isfile(settings_file):
    try:
        with open(settings_file) as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        settings = {}
else:
    settings = {}

# Add plugin reference
plugins = settings.setdefault('plugins', [])
has_plugin = any(
    (isinstance(p, str) and p == plugin_dir)
    or (isinstance(p, dict) and p.get('path') == plugin_dir)
    for p in plugins
)
if not has_plugin:
    plugins.append({'type': 'local', 'path': plugin_dir})

# Write hooks — use venv entry point paths
hooks = settings.setdefault('hooks', {})
for event, entry_point in CLAUDE_HOOK_EVENTS.items():
    hook_cmd = os.path.join(venv_bin_dir, entry_point)
    event_hooks = hooks.setdefault(event, [])
    already = any(
        h.get('command', '') == hook_cmd
        for entry in event_hooks
        for h in entry.get('hooks', [])
    )
    if not already:
        event_hooks.append({'hooks': [{'type': 'command', 'command': hook_cmd}]})

with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
"

    info "Registered tracing hooks in ${settings_file}"

    # Summary
    echo ""
    echo -e "  ${BOLD}Claude Agent SDK:${NC}"
    echo ""
    echo "    Pass the plugin path when launching your agent:"
    echo ""
    echo "      import { Agent } from '@anthropic-ai/agent-sdk';"
    echo ""
    echo "      const agent = new Agent({"
    echo "        plugins: ['${plugin_dir}'],"
    echo "        // ... other options"
    echo "      });"
    echo ""
    echo -e "  ${BOLD}Tracing:${NC}"
    echo ""
    echo "    Spans are sent directly to your configured backend."
    echo ""
    info "Setup complete! Test with: ARIZE_DRY_RUN=true claude"
}

# ---------------------------------------------------------------------------
# Cursor harness setup
# ---------------------------------------------------------------------------
setup_cursor() {
    header "Setting up Arize tracing for Cursor IDE"

    local plugin_dir="${INSTALL_DIR}/cursor-tracing"
    [[ -d "$plugin_dir" ]] || plugin_dir="${INSTALL_DIR}/plugins/cursor-tracing"
    if [[ ! -d "$plugin_dir" ]]; then
        err "Cursor tracing plugin not found in ${INSTALL_DIR}"
        exit 1
    fi
    info "Plugin installed at: ${plugin_dir}"

    local cursor_dir="${HOME}/.cursor"
    local state_dir="${STATE_BASE_DIR}/cursor"
    mkdir -p "$cursor_dir" "$state_dir"

    local hooks_file="${cursor_dir}/hooks.json"
    local hook_cmd
    hook_cmd=$(venv_bin "arize-hook-cursor")

    # Use Python for JSON manipulation
    local vp
    vp=$(venv_python 2>/dev/null) || vp=$(find_python 2>/dev/null) || true
    if [[ -z "$vp" ]]; then
        err "Python is required for JSON manipulation but was not found"
        exit 1
    fi

    "$vp" -c "
import json, os, shutil

hooks_file = '${hooks_file}'
hook_cmd = '${hook_cmd}'

CURSOR_HOOK_EVENTS = [
    'beforeSubmitPrompt', 'afterAgentResponse', 'afterAgentThought',
    'beforeShellExecution', 'afterShellExecution',
    'beforeMCPExecution', 'afterMCPExecution',
    'beforeReadFile', 'afterFileEdit', 'stop',
    'beforeTabFileRead', 'afterTabFileEdit',
]

if os.path.isfile(hooks_file):
    try:
        hooks_data = json.loads(open(hooks_file).read())
    except (json.JSONDecodeError, OSError):
        hooks_data = {'version': 1, 'hooks': {}}
    shutil.copy2(hooks_file, hooks_file + '.bak')
else:
    hooks_data = {'version': 1, 'hooks': {}}

hooks = hooks_data.setdefault('hooks', {})
for event in CURSOR_HOOK_EVENTS:
    event_list = hooks.setdefault(event, [])
    if not any(h.get('command') == hook_cmd for h in event_list):
        event_list.append({'command': hook_cmd})

with open(hooks_file, 'w') as f:
    json.dump(hooks_data, f, indent=2)
    f.write('\n')
"

    info "Registered Arize hooks in ${hooks_file}"

    echo ""
    echo -e "  ${BOLD}Cursor tracing setup complete!${NC}"
    echo ""
    echo -e "  ${BOLD}What was configured:${NC}"
    echo ""
    echo "    - Cursor hooks.json at ${hooks_file}"
    echo "      (12 hook events routing to ${hook_cmd})"
    echo "    - State directory at ${state_dir}"
    echo "    - Spans are sent directly to your configured backend"
    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo ""
    echo "    1. Restart Cursor IDE to pick up the new hooks"
    echo "    2. Start a conversation — spans will appear in your configured backend"
    echo ""
    info "Setup complete!"
}

# ---------------------------------------------------------------------------
# Codex harness setup
# ---------------------------------------------------------------------------
detect_shell_profile() {
    for name in .zshrc .bashrc .bash_profile; do
        if [[ -f "${HOME}/${name}" ]]; then
            echo "${HOME}/${name}"
            return 0
        fi
    done
    return 1
}

discover_real_codex() {
    local proxy_path="${HOME}/.local/bin/codex"
    local current
    current=$(command -v codex 2>/dev/null || true)
    [[ -z "$current" ]] && return 1

    if [[ "$current" == "$proxy_path" && -f "$proxy_path" ]]; then
        current=$(sed -n 's/^REAL_CODEX="\([^"]*\)"$/\1/p' "$proxy_path" | head -1)
    fi
    [[ -n "$current" && -x "$current" ]] || return 1
    echo "$current"
}

setup_codex() {
    header "Setting up Arize tracing for Codex CLI"

    local plugin_dir="${INSTALL_DIR}/codex-tracing"
    [[ -d "$plugin_dir" ]] || plugin_dir="${INSTALL_DIR}/plugins/codex-tracing"
    if [[ ! -d "$plugin_dir" ]]; then
        err "Codex tracing plugin not found in ${INSTALL_DIR}"
        exit 1
    fi
    info "Plugin installed at: ${plugin_dir}"

    local codex_config_dir="${HOME}/.codex"
    local codex_config="${codex_config_dir}/config.toml"
    local env_file="${codex_config_dir}/arize-env.sh"
    local notify_cmd
    notify_cmd=$(venv_bin "arize-hook-codex-notify")

    mkdir -p "$codex_config_dir"
    [[ -f "$codex_config" ]] || touch "$codex_config"

    # --- 1. Configure notify hook ---
    local notify_line="notify = [\"${notify_cmd}\"]"

    if grep -q "^notify" "$codex_config" 2>/dev/null; then
        cp "$codex_config" "${codex_config}.bak"
        sed -i.tmp "s|^notify.*|${notify_line}|" "$codex_config"
        rm -f "${codex_config}.tmp"
        info "Updated existing notify hook in config.toml"
    elif grep -qn '^\[' "$codex_config" 2>/dev/null; then
        # Insert before first section header
        local first_section
        first_section=$(grep -n '^\[' "$codex_config" | head -1 | cut -d: -f1)
        cp "$codex_config" "${codex_config}.bak"
        {
            head -n $((first_section - 1)) "${codex_config}.bak"
            echo ""
            echo "# Arize tracing — OpenInference spans per turn"
            echo "$notify_line"
            echo ""
            tail -n +"${first_section}" "${codex_config}.bak"
        } > "$codex_config"
        info "Added notify hook to config.toml"
    else
        echo "" >> "$codex_config"
        echo "# Arize tracing — OpenInference spans per turn" >> "$codex_config"
        echo "$notify_line" >> "$codex_config"
        info "Added notify hook to config.toml"
    fi

    # --- 2. Write env file template ---
    if [[ ! -f "$env_file" ]]; then
        cat > "$env_file" <<'ENVEOF'
# Arize Codex tracing environment
# Source this file in your shell profile or export vars before running codex.
#
# Uncomment and set the variables for your backend:

# Common
export ARIZE_TRACE_ENABLED=true
# export ARIZE_PROJECT_NAME=codex
# export ARIZE_USER_ID=

# Phoenix (self-hosted)
# export PHOENIX_ENDPOINT=http://localhost:6006

# Arize AX (cloud)
# export ARIZE_API_KEY=
# export ARIZE_SPACE_ID=
ENVEOF
        chmod 600 "$env_file"
        info "Created env file template at ${env_file}"
    else
        info "Env file already exists at ${env_file}"
    fi

    # --- 3. Configure OTLP exporter in config.toml ---
    local buffer_port
    # Legacy installs may still have collector.port in config
    buffer_port=$(cfg_get "collector.port") || true
    [[ -z "$buffer_port" ]] && buffer_port=4318

    # Remove old [otel] section if present
    if grep -q '^\[otel' "$codex_config" 2>/dev/null; then
        cp "$codex_config" "${codex_config}.bak"
        awk '
            BEGIN { skip=0 }
            /^\[otel(\.|\])/ { skip=1; next }
            skip && /^\[/ && $0 !~ /^\[otel(\.|\])/ { skip=0 }
            !skip { print }
        ' "${codex_config}.bak" > "$codex_config"
    fi

    # Also remove Arize comment lines above old [otel]
    if grep -q "# Arize shared collector" "$codex_config" 2>/dev/null; then
        sed -i.tmp '/# Arize shared collector/d' "$codex_config"
        rm -f "${codex_config}.tmp"
    fi
    if grep -q "# Arize Codex buffer service" "$codex_config" 2>/dev/null; then
        sed -i.tmp '/# Arize Codex buffer service/d' "$codex_config"
        rm -f "${codex_config}.tmp"
    fi

    cat >> "$codex_config" <<OTELEOF

# Arize Codex buffer service -- captures Codex events for rich span trees
[otel]
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:${buffer_port}/v1/logs"
protocol = "json"
OTELEOF
    info "Added [otel] exporter pointing to Codex buffer service (port ${buffer_port})"

    # --- 4. Install codex proxy wrapper ---
    local proxy_dir="${HOME}/.local/bin"
    local proxy_path="${proxy_dir}/codex"
    local proxy_backup="${proxy_dir}/codex.arize-backup"
    local proxy_template="${plugin_dir}/scripts/codex_proxy.sh"

    local real_codex_bin
    real_codex_bin=$(discover_real_codex || true)
    if [[ -z "$real_codex_bin" ]]; then
        warn "Could not find codex binary — skipping proxy install"
    else
        mkdir -p "$proxy_dir"
        if [[ -f "$proxy_path" ]] && ! grep -q "ARIZE_CODEX_PROXY" "$proxy_path" 2>/dev/null; then
            cp "$proxy_path" "$proxy_backup"
            info "Backed up existing ${proxy_path} to ${proxy_backup}"
        fi

        if [[ -f "$proxy_template" ]]; then
            local ctl_cmd
            ctl_cmd=$(venv_bin "arize-codex-buffer")
            sed \
                -e "s|__REAL_CODEX__|${real_codex_bin}|g" \
                -e "s|__ARIZE_ENV_FILE__|${env_file}|g" \
                -e "s|__SHARED_COLLECTOR_CTL__|${ctl_cmd}|g" \
                "$proxy_template" > "$proxy_path"
            chmod +x "$proxy_path"
            info "Installed codex proxy to ${proxy_path}"
        else
            # No template — try Python proxy entry point
            local py_proxy
            py_proxy=$(venv_bin "arize-codex-proxy")
            if [[ -f "$py_proxy" ]]; then
                cat > "$proxy_path" <<PROXYEOF
#!/bin/bash
REAL_CODEX="${real_codex_bin}"
ARIZE_CODEX_PROXY=true
exec "${py_proxy}" "\$@"
PROXYEOF
                chmod +x "$proxy_path"
                info "Installed codex proxy to ${proxy_path}"
            fi
        fi
    fi

    # --- 5. PATH management ---
    # Clean up old collector auto-start lines
    for profile in "${HOME}/.zshrc" "${HOME}/.bashrc"; do
        if [[ -f "$profile" ]] && grep -q "collector_ctl.sh" "$profile" 2>/dev/null; then
            cp "$profile" "${profile}.bak"
            sed -i.tmp '/arize-codex.*collector_ctl/d; /collector_ensure/d; /event_buffer_ensure/d' "$profile"
            rm -f "${profile}.tmp"
            info "Removed old collector auto-start from $(basename "$profile")"
        fi
    done

    # Offer to add ~/.local/bin to PATH
    if [[ -n "$_tty_in" && -n "$real_codex_bin" ]]; then
        local add_to_profile
        read -rp "  Ensure ~/.local/bin is prepended in your shell profile for the codex proxy? [Y/n]: " add_to_profile < "$_tty_in"
        add_to_profile="${add_to_profile:-y}"
        if [[ "$add_to_profile" =~ ^[Yy] ]]; then
            local shell_profile
            shell_profile=$(detect_shell_profile || true)
            if [[ -n "$shell_profile" ]]; then
                local path_marker="# Arize Codex tracing - prepend ~/.local/bin for codex proxy"
                if ! grep -q "prepend ~/.local/bin for codex proxy" "$shell_profile" 2>/dev/null; then
                    echo "" >> "$shell_profile"
                    echo "$path_marker" >> "$shell_profile"
                    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$shell_profile"
                    info "Added PATH update to $(basename "$shell_profile")"
                else
                    info "PATH update already present in $(basename "$shell_profile")"
                fi
            fi
        fi
    fi

    # Summary
    echo ""
    echo -e "  ${BOLD}Codex tracing setup complete!${NC}"
    echo ""
    echo -e "  ${BOLD}What was configured:${NC}"
    echo ""
    echo "    - Notify hook in ~/.codex/config.toml"
    echo "    - OTLP exporter in ~/.codex/config.toml (buffer service port ${buffer_port})"
    if [[ -n "$real_codex_bin" ]]; then
        echo "    - Codex proxy wrapper at ${proxy_path}"
        echo "      (real codex: ${real_codex_bin})"
    fi
    echo "    - Env file template at ${env_file}"
    echo ""
    echo "    View buffer service logs: tail -f ${BUFFER_LOG_FILE}"
    echo ""
    info "Setup complete! Test with: ARIZE_DRY_RUN=true codex"
}

# ---------------------------------------------------------------------------
# Skills installation
# ---------------------------------------------------------------------------
install_skills() {
    local harness="$1"
    local skills_src="${INSTALL_DIR}/${harness}-tracing/skills"

    if [[ ! -d "$skills_src" ]]; then
        warn "No skills found for ${harness} at ${skills_src}"
        return 0
    fi

    local target_dir=".agents/skills"
    mkdir -p "$target_dir"

    for skill_dir in "$skills_src"/*/; do
        [[ -d "$skill_dir" ]] || continue
        local skill_name
        skill_name=$(basename "$skill_dir")
        local link="${target_dir}/${skill_name}"

        if [[ -L "$link" ]]; then
            rm -f "$link"
        elif [[ -d "$link" ]]; then
            warn "Skipping ${skill_name}: ${link} already exists and is not a symlink"
            continue
        fi

        ln -s "$skill_dir" "$link"
        info "Linked skill: ${link} -> ${skill_dir}"
    done
}

# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
update_install() {
    local branch="${1:-$INSTALL_BRANCH}"
    local tarball_url="${2:-$TARBALL_URL}"

    header "Updating arize-agent-kit"

    if [[ ! -d "$INSTALL_DIR" ]]; then
        err "arize-agent-kit is not installed at ${INSTALL_DIR}"
        err "Run install first: install.sh claude, install.sh codex, or install.sh cursor"
        exit 1
    fi

    stop_codex_buffer

    if [[ -d "${INSTALL_DIR}/.git" ]]; then
        if ! git_sync_harness_repo "$branch"; then
            warn "Git sync failed — re-cloning"
            rm -rf "$INSTALL_DIR"
            install_repo "$branch" "$tarball_url"
        fi
    else
        info "No git repo found — re-downloading"
        rm -rf "$INSTALL_DIR"
        install_repo "$branch" "$tarball_url"
    fi

    # Re-install package
    local python_cmd
    python_cmd=$(venv_python 2>/dev/null) || python_cmd=$(find_python 2>/dev/null) || true
    if [[ -n "$python_cmd" ]]; then
        local pip
        pip=$(venv_pip 2>/dev/null) || true
        if [[ -n "$pip" ]]; then
            info "Reinstalling package..."
            "$pip" install --quiet "$INSTALL_DIR" 2>/dev/null || warn "Package reinstall failed"
        fi
    else
        warn "No Python found"
    fi

    # Only restart buffer service if Codex is configured
    local codex_configured
    codex_configured=$(cfg_get "harnesses.codex.project_name") || true
    if [[ -n "$codex_configured" ]]; then
        local buffer_src="${INSTALL_DIR}/core/codex_buffer.py"
        if [[ -f "$buffer_src" && -n "$python_cmd" ]]; then
            write_buffer_launcher "$python_cmd"
            start_codex_buffer
        fi
    fi

    # Clean up legacy collector artifacts
    rm -f "$COLLECTOR_BIN" "$PID_FILE" "$COLLECTOR_LOG_FILE"

    info "Update complete! Re-run 'install.sh claude', 'install.sh codex', or 'install.sh cursor' to reconfigure harness settings."
}

# ---------------------------------------------------------------------------
# Uninstall helpers
# ---------------------------------------------------------------------------
cleanup_claude_config() {
    local settings_file="${HOME}/.claude/settings.json"
    [[ -f "$settings_file" ]] || return 0

    local vp
    vp=$(venv_python 2>/dev/null) || vp=$(find_python 2>/dev/null) || true
    if [[ -z "$vp" ]]; then
        warn "Python not available — cannot clean up Claude settings automatically"
        return 0
    fi

    local plugin_dir="${INSTALL_DIR}/claude-code-tracing"
    local legacy_plugin_dir="${INSTALL_DIR}/plugins/claude-code-tracing"

    # Check what needs cleanup and prompt for each
    local has_plugin=0 has_hooks=0 has_env_keys=0
    local _cleanup_check
    _cleanup_check=$("$vp" -c "
import json, sys
try:
    settings = json.loads(open('${settings_file}').read())
except: settings = {}

plugin_dir = '${plugin_dir}'
legacy = '${legacy_plugin_dir}'
plugins = settings.get('plugins', [])
hp = 1 if any((isinstance(p,str) and p in (plugin_dir,legacy)) or (isinstance(p,dict) and p.get('path') in (plugin_dir,legacy)) for p in plugins) else 0

hooks = settings.get('hooks', {})
hh = 0
for entries in hooks.values():
    for e in entries:
        for h in e.get('hooks', []):
            if 'arize' in h.get('command','') or 'claude-code-tracing' in h.get('command',''):
                hh = 1; break

env = settings.get('env', {})
env_keys = ['ARIZE_TRACE_ENABLED','PHOENIX_ENDPOINT','PHOENIX_API_KEY','ARIZE_API_KEY','ARIZE_SPACE_ID','ARIZE_OTLP_ENDPOINT','ARIZE_PROJECT_NAME','ARIZE_USER_ID','ARIZE_DRY_RUN','ARIZE_VERBOSE','ARIZE_LOG_FILE']
he = 1 if any(k in env for k in env_keys) else 0

print(hp, hh, he)
" 2>/dev/null) || true
    read -r has_plugin has_hooks has_env_keys <<< "${_cleanup_check:-0 0 0}"

    local changed=false

    if [[ "$has_plugin" == "1" ]]; then
        if confirm "  Remove Arize Claude plugin path from ${settings_file}? [y/N]: " "n"; then
            changed=true
        fi
    fi

    if [[ "$has_hooks" == "1" ]]; then
        if confirm "  Remove Arize tracing hooks from ${settings_file}? [y/N]: " "n"; then
            changed=true
        fi
    fi

    if [[ "$has_env_keys" == "1" ]]; then
        if confirm "  Remove Arize env keys from ${settings_file}? [y/N]: " "n"; then
            changed=true
        fi
    fi

    if [[ "$changed" == true ]]; then
        "$vp" -c "
import json, os, sys

settings_file = '${settings_file}'
plugin_dir = '${plugin_dir}'
legacy = '${legacy_plugin_dir}'
ARIZE_ENV_KEYS = ['ARIZE_TRACE_ENABLED','PHOENIX_ENDPOINT','PHOENIX_API_KEY','ARIZE_API_KEY','ARIZE_SPACE_ID','ARIZE_OTLP_ENDPOINT','ARIZE_PROJECT_NAME','ARIZE_USER_ID','ARIZE_DRY_RUN','ARIZE_VERBOSE','ARIZE_LOG_FILE']

try:
    settings = json.loads(open(settings_file).read())
except: settings = {}

# Remove plugin references
plugins = settings.get('plugins', [])
settings['plugins'] = [p for p in plugins if not ((isinstance(p,str) and p in (plugin_dir,legacy)) or (isinstance(p,dict) and p.get('path') in (plugin_dir,legacy)))]

# Remove Arize tracing hooks
hooks = settings.get('hooks', {})
new_hooks = {}
for event, entries in hooks.items():
    filtered = []
    for entry in entries:
        entry_hooks = [h for h in entry.get('hooks',[]) if not ('arize' in h.get('command','') or 'claude-code-tracing' in h.get('command',''))]
        if entry_hooks:
            entry['hooks'] = entry_hooks
            filtered.append(entry)
    if filtered:
        new_hooks[event] = filtered
if new_hooks:
    settings['hooks'] = new_hooks
else:
    settings.pop('hooks', None)

# Remove env keys
env = settings.get('env', {})
for k in ARIZE_ENV_KEYS:
    env.pop(k, None)

with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
" 2>/dev/null
        info "Cleaned up Claude settings.json"
    fi

    # Remove Claude state directory
    local state_dir="${STATE_BASE_DIR}/claude-code"
    if [[ -d "$state_dir" ]]; then
        if confirm "  Remove Claude runtime state at ${state_dir}? [Y/n]: " "y"; then
            rm -rf "$state_dir"
            info "Removed ${state_dir}"
        fi
    fi
}

_uninstall_codex() {
    info "Removing Codex tracing configuration..."

    local codex_config_dir="${HOME}/.codex"
    local codex_config="${codex_config_dir}/config.toml"
    local proxy_dir="${HOME}/.local/bin"
    local proxy_path="${proxy_dir}/codex"
    local proxy_backup="${proxy_dir}/codex.arize-backup"

    # Remove notify hook and [otel] section from config.toml
    if [[ -f "$codex_config" ]]; then
        cp "$codex_config" "${codex_config}.bak"
        # Remove Arize comment lines and notify lines referencing arize
        sed -i.tmp '/^# Arize tracing/d' "$codex_config"
        sed -i.tmp '/^notify.*arize/d' "$codex_config"
        rm -f "${codex_config}.tmp"

        # Remove [otel] sections pointing at localhost buffer service
        if grep -q '^\[otel' "$codex_config" 2>/dev/null; then
            awk '
                BEGIN { skip=0 }
                /^\[otel(\.|\])/ { skip=1; next }
                skip && /^\[/ && $0 !~ /^\[otel(\.|\])/ { skip=0 }
                !skip { print }
            ' "$codex_config" > "${codex_config}.tmp" && mv "${codex_config}.tmp" "$codex_config"
        fi
        # Remove Arize shared collector / buffer service comments
        sed -i.tmp '/# Arize shared collector/d; /# Arize Codex buffer service/d' "$codex_config"
        rm -f "${codex_config}.tmp"
        info "Cleaned up config.toml"
    fi

    # Remove proxy
    if [[ -f "$proxy_path" ]] && grep -qi "arize\|ARIZE_CODEX_PROXY" "$proxy_path" 2>/dev/null; then
        rm -f "$proxy_path"
        info "Removed codex proxy from ${proxy_path}"
    fi
    if [[ -f "$proxy_backup" ]]; then
        mv "$proxy_backup" "$proxy_path"
        chmod +x "$proxy_path"
        info "Restored previous codex wrapper to ${proxy_path}"
    fi

    # Clean up PATH injection from shell profiles
    for profile in "${HOME}/.zshrc" "${HOME}/.bashrc" "${HOME}/.bash_profile"; do
        if [[ -f "$profile" ]]; then
            local needs_cleanup=false
            if grep -q "prepend ~/.local/bin for codex proxy" "$profile" 2>/dev/null; then
                needs_cleanup=true
            fi
            if grep -q "collector_ctl.sh" "$profile" 2>/dev/null; then
                needs_cleanup=true
            fi
            if [[ "$needs_cleanup" == true ]]; then
                cp "$profile" "${profile}.bak"
                sed -i.tmp '/Arize Codex tracing - prepend/d' "$profile"
                sed -i.tmp '/export PATH="\$HOME\/\.local\/bin:\$PATH"/d' "$profile"
                sed -i.tmp '/arize-codex.*collector_ctl/d; /collector_ensure/d; /event_buffer_ensure/d' "$profile"
                rm -f "${profile}.tmp"
                info "Cleaned up $(basename "$profile")"
            fi
        fi
    done

    # Remove state and env file
    rm -rf "${STATE_BASE_DIR}/codex"
    [[ -f "${codex_config_dir}/arize-env.sh" ]] && rm -f "${codex_config_dir}/arize-env.sh" && info "Removed ${codex_config_dir}/arize-env.sh"

    cfg_delete "harnesses.codex"
    info "Codex tracing cleanup complete."
}

_uninstall_cursor() {
    info "Removing Cursor tracing configuration..."

    local hooks_file="${HOME}/.cursor/hooks.json"
    local hook_cmd
    hook_cmd=$(venv_bin "arize-hook-cursor")
    local bash_hook_cmd="bash ${INSTALL_DIR}/cursor-tracing/hooks/hook-handler.sh"

    if [[ -f "$hooks_file" ]]; then
        local vp
        vp=$(venv_python 2>/dev/null) || vp=$(find_python 2>/dev/null) || true
        if [[ -n "$vp" ]]; then
            "$vp" -c "
import json, os

hooks_file = '${hooks_file}'
hook_cmd = '${hook_cmd}'
bash_hook_cmd = '${bash_hook_cmd}'

try:
    hooks_data = json.loads(open(hooks_file).read())
except (json.JSONDecodeError, OSError):
    exit(0)

hooks = hooks_data.get('hooks', {})
new_hooks = {}
for event, entries in hooks.items():
    filtered = [h for h in entries if h.get('command') not in (hook_cmd, bash_hook_cmd) and 'arize' not in h.get('command','').lower()]
    if filtered:
        new_hooks[event] = filtered
hooks_data['hooks'] = new_hooks

if not new_hooks:
    os.unlink(hooks_file)
else:
    with open(hooks_file, 'w') as f:
        json.dump(hooks_data, f, indent=2)
        f.write('\n')
" 2>/dev/null
            if [[ -f "$hooks_file" ]]; then
                info "Removed Arize hooks from ${hooks_file} (other hooks preserved)"
            else
                info "Removed ${hooks_file} (no hooks remaining)"
            fi
        fi
    fi

    rm -rf "${STATE_BASE_DIR}/cursor"
    cfg_delete "harnesses.cursor"
    info "Cursor tracing cleanup complete."
}

do_uninstall() {
    header "Uninstalling arize-agent-kit"

    # Stop buffer service and any legacy collector
    info "Stopping background services..."
    stop_codex_buffer

    # Clean up each harness
    if [[ -d "${INSTALL_DIR}/codex-tracing" ]] || [[ -d "${HOME}/.codex" ]]; then
        _uninstall_codex
    fi

    if [[ -d "${INSTALL_DIR}/cursor-tracing" ]] || [[ -f "${HOME}/.cursor/hooks.json" ]] || [[ -d "${STATE_BASE_DIR}/cursor" ]]; then
        _uninstall_cursor
    fi

    info "Checking Claude tracing configuration..."
    cleanup_claude_config

    # Remove shared runtime (buffer service + legacy collector artifacts)
    info "Removing shared runtime..."
    rm -f "$BUFFER_BIN" "$BUFFER_PID_FILE" "$BUFFER_LOG_FILE"
    rm -f "$COLLECTOR_BIN" "$PID_FILE" "$COLLECTOR_LOG_FILE"
    [[ -d "$VENV_DIR" ]] && rm -rf "$VENV_DIR" && info "Removed venv"

    # Remove empty directories
    rmdir "$BIN_DIR" 2>/dev/null || true
    rmdir "$PID_DIR" 2>/dev/null || true
    rmdir "$LOG_DIR" 2>/dev/null || true

    # Remove config and install directory
    if [[ -f "$CONFIG_FILE" ]]; then
        rm -f "$CONFIG_FILE"
        info "Removed ${CONFIG_FILE}"
    fi

    if [[ -d "$INSTALL_DIR" ]]; then
        rm -rf "$INSTALL_DIR"
        info "Removed ${INSTALL_DIR}"
    else
        info "Repository checkout already absent at ${INSTALL_DIR}"
    fi

    echo ""
    echo "  The following may need manual cleanup:"
    echo ""
    echo "  - Claude Agent SDK: remove any hardcoded local plugin path from your application code"
    echo "  - Claude Code marketplace installs are managed separately by Claude"
    echo "  - Shell profile: remove any manual 'source ~/.codex/arize-env.sh' lines you added"
    echo ""
    info "Uninstall complete."
}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
usage() {
    echo ""
    echo "  Arize Agent Kit Installer"
    echo ""
    echo "  Usage: install.sh <command> [flags]"
    echo ""
    echo "  Commands:"
    echo "    claude      Install and configure tracing for Claude Code / Agent SDK"
    echo "    codex       Install and configure tracing for OpenAI Codex CLI"
    echo "    cursor      Install and configure tracing for Cursor IDE"
    echo "    update      Update the installed arize-agent-kit to latest"
    echo "    uninstall   Remove arize-agent-kit and print cleanup reminders"
    echo ""
    echo "  Flags:"
    echo "    --with-skills   Symlink harness skills into .agents/skills/ in the current directory"
    echo "    --branch NAME   Install from a specific git branch (default: main)"
    echo ""
    echo "  Examples:"
    echo "    curl -sSL .../install.sh | bash -s -- claude"
    echo "    ./install.sh codex --with-skills"
    echo "    ./install.sh cursor --branch dev"
    echo "    ./install.sh update"
    echo "    ./install.sh uninstall"
    echo ""
}

main() {
    local cmd="${1:-}"
    shift || true

    # Parse flags
    local with_skills=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --with-skills)
                with_skills=true
                shift
                ;;
            --branch)
                INSTALL_BRANCH="${2:-main}"
                TARBALL_URL="https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/${INSTALL_BRANCH}.tar.gz"
                shift 2
                ;;
            *)
                shift
                ;;
        esac
    done

    case "$cmd" in
        claude)
            install_repo
            setup_shared_runtime "claude-code"
            setup_claude
            [[ "$with_skills" == true ]] && install_skills "claude-code"
            ;;
        codex)
            install_repo
            setup_shared_runtime "codex"
            setup_codex
            [[ "$with_skills" == true ]] && install_skills "codex"
            ;;
        cursor)
            install_repo
            setup_shared_runtime "cursor"
            setup_cursor
            [[ "$with_skills" == true ]] && install_skills "cursor"
            ;;
        update)
            update_install
            ;;
        uninstall)
            do_uninstall
            ;;
        -h|--help|help)
            usage
            ;;
        "")
            usage
            exit 1
            ;;
        *)
            err "Unknown command: ${cmd}"
            usage
            exit 1
            ;;
    esac
}

main "$@"
