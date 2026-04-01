#!/bin/bash
# Install Arize tracing for OpenAI Codex CLI
#
# This script configures Codex to send OpenInference traces to Arize AX or Phoenix.
# It sets up:
#   1. The shared collector/exporter (~/.arize-agent-kit/) for backend export
#   2. The Codex event buffer for child-span assembly
#   3. The notify hook (creates OpenInference LLM spans per turn)
#   4. Native OTLP export (sends Codex's built-in telemetry events to the event buffer)
#
# Usage:
#   ./install.sh                  # Interactive setup
#   ./install.sh uninstall        # Remove tracing configuration
#   ./install.sh --target phoenix        # Non-interactive: Phoenix at localhost:6006
#   ./install.sh --target arize          # Non-interactive: Arize AX (requires env vars)
#   ./install.sh --target arize --otlp   # Also enable native OTLP export

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NOTIFY_SCRIPT="${SCRIPT_DIR}/hooks/notify.sh"
EVENT_BUFFER_CTL="${SCRIPT_DIR}/scripts/collector_ctl.sh"
SHARED_COLLECTOR_CTL="${REPO_ROOT}/core/collector_ctl.sh"
PROXY_TEMPLATE="${SCRIPT_DIR}/scripts/codex_proxy.sh"
CODEX_CONFIG_DIR="${HOME}/.codex"
CODEX_CONFIG="${CODEX_CONFIG_DIR}/config.toml"
PROXY_DIR="${HOME}/.local/bin"
PROXY_PATH="${PROXY_DIR}/codex"
PROXY_BACKUP="${PROXY_DIR}/codex.arize-backup"
PATH_PROFILE_MARKER="# Arize Codex tracing - prepend ~/.local/bin for codex proxy"

# Shared collector layout
SHARED_BASE="${HOME}/.arize-agent-kit"
SHARED_CONFIG="${SHARED_BASE}/config.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[arize]${NC} $*"; }
warn() { echo -e "${YELLOW}[arize]${NC} $*"; }
err()  { echo -e "${RED}[arize]${NC} $*" >&2; }

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

discover_real_codex() {
  local current_codex
  current_codex=$(command -v codex 2>/dev/null || true)
  if [[ -z "$current_codex" ]]; then
    return 1
  fi
  if [[ "$current_codex" == "$PROXY_PATH" && -f "$PROXY_PATH" ]]; then
    current_codex=$(sed -n 's/^REAL_CODEX="\([^"]*\)"$/\1/p' "$PROXY_PATH" | head -1)
  fi
  [[ -n "$current_codex" && -x "$current_codex" ]] || return 1
  echo "$current_codex"
}

