"""Tests for install.sh — the native bash installer."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_BAT = REPO_ROOT / "install.bat"


# ---------------------------------------------------------------------------
# File existence and basic validity
# ---------------------------------------------------------------------------

def test_install_sh_exists():
    """install.sh must exist at repo root."""
    assert INSTALL_SH.is_file()


def test_install_bat_exists():
    """install.bat must exist at repo root."""
    assert INSTALL_BAT.is_file()


def test_install_sh_is_executable():
    """install.sh must be executable."""
    assert os.access(INSTALL_SH, os.X_OK)


def test_install_sh_has_bash_shebang():
    """install.sh must start with a bash shebang."""
    first_line = INSTALL_SH.read_text().splitlines()[0]
    assert first_line.startswith("#!/bin/bash"), f"Expected bash shebang, got: {first_line}"


@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_syntax_valid():
    """install.sh must parse without syntax errors."""
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"Bash syntax error: {result.stderr}"


# ---------------------------------------------------------------------------
# Help / usage
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_help():
    """install.sh --help exits 0 and shows usage."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout or "usage" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_no_args_exits_nonzero():
    """install.sh with no arguments should exit with error."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0


@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
def test_install_sh_unknown_command_exits_nonzero():
    """install.sh with unknown command should exit with error."""
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "bogus"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Script content checks
# ---------------------------------------------------------------------------

def test_install_sh_has_all_commands():
    """install.sh must support claude, codex, copilot, cursor, update, uninstall."""
    text = INSTALL_SH.read_text()
    for cmd in ["claude", "codex", "copilot", "cursor", "update", "uninstall"]:
        assert cmd in text, f"Missing command: {cmd}"


def test_install_sh_existing_repo_syncs_requested_branch():
    """Existing harness git dir must fetch/checkout INSTALL_BRANCH, not only git pull."""
    text = INSTALL_SH.read_text()
    assert "Syncing with origin/" in text
    assert "checkout -B" in text and "FETCH_HEAD" in text


def test_install_sh_venv_not_gated_on_collector_py():
    """Hooks need the venv even when core/collector.py is missing (e.g. shallow main branch)."""
    text = INSTALL_SH.read_text()
    assert 'local pyproject="${INSTALL_DIR}/pyproject.toml"' in text
    assert 'if [[ -f "$pyproject" ]]; then' in text
    assert "hook_smoke=" in text and "arize-hook-session-start" in text


def test_install_sh_masks_api_key_prompts():
    """Backend API keys must be read with masked terminal output (not plain read -r)."""
    text = INSTALL_SH.read_text()
    assert "tty_read_masked_line" in text
    assert 'tty_read_masked_line "  Arize API key: "' in text
    assert 'CRED_ARIZE_API_KEY="$REPLY"' in text
    assert 'tty_read_masked_line "  Phoenix API key (blank if none): "' in text
    assert 'CRED_PHOENIX_API_KEY="$REPLY"' in text


def test_install_sh_has_hook_entry_points():
    """install.sh must reference all Claude hook entry points."""
    text = INSTALL_SH.read_text()
    expected_hooks = [
        "arize-hook-session-start",
        "arize-hook-user-prompt-submit",
        "arize-hook-pre-tool-use",
        "arize-hook-post-tool-use",
        "arize-hook-stop",
        "arize-hook-subagent-stop",
        "arize-hook-notification",
        "arize-hook-permission-request",
        "arize-hook-session-end",
    ]
    for hook in expected_hooks:
        assert hook in text, f"Missing hook entry point: {hook}"


def test_install_sh_has_cursor_events():
    """install.sh must reference all Cursor hook events."""
    text = INSTALL_SH.read_text()
    expected_events = [
        "beforeSubmitPrompt",
        "afterAgentResponse",
        "afterAgentThought",
        "beforeShellExecution",
        "afterShellExecution",
        "beforeMCPExecution",
        "afterMCPExecution",
        "beforeReadFile",
        "afterFileEdit",
        "beforeTabFileRead",
        "afterTabFileEdit",
    ]
    for event in expected_events:
        assert event in text, f"Missing Cursor event: {event}"


def test_install_sh_has_copilot_hook_entry_points():
    """install.sh must reference all Copilot hook entry points."""
    text = INSTALL_SH.read_text()
    expected_hooks = [
        "arize-hook-copilot-session-start",
        "arize-hook-copilot-user-prompt",
        "arize-hook-copilot-pre-tool",
        "arize-hook-copilot-post-tool",
        "arize-hook-copilot-stop",
        "arize-hook-copilot-subagent-stop",
        "arize-hook-copilot-error",
        "arize-hook-copilot-session-end",
    ]
    for hook in expected_hooks:
        assert hook in text, f"Missing Copilot hook entry point: {hook}"


def test_install_sh_has_setup_copilot_function():
    """install.sh must define setup_copilot function."""
    text = INSTALL_SH.read_text()
    assert "setup_copilot()" in text


def test_install_sh_copilot_vscode_hooks_format():
    """install.sh must write VS Code hooks with PascalCase keys and command field."""
    text = INSTALL_SH.read_text()
    assert "copilot-tracing.json" in text
    # VS Code events use PascalCase
    for event in ["SessionStart", "UserPromptSubmit", "PreToolUse",
                   "PostToolUse", "Stop", "SubagentStop"]:
        assert f'"{event}": "arize-hook-copilot-' in text, \
            f"Missing VS Code PascalCase event: {event}"
    # VS Code uses "command" field
    assert '"type": "command", "command": hook_cmd' in text


def test_install_sh_copilot_cli_hooks_format():
    """install.sh must write CLI hooks with camelCase keys, bash field, version 1."""
    text = INSTALL_SH.read_text()
    # CLI events use camelCase
    for event in ["sessionStart", "userPromptSubmitted", "preToolUse",
                   "postToolUse", "errorOccurred", "sessionEnd"]:
        assert f'"{event}": "arize-hook-copilot-' in text, \
            f"Missing CLI camelCase event: {event}"
    # CLI uses "bash" field and version 1
    assert '"type": "command", "bash": hook_cmd' in text
    assert '"version": 1' in text


def test_install_sh_venv_skip_requires_package_install():
    """Skipping pip install must require arize-agent-kit + console scripts, not yaml alone."""
    text = INSTALL_SH.read_text()
    assert 'import core" 2>/dev/null' in text or '"import core"' in text
    assert "arize-codex-buffer" in text


def test_install_sh_uses_pip_install_package():
    """install.sh must install the package via pip (not just individual deps)."""
    text = INSTALL_SH.read_text()
    assert 'pip" install' in text or "pip install" in text


def test_install_sh_no_jq_dependency():
    """install.sh must not require jq (uses Python for JSON instead)."""
    text = INSTALL_SH.read_text()
    # Should not have jq as a required dependency check
    assert "jq is required" not in text


def test_install_sh_does_not_reference_install_py():
    """install.sh must not reference install.py."""
    text = INSTALL_SH.read_text()
    assert "install.py" not in text


def test_install_bat_has_all_commands():
    """install.bat must support claude, codex, cursor, update, uninstall."""
    text = INSTALL_BAT.read_text()
    for cmd in ["claude", "codex", "cursor", "update", "uninstall"]:
        assert cmd.lower() in text.lower(), f"Missing command: {cmd}"


def test_install_bat_does_not_reference_install_py():
    """install.bat must not reference install.py."""
    text = INSTALL_BAT.read_text()
    assert "install.py" not in text


def test_install_bat_venv_not_gated_on_collector_py():
    """Windows installer must create venv when pyproject exists without requiring collector.py."""
    text = INSTALL_BAT.read_text()
    assert 'if exist "%INSTALL_DIR%\\pyproject.toml" (' in text
    assert 'if exist "%INSTALL_DIR%\\core\\collector.py" (' in text


def test_install_bat_venv_skip_requires_package_install():
    """Windows venv fast-path must verify package + arize-collector-ctl.exe exists."""
    text = INSTALL_BAT.read_text()
    assert "import core" in text
    assert "arize-collector-ctl.exe" in text


# ---------------------------------------------------------------------------
# Direct-send architecture: collector → buffer service rename
# ---------------------------------------------------------------------------

class TestCollectorToBufferRename:
    """Verify the collector has been renamed to buffer service throughout install.sh."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_no_setup_shared_collector_function(self):
        """setup_shared_collector must be renamed to setup_shared_runtime."""
        assert "setup_shared_collector" not in self.text

    def test_setup_shared_runtime_exists(self):
        """setup_shared_runtime function must be defined."""
        assert "setup_shared_runtime()" in self.text

    def test_no_write_collector_launcher_function(self):
        """write_collector_launcher must be renamed to write_buffer_launcher."""
        assert "write_collector_launcher" not in self.text

    def test_write_buffer_launcher_exists(self):
        """write_buffer_launcher function must be defined."""
        assert "write_buffer_launcher()" in self.text

    def test_no_start_collector_function(self):
        """start_collector must be renamed to start_codex_buffer."""
        # Must not contain start_collector as a function name (word boundary)
        import re
        assert not re.search(r'\bstart_collector\b', self.text)

    def test_start_codex_buffer_exists(self):
        """start_codex_buffer function must be defined."""
        assert "start_codex_buffer()" in self.text

    def test_no_stop_collector_function(self):
        """stop_collector must be renamed to stop_codex_buffer."""
        import re
        assert not re.search(r'\bstop_collector\b', self.text)

    def test_stop_codex_buffer_exists(self):
        """stop_codex_buffer function must be defined."""
        assert "stop_codex_buffer()" in self.text

    def test_no_arize_collector_ctl_reference(self):
        """No references to arize-collector-ctl should remain in install.sh."""
        assert "arize-collector-ctl" not in self.text

    def test_main_calls_setup_shared_runtime(self):
        """main() must call setup_shared_runtime for all four harnesses."""
        assert 'setup_shared_runtime "claude-code"' in self.text
        assert 'setup_shared_runtime "codex"' in self.text
        assert 'setup_shared_runtime "copilot"' in self.text
        assert 'setup_shared_runtime "cursor"' in self.text


