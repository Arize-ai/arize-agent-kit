#!/bin/bash
# Arize Agent Kit — Curl-pipe installer for non-marketplace harnesses
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- update
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall
#
# Installs the arize-agent-kit repo, sets up the shared background collector/exporter,
# and configures tracing for the specified harness.
# Idempotent — safe to run multiple times.

set -euo pipefail

# --- Constants ---
REPO_URL="https://github.com/Arize-ai/arize-agent-kit.git"
INSTALL_BRANCH="${ARIZE_INSTALL_BRANCH:-main}"
TARBALL_URL="https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/${INSTALL_BRANCH}.tar.gz"
INSTALL_DIR="${HOME}/.arize/harness"

# Shared collector layout
SHARED_CONFIG="${INSTALL_DIR}/config.json"
SHARED_BIN_DIR="${INSTALL_DIR}/bin"
SHARED_COLLECTOR_BIN="${SHARED_BIN_DIR}/arize-collector"
SHARED_RUN_DIR="${INSTALL_DIR}/run"
SHARED_PID_FILE="${SHARED_RUN_DIR}/collector.pid"
SHARED_LOG_DIR="${INSTALL_DIR}/logs"
SHARED_LOG_FILE="${SHARED_LOG_DIR}/collector.log"
SHARED_VENV_DIR="${INSTALL_DIR}/venv"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[arize]${NC} $*"; }
warn()  { echo -e "${YELLOW}[arize]${NC} $*"; }
err()   { echo -e "${RED}[arize]${NC} $*" >&2; }
header() { echo -e "\n${BOLD}${BLUE}$*${NC}\n"; }

# --- Helpers ---
command_exists() {
  command -v "$1" &>/dev/null
}

# Find a working Python 3 interpreter
find_python() {
  local candidates=(python3 python /usr/bin/python3 /usr/local/bin/python3 "$HOME/.local/bin/python3")
  # Check conda
  local conda_base
  conda_base=$(conda info --base 2>/dev/null) && [[ -n "$conda_base" ]] && candidates+=("${conda_base}/bin/python3")
  # Check pyenv
  [[ -d "$HOME/.pyenv/shims" ]] && candidates+=("$HOME/.pyenv/shims/python3")
  # Check common brew paths
  [[ -x "/opt/homebrew/bin/python3" ]] && candidates+=("/opt/homebrew/bin/python3")

  for p in "${candidates[@]}"; do
    if command -v "$p" &>/dev/null && "$p" -c "import sys; assert sys.version_info >= (3, 8)" 2>/dev/null; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

# Create an isolated venv for the collector with gRPC dependencies
setup_collector_venv() {
  local python_cmd="$1"
  local backend_target="$2"

  # Phoenix doesn't need the venv — it's pure stdlib
  if [[ "$backend_target" != "arize" ]]; then
    info "Phoenix backend selected — no additional Python packages needed"
    return 0
  fi

  # Check if venv already has the packages
  if [[ -x "${SHARED_VENV_DIR}/bin/python" ]] || [[ -x "${SHARED_VENV_DIR}/Scripts/python.exe" ]]; then
    local venv_python="${SHARED_VENV_DIR}/bin/python"
    [[ -x "$venv_python" ]] || venv_python="${SHARED_VENV_DIR}/Scripts/python.exe"
    if "$venv_python" -c "import grpc; import opentelemetry" 2>/dev/null; then
      info "Collector venv already has required packages"
      return 0
    fi
  fi

  info "Creating collector venv for Arize AX gRPC export..."
  "$python_cmd" -m venv "$SHARED_VENV_DIR" 2>/dev/null || {
    err "Failed to create venv with $python_cmd"
    err "You may need to install the venv module: apt install python3-venv (Debian/Ubuntu)"
    return 1
  }

  local venv_pip="${SHARED_VENV_DIR}/bin/pip"
  [[ -x "$venv_pip" ]] || venv_pip="${SHARED_VENV_DIR}/Scripts/pip.exe"

  info "Installing opentelemetry-proto and grpcio into collector venv..."
  "$venv_pip" install --quiet opentelemetry-proto grpcio 2>&1 | while read -r line; do
    _log_to_file "pip: $line" 2>/dev/null || true
  done

  if [[ $? -ne 0 ]]; then
    err "Failed to install Python packages"
    err "Check logs at ${SHARED_LOG_FILE}"
    return 1
  fi

  info "Collector venv ready at ${SHARED_VENV_DIR}"
}

confirm_optional_cleanup() {
  local prompt="$1"
  local default="${2:-n}"
  local reply

  if [[ ! -t 0 ]]; then
    [[ "$default" =~ ^[Yy]$ ]]
    return
  fi

  read -rp "$prompt" reply
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy]$ ]]
}

# --- install_repo: clone or tarball fallback ---
install_repo() {
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Repository already installed at ${INSTALL_DIR}"
    info "Pulling latest changes..."
    git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || {
      warn "git pull failed — re-cloning"
      rm -rf "$INSTALL_DIR"
      install_repo
      return
    }
    return
  fi

  if [[ -d "$INSTALL_DIR" ]] && [[ ! -d "${INSTALL_DIR}/.git" ]]; then
    info "Existing non-git install found — removing for fresh clone"
    rm -rf "$INSTALL_DIR"
  fi

  if command_exists git; then
    info "Cloning arize-agent-kit..."
    git clone --depth 1 --branch "$INSTALL_BRANCH" "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || {
      warn "git clone failed — falling back to tarball"
      install_repo_tarball
      return
    }
  else
    install_repo_tarball
  fi
}

install_repo_tarball() {
  info "Downloading arize-agent-kit tarball..."
  local tmp_tar
  tmp_tar="$(mktemp)"
  trap 'rm -f "$tmp_tar"' RETURN

  if command_exists curl; then
    curl -sSL "$TARBALL_URL" -o "$tmp_tar"
  elif command_exists wget; then
    wget -qO "$tmp_tar" "$TARBALL_URL"
  else
    err "Neither curl nor wget found — cannot download"
    exit 1
  fi

  mkdir -p "$INSTALL_DIR"
  tar xzf "$tmp_tar" --strip-components=1 -C "$INSTALL_DIR"
  info "Extracted to ${INSTALL_DIR}"
}