# --- Uninstall ---
if [[ "${1:-}" == "uninstall" ]]; then
  info "Removing Arize tracing from Codex config..."

  if [[ -f "$CODEX_CONFIG" ]]; then
    # Remove notify line referencing our script
    if grep -qF "$NOTIFY_SCRIPT" "$CODEX_CONFIG" 2>/dev/null; then
      cp "$CODEX_CONFIG" "${CODEX_CONFIG}.bak"
      sed -i.tmp "\|$NOTIFY_SCRIPT|d" "$CODEX_CONFIG"
      rm -f "${CODEX_CONFIG}.tmp"
      info "Removed notify hook from config.toml (backup: config.toml.bak)"
    else
      info "No Arize notify hook found in config.toml"
    fi

    # Remove [otel] section pointing at event buffer (check both old port 4318 and new 4319)
    if grep -qE "endpoint = \"http://127\.0\.0\.1:(4318|4319)/v1/logs\"" "$CODEX_CONFIG" 2>/dev/null; then
      cp "$CODEX_CONFIG" "${CODEX_CONFIG}.bak"
      awk '
        BEGIN { skip=0 }
        /^\[otel(\.|\])/ { skip=1; next }
        skip && /^\[/ && $0 !~ /^\[otel(\.|\])/ { skip=0 }
        !skip { print }
      ' "${CODEX_CONFIG}.bak" > "$CODEX_CONFIG"
      info "Removed Arize [otel] exporter from config.toml"
    else
      info "No Arize [otel] exporter found in config.toml"
    fi
  fi

  # Stop event buffer if running
  if [[ -f "$EVENT_BUFFER_CTL" ]]; then
    source "$EVENT_BUFFER_CTL"
    event_buffer_stop >/dev/null 2>&1 || true
    info "Stopped event buffer"
  fi

  # Stop shared collector if running (only if no other harnesses need it)
  if [[ -f "$SHARED_COLLECTOR_CTL" ]]; then
    source "$SHARED_COLLECTOR_CTL"
    collector_stop >/dev/null 2>&1 || true
    info "Stopped shared collector"
  fi

  # Remove collector auto-start from shell profile
  for profile in "${HOME}/.zshrc" "${HOME}/.bashrc"; do
    if [[ -f "$profile" ]] && grep -q "collector_ctl.sh" "$profile" 2>/dev/null; then
      cp "$profile" "${profile}.bak"
      sed -i.tmp '/arize-codex.*collector_ctl/d; /collector_ensure/d; /event_buffer_ensure/d' "$profile"
      rm -f "${profile}.tmp"
      info "Removed collector auto-start from $(basename "$profile")"
    fi
  done

  # Remove codex proxy wrapper and restore any previous user wrapper
  if [[ -f "$PROXY_PATH" ]] && grep -q "ARIZE_CODEX_PROXY" "$PROXY_PATH" 2>/dev/null; then
    rm -f "$PROXY_PATH"
    info "Removed codex proxy from ${PROXY_PATH}"
  fi
  if [[ -f "$PROXY_BACKUP" ]]; then
    mv "$PROXY_BACKUP" "$PROXY_PATH"
    chmod +x "$PROXY_PATH"
    info "Restored previous codex wrapper to ${PROXY_PATH}"
  fi

  # Remove PATH injection marker if we added one
  for profile in "${HOME}/.zshrc" "${HOME}/.bashrc" "${HOME}/.bash_profile"; do
    if [[ -f "$profile" ]] && grep -q "prepend ~/.local/bin for codex proxy" "$profile" 2>/dev/null; then
      cp "$profile" "${profile}.bak"
      sed -i.tmp '/Arize Codex tracing - prepend \~\/\.local\/bin for codex proxy/d; /export PATH="\$HOME\/\.local\/bin:\$PATH"/d' "$profile"
      rm -f "${profile}.tmp"
      info "Removed PATH update from $(basename "$profile")"
    fi
  done

  # Clean up Codex state
  rm -rf "${HOME}/.arize-codex"
  info "Cleaned up Codex state directory"

  if [[ -f "${CODEX_CONFIG_DIR}/arize-env.sh" ]]; then
    rm -f "${CODEX_CONFIG_DIR}/arize-env.sh"
    info "Removed ${CODEX_CONFIG_DIR}/arize-env.sh"
  fi

  info "Uninstall complete."
  exit 0
fi

# --- Prerequisites ---
command -v jq &>/dev/null || { err "jq is required. Install: brew install jq"; exit 1; }
command -v codex &>/dev/null || warn "codex CLI not found in PATH — make sure it's installed"
REAL_CODEX_BIN="$(discover_real_codex || true)"
[[ -n "${REAL_CODEX_BIN}" ]] || { err "Could not determine the real codex binary path"; exit 1; }

# --- Ensure config directory exists ---
mkdir -p "$CODEX_CONFIG_DIR"
[[ -f "$CODEX_CONFIG" ]] || touch "$CODEX_CONFIG"

# --- Parse flags ---
TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --otlp) shift ;;  # Accepted for backwards compat but always enabled now
    *) shift ;;
  esac
done

# --- Determine target ---
if [[ -n "$TARGET" ]]; then
  # Non-interactive mode
  :
else
  echo ""
  echo "  Arize Codex Tracing Setup"
  echo "  ========================="
  echo ""
  echo "  Choose a tracing backend:"
  echo ""
  echo "  1) Phoenix (self-hosted) — No Python required"
  echo "  2) Arize AX (cloud)     — Requires Python + opentelemetry"
  echo ""
  read -rp "  Enter choice [1/2]: " choice
  case "$choice" in
    1) TARGET="phoenix" ;;
    2) TARGET="arize" ;;
    *) err "Invalid choice"; exit 1 ;;
  esac
fi