# ---------------------------------------------------------------------------
# Buffer service constants
# ---------------------------------------------------------------------------

class TestBufferServiceConstants:
    """Verify buffer service constants are properly defined."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_buffer_bin_defined(self):
        """BUFFER_BIN constant must point to arize-codex-buffer."""
        assert 'BUFFER_BIN="${BIN_DIR}/arize-codex-buffer"' in self.text

    def test_buffer_pid_file_defined(self):
        """BUFFER_PID_FILE must point to codex-buffer.pid."""
        assert 'BUFFER_PID_FILE="${PID_DIR}/codex-buffer.pid"' in self.text

    def test_buffer_log_file_defined(self):
        """BUFFER_LOG_FILE must point to codex-buffer.log."""
        assert 'BUFFER_LOG_FILE="${LOG_DIR}/codex-buffer.log"' in self.text

    def test_legacy_collector_paths_kept_for_cleanup(self):
        """Legacy collector paths must remain for upgrade cleanup."""
        assert 'COLLECTOR_BIN="${BIN_DIR}/arize-collector"' in self.text
        assert 'PID_FILE="${PID_DIR}/collector.pid"' in self.text
        assert 'COLLECTOR_LOG_FILE="${LOG_DIR}/collector.log"' in self.text


# ---------------------------------------------------------------------------
# Buffer service only started for Codex
# ---------------------------------------------------------------------------

class TestBufferServiceCodexOnly:
    """Buffer service should only be started for Codex, not Claude or Cursor."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_buffer_start_gated_on_codex(self):
        """write_buffer_launcher and start_codex_buffer must be inside a codex check."""
        # The setup_shared_runtime function must gate buffer service on codex
        assert 'if [[ "$harness_name" == "codex" ]]; then' in self.text

    def test_buffer_launcher_references_codex_buffer_py(self):
        """write_buffer_launcher must reference core/codex_buffer.py, not core/collector.py."""
        assert "core/codex_buffer.py" in self.text
        assert "core/collector.py" not in self.text

    def test_claude_summary_no_collector_references(self):
        """Claude setup summary must say spans are sent directly, not mention collector."""
        # Find the Claude setup summary section
        assert "Spans are sent directly to your configured backend" in self.text

    def test_cursor_summary_mentions_direct_send(self):
        """Cursor setup summary must mention direct backend sending."""
        assert "Spans are sent directly to your configured backend" in self.text