# --- setup_shared_collector: configure and start the shared collector ---
setup_shared_collector() {
  header "Setting up shared background collector"

  # Ensure shared directories exist
  mkdir -p "$SHARED_BIN_DIR"
  mkdir -p "$SHARED_RUN_DIR"
  mkdir -p "$SHARED_LOG_DIR"

  # --- Write shared config ---
  local harness_name="${1:-}"
  local harness_project="${harness_name:-default}"

  # If config already exists with a valid backend, just add the harness entry
  local existing_backend=""
  if command_exists jq && [[ -f "$SHARED_CONFIG" ]]; then
    existing_backend=$(jq -r '.backend.target // empty' "$SHARED_CONFIG" 2>/dev/null) || true
  fi

  local backend_target=""

  if [[ -n "$existing_backend" ]]; then
    backend_target="$existing_backend"
    info "Existing backend config found (${existing_backend}) — adding harness entry"
    if [[ -n "$harness_name" ]]; then
      local tmp_config="${SHARED_CONFIG}.tmp.$$"
      jq --arg hn "$harness_name" --arg pn "$harness_project" \
         '.harnesses[$hn].project_name = $pn' \
         "$SHARED_CONFIG" > "$tmp_config" && mv "$tmp_config" "$SHARED_CONFIG"
      chmod 600 "$SHARED_CONFIG"
      info "Added harness '${harness_name}' to ${SHARED_CONFIG}"
    fi
    # Skip backend credential prompts — existing config is preserved
  else
    # No existing config — collect backend credentials
    local phoenix_endpoint="http://localhost:6006"
    local phoenix_api_key=""
    local arize_api_key=""
    local arize_space_id=""
    local arize_endpoint="otlp.arize.com:443"

    # Detect backend from environment variables (non-interactive or pre-set)
    if [[ -n "${ARIZE_API_KEY:-}" && -n "${ARIZE_SPACE_ID:-}" ]]; then
      backend_target="arize"
      arize_api_key="$ARIZE_API_KEY"
      arize_space_id="$ARIZE_SPACE_ID"
      [[ -n "${ARIZE_OTLP_ENDPOINT:-}" ]] && arize_endpoint="$ARIZE_OTLP_ENDPOINT"
    elif [[ -n "${PHOENIX_ENDPOINT:-}" ]]; then
      backend_target="phoenix"
      phoenix_endpoint="$PHOENIX_ENDPOINT"
      [[ -n "${PHOENIX_API_KEY:-}" ]] && phoenix_api_key="$PHOENIX_API_KEY"
    fi

    # Interactive prompt if backend not detected
    # Try /dev/tty for input when stdin is piped (e.g. curl | bash)
    local tty_in=""
    if [[ -t 0 ]]; then
      tty_in="/dev/stdin"
    elif exec 3< /dev/tty 2>/dev/null; then
      exec 3<&-
      tty_in="/dev/tty"
    fi
    if [[ -z "$backend_target" && -n "$tty_in" ]]; then

      echo ""
      echo "  Choose a tracing backend:"
      echo ""
      echo "    1) Phoenix (self-hosted)"
      echo "    2) Arize AX (cloud)"
      echo ""
      local choice=""
      read -rp "  Backend [1/2]: " choice < "$tty_in"
      case "$choice" in
        1|phoenix)
          backend_target="phoenix"
          read -rp "  Phoenix endpoint [http://localhost:6006]: " phoenix_endpoint < "$tty_in"
          phoenix_endpoint="${phoenix_endpoint:-http://localhost:6006}"
          read -rp "  Phoenix API key (blank if none): " phoenix_api_key < "$tty_in"
          ;;
        2|arize)
          backend_target="arize"
          read -rp "  Arize API key: " arize_api_key < "$tty_in"
          if [[ -z "$arize_api_key" ]]; then
            err "Arize API key is required"
            exit 1
          fi
          read -rp "  Arize space ID: " arize_space_id < "$tty_in"
          if [[ -z "$arize_space_id" ]]; then
            err "Arize space ID is required"
            exit 1
          fi
          read -rp "  Arize OTLP endpoint [otlp.arize.com:443]: " arize_endpoint < "$tty_in"
          arize_endpoint="${arize_endpoint:-otlp.arize.com:443}"
          ;;
        *)
          err "Invalid choice: $choice"
          exit 1
          ;;
      esac

      # Collector port (optional, default 4318)
      echo ""
      local collector_port="4318"
      read -rp "  Collector port [4318]: " collector_port < "$tty_in"
      collector_port="${collector_port:-4318}"
    fi

    # Non-interactive without env vars
    if [[ -z "$backend_target" ]]; then
      if [[ -z "$tty_in" ]]; then
        # Piped install (curl | bash) without env vars — can't prompt
        echo ""
        warn "No backend credentials detected and no interactive terminal available."
        warn "To configure Arize AX, re-run with env vars:"
        warn "  ARIZE_API_KEY=... ARIZE_SPACE_ID=... curl -fsSL ... | bash -s -- claude"
        warn "Defaulting to Phoenix at ${phoenix_endpoint}"
        echo ""
      fi
      backend_target="phoenix"
      info "Backend: Phoenix at ${phoenix_endpoint}"
    fi

    local collector_port="${collector_port:-4318}"

    # Write fresh config with backend + harness
    local harnesses_json="{}"
    if [[ -n "$harness_name" ]]; then
      harnesses_json="{\"${harness_name}\": {\"project_name\": \"${harness_project}\"}}"
    fi
    local config_json
    config_json=$(cat <<CFGEOF
{
  "collector": {
    "host": "127.0.0.1",
    "port": ${collector_port}
  },
  "backend": {
    "target": "${backend_target}",
    "phoenix": {
      "endpoint": "${phoenix_endpoint}",
      "api_key": "${phoenix_api_key}"
    },
    "arize": {
      "endpoint": "${arize_endpoint}",
      "api_key": "${arize_api_key}",
      "space_id": "${arize_space_id}"
    }
  },
  "harnesses": ${harnesses_json}
}
CFGEOF
    )
    if command_exists jq; then
      echo "$config_json" | jq . > "$SHARED_CONFIG"
    else
      echo "$config_json" > "$SHARED_CONFIG"
    fi
    chmod 600 "$SHARED_CONFIG"
    info "Wrote shared config to ${SHARED_CONFIG} (backend=${backend_target}, harness=${harness_name:-none})"
  fi

  # --- Find Python ---
  local python_cmd
  python_cmd=$(find_python) || {
    warn "No Python 3.8+ interpreter found"
    warn "Install Python 3 and re-run the installer to start the collector"
    return 0
  }
  info "Found Python: ${python_cmd} ($("$python_cmd" --version 2>&1))"

  # --- Install collector runtime ---
  local collector_src="${INSTALL_DIR}/core/collector.py"
  if [[ ! -f "$collector_src" ]]; then
    warn "Collector source not found at ${collector_src} — collector will not start"
    warn "Re-run install after updating to get the shared collector"
    return 0
  fi

  # --- Set up venv for Arize AX (installs grpcio + opentelemetry-proto) ---
  setup_collector_venv "$python_cmd" "$backend_target" || {
    warn "Collector venv setup failed — Arize AX export will not work"
    warn "Phoenix export will still work (no additional packages needed)"
  }

  # --- Create launcher script ---
  # Use venv python if it exists (Arize AX), fall back to system python (Phoenix)
  local launcher_python="$python_cmd"
  if [[ -x "${SHARED_VENV_DIR}/bin/python" ]]; then
    launcher_python="${SHARED_VENV_DIR}/bin/python"
  elif [[ -x "${SHARED_VENV_DIR}/Scripts/python.exe" ]]; then
    launcher_python="${SHARED_VENV_DIR}/Scripts/python.exe"
  fi

  cat > "$SHARED_COLLECTOR_BIN" <<BINEOF