# --- Collect credentials ---
case "$TARGET" in
  phoenix)
    if [[ -z "${PHOENIX_ENDPOINT:-}" ]]; then
      read -rp "  Phoenix endpoint [http://localhost:6006]: " ep
      PHOENIX_ENDPOINT="${ep:-http://localhost:6006}"
    fi
    info "Target: Phoenix at $PHOENIX_ENDPOINT"
    ;;
  arize)
    if [[ -z "${ARIZE_API_KEY:-}" ]]; then
      read -rp "  Arize API key: " ARIZE_API_KEY
    fi
    if [[ -z "${ARIZE_SPACE_ID:-}" ]]; then
      read -rp "  Arize Space ID: " ARIZE_SPACE_ID
    fi
    [[ -z "$ARIZE_API_KEY" || -z "$ARIZE_SPACE_ID" ]] && { err "API key and Space ID required"; exit 1; }
    info "Target: Arize AX"
    ;;
  *)
    err "Unknown target: $TARGET (use 'phoenix' or 'arize')"
    exit 1
    ;;
esac

# --- Configure notify hook ---
NOTIFY_LINE="notify = [\"bash\", \"${NOTIFY_SCRIPT}\"]"

if grep -q "^notify" "$CODEX_CONFIG" 2>/dev/null; then
  # Replace existing notify line (wherever it is)
  cp "$CODEX_CONFIG" "${CODEX_CONFIG}.bak"
  sed -i.tmp "s|^notify.*|${NOTIFY_LINE}|" "$CODEX_CONFIG"
  rm -f "${CODEX_CONFIG}.tmp"
  info "Updated existing notify hook in config.toml"
else
  # Insert notify BEFORE the first [section] header so it stays top-level.
  # In TOML, keys after a [section] belong to that section.
  if grep -qn '^\[' "$CODEX_CONFIG" 2>/dev/null; then
    first_section=$(grep -n '^\[' "$CODEX_CONFIG" | head -1 | cut -d: -f1)
    cp "$CODEX_CONFIG" "${CODEX_CONFIG}.bak"
    {
      head -n $((first_section - 1)) "$CODEX_CONFIG.bak"
      echo ""
      echo "# Arize tracing — OpenInference spans per turn"
      echo "$NOTIFY_LINE"
      echo ""
      tail -n +${first_section} "$CODEX_CONFIG.bak"
    } > "$CODEX_CONFIG"
  else
    # No sections — safe to append
    echo "" >> "$CODEX_CONFIG"
    echo "# Arize tracing — OpenInference spans per turn" >> "$CODEX_CONFIG"
    echo "$NOTIFY_LINE" >> "$CODEX_CONFIG"
  fi
  info "Added notify hook to config.toml"
fi

# --- Write environment variables ---
# Store credentials in a shell env file that the notify script can source,
# and also show the user how to set them in their shell profile.

ENV_FILE="${CODEX_CONFIG_DIR}/arize-env.sh"

case "$TARGET" in
  phoenix)
    cat > "$ENV_FILE" <<EOF
# Arize Codex tracing environment (auto-generated)
export ARIZE_TRACE_ENABLED=true
export PHOENIX_ENDPOINT="${PHOENIX_ENDPOINT}"
${PHOENIX_API_KEY:+export PHOENIX_API_KEY="${PHOENIX_API_KEY}"}
export ARIZE_PROJECT_NAME="${ARIZE_PROJECT_NAME:-codex}"
EOF
    ;;
  arize)
    cat > "$ENV_FILE" <<EOF
# Arize Codex tracing environment (auto-generated)
export ARIZE_TRACE_ENABLED=true
export ARIZE_API_KEY="${ARIZE_API_KEY}"
export ARIZE_SPACE_ID="${ARIZE_SPACE_ID}"
${ARIZE_OTLP_ENDPOINT:+export ARIZE_OTLP_ENDPOINT="${ARIZE_OTLP_ENDPOINT}"}
export ARIZE_PROJECT_NAME="${ARIZE_PROJECT_NAME:-codex}"
EOF
    ;;
esac

chmod 600 "$ENV_FILE"
info "Wrote credentials to $ENV_FILE"

# --- Install shared collector config ---
# The shared collector at ~/.arize-agent-kit/ handles backend export for all
# harnesses.  Write its config.json with the backend credentials.
mkdir -p "${SHARED_BASE}/bin" "${SHARED_BASE}/run" "${SHARED_BASE}/logs"

