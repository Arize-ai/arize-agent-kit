#!/bin/bash
# Arize Agent Kit — Bootstrapper (macOS/Linux)
# Finds Python 3.9+, creates a venv, installs the package, then hands off
# all configuration to the `arize-install` Python CLI.
#
# Usage:
#   curl -sSL .../install.sh | bash -s -- claude
#   curl -sSL .../install.sh | bash -s -- codex --backend arize --api-key KEY
#   ./install.sh update
#   ./install.sh uninstall --harness claude
set -euo pipefail

REPO_URL="https://github.com/Arize-ai/arize-agent-kit.git"
INSTALL_BRANCH="${ARIZE_INSTALL_BRANCH:-main}"
TARBALL_URL="https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/${INSTALL_BRANCH}.tar.gz"
INSTALL_DIR="${HOME}/.arize/harness"
VENV_DIR="${INSTALL_DIR}/venv"

RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' BOLD='\033[1m' NC='\033[0m'
[[ -n "${NO_COLOR:-}" ]] || [[ ! -t 1 ]] && { RED="" GREEN="" YELLOW="" BOLD="" NC=""; }

info()  { echo -e "${GREEN}[arize]${NC} $*"; }
warn()  { echo -e "${YELLOW}[arize]${NC} $*"; }
err()   { echo -e "${RED}[arize]${NC} $*" >&2; }
command_exists() { command -v "$1" &>/dev/null; }

venv_bin() {
    if [[ -d "${VENV_DIR}/Scripts" ]]; then echo "${VENV_DIR}/Scripts/$1"
    else echo "${VENV_DIR}/bin/$1"; fi
}

find_python() {
    local candidates=(python3 python /usr/bin/python3 /usr/local/bin/python3 "$HOME/.local/bin/python3")
    [[ -d "$HOME/.pyenv/shims" ]] && candidates+=("$HOME/.pyenv/shims/python3")
    [[ -x "/opt/homebrew/bin/python3" ]] && candidates+=("/opt/homebrew/bin/python3")
    local cb; cb=$(conda info --base 2>/dev/null) && [[ -n "$cb" ]] && candidates+=("${cb}/bin/python3")
    for p in "${candidates[@]}"; do
        local r; [[ "$p" == /* ]] && r="$p" || r=$(command -v "$p" 2>/dev/null || true)
        [[ -z "$r" || ! -f "$r" ]] && continue
        "$r" -c "import sys; assert sys.version_info >= (3, 9)" 2>/dev/null && { echo "$r"; return 0; }
    done
    return 1
}

install_repo() {
    local branch="${INSTALL_BRANCH}"
    if [[ -d "${INSTALL_DIR}/.git" ]]; then
        info "Repository exists — syncing with origin/${branch}..."
        if git -C "$INSTALL_DIR" fetch --depth 1 origin "$branch" 2>/dev/null \
            && git -C "$INSTALL_DIR" checkout -B "$branch" FETCH_HEAD 2>/dev/null; then return 0; fi
        if git -C "$INSTALL_DIR" fetch origin "$branch" 2>/dev/null \
            && git -C "$INSTALL_DIR" checkout -B "$branch" FETCH_HEAD 2>/dev/null; then return 0; fi
        warn "git update failed — re-cloning"; rm -rf "$INSTALL_DIR"
    fi
    [[ -d "$INSTALL_DIR" && ! -d "${INSTALL_DIR}/.git" ]] && rm -rf "$INSTALL_DIR"
    if command_exists git; then
        info "Cloning arize-agent-kit..."
        git clone --depth 1 --branch "$branch" "$REPO_URL" "$INSTALL_DIR" 2>/dev/null && return 0
        warn "git clone failed — falling back to tarball"
    fi
    info "Downloading tarball..."
    local tmp; tmp="$(mktemp)"; trap 'rm -f "$tmp"' RETURN
    if command_exists curl; then curl -sSfL "$TARBALL_URL" -o "$tmp"
    elif command_exists wget; then wget -qO "$tmp" "$TARBALL_URL"
    else err "Neither curl nor wget found"; exit 1; fi
    mkdir -p "$INSTALL_DIR"
    tar xzf "$tmp" --strip-components=1 -C "$INSTALL_DIR"
}

setup_venv() {
    local python_cmd="$1"
    if [[ -x "$(venv_bin python)" ]]; then
        "$(venv_bin python)" -c "import core" 2>/dev/null && [[ -x "$(venv_bin arize-install)" ]] \
            && { info "Venv already set up"; return 0; }
    fi
    info "Creating venv..."
    "$python_cmd" -m venv "$VENV_DIR" 2>/dev/null || {
        err "Failed to create venv — you may need: apt install python3-venv"; return 1; }
    local pip; pip="$(venv_bin pip)"
    [[ -x "$pip" ]] || { err "pip not found in venv"; return 1; }
    info "Installing arize-agent-kit..."
    "$pip" install --quiet "$INSTALL_DIR" 2>/dev/null || { err "pip install failed"; return 1; }
    info "Venv ready"
}

usage() {
    cat <<EOF

${BOLD}Arize Agent Kit Installer${NC}

Usage: install.sh <command> [options]

Commands:  claude | codex | cursor | update | uninstall

All other options are passed through to arize-install.
Run: arize-install <command> --help  for details.

EOF
}

main() {
    local command="${1:-}"
    case "$command" in -h|--help|help|"") usage; [[ -z "$command" ]] && exit 1; exit 0;; esac
    shift || true

    # Extract --branch (consumed here); everything else passes through
    local pass_through=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --branch) INSTALL_BRANCH="${2:-main}"
                TARBALL_URL="https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/${INSTALL_BRANCH}.tar.gz"
                shift 2 ;;
            *) pass_through+=("$1"); shift ;;
        esac
    done

    # Fast path: if arize-install exists, hand off immediately
    local ai; ai="$(venv_bin arize-install)"
    [[ -x "$ai" ]] && exec "$ai" "$command" "${pass_through[@]+"${pass_through[@]}"}"

    # First-time bootstrap
    install_repo
    local py; py=$(find_python) || { err "Python 3.9+ required"; exit 1; }
    setup_venv "$py"

    ai="$(venv_bin arize-install)"
    [[ -x "$ai" ]] || { err "arize-install not found after setup"; exit 1; }
    exec "$ai" "$command" "${pass_through[@]+"${pass_through[@]}"}"
}

main "$@"
