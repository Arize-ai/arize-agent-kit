#!/bin/bash
# Arize Codex Tracing Plugin - Interactive Setup
# Run after: claude plugin install codex-tracing@arize-agent-kit
# Or run directly: bash codex-tracing/scripts/setup.sh

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[arize]${NC} $*"; }
warn() { echo -e "${YELLOW}[arize]${NC} $*"; }
err()  { echo -e "${RED}[arize]${NC} $*" >&2; }

echo ""
echo -e "${GREEN}▸ ARIZE${NC} Codex Tracing Setup"
echo ""

# --- Paths ---
SHARED_BASE="${HOME}/.arize/harness"
SHARED_CONFIG="${SHARED_BASE}/config.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CODEX_CONFIG_DIR="${HOME}/.codex"
CODEX_CONFIG="${CODEX_CONFIG_DIR}/config.toml"
ENV_FILE="${CODEX_CONFIG_DIR}/arize-env.sh"

_AK_PYTHON="${SHARED_BASE}/venv/bin/python3"
_AK_CONFIG_PY="${REPO_DIR}/core/config.py"

# --- Validate Python + PyYAML availability ---
if [[ ! -x "$_AK_PYTHON" ]]; then
  _AK_PYTHON="python3"
fi
if ! "$_AK_PYTHON" -c "import yaml" 2>/dev/null; then
  err "PyYAML not available. Run install.sh first to set up the collector venv."
  exit 1
fi

# --- Config helpers (require python + config.py) ---
_cfg_get() { "${_AK_PYTHON}" "${_AK_CONFIG_PY}" get "$1" 2>/dev/null; }
_cfg_set() { "${_AK_PYTHON}" "${_AK_CONFIG_PY}" set "$1" "$2"; }

# --- Check for existing config ---
existing_backend=""
if [[ -f "$SHARED_CONFIG" ]]; then
  existing_backend=$(_cfg_get "backend.target") || true
fi

if [[ -n "$existing_backend" ]]; then
  echo -e "${YELLOW}Existing config found:${NC} backend=${existing_backend} in ${SHARED_CONFIG}"
  echo "Skipping credential prompts — adding codex harness entry."
  echo ""

  # Add codex harness entry
  _cfg_set "harnesses.codex.project_name" "codex"
  info "Added codex harness to existing config"

  # Write env file from existing config
  mkdir -p "$CODEX_CONFIG_DIR"
  case "$existing_backend" in
    phoenix)
      phoenix_ep=$(_cfg_get "backend.phoenix.endpoint")
      phoenix_ep="${phoenix_ep:-http://localhost:6006}"
      phoenix_key=$(_cfg_get "backend.phoenix.api_key")
      cat > "$ENV_FILE" <<EOF
# Arize Codex tracing environment (auto-generated)
export ARIZE_TRACE_ENABLED=true
export PHOENIX_ENDPOINT="${phoenix_ep}"
${phoenix_key:+export PHOENIX_API_KEY="${phoenix_key}"}
export ARIZE_PROJECT_NAME="codex"
EOF
      ;;
    arize)
      arize_ep=$(_cfg_get "backend.arize.endpoint")
      arize_ep="${arize_ep:-otlp.arize.com:443}"
      arize_key=$(_cfg_get "backend.arize.api_key")
      arize_space=$(_cfg_get "backend.arize.space_id")
      cat > "$ENV_FILE" <<EOF
# Arize Codex tracing environment (auto-generated)
export ARIZE_TRACE_ENABLED=true
export ARIZE_API_KEY="${arize_key}"
export ARIZE_SPACE_ID="${arize_space}"
export ARIZE_OTLP_ENDPOINT="${arize_ep}"
export ARIZE_PROJECT_NAME="codex"
EOF
      ;;
    *)
      err "Unknown backend in config: $existing_backend"
      exit 1
      ;;
  esac
  chmod 600 "$ENV_FILE"
  info "Wrote credentials to $ENV_FILE"
else
  # --- No existing config — prompt for backend ---
  echo "Which backend do you want to use?"
  echo ""
  echo "  1) Phoenix (self-hosted, no Python required)"
  echo "  2) Arize AX (cloud, requires Python)"
  echo ""
  read -rp "Enter choice [1/2]: " choice

  case "$choice" in
    1|phoenix|Phoenix)
      TARGET="phoenix"
      echo ""
      read -rp "Phoenix endpoint [http://localhost:6006]: " phoenix_endpoint
      phoenix_endpoint="${phoenix_endpoint:-http://localhost:6006}"
      info "Target: Phoenix at $phoenix_endpoint"
      ;;
    2|arize|ax|AX)
      TARGET="arize"
      echo ""
      read -rp "Arize API Key: " api_key
      read -rp "Arize Space ID: " space_id

      if [[ -z "$api_key" || -z "$space_id" ]]; then
        err "API key and Space ID are required for Arize AX"
        exit 1
      fi

      echo ""
      echo -e "${YELLOW}OTLP Endpoint${NC} (for hosted Arize instances, leave blank for default):"
      read -rp "OTLP Endpoint [otlp.arize.com:443]: " otlp_endpoint
      otlp_endpoint="${otlp_endpoint:-otlp.arize.com:443}"
      info "Target: Arize AX (endpoint: $otlp_endpoint)"
      ;;
    *)
      err "Invalid choice. Run setup again."
      exit 1
      ;;
  esac

  # --- Write config.yaml ---
  mkdir -p "${SHARED_BASE}/bin" "${SHARED_BASE}/run" "${SHARED_BASE}/logs"

  case "$TARGET" in
    phoenix)
      cat > "$SHARED_CONFIG" <<EOF
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "phoenix"
  phoenix:
    endpoint: "${phoenix_endpoint}"
    api_key: ""
  arize:
    endpoint: "otlp.arize.com:443"
    api_key: ""
    space_id: ""