#!/bin/bash
# Arize Agent Kit — shared collector launcher
# Auto-generated by install.sh. Do not edit manually.
exec "${launcher_python}" "${collector_src}" "\$@"
BINEOF
  chmod +x "$SHARED_COLLECTOR_BIN"
  info "Installed collector launcher at ${SHARED_COLLECTOR_BIN}"

  # --- Start the collector ---
  start_shared_collector
}

# --- start_shared_collector: start or verify the shared collector process ---
start_shared_collector() {
  # Read port from config (default 4318)
  local collector_port="4318"
  if command_exists jq && [[ -f "$SHARED_CONFIG" ]]; then
    local cfg_port
    cfg_port=$(jq -r '.collector.port // empty' "$SHARED_CONFIG" 2>/dev/null) || true
    [[ -n "$cfg_port" ]] && collector_port="$cfg_port"
  fi

  # Check if already running via health endpoint
  if curl -sf "http://127.0.0.1:${collector_port}/health" >/dev/null 2>&1; then
    info "Shared collector is already running"
    return 0
  fi

  # Clean up stale PID file
  if [[ -f "$SHARED_PID_FILE" ]]; then
    local old_pid
    old_pid=$(cat "$SHARED_PID_FILE" 2>/dev/null)
    if [[ -n "$old_pid" ]] && ! kill -0 "$old_pid" 2>/dev/null; then
      rm -f "$SHARED_PID_FILE"
    fi
  fi

  if [[ ! -x "$SHARED_COLLECTOR_BIN" ]]; then
    warn "Collector binary not found at ${SHARED_COLLECTOR_BIN} — skipping start"
    return 0
  fi

  info "Starting shared collector..."
  nohup "$SHARED_COLLECTOR_BIN" >> "$SHARED_LOG_FILE" 2>&1 &
  echo $! > "$SHARED_PID_FILE"

  # Wait for startup (up to 3 seconds)
  local attempts=0
  while [[ $attempts -lt 30 ]]; do
    if curl -sf "http://127.0.0.1:${collector_port}/health" >/dev/null 2>&1; then
      info "Shared collector started (listening on 127.0.0.1:${collector_port})"
      return 0
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done

  warn "Collector did not become healthy within 3 seconds"
  warn "Check logs at ${SHARED_LOG_FILE} for details"
  warn "Harness tracing will work once the collector is running"
  return 0
}