# ---------------------------------------------------------------------------
# Per-harness credentials
# ---------------------------------------------------------------------------

class TestPerHarnessCredentials:
    """Verify per-harness credential support in install.sh."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_collect_backend_credentials_takes_harness_name(self):
        """collect_backend_credentials must accept a harness_name parameter."""
        assert 'local harness_name="${1:-}"' in self.text

    def test_cred_per_harness_variable_initialized(self):
        """CRED_PER_HARNESS must be initialized to false."""
        assert "CRED_PER_HARNESS=false" in self.text

    def test_existing_backend_reuse_prompt(self):
        """Must offer to reuse existing backend config."""
        assert "Use different backend for" in self.text
        assert "existing_backend" in self.text

    def test_per_harness_override_sets_flag(self):
        """Choosing to override must set CRED_PER_HARNESS=true."""
        assert "CRED_PER_HARNESS=true" in self.text

    def test_write_config_accepts_per_harness_param(self):
        """write_config must accept per_harness as 9th parameter."""
        assert 'local per_harness="${9:-false}"' in self.text

    def test_write_config_accepts_project_name_param(self):
        """write_config must accept project_name as 8th parameter."""
        assert 'local project_name="${8:-$harness_name}"' in self.text

    def test_write_config_per_harness_backend_block(self):
        """When per_harness is true, config must include harness-level backend block."""
        assert 'if [[ "$per_harness" == true ]]; then' in self.text
        # The per-harness YAML template should have backend nested under harness
        assert "    backend:" in self.text

    def test_write_config_no_collector_section(self):
        """Fresh config must not include a collector: section."""
        # The heredoc config template should not have collector block
        lines = self.text.split("\n")
        in_cfgeof = False
        for line in lines:
            if "cat > \"$CONFIG_FILE\" <<CFGEOF" in line:
                in_cfgeof = True
                continue
            if in_cfgeof and line.strip() == "CFGEOF":
                break
            if in_cfgeof:
                assert not line.startswith("collector:"), \
                    "Fresh config template must not contain collector: section"

    def test_buffer_port_only_for_codex(self):
        """Buffer port prompt must only appear for Codex harness."""
        assert 'if [[ "$harness_name" == "codex" ]]; then' in self.text
        assert "Buffer service port" in self.text


# ---------------------------------------------------------------------------
# Project name collection
# ---------------------------------------------------------------------------

class TestProjectNameCollection:
    """Verify project name prompt during install."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_collect_project_name_function_exists(self):
        """collect_project_name function must be defined."""
        assert "collect_project_name()" in self.text

    def test_collect_project_name_defaults_to_harness_name(self):
        """Project name must default to harness name."""
        assert 'local default_name="$harness_name"' in self.text
        assert 'CRED_PROJECT_NAME="$default_name"' in self.text

    def test_collect_project_name_prompts_user(self):
        """Must prompt user for project name."""
        assert "Set project name (default:" in self.text

    def test_collect_project_name_called_in_setup(self):
        """collect_project_name must be called during setup_shared_runtime."""
        assert 'collect_project_name "$harness_name"' in self.text

    def test_project_name_passed_to_write_config(self):
        """CRED_PROJECT_NAME must be passed to write_config."""
        assert '"$CRED_PROJECT_NAME"' in self.text