case "$TARGET" in
  phoenix)
    cat > "$SHARED_CONFIG" <<EOF
{
  "collector": {
    "host": "127.0.0.1",
    "port": 4318
  },
  "backend": {
    "target": "phoenix",
    "phoenix": {
      "endpoint": "${PHOENIX_ENDPOINT}",
      "api_key": "${PHOENIX_API_KEY:-}",
      "project_name": "${ARIZE_PROJECT_NAME:-codex}"
    },
    "arize": {
      "endpoint": "otlp.arize.com:443",
      "api_key": "",
      "space_id": ""
    }
  }
}
EOF
    ;;
  arize)
    cat > "$SHARED_CONFIG" <<EOF
{
  "collector": {
    "host": "127.0.0.1",
    "port": 4318
  },
  "backend": {
    "target": "arize",
    "phoenix": {
      "endpoint": "http://localhost:6006",
      "api_key": ""
    },
    "arize": {
      "endpoint": "${ARIZE_OTLP_ENDPOINT:-otlp.arize.com:443}",
      "api_key": "${ARIZE_API_KEY}",
      "space_id": "${ARIZE_SPACE_ID}",
      "project_name": "${ARIZE_PROJECT_NAME:-codex}"
    }
  }
}
EOF
    ;;
esac

chmod 600 "$SHARED_CONFIG"
info "Wrote shared collector config to $SHARED_CONFIG"

# Install shared collector runtime (symlink core/collector.py)
SHARED_COLLECTOR_PY="${REPO_ROOT}/core/collector.py"
SHARED_BIN="${SHARED_BASE}/bin/arize-collector"
if [[ -f "$SHARED_COLLECTOR_PY" ]]; then
  # Create a wrapper script that invokes the collector with python3
  cat > "$SHARED_BIN" <<BINEOF
#!/bin/bash
exec python3 "${SHARED_COLLECTOR_PY}" "\$@"
BINEOF
  chmod +x "$SHARED_BIN"
  info "Installed shared collector to $SHARED_BIN"
fi

# --- Configure native OTLP export via Codex event buffer ---
# The event buffer captures Codex's native OTel events and buffers them for
# child-span assembly.  It runs on port 4319 (separate from shared collector on 4318).
EVENT_BUFFER_PORT="${CODEX_EVENT_PORT:-${CODEX_COLLECTOR_PORT:-4319}}"

