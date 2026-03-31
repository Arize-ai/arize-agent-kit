#!/bin/bash
# Arize Agent Kit — Curl-pipe installer for non-marketplace harnesses
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- update
#   curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall
#
# Installs the arize-agent-kit repo and configures tracing for the specified harness.
# Idempotent — safe to run multiple times.

set -euo pipefail

# --- Constants ---
REPO_URL="https://github.com/Arize-ai/arize-agent-kit.git"
TARBALL_URL="https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/main.tar.gz"
INSTALL_DIR="${HOME}/.arize-agent-kit"

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
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || {
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

  echo ""
  echo -e "  ${BOLD}Claude Code CLI (marketplace — recommended):${NC}"
  echo ""
  echo "    The easiest way to install for Claude Code CLI is via the marketplace:"
  echo ""
  echo "      claude plugin add arize-agent-kit"
  echo ""
  echo -e "  ${BOLD}Claude Code CLI (manual):${NC}"
  echo ""
  echo "    Add to your Claude Code settings (${HOME}/.claude/settings.json):"
  echo ""
  echo "      {\"plugins\": [\"${plugin_dir}\"]}"
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
  echo -e "  ${BOLD}Environment variables:${NC}"
  echo ""
  echo "    # Required — choose one backend:"
  echo "    # Phoenix (self-hosted):"
  echo "    export ARIZE_TRACE_ENABLED=true"
  echo "    export PHOENIX_ENDPOINT=http://localhost:6006"
  echo ""
  echo "    # Arize AX (cloud):"
  echo "    export ARIZE_TRACE_ENABLED=true"
  echo "    export ARIZE_API_KEY=<your-key>"
  echo "    export ARIZE_SPACE_ID=<your-space-id>"
  echo ""
  echo "    # Optional:"
  echo "    export ARIZE_PROJECT_NAME=my-project"
  echo "    export ARIZE_USER_ID=my-user-id"
  echo ""

  # Run interactive setup if available and stdin is a terminal
  local setup_script="${plugin_dir}/scripts/setup.sh"
  if [[ ! -f "$setup_script" ]]; then
    setup_script="${plugin_dir}/setup.sh"
  fi
  if [[ -f "$setup_script" && -t 0 ]]; then
    echo ""
    read -rp "  Run interactive setup now? [Y/n]: " run_setup
    run_setup="${run_setup:-y}"
    if [[ "$run_setup" =~ ^[Yy] ]]; then
      bash "$setup_script"
    fi
  fi

  echo ""
  info "Setup complete! Test with: ARIZE_DRY_RUN=true claude"
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

  # --- Configure notify hook ---
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

  # --- Write env file template ---
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

  # --- Collector instructions ---
  local collector_ctl="${plugin_dir}/scripts/collector_ctl.sh"

  echo ""
  echo -e "  ${BOLD}Environment variables:${NC}"
  echo ""
  echo "    Edit ${env_file} with your credentials, then:"
  echo ""
  echo "      source ${env_file}"
  echo ""
  echo -e "  ${BOLD}Collector (optional — captures Codex native OTel events):${NC}"
  echo ""
  if [[ -f "$collector_ctl" ]]; then
    echo "    source ${collector_ctl}"
    echo "    collector_ensure    # start if not running"
    echo "    collector_status    # check status"
    echo "    collector_stop      # stop"
  else
    echo "    Collector scripts not found — native OTel capture unavailable"
  fi
  echo ""
  echo "  Test with: ARIZE_DRY_RUN=true codex"
  echo ""

  # Run the codex-specific installer if available and interactive
  local codex_install="${plugin_dir}/install.sh"
  if [[ -f "$codex_install" && -t 0 ]]; then
    echo ""
    read -rp "  Run full Codex setup (configures OTLP exporter + proxy)? [y/N]: " run_full
    if [[ "${run_full:-n}" =~ ^[Yy] ]]; then
      bash "$codex_install"
    fi
  fi

  info "Setup complete!"
}

# --- update_install ---
update_install() {
  header "Updating arize-agent-kit"

  if [[ ! -d "$INSTALL_DIR" ]]; then
    err "arize-agent-kit is not installed at ${INSTALL_DIR}"
    err "Run install first: install.sh claude  or  install.sh codex"
    exit 1
  fi

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

  info "Update complete! Re-run 'install.sh claude' or 'install.sh codex' to reconfigure."
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

  if [[ -d "${HOME}/.arize-claude-code" ]]; then
    if confirm_optional_cleanup "  Remove Claude runtime state at ${HOME}/.arize-claude-code? [Y/n]: " "y"; then
      rm -rf "${HOME}/.arize-claude-code"
      info "Removed ${HOME}/.arize-claude-code"
    else
      info "Left ${HOME}/.arize-claude-code in place"
    fi
  fi
}

# --- uninstall ---
uninstall() {
  header "Uninstalling arize-agent-kit"

  local codex_install="${INSTALL_DIR}/codex-tracing/install.sh"
  if [[ ! -f "$codex_install" ]]; then
    codex_install="${INSTALL_DIR}/plugins/codex-tracing/install.sh"
  fi

  if [[ -f "$codex_install" ]]; then
    info "Removing Codex tracing configuration..."
    bash "$codex_install" uninstall || warn "Codex uninstall encountered an issue; some manual cleanup may still be required"
  fi

  info "Checking Claude tracing configuration..."
  cleanup_claude_config

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
  echo "  - Codex: verify ~/.codex/config.toml no longer references Arize"
  echo "  - Codex: verify ~/.local/bin/codex and shell profile changes were restored if you had a custom wrapper"
  echo "  - Shell profile: remove any manual 'source ~/.codex/arize-env.sh' lines you added"
  echo ""
  info "Uninstall complete."
}

# --- Usage ---
usage() {
  echo ""
  echo "  Arize Agent Kit Installer"
  echo ""
  echo "  Usage: install.sh <command>"
  echo ""
  echo "  Commands:"
  echo "    claude      Install and configure tracing for Claude Code / Agent SDK"
  echo "    codex       Install and configure tracing for OpenAI Codex CLI"
  echo "    update      Update the installed arize-agent-kit to latest"
  echo "    uninstall   Remove arize-agent-kit and print cleanup reminders"
  echo ""
  echo "  Examples:"
  echo "    curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude"
  echo "    curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- codex"
  echo "    bash install.sh update"
  echo ""
}

# --- Main ---
main() {
  local cmd="${1:-}"

  case "$cmd" in
    claude)
      install_repo
      setup_claude
      ;;
    codex)
      command_exists jq || { err "jq is required. Install: brew install jq  or  apt install jq"; exit 1; }
      install_repo
      setup_codex
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