harnesses:
  codex:
    project_name: "codex"
EOF
      ;;
    arize)
      cat > "$SHARED_CONFIG" <<EOF
collector:
  host: "127.0.0.1"
  port: 4318
backend:
  target: "arize"
  phoenix:
    endpoint: "http://localhost:6006"
    api_key: ""
  arize:
    endpoint: "${otlp_endpoint}"
    api_key: "${api_key}"
    space_id: "${space_id}"
harnesses:
  codex:
    project_name: "codex"
EOF
      ;;
  esac

  chmod 600 "$SHARED_CONFIG"
  info "Wrote shared collector config to $SHARED_CONFIG"

  # --- Write env file ---
  mkdir -p "$CODEX_CONFIG_DIR"

  case "$TARGET" in
    phoenix)
      cat > "$ENV_FILE" <<EOF
# Arize Codex tracing environment (auto-generated)
export ARIZE_TRACE_ENABLED=true
export PHOENIX_ENDPOINT="${phoenix_endpoint}"
export ARIZE_PROJECT_NAME="codex"
EOF
      ;;
    arize)
      cat > "$ENV_FILE" <<EOF
# Arize Codex tracing environment (auto-generated)
export ARIZE_TRACE_ENABLED=true
export ARIZE_API_KEY="${api_key}"
export ARIZE_SPACE_ID="${space_id}"
export ARIZE_OTLP_ENDPOINT="${otlp_endpoint}"
export ARIZE_PROJECT_NAME="codex"
EOF
      ;;
  esac

  chmod 600 "$ENV_FILE"
  info "Wrote credentials to $ENV_FILE"

  if [[ "$TARGET" == "arize" ]]; then
    echo ""
    echo -e "${YELLOW}Note:${NC} Arize AX backend requires Python dependencies for the collector:"
    echo "  pip install opentelemetry-proto grpcio"
  fi
fi

# --- Configure OTLP exporter in ~/.codex/config.toml ---
mkdir -p "$CODEX_CONFIG_DIR"
[[ -f "$CODEX_CONFIG" ]] || touch "$CODEX_CONFIG"

COLLECTOR_PORT=$(_cfg_get "collector.port")
COLLECTOR_PORT="${COLLECTOR_PORT:-4318}"

# Remove old [otel] section if present
if grep -q "^\[otel\]" "$CODEX_CONFIG" 2>/dev/null; then
  cp "$CODEX_CONFIG" "${CODEX_CONFIG}.bak"
  awk '
    BEGIN { skip=0; blanks=0 }
    /^\[otel(\.|\])/ { skip=1; blanks=0; next }
    skip && /^\[/ && $0 !~ /^\[otel(\.|\])/ { skip=0 }
    !skip && /^[[:space:]]*$/ { blanks++; next }
    !skip { for (i=0; i<blanks && NR>1; i++) print ""; blanks=0; print }
  ' "${CODEX_CONFIG}.bak" > "$CODEX_CONFIG"
  info "Removed old [otel] section from config.toml"
fi

cat >> "$CODEX_CONFIG" <<EOF

# Arize shared collector — captures Codex events for rich span trees
[otel]
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:${COLLECTOR_PORT}/v1/logs"
protocol = "json"
EOF
info "Added [otel] exporter pointing to shared collector (port $COLLECTOR_PORT)"

# --- Optional: User ID ---
echo ""
echo -e "${BLUE}Optional:${NC} Set a user ID to identify your spans (useful for teams)."
read -rp "User ID (leave blank to skip): " user_id
if [[ -n "$user_id" ]]; then
  _cfg_set "user_id" "$user_id"
  info "User ID set: $user_id"
fi

# --- Summary ---
echo ""
info "Setup complete!"
echo ""
echo "  Configuration:"
echo "    Config file:  ${SHARED_CONFIG}"
echo "    Env file:     ${ENV_FILE}"
echo "    Codex config: ${CODEX_CONFIG}"
echo ""
echo "  Next steps:"
echo "    1. Start the shared collector (if not already running):"
echo "       source ~/.arize/harness/core/collector_ctl.sh && collector_start"
echo "    2. Run codex — traces will be sent to your configured backend"
echo ""
echo "  To verify setup: ARIZE_DRY_RUN=true codex"
echo ""