if grep -q "^\[otel\]" "$CODEX_CONFIG" 2>/dev/null; then
  # Update existing [otel] section to point at event buffer
  cp "$CODEX_CONFIG" "${CODEX_CONFIG}.bak"
  # Remove old [otel] section and any nested [otel.*] tables.
  awk '
    BEGIN { skip=0 }
    /^\[otel(\.|\])/ { skip=1; next }
    skip && /^\[/ && $0 !~ /^\[otel(\.|\])/ { skip=0 }
    !skip { print }
  ' "${CODEX_CONFIG}.bak" > "$CODEX_CONFIG"
  info "Removed old [otel] section from config.toml"
fi

cat >> "$CODEX_CONFIG" <<EOF

# Arize event buffer — captures Codex events for rich span trees
[otel]
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:${EVENT_BUFFER_PORT}/v1/logs"
protocol = "json"
EOF
info "Added [otel] exporter pointing to event buffer (port $EVENT_BUFFER_PORT)"

# --- Install codex proxy wrapper ---
mkdir -p "$PROXY_DIR"
if [[ -f "$PROXY_PATH" ]] && ! grep -q "ARIZE_CODEX_PROXY" "$PROXY_PATH" 2>/dev/null; then
  cp "$PROXY_PATH" "$PROXY_BACKUP"
  info "Backed up existing ${PROXY_PATH} to ${PROXY_BACKUP}"
fi
sed \
  -e "s|__REAL_CODEX__|${REAL_CODEX_BIN}|g" \
  -e "s|__ARIZE_ENV_FILE__|${ENV_FILE}|g" \
  -e "s|__SHARED_COLLECTOR_CTL__|${SHARED_COLLECTOR_CTL}|g" \
  -e "s|__EVENT_BUFFER_CTL__|${EVENT_BUFFER_CTL}|g" \
  "$PROXY_TEMPLATE" > "$PROXY_PATH"
chmod +x "$PROXY_PATH"
info "Installed codex proxy to ${PROXY_PATH}"

# --- Start shared collector ---
if [[ -f "$SHARED_COLLECTOR_CTL" ]]; then
  source "$SHARED_COLLECTOR_CTL"
  if collector_start >/dev/null 2>&1; then
    info "Shared collector started (port 4318)"
  else
    warn "Could not start shared collector — the proxy will retry on next codex launch"
  fi
fi

# --- Start event buffer ---
if [[ -f "$EVENT_BUFFER_CTL" ]]; then
  source "$EVENT_BUFFER_CTL"
  if event_buffer_start >/dev/null 2>&1; then
    info "Event buffer started (port $EVENT_BUFFER_PORT)"
  else
    warn "Could not start event buffer — the proxy will retry on next codex launch"
  fi
fi

# --- Ensure ~/.local/bin is on PATH ahead of the real codex ---
PROFILE_LINE='export PATH="$HOME/.local/bin:$PATH"'
SHELL_PROFILE="$(detect_shell_profile)"

for profile in "${HOME}/.zshrc" "${HOME}/.bashrc" "${HOME}/.bash_profile"; do
  if [[ -f "$profile" ]] && grep -q "collector_ctl.sh" "$profile" 2>/dev/null; then
    cp "$profile" "${profile}.bak"
    sed -i.tmp '/arize-codex.*collector_ctl/d; /collector_ensure/d; /event_buffer_ensure/d' "$profile"
    rm -f "${profile}.tmp"
    info "Removed old collector auto-start from $(basename "$profile")"
  fi
done

add_to_profile="n"
if [[ -t 0 ]]; then
  echo ""
  read -rp "  Ensure ~/.local/bin is prepended in your shell profile for the codex proxy? [Y/n]: " add_to_profile
  add_to_profile="${add_to_profile:-y}"
else
  add_to_profile="y"
fi

if [[ "$add_to_profile" =~ ^[Yy] ]]; then
  if [[ -n "$SHELL_PROFILE" ]]; then
    if grep -q "prepend ~/.local/bin for codex proxy" "$SHELL_PROFILE" 2>/dev/null; then
      info "PATH update already present in $(basename "$SHELL_PROFILE")"
    else
      echo "" >> "$SHELL_PROFILE"
      echo "$PATH_PROFILE_MARKER" >> "$SHELL_PROFILE"
      echo "$PROFILE_LINE" >> "$SHELL_PROFILE"
      info "Added PATH update to $(basename "$SHELL_PROFILE")"
    fi
  else
    warn "Could not detect shell profile. Add manually:"
    echo "    $PROFILE_LINE"
  fi
fi

# --- Write event buffer port to env file ---
if ! grep -q "CODEX_EVENT_PORT" "$ENV_FILE" 2>/dev/null; then
  echo "export CODEX_EVENT_PORT=${EVENT_BUFFER_PORT}" >> "$ENV_FILE"
fi

# --- Summary ---
echo ""
info "Setup complete!"
echo ""
echo "  Add this to your shell profile (.zshrc / .bashrc) if not already done:"
echo ""
echo "    source ${ENV_FILE}"
echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
echo ""
echo "  Or export the variables before running codex:"
echo ""
case "$TARGET" in
  phoenix)
    echo "    export ARIZE_TRACE_ENABLED=true"
    echo "    export PHOENIX_ENDPOINT=${PHOENIX_ENDPOINT}"
    ;;
  arize)
    echo "    export ARIZE_TRACE_ENABLED=true"
    echo "    export ARIZE_API_KEY=<your-key>"
    echo "    export ARIZE_SPACE_ID=<your-space-id>"
    ;;
esac
echo ""
echo "  Architecture:"
echo "    Shared collector (port 4318) — exports spans to ${TARGET}"
echo "    Event buffer (port ${EVENT_BUFFER_PORT}) — buffers Codex OTel events for child spans"
echo ""
echo "  The proxy wrapper at ${PROXY_PATH} ensures both are running before Codex starts."
echo "  Manage the shared collector: source ${SHARED_COLLECTOR_CTL}"
echo "    collector_status  — check if running"
echo "    collector_stop    — stop the collector"
echo "    collector_ensure  — start if not running (idempotent)"
echo ""
echo "  Manage the event buffer: source ${EVENT_BUFFER_CTL}"
echo "    event_buffer_status  — check if running"
echo "    event_buffer_stop    — stop the event buffer"
echo "    event_buffer_ensure  — start if not running (idempotent)"
echo ""
echo "  Test with: ARIZE_DRY_RUN=true codex"
echo ""
echo "  View traces:"
case "$TARGET" in
  phoenix) echo "    Open ${PHOENIX_ENDPOINT} in your browser" ;;
  arize)   echo "    Open https://app.arize.com and navigate to your space" ;;
esac
echo ""