# --- stop_shared_collector: stop the shared collector process ---
stop_shared_collector() {
  # Try health-based PID detection first, then PID file
  if [[ -f "$SHARED_PID_FILE" ]]; then
    local pid
    pid=$(cat "$SHARED_PID_FILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      info "Stopping shared collector (PID ${pid})..."
      kill "$pid" 2>/dev/null
      # Wait for graceful shutdown (up to 5 seconds for flush)
      local attempts=0
      while kill -0 "$pid" 2>/dev/null && [[ $attempts -lt 50 ]]; do
        sleep 0.1
        attempts=$((attempts + 1))
      done
      if kill -0 "$pid" 2>/dev/null; then
        warn "Collector did not exit gracefully — sending SIGKILL"
        kill -9 "$pid" 2>/dev/null || true
      fi
      info "Shared collector stopped"
    fi
    rm -f "$SHARED_PID_FILE"
  else
    info "No collector PID file found — collector is not running"
  fi
}

# --- setup_claude: Claude Code / Agent SDK ---
setup_claude() {
  header "Setting up Arize tracing for Claude Code"

  local plugin_dir="${INSTALL_DIR}/claude-code-tracing"

  if [[ ! -d "$plugin_dir" ]]; then
    # Fall back to plugins/ layout if core refactor hasn't landed yet
    plugin_dir="${INSTALL_DIR}/plugins/claude-code-tracing"
  fi

  if [[ ! -d "$plugin_dir" ]]; then
    err "Claude Code tracing plugin not found in ${INSTALL_DIR}"
    exit 1
  fi

  info "Plugin installed at: ${plugin_dir}"

  # --- Register plugin and enable tracing in Claude settings ---
  local claude_settings="${HOME}/.claude/settings.json"
  mkdir -p "$(dirname "$claude_settings")"

  if [[ ! -f "$claude_settings" ]]; then
    echo '{}' > "$claude_settings"
  fi

  if command_exists jq; then
    local tmp_settings="${claude_settings}.tmp.$$"

    # Add plugin as local plugin if not already registered
    local has_plugin
    has_plugin=$(jq --arg p "$plugin_dir" '
      (.plugins // []) | map(select(
        (type == "string" and . == $p) or
        (type == "object" and .path == $p)
      )) | length
    ' "$claude_settings" 2>/dev/null) || has_plugin="0"

    if [[ "${has_plugin:-0}" -eq 0 ]]; then
      jq --arg p "$plugin_dir" '.plugins = ((.plugins // []) + [{"type": "local", "path": $p}])' \
        "$claude_settings" > "$tmp_settings" && mv "$tmp_settings" "$claude_settings"
      info "Added plugin to ${claude_settings}"
    else
      info "Plugin already registered in ${claude_settings}"
    fi

    # Enable tracing env var
    jq '.env = ((.env // {}) + {"ARIZE_TRACE_ENABLED": "true"})' \
      "$claude_settings" > "$tmp_settings" && mv "$tmp_settings" "$claude_settings"
    info "Enabled ARIZE_TRACE_ENABLED in ${claude_settings}"
  else
    warn "jq not available — add the plugin manually to ${claude_settings}"
  fi

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
  echo "    The shared background collector is already running and will export"
  echo "    spans to your configured backend automatically. No additional setup"
  echo "    is needed — just use Claude Code or your Agent SDK application."
  echo ""
  echo "    Check collector status:  curl -s http://127.0.0.1:4318/health | python3 -m json.tool"
  echo "    View collector logs:     tail -f ${SHARED_LOG_FILE}"
  echo ""

  echo ""
  info "Setup complete! Test with: ARIZE_DRY_RUN=true claude"
}

# --- setup_cursor: Cursor IDE ---
setup_cursor() {
  header "Setting up Arize tracing for Cursor IDE"

  local plugin_dir="${INSTALL_DIR}/cursor-tracing"

  if [[ ! -d "$plugin_dir" ]]; then
    plugin_dir="${INSTALL_DIR}/plugins/cursor-tracing"
  fi

  if [[ ! -d "$plugin_dir" ]]; then
    err "Cursor tracing plugin not found in ${INSTALL_DIR}"
    exit 1
  fi

  info "Plugin installed at: ${plugin_dir}"

  local cursor_hooks_json="${HOME}/.cursor/hooks.json"
  local hook_command="bash ${plugin_dir}/hooks/hook-handler.sh"
  local state_dir="${HOME}/.arize/harness/state/cursor"

  # Ensure directories exist
  mkdir -p "${HOME}/.cursor"
  mkdir -p "$state_dir"

  # --- 1. Write/merge hooks.json with absolute paths ---
  local hook_events=(
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

  if [[ -f "$cursor_hooks_json" ]]; then
    # Merge: add our hooks without clobbering existing entries
    cp "$cursor_hooks_json" "${cursor_hooks_json}.bak"

    local merged="$cursor_hooks_json"
    local tmp_merged="${cursor_hooks_json}.tmp.$$"

    # Start with existing content
    local current
    current=$(cat "$merged")

    for event in "${hook_events[@]}"; do
      # Check if our hook command is already present for this event
      if echo "$current" | jq -e --arg cmd "$hook_command" --arg evt "$event" \
        '.hooks[$evt] // [] | map(select(.command == $cmd)) | length > 0' >/dev/null 2>&1; then
        continue
      fi

      # Add our hook entry to this event
      current=$(echo "$current" | jq --arg cmd "$hook_command" --arg evt "$event" \
        '.hooks[$evt] = ((.hooks[$evt] // []) + [{"command": $cmd}])')
    done

    echo "$current" | jq '.' > "$tmp_merged" && mv "$tmp_merged" "$merged"
    info "Merged Arize hooks into existing ${cursor_hooks_json}"
  else
    # Generate fresh hooks.json with absolute paths
    local hooks_obj="{}"
    for event in "${hook_events[@]}"; do
      hooks_obj=$(echo "$hooks_obj" | jq --arg cmd "$hook_command" --arg evt "$event" \
        '.[$evt] = [{"command": $cmd}]')
    done

    jq -n --argjson hooks "$hooks_obj" '{"version": 1, "hooks": $hooks}' > "$cursor_hooks_json"
    info "Created ${cursor_hooks_json}"
  fi

  # --- 2. Read collector port from shared config ---
  local collector_port="4318"
  if command_exists jq && [[ -f "$SHARED_CONFIG" ]]; then
    local cfg_port
    cfg_port=$(jq -r '.collector.port // empty' "$SHARED_CONFIG" 2>/dev/null) || true
    [[ -n "$cfg_port" ]] && collector_port="$cfg_port"
  fi

  # --- 3. Summary ---
  echo ""
  echo -e "  ${BOLD}Cursor tracing setup complete!${NC}"
  echo ""
  echo -e "  ${BOLD}What was configured:${NC}"
  echo ""
  echo "    - Cursor hooks.json at ${cursor_hooks_json}"
  echo "      (12 hook events routing to ${plugin_dir}/hooks/hook-handler.sh)"
  echo "    - State directory at ${state_dir}"
  echo ""
  echo -e "  ${BOLD}Tracing:${NC}"
  echo ""
  echo "    The shared background collector is running and will export"
  echo "    spans to your configured backend automatically."
  echo ""
  echo "    Check collector status:  curl -s http://127.0.0.1:${collector_port}/health | python3 -m json.tool"
  echo "    View collector logs:     tail -f ${SHARED_LOG_FILE}"
  echo ""
  echo -e "  ${BOLD}Next steps:${NC}"
  echo ""
  echo "    1. Restart Cursor IDE to pick up the new hooks"
  echo "    2. Start a conversation — spans will appear in your configured backend"
  echo ""
  echo "  Test with: ARIZE_DRY_RUN=true (open Cursor and start a conversation)"
  echo ""

  info "Setup complete!"
}

# --- detect_shell_profile: find the user's active shell profile ---
detect_shell_profile() {
  if [[ -f "${HOME}/.zshrc" ]]; then
    echo "${HOME}/.zshrc"
  elif [[ -f "${HOME}/.bashrc" ]]; then
    echo "${HOME}/.bashrc"
  elif [[ -f "${HOME}/.bash_profile" ]]; then
    echo "${HOME}/.bash_profile"
  else
    echo ""
  fi
}

# --- discover_real_codex: find the actual codex binary (not our proxy) ---
discover_real_codex() {
  local current_codex proxy_path="${HOME}/.local/bin/codex"
  current_codex=$(command -v codex 2>/dev/null || true)
  if [[ -z "$current_codex" ]]; then
    return 1
  fi
  if [[ "$current_codex" == "$proxy_path" && -f "$proxy_path" ]]; then
    current_codex=$(sed -n 's/^REAL_CODEX="\([^"]*\)"$/\1/p' "$proxy_path" | head -1)
  fi
  [[ -n "$current_codex" && -x "$current_codex" ]] || return 1
  echo "$current_codex"
}

# --- setup_codex: OpenAI Codex CLI ---
setup_codex() {
  header "Setting up Arize tracing for Codex CLI"

  local plugin_dir="${INSTALL_DIR}/codex-tracing"

  if [[ ! -d "$plugin_dir" ]]; then
    plugin_dir="${INSTALL_DIR}/plugins/codex-tracing"
  fi

  if [[ ! -d "$plugin_dir" ]]; then
    err "Codex tracing plugin not found in ${INSTALL_DIR}"
    exit 1
  fi

  info "Plugin installed at: ${plugin_dir}"

  local codex_config_dir="${HOME}/.codex"
  local codex_config="${codex_config_dir}/config.toml"
  local notify_script="${plugin_dir}/hooks/notify.sh"
  local env_file="${codex_config_dir}/arize-env.sh"

  # Ensure codex config directory exists
  mkdir -p "$codex_config_dir"
  [[ -f "$codex_config" ]] || touch "$codex_config"

  # --- 1. Configure notify hook ---
  local notify_line="notify = [\"bash\", \"${notify_script}\"]"

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
  # Read collector port from shared config
  local collector_port="4318"
  if command_exists jq && [[ -f "$SHARED_CONFIG" ]]; then
    local cfg_port
    cfg_port=$(jq -r '.collector.port // empty' "$SHARED_CONFIG" 2>/dev/null) || true
    [[ -n "$cfg_port" ]] && collector_port="$cfg_port"
  fi

  # Remove old [otel] section if present
  if grep -q "^\[otel\]" "$codex_config" 2>/dev/null; then
    cp "$codex_config" "${codex_config}.bak"
    awk '
      BEGIN { skip=0 }
      /^\[otel(\.|\])/ { skip=1; next }
      skip && /^\[/ && $0 !~ /^\[otel(\.|\])/ { skip=0 }
      !skip { print }
    ' "${codex_config}.bak" > "$codex_config"
    info "Removed old [otel] section from config.toml"
  fi

  # Add new [otel] section pointing at shared collector
  cat >> "$codex_config" <<OTELEOF

# Arize shared collector -- captures Codex events for rich span trees
[otel]
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:${collector_port}/v1/logs"
protocol = "json"
OTELEOF
  info "Added [otel] exporter pointing to shared collector (port $collector_port)"

  # --- 4. Install codex proxy wrapper ---
  local proxy_dir="${HOME}/.local/bin"
  local proxy_path="${proxy_dir}/codex"
  local proxy_backup="${proxy_dir}/codex.arize-backup"
  local proxy_template="${plugin_dir}/scripts/codex_proxy.sh"

  local real_codex_bin
  real_codex_bin=$(discover_real_codex || true)
  if [[ -z "$real_codex_bin" ]]; then
    warn "Could not find codex binary -- skipping proxy install"
  else
    mkdir -p "$proxy_dir"
    if [[ -f "$proxy_path" ]] && ! grep -q "ARIZE_CODEX_PROXY" "$proxy_path" 2>/dev/null; then
      cp "$proxy_path" "$proxy_backup"
      info "Backed up existing ${proxy_path} to ${proxy_backup}"
    fi
    sed \
      -e "s|__REAL_CODEX__|${real_codex_bin}|g" \
      -e "s|__ARIZE_ENV_FILE__|${env_file}|g" \
      -e "s|__SHARED_COLLECTOR_CTL__|${INSTALL_DIR}/core/collector_ctl.sh|g" \
      "$proxy_template" > "$proxy_path"
    chmod +x "$proxy_path"
    info "Installed codex proxy to ${proxy_path}"
  fi

  # --- 5. PATH management ---
  local shell_profile
  shell_profile=$(detect_shell_profile)

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
  if [[ -t 0 && -n "$real_codex_bin" ]]; then
    local add_to_profile="n"
    read -rp "  Ensure ~/.local/bin is prepended in your shell profile for the codex proxy? [Y/n]: " add_to_profile
    add_to_profile="${add_to_profile:-y}"
    if [[ "$add_to_profile" =~ ^[Yy] && -n "$shell_profile" ]]; then
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

  # --- Summary ---
  echo ""
  echo -e "  ${BOLD}Codex tracing setup complete!${NC}"
  echo ""
  echo -e "  ${BOLD}What was configured:${NC}"
  echo ""
  echo "    - Notify hook in ~/.codex/config.toml"
  echo "    - OTLP exporter in ~/.codex/config.toml (port ${collector_port})"
  if [[ -n "$real_codex_bin" ]]; then
    echo "    - Codex proxy wrapper at ${proxy_path}"
    echo "      (real codex: ${real_codex_bin})"
  fi
  echo "    - Env file template at ${env_file}"
  echo ""
  echo -e "  ${BOLD}Tracing:${NC}"
  echo ""
  echo "    The shared background collector is running and will export"
  echo "    spans to your configured backend automatically."
  echo ""
  echo "    Check collector status:  curl -s http://127.0.0.1:${collector_port}/health | python3 -m json.tool"
  echo "    View collector logs:     tail -f ${SHARED_LOG_FILE}"
  echo ""
  echo -e "  ${BOLD}Environment variables (optional overrides):${NC}"
  echo ""
  echo "    Edit ${env_file} with any additional settings, then:"
  echo ""
  echo "      source ${env_file}"
  echo ""
  echo "  Test with: ARIZE_DRY_RUN=true codex"
  echo ""

  info "Setup complete!"
}

# --- update_install ---
update_install() {
  header "Updating arize-agent-kit"

  if [[ ! -d "$INSTALL_DIR" ]]; then
    err "arize-agent-kit is not installed at ${INSTALL_DIR}"
    err "Run install first: install.sh claude, install.sh codex, or install.sh cursor"
    exit 1
  fi

  # Stop collector before update to avoid stale references
  stop_shared_collector

  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Pulling latest changes..."
    git -C "$INSTALL_DIR" pull --ff-only || {
      warn "Fast-forward pull failed — re-cloning"
      rm -rf "$INSTALL_DIR"
      install_repo
    }
  else
    info "No git repo found — re-downloading"
    rm -rf "$INSTALL_DIR"
    install_repo
  fi

  # Re-install collector runtime and restart
  if [[ -f "${INSTALL_DIR}/core/collector.py" ]]; then
    mkdir -p "$SHARED_BIN_DIR"

    # Determine the right python for the launcher
    local launcher_python=""
    if [[ -x "${SHARED_VENV_DIR}/bin/python" ]]; then
      launcher_python="${SHARED_VENV_DIR}/bin/python"
    elif [[ -x "${SHARED_VENV_DIR}/Scripts/python.exe" ]]; then
      launcher_python="${SHARED_VENV_DIR}/Scripts/python.exe"
    else
      launcher_python=$(find_python) || {
        warn "No Python found — collector will not start"
        return 0
      }
    fi

    cat > "$SHARED_COLLECTOR_BIN" <<BINEOF
#!/bin/bash
# Arize Agent Kit — shared collector launcher
# Auto-generated by install.sh. Do not edit manually.
exec "${launcher_python}" "${INSTALL_DIR}/core/collector.py" "\$@"
BINEOF
    chmod +x "$SHARED_COLLECTOR_BIN"
    info "Updated collector runtime"
  fi

  start_shared_collector

  info "Update complete! Re-run 'install.sh claude', 'install.sh codex', or 'install.sh cursor' to reconfigure harness settings."
}

cleanup_claude_config() {
  local plugin_dir="${INSTALL_DIR}/claude-code-tracing"
  local legacy_plugin_dir="${INSTALL_DIR}/plugins/claude-code-tracing"
  local global_settings="${HOME}/.claude/settings.json"
  local local_settings=".claude/settings.local.json"
  local arize_env_keys='
    del(
      .ARIZE_TRACE_ENABLED,
      .PHOENIX_ENDPOINT,
      .PHOENIX_API_KEY,
      .ARIZE_API_KEY,
      .ARIZE_SPACE_ID,
      .ARIZE_OTLP_ENDPOINT,
      .ARIZE_PROJECT_NAME,
      .ARIZE_USER_ID,
      .ARIZE_DRY_RUN,
      .ARIZE_VERBOSE,
      .ARIZE_LOG_FILE
    )
  '

  if [[ -f "$global_settings" ]] && command_exists jq; then
    if jq -e --arg path "$plugin_dir" --arg legacy "$legacy_plugin_dir" '
      (.plugins // []) | index($path) != null or index($legacy) != null
    ' "$global_settings" >/dev/null 2>&1; then
      if confirm_optional_cleanup "  Remove Arize Claude plugin path from ${global_settings}? [y/N]: " "n"; then
        cp "$global_settings" "${global_settings}.bak"
        jq --arg path "$plugin_dir" --arg legacy "$legacy_plugin_dir" '
          .plugins = ((.plugins // []) | map(select(. != $path and . != $legacy)))
        ' "$global_settings" > "${global_settings}.tmp" && mv "${global_settings}.tmp" "$global_settings"
        info "Removed Arize Claude plugin path from ${global_settings}"
      else
        info "Left ${global_settings} unchanged"
      fi
    fi

    if jq -e '
      (.env // {}) as $env
      | [
          "ARIZE_TRACE_ENABLED",
          "PHOENIX_ENDPOINT",
          "PHOENIX_API_KEY",
          "ARIZE_API_KEY",
          "ARIZE_SPACE_ID",
          "ARIZE_OTLP_ENDPOINT",
          "ARIZE_PROJECT_NAME",
          "ARIZE_USER_ID",
          "ARIZE_DRY_RUN",
          "ARIZE_VERBOSE",
          "ARIZE_LOG_FILE"
        ]
      | any(. as $k | $env[$k] != null)
    ' "$global_settings" >/dev/null 2>&1; then
      if confirm_optional_cleanup "  Remove Arize env keys from ${global_settings}? [y/N]: " "n"; then
        cp "$global_settings" "${global_settings}.bak"
        jq "
          .env = ((.env // {}) | ${arize_env_keys})
        " "$global_settings" > "${global_settings}.tmp" && mv "${global_settings}.tmp" "$global_settings"
        info "Removed Arize env keys from ${global_settings}"
      else
        info "Left ${global_settings} env unchanged"
      fi
    fi
  fi

  if [[ -f "$local_settings" ]] && command_exists jq; then
    if jq -e '
      (.env // {}) as $env
      | [
          "ARIZE_TRACE_ENABLED",
          "PHOENIX_ENDPOINT",
          "PHOENIX_API_KEY",
          "ARIZE_API_KEY",
          "ARIZE_SPACE_ID",
          "ARIZE_OTLP_ENDPOINT",
          "ARIZE_PROJECT_NAME",
          "ARIZE_USER_ID",
          "ARIZE_DRY_RUN",
          "ARIZE_VERBOSE",
          "ARIZE_LOG_FILE"
        ]
      | any(. as $k | $env[$k] != null)
    ' "$local_settings" >/dev/null 2>&1; then
      if confirm_optional_cleanup "  Remove Arize env keys from ${local_settings}? [y/N]: " "n"; then
        cp "$local_settings" "${local_settings}.bak"
        jq "
          .env = ((.env // {}) | ${arize_env_keys})
        " "$local_settings" > "${local_settings}.tmp" && mv "${local_settings}.tmp" "$local_settings"
        info "Removed Arize env keys from ${local_settings}"
      else
        info "Left ${local_settings} unchanged"
      fi
    fi
  fi

  if [[ -d "${HOME}/.arize/harness/state/claude-code" ]]; then
    if confirm_optional_cleanup "  Remove Claude runtime state at ${HOME}/.arize/harness/state/claude-code? [Y/n]: " "y"; then
      rm -rf "${HOME}/.arize/harness/state/claude-code"
      info "Removed ${HOME}/.arize/harness/state/claude-code"
    else
      info "Left ${HOME}/.arize/harness/state/claude-code in place"
    fi
  fi
}

# --- Per-harness uninstall helpers ---

_uninstall_codex() {
  info "Removing Codex tracing configuration..."

  local codex_config_dir="${HOME}/.codex"
  local codex_config="${codex_config_dir}/config.toml"
  local proxy_dir="${HOME}/.local/bin"
  local proxy_path="${proxy_dir}/codex"
  local proxy_backup="${proxy_dir}/codex.arize-backup"
  local notify_script="${INSTALL_DIR}/codex-tracing/hooks/notify.sh"

  # 1. Remove notify hook from config.toml
  if [[ -f "$codex_config" ]]; then
    if grep -qF "$notify_script" "$codex_config" 2>/dev/null; then
      cp "$codex_config" "${codex_config}.bak"
      sed -i.tmp "\|$notify_script|d" "$codex_config"
      rm -f "${codex_config}.tmp"
      info "Removed notify hook from config.toml (backup: config.toml.bak)"
    else
      info "No Arize notify hook found in config.toml"
    fi

    # 2. Remove [otel] section pointing at our collector (check both port 4318 and 4319)
    if grep -qE "endpoint = \"http://127\.0\.0\.1:(4318|4319)/v1/logs\"" "$codex_config" 2>/dev/null; then
      cp "$codex_config" "${codex_config}.bak"
      awk '
        BEGIN { skip=0 }
        /^\[otel(\.|\])/ { skip=1; next }
        skip && /^\[/ && $0 !~ /^\[otel(\.|\])/ { skip=0 }
        !skip { print }
      ' "${codex_config}.bak" > "$codex_config"
      info "Removed Arize [otel] exporter from config.toml"
    else
      info "No Arize [otel] exporter found in config.toml"
    fi
  fi

  # 3. Remove codex proxy wrapper and restore backup
  if [[ -f "$proxy_path" ]] && grep -q "ARIZE_CODEX_PROXY" "$proxy_path" 2>/dev/null; then
    rm -f "$proxy_path"
    info "Removed codex proxy from ${proxy_path}"
  fi
  if [[ -f "$proxy_backup" ]]; then
    mv "$proxy_backup" "$proxy_path"
    chmod +x "$proxy_path"
    info "Restored previous codex wrapper to ${proxy_path}"
  fi

  # 4. Clean up PATH injection from shell profiles
  for profile in "${HOME}/.zshrc" "${HOME}/.bashrc" "${HOME}/.bash_profile"; do
    if [[ -f "$profile" ]] && grep -q "prepend ~/.local/bin for codex proxy" "$profile" 2>/dev/null; then
      cp "$profile" "${profile}.bak"
      sed -i.tmp '/Arize Codex tracing - prepend \~\/\.local\/bin for codex proxy/d; /export PATH="\$HOME\/\.local\/bin:\$PATH"/d' "$profile"
      rm -f "${profile}.tmp"
      info "Removed PATH update from $(basename "$profile")"
    fi
  done

  # 5. Remove collector auto-start lines from shell profiles
  for profile in "${HOME}/.zshrc" "${HOME}/.bashrc"; do
    if [[ -f "$profile" ]] && grep -q "collector_ctl.sh" "$profile" 2>/dev/null; then
      cp "$profile" "${profile}.bak"
      sed -i.tmp '/arize-codex.*collector_ctl/d; /collector_ensure/d; /event_buffer_ensure/d' "$profile"
      rm -f "${profile}.tmp"
      info "Removed collector auto-start from $(basename "$profile")"
    fi
  done

  # 6. Clean up codex state directory
  rm -rf "${HOME}/.arize/harness/state/codex"
  info "Cleaned up Codex state directory"

  # 7. Remove env file
  if [[ -f "${codex_config_dir}/arize-env.sh" ]]; then
    rm -f "${codex_config_dir}/arize-env.sh"
    info "Removed ${codex_config_dir}/arize-env.sh"
  fi

  # 8. Remove codex harness entry from config.json
  if command_exists jq && [[ -f "$SHARED_CONFIG" ]]; then
    if jq -e '.harnesses.codex' "$SHARED_CONFIG" >/dev/null 2>&1; then
      cp "$SHARED_CONFIG" "${SHARED_CONFIG}.bak"
      jq 'del(.harnesses.codex)' "$SHARED_CONFIG" > "${SHARED_CONFIG}.tmp" && mv "${SHARED_CONFIG}.tmp" "$SHARED_CONFIG"
      info "Removed codex harness entry from config.json"
    fi
  fi

  info "Codex tracing cleanup complete."
}

_uninstall_cursor() {
  info "Removing Cursor tracing configuration..."

  local cursor_hooks_json="${HOME}/.cursor/hooks.json"
  local plugin_dir="${INSTALL_DIR}/cursor-tracing"
  local hook_command="bash ${plugin_dir}/hooks/hook-handler.sh"

  # 1. Remove our hooks from hooks.json
  if [[ -f "$cursor_hooks_json" ]] && command_exists jq; then
    if grep -qF "$hook_command" "$cursor_hooks_json" 2>/dev/null; then
      cp "$cursor_hooks_json" "${cursor_hooks_json}.bak"

      # Remove our hook entries from each event, then remove empty event arrays
      jq --arg cmd "$hook_command" '
        .hooks |= (
          to_entries
          | map(.value |= map(select(.command != $cmd)))
          | map(select(.value | length > 0))
          | from_entries
        )
      ' "$cursor_hooks_json" > "${cursor_hooks_json}.tmp" && \
        mv "${cursor_hooks_json}.tmp" "$cursor_hooks_json"

      # If hooks object is now empty, remove the file
      local remaining
      remaining=$(jq '.hooks | length' "$cursor_hooks_json" 2>/dev/null || echo "0")
      if [[ "$remaining" -eq 0 ]]; then
        rm -f "$cursor_hooks_json"
        info "Removed ${cursor_hooks_json} (no hooks remaining)"
      else
        info "Removed Arize hooks from ${cursor_hooks_json} (other hooks preserved)"
      fi
    else
      info "No Arize hooks found in ${cursor_hooks_json}"
    fi
  fi

  # 2. Clean up cursor state directory
  if [[ -d "${HOME}/.arize/harness/state/cursor" ]]; then
    rm -rf "${HOME}/.arize/harness/state/cursor"
    info "Removed ${HOME}/.arize/harness/state/cursor"
  fi

  # 3. Remove cursor harness entry from config.json
  if command_exists jq && [[ -f "$SHARED_CONFIG" ]]; then
    if jq -e '.harnesses.cursor' "$SHARED_CONFIG" >/dev/null 2>&1; then
      cp "$SHARED_CONFIG" "${SHARED_CONFIG}.bak"
      jq 'del(.harnesses.cursor)' "$SHARED_CONFIG" > "${SHARED_CONFIG}.tmp" && \
        mv "${SHARED_CONFIG}.tmp" "$SHARED_CONFIG"
      info "Removed cursor harness entry from config.json"
    fi
  fi

  info "Cursor tracing cleanup complete."
}

# --- uninstall ---
uninstall() {
  header "Uninstalling arize-agent-kit"

  # 1. Stop the shared collector first
  info "Stopping shared collector..."
  stop_shared_collector

  # 2. Clean up harness-specific config (Codex)
  if [[ -d "${INSTALL_DIR}/codex-tracing" ]] || [[ -d "${HOME}/.codex" ]]; then
    _uninstall_codex
  fi

  # 2b. Clean up harness-specific config (Cursor)
  if [[ -d "${INSTALL_DIR}/cursor-tracing" ]] || [[ -f "${HOME}/.cursor/hooks.json" ]] || [[ -d "${HOME}/.arize/harness/state/cursor" ]]; then
    _uninstall_cursor
  fi

  # 3. Clean up harness-specific config (Claude)
  info "Checking Claude tracing configuration..."
  cleanup_claude_config

  # 4. Remove shared collector runtime files and venv
  info "Removing shared collector runtime..."
  rm -f "$SHARED_COLLECTOR_BIN"
  rm -f "$SHARED_PID_FILE"
  rm -f "$SHARED_LOG_FILE"
  [[ -d "$SHARED_VENV_DIR" ]] && rm -rf "$SHARED_VENV_DIR" && info "Removed collector venv"
  # Remove shared directories if empty
  rmdir "$SHARED_BIN_DIR" 2>/dev/null || true
  rmdir "$SHARED_RUN_DIR" 2>/dev/null || true
  rmdir "$SHARED_LOG_DIR" 2>/dev/null || true

  # 5. Remove shared config and install directory
  if [[ -f "$SHARED_CONFIG" ]]; then
    rm -f "$SHARED_CONFIG"
    info "Removed ${SHARED_CONFIG}"
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

# --- Usage ---
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
  echo "    --with-skills   Symlink setup skills into .agents/skills/ in the current directory"
  echo "    --branch <name> Install from a specific git branch (default: main)"
  echo ""
  echo "  The installer sets up a shared background collector that receives spans"
  echo "  from all harnesses and exports them to your configured backend (Phoenix"
  echo "  or Arize AX). No additional Python packages or manual process management"
  echo "  required."
  echo ""
  echo "  Examples:"
  echo "    curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude"
  echo "    curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex"
  echo "    curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- cursor"
  echo "    bash install.sh update"
  echo ""
}

# --- install_skills: symlink harness skills into .agents/skills/ ---
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

# --- Main ---
main() {
  local cmd="${1:-}"
  shift || true

  # Parse flags
  local with_skills=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-skills) with_skills=true; shift ;;
      --branch) INSTALL_BRANCH="${2:-main}"; TARBALL_URL="https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/${INSTALL_BRANCH}.tar.gz"; shift 2 ;;
      *) shift ;;
    esac
  done

  case "$cmd" in
    claude)
      command_exists jq || { err "jq is required. Install: brew install jq  or  apt install jq"; exit 1; }
      install_repo
      setup_shared_collector "claude-code"
      setup_claude
      [[ "$with_skills" == true ]] && install_skills "claude-code"
      ;;
    codex)
      command_exists jq || { err "jq is required. Install: brew install jq  or  apt install jq"; exit 1; }
      install_repo
      setup_shared_collector "codex"
      setup_codex
      [[ "$with_skills" == true ]] && install_skills "codex"
      ;;
    cursor)
      command_exists jq || { err "jq is required. Install: brew install jq  or  apt install jq"; exit 1; }
      install_repo
      setup_shared_collector "cursor"
      setup_cursor
      [[ "$with_skills" == true ]] && install_skills "cursor"
      ;;
    update)
      update_install
      ;;
    uninstall)
      uninstall
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