# ---------------------------------------------------------------------------
# Upgrade / uninstall cleanup
# ---------------------------------------------------------------------------

class TestUpgradeAndUninstallCleanup:
    """Verify upgrade and uninstall handle both old and new artifacts."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_stop_codex_buffer_stops_legacy_pid(self):
        """stop_codex_buffer must stop both legacy collector.pid and new codex-buffer.pid."""
        assert '"$PID_FILE" "legacy collector"' in self.text
        assert '"$BUFFER_PID_FILE" "buffer service"' in self.text

    def test_update_calls_stop_codex_buffer(self):
        """update_install must call stop_codex_buffer, not stop_collector."""
        # Find the update_install function body
        in_update = False
        for line in self.text.split("\n"):
            if "update_install()" in line:
                in_update = True
            if in_update and "stop_codex_buffer" in line:
                break
        else:
            pytest.fail("update_install must call stop_codex_buffer")

    def test_update_only_restarts_buffer_for_codex(self):
        """update_install must only restart buffer service if Codex is configured."""
        assert 'codex_configured=$(cfg_get "harnesses.codex.project_name")' in self.text

    def test_update_cleans_legacy_collector_artifacts(self):
        """update_install must remove legacy collector binary, PID, and log files."""
        assert 'rm -f "$COLLECTOR_BIN" "$PID_FILE" "$COLLECTOR_LOG_FILE"' in self.text

    def test_uninstall_removes_buffer_artifacts(self):
        """do_uninstall must remove buffer service artifacts."""
        assert 'rm -f "$BUFFER_BIN" "$BUFFER_PID_FILE" "$BUFFER_LOG_FILE"' in self.text

    def test_uninstall_removes_legacy_collector_artifacts(self):
        """do_uninstall must also remove legacy collector artifacts."""
        # Both buffer and collector cleanup in uninstall
        assert 'rm -f "$COLLECTOR_BIN" "$PID_FILE" "$COLLECTOR_LOG_FILE"' in self.text

    def test_uninstall_calls_stop_codex_buffer(self):
        """do_uninstall must call stop_codex_buffer."""
        in_uninstall = False
        for line in self.text.split("\n"):
            if "do_uninstall()" in line:
                in_uninstall = True
            if in_uninstall and "stop_codex_buffer" in line:
                break
        else:
            pytest.fail("do_uninstall must call stop_codex_buffer")


# ---------------------------------------------------------------------------
# Codex-specific messaging
# ---------------------------------------------------------------------------

class TestCodexMessaging:
    """Verify Codex setup messages reference buffer service correctly."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_codex_otel_comment_updated(self):
        """Codex OTLP config comment must reference buffer service."""
        assert "# Arize Codex buffer service" in self.text

    def test_codex_summary_references_buffer_logs(self):
        """Codex summary must reference buffer log file."""
        assert "View buffer service logs" in self.text

    def test_codex_proxy_uses_arize_codex_buffer(self):
        """Codex proxy wrapper must reference arize-codex-buffer entry point."""
        assert 'venv_bin "arize-codex-buffer"' in self.text


# ---------------------------------------------------------------------------
# Header / description updated
# ---------------------------------------------------------------------------

class TestScriptDescription:
    """Verify the script header describes the new architecture."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_header_no_background_collector(self):
        """Script header must not mention 'background collector'."""
        # Check the first 15 lines for header
        header = "\n".join(self.text.split("\n")[:15])
        assert "background" not in header.lower() or "collector" not in header.lower()

    def test_header_mentions_shared_venv_and_config(self):
        """Script header must mention shared venv and config."""
        header = "\n".join(self.text.split("\n")[:15])
        assert "shared venv and config" in header
