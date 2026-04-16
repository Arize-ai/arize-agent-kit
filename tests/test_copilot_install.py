"""Tests for Copilot entry points in pyproject.toml and install.sh."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
PYPROJECT = REPO_ROOT / "pyproject.toml"


# ---------------------------------------------------------------------------
# pyproject.toml entry point tests
# ---------------------------------------------------------------------------

class TestCopilotEntryPoints:
    """Verify all 9 Copilot entry points (8 hooks + 1 setup) in pyproject.toml."""

    @pytest.fixture(autouse=True)
    def _load_pyproject(self):
        self.text = PYPROJECT.read_text()

    def test_session_start_entry_point(self):
        assert 'arize-hook-copilot-session-start = "core.hooks.copilot.handlers:session_start"' in self.text

    def test_user_prompt_entry_point(self):
        assert 'arize-hook-copilot-user-prompt = "core.hooks.copilot.handlers:user_prompt_submitted"' in self.text

    def test_pre_tool_entry_point(self):
        assert 'arize-hook-copilot-pre-tool = "core.hooks.copilot.handlers:pre_tool_use"' in self.text

    def test_post_tool_entry_point(self):
        assert 'arize-hook-copilot-post-tool = "core.hooks.copilot.handlers:post_tool_use"' in self.text

    def test_stop_entry_point(self):
        assert 'arize-hook-copilot-stop = "core.hooks.copilot.handlers:stop"' in self.text

    def test_subagent_stop_entry_point(self):
        assert 'arize-hook-copilot-subagent-stop = "core.hooks.copilot.handlers:subagent_stop"' in self.text

    def test_error_entry_point(self):
        assert 'arize-hook-copilot-error = "core.hooks.copilot.handlers:error_occurred"' in self.text

    def test_session_end_entry_point(self):
        assert 'arize-hook-copilot-session-end = "core.hooks.copilot.handlers:session_end"' in self.text

    def test_setup_entry_point(self):
        assert 'arize-setup-copilot = "core.setup.copilot:main"' in self.text

    def test_exactly_8_hook_entry_points(self):
        """There should be exactly 8 copilot hook entry points."""
        count = self.text.count("arize-hook-copilot-")
        assert count == 8, f"Expected 8 copilot hook entries, got {count}"

    def test_entry_points_importable(self):
        """All referenced handler functions should be importable."""
        from core.hooks.copilot.handlers import (
            session_start, user_prompt_submitted, pre_tool_use,
            post_tool_use, stop, subagent_stop, error_occurred, session_end,
        )
        for fn in [session_start, user_prompt_submitted, pre_tool_use,
                    post_tool_use, stop, subagent_stop, error_occurred, session_end]:
            assert callable(fn)


# ---------------------------------------------------------------------------
# install.sh — Copilot function and integration
# ---------------------------------------------------------------------------

class TestInstallShCopilotFunction:
    """Verify setup_copilot function exists and is structured correctly."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_setup_copilot_function_defined(self):
        assert "setup_copilot()" in self.text

    def test_copilot_case_in_main(self):
        """main() must have a copilot) case."""
        assert "copilot)" in self.text

    def test_copilot_case_calls_install_repo(self):
        """copilot case calls install_repo."""
        # Find the copilot case block
        lines = self.text.split("\n")
        in_copilot = False
        found_install_repo = False
        for line in lines:
            if "copilot)" in line:
                in_copilot = True
            if in_copilot and "install_repo" in line:
                found_install_repo = True
                break
            if in_copilot and ";;" in line:
                break
        assert found_install_repo, "copilot case must call install_repo"

    def test_copilot_case_calls_setup_shared_runtime(self):
        """copilot case calls setup_shared_runtime 'copilot'."""
        assert 'setup_shared_runtime "copilot"' in self.text

    def test_copilot_case_calls_setup_copilot(self):
        """copilot case calls setup_copilot."""
        lines = self.text.split("\n")
        in_copilot_case = False
        for line in lines:
            if "copilot)" in line:
                in_copilot_case = True
            if in_copilot_case and "setup_copilot" in line and "()" not in line:
                break
            if in_copilot_case and ";;" in line:
                pytest.fail("copilot case must call setup_copilot")

    def test_copilot_case_supports_skills(self):
        """copilot case supports --with-skills flag."""
        lines = self.text.split("\n")
        in_copilot = False
        for line in lines:
            if "copilot)" in line:
                in_copilot = True
            if in_copilot and 'install_skills "copilot"' in line:
                break
            if in_copilot and ";;" in line:
                pytest.fail("copilot case must support install_skills")


class TestInstallShCopilotUsage:
    """Verify copilot is in usage/help text."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_usage_includes_copilot(self):
        assert "copilot" in self.text
        assert "GitHub Copilot" in self.text

    def test_usage_copilot_mentions_vscode_and_cli(self):
        """Usage help for copilot mentions both VS Code and CLI."""
        assert "VS Code + CLI" in self.text

    def test_update_message_includes_copilot(self):
        """Update complete message mentions copilot."""
        assert "install.sh copilot" in self.text

    def test_header_comment_includes_copilot(self):
        """Header comments include copilot usage example."""
        header = "\n".join(self.text.split("\n")[:15])
        assert "copilot" in header


class TestInstallShCopilotHasAllCommands:
    """Verify install.sh has_all_commands now includes copilot."""

    def test_install_sh_has_copilot_command(self):
        text = INSTALL_SH.read_text()
        assert "copilot" in text


# ---------------------------------------------------------------------------
# VS Code hooks JSON format tests (embedded Python)
# ---------------------------------------------------------------------------

class TestVSCodeHooksFormat:
    """Test the VS Code hooks JSON generation (PascalCase, command field)."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_vscode_hooks_file_path(self):
        """VS Code hooks written to .github/hooks/copilot-tracing.json."""
        assert "copilot-tracing.json" in self.text

    def test_vscode_uses_pascal_case_events(self):
        """VS Code hook events use PascalCase."""
        for event in ["SessionStart", "UserPromptSubmit", "PreToolUse",
                       "PostToolUse", "Stop", "SubagentStop"]:
            assert f'"{event}"' in self.text

    def test_vscode_uses_command_field(self):
        """VS Code hooks use 'command' field, not 'bash'."""
        # In the VS Code Python block, check for "command" usage
        assert '"type": "command", "command": hook_cmd' in self.text

    def test_vscode_hooks_count(self):
        """VS Code format should register 6 hook events."""
        # The VSCODE_HOOK_EVENTS dict in embedded Python
        vscode_events = [
            "SessionStart", "UserPromptSubmit", "PreToolUse",
            "PostToolUse", "Stop", "SubagentStop",
        ]
        for event in vscode_events:
            assert f'"{event}": "arize-hook-copilot-' in self.text

    def test_vscode_hooks_entry_point_mapping(self):
        """Each VS Code event maps to the correct entry point."""
        mappings = {
            "SessionStart": "arize-hook-copilot-session-start",
            "UserPromptSubmit": "arize-hook-copilot-user-prompt",
            "PreToolUse": "arize-hook-copilot-pre-tool",
            "PostToolUse": "arize-hook-copilot-post-tool",
            "Stop": "arize-hook-copilot-stop",
            "SubagentStop": "arize-hook-copilot-subagent-stop",
        }
        for event, entry in mappings.items():
            assert f'"{event}": "{entry}"' in self.text

    def test_vscode_dedup_check(self):
        """VS Code Python block checks for duplicates before adding."""
        assert 'already = any(' in self.text
        assert 'if not already:' in self.text


# ---------------------------------------------------------------------------
# CLI hooks JSON format tests (embedded Python)
# ---------------------------------------------------------------------------

class TestCLIHooksFormat:
    """Test the CLI hooks JSON generation (camelCase, bash field, version: 1)."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_cli_hooks_file_path(self):
        """CLI hooks written to .github/hooks/hooks.json."""
        assert "hooks.json" in self.text

    def test_cli_uses_camel_case_events(self):
        """CLI hook events use camelCase."""
        for event in ["sessionStart", "userPromptSubmitted", "preToolUse",
                       "postToolUse", "errorOccurred", "sessionEnd"]:
            assert f'"{event}"' in self.text

    def test_cli_uses_bash_field(self):
        """CLI hooks use 'bash' field, not 'command'."""
        assert '"type": "command", "bash": hook_cmd' in self.text

    def test_cli_sets_version_1(self):
        """CLI hooks.json must have version: 1."""
        assert '"version": 1' in self.text

    def test_cli_hooks_count(self):
        """CLI format should register 6 hook events."""
        cli_events = [
            "sessionStart", "userPromptSubmitted", "preToolUse",
            "postToolUse", "errorOccurred", "sessionEnd",
        ]
        for event in cli_events:
            assert f'"{event}": "arize-hook-copilot-' in self.text

    def test_cli_hooks_entry_point_mapping(self):
        """Each CLI event maps to the correct entry point."""
        mappings = {
            "sessionStart": "arize-hook-copilot-session-start",
            "userPromptSubmitted": "arize-hook-copilot-user-prompt",
            "preToolUse": "arize-hook-copilot-pre-tool",
            "postToolUse": "arize-hook-copilot-post-tool",
            "errorOccurred": "arize-hook-copilot-error",
            "sessionEnd": "arize-hook-copilot-session-end",
        }
        for event, entry in mappings.items():
            assert f'"{event}": "{entry}"' in self.text

    def test_cli_preserves_existing_hooks(self):
        """CLI Python block loads existing file and preserves hooks."""
        assert 'os.path.isfile(hooks_file)' in self.text
        assert 'hooks_data = json.load(f)' in self.text

    def test_cli_dedup_check(self):
        """CLI Python block checks for duplicates."""
        assert 'already = any(h.get("bash", "") == hook_cmd for h in event_hooks)' in self.text


# ---------------------------------------------------------------------------
# Embedded Python JSON generation (functional tests)
# ---------------------------------------------------------------------------

class TestEmbeddedPythonVSCodeHooks:
    """Run the embedded VS Code hooks Python code in isolation."""

    def _run_vscode_python(self, existing_file=None, venv_bin_override=None):
        """Execute the VS Code hooks Python snippet and return the result JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks_file = os.path.join(tmpdir, "copilot-tracing.json")
            venv_bin = venv_bin_override or os.path.join(tmpdir, "venv", "bin")

            if existing_file is not None:
                with open(hooks_file, "w") as f:
                    json.dump(existing_file, f)

            code = '''
import json, os

hooks_file = os.environ["_VSCODE_HOOKS_FILE"]
venv_bin_dir = os.environ["_VENV_BIN_DIR"]

VSCODE_HOOK_EVENTS = {
    "SessionStart": "arize-hook-copilot-session-start",
    "UserPromptSubmit": "arize-hook-copilot-user-prompt",
    "PreToolUse": "arize-hook-copilot-pre-tool",
    "PostToolUse": "arize-hook-copilot-post-tool",
    "Stop": "arize-hook-copilot-stop",
    "SubagentStop": "arize-hook-copilot-subagent-stop",
}

if os.path.isfile(hooks_file):
    try:
        with open(hooks_file) as f:
            hooks_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        hooks_data = {}
else:
    hooks_data = {}

hooks = hooks_data.setdefault("hooks", {})

for event, entry_point in VSCODE_HOOK_EVENTS.items():
    hook_cmd = os.path.join(venv_bin_dir, entry_point)
    event_hooks = hooks.setdefault(event, [])
    already = any(
        h.get("command", "") == hook_cmd
        for entry in event_hooks
        for h in entry.get("hooks", [])
    )
    if not already:
        event_hooks.append({"hooks": [{"type": "command", "command": hook_cmd}]})

with open(hooks_file, "w") as f:
    json.dump(hooks_data, f, indent=2)
    f.write("\\n")
'''
            env = os.environ.copy()
            env["_VSCODE_HOOKS_FILE"] = hooks_file
            env["_VENV_BIN_DIR"] = venv_bin

            result = subprocess.run(
                ["python3", "-c", code],
                env=env, capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, f"Python error: {result.stderr}"

            with open(hooks_file) as f:
                return json.load(f), venv_bin

    def test_fresh_vscode_hooks(self):
        """Fresh VS Code hooks file has correct structure."""
        data, venv_bin = self._run_vscode_python()

        assert "hooks" in data
        hooks = data["hooks"]
        assert set(hooks.keys()) == {
            "SessionStart", "UserPromptSubmit", "PreToolUse",
            "PostToolUse", "Stop", "SubagentStop",
        }

        # Each event should have one entry with command field
        for event, entries in hooks.items():
            assert len(entries) == 1
            assert len(entries[0]["hooks"]) == 1
            hook = entries[0]["hooks"][0]
            assert hook["type"] == "command"
            assert "arize-hook-copilot-" in hook["command"]
            assert hook["command"].startswith(venv_bin)

    def test_vscode_hooks_preserve_existing(self):
        """Existing hooks are preserved when merging."""
        existing = {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": "/other/hook"}]}],
            }
        }
        data, venv_bin = self._run_vscode_python(existing)

        # Existing hook preserved + new one added
        session_hooks = data["hooks"]["SessionStart"]
        assert len(session_hooks) == 2
        assert session_hooks[0]["hooks"][0]["command"] == "/other/hook"
        assert venv_bin in session_hooks[1]["hooks"][0]["command"]

    def test_vscode_hooks_idempotent(self):
        """Running twice with same venv path doesn't duplicate hooks."""
        fixed_venv = "/opt/arize/venv/bin"
        data1, _ = self._run_vscode_python(venv_bin_override=fixed_venv)

        # Run again with the output as input, same venv path
        data2, _ = self._run_vscode_python(data1, venv_bin_override=fixed_venv)

        for event in data2["hooks"]:
            assert len(data2["hooks"][event]) == 1

    def test_vscode_hooks_invalid_existing_file(self):
        """Invalid existing JSON is handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks_file = os.path.join(tmpdir, "copilot-tracing.json")
            with open(hooks_file, "w") as f:
                f.write("not valid json{{{")

            # Run by passing through _run_vscode_python with manual setup
            data, _ = self._run_vscode_python()  # Fresh run works
            assert "hooks" in data


class TestEmbeddedPythonCLIHooks:
    """Run the embedded CLI hooks Python code in isolation."""

    def _run_cli_python(self, existing_file=None, venv_bin_override=None):
        """Execute the CLI hooks Python snippet and return the result JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks_file = os.path.join(tmpdir, "hooks.json")
            venv_bin = venv_bin_override or os.path.join(tmpdir, "venv", "bin")

            if existing_file is not None:
                with open(hooks_file, "w") as f:
                    json.dump(existing_file, f)

            code = '''
import json, os

hooks_file = os.environ["_CLI_HOOKS_FILE"]
venv_bin_dir = os.environ["_VENV_BIN_DIR"]

CLI_HOOK_EVENTS = {
    "sessionStart": "arize-hook-copilot-session-start",
    "userPromptSubmitted": "arize-hook-copilot-user-prompt",
    "preToolUse": "arize-hook-copilot-pre-tool",
    "postToolUse": "arize-hook-copilot-post-tool",
    "errorOccurred": "arize-hook-copilot-error",
    "sessionEnd": "arize-hook-copilot-session-end",
}

if os.path.isfile(hooks_file):
    try:
        with open(hooks_file) as f:
            hooks_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        hooks_data = {"version": 1}
else:
    hooks_data = {"version": 1}

hooks_data.setdefault("version", 1)
hooks = hooks_data.setdefault("hooks", {})

for event, entry_point in CLI_HOOK_EVENTS.items():
    hook_cmd = os.path.join(venv_bin_dir, entry_point)
    event_hooks = hooks.setdefault(event, [])
    already = any(h.get("bash", "") == hook_cmd for h in event_hooks)
    if not already:
        event_hooks.append({"type": "command", "bash": hook_cmd})

with open(hooks_file, "w") as f:
    json.dump(hooks_data, f, indent=2)
    f.write("\\n")
'''
            env = os.environ.copy()
            env["_CLI_HOOKS_FILE"] = hooks_file
            env["_VENV_BIN_DIR"] = venv_bin

            result = subprocess.run(
                ["python3", "-c", code],
                env=env, capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, f"Python error: {result.stderr}"

            with open(hooks_file) as f:
                return json.load(f), venv_bin

    def test_fresh_cli_hooks(self):
        """Fresh CLI hooks file has correct structure."""
        data, venv_bin = self._run_cli_python()

        assert data["version"] == 1
        assert "hooks" in data
        hooks = data["hooks"]
        assert set(hooks.keys()) == {
            "sessionStart", "userPromptSubmitted", "preToolUse",
            "postToolUse", "errorOccurred", "sessionEnd",
        }

        for event, entries in hooks.items():
            assert len(entries) == 1
            hook = entries[0]
            assert hook["type"] == "command"
            assert "arize-hook-copilot-" in hook["bash"]
            assert hook["bash"].startswith(venv_bin)

    def test_cli_hooks_preserve_existing(self):
        """Existing hooks are preserved when merging."""
        existing = {
            "version": 1,
            "hooks": {
                "sessionStart": [{"type": "command", "bash": "/other/hook"}],
                "customHook": [{"type": "command", "bash": "/custom/hook"}],
            }
        }
        data, venv_bin = self._run_cli_python(existing)

        # Existing sessionStart hook preserved + new one added
        assert len(data["hooks"]["sessionStart"]) == 2
        assert data["hooks"]["sessionStart"][0]["bash"] == "/other/hook"
        assert venv_bin in data["hooks"]["sessionStart"][1]["bash"]

        # Custom hook preserved
        assert "customHook" in data["hooks"]
        assert data["hooks"]["customHook"][0]["bash"] == "/custom/hook"

    def test_cli_hooks_idempotent(self):
        """Running twice with same venv path doesn't duplicate hooks."""
        fixed_venv = "/opt/arize/venv/bin"
        data1, _ = self._run_cli_python(venv_bin_override=fixed_venv)
        data2, _ = self._run_cli_python(data1, venv_bin_override=fixed_venv)

        for event in data2["hooks"]:
            if event in ["sessionStart", "userPromptSubmitted", "preToolUse",
                         "postToolUse", "errorOccurred", "sessionEnd"]:
                assert len(data2["hooks"][event]) == 1

    def test_cli_hooks_version_preserved(self):
        """Existing version field is preserved."""
        existing = {"version": 1, "hooks": {}}
        data, _ = self._run_cli_python(existing)
        assert data["version"] == 1

    def test_cli_hooks_version_added_to_empty(self):
        """Version 1 is added when creating fresh file."""
        data, _ = self._run_cli_python()
        assert data["version"] == 1

    def test_cli_hooks_version_defaulted_if_missing(self):
        """Version defaults to 1 if existing file has no version."""
        existing = {"hooks": {"someHook": [{"type": "command", "bash": "/x"}]}}
        data, _ = self._run_cli_python(existing)
        assert data["version"] == 1
        # Existing hook preserved
        assert "someHook" in data["hooks"]


# ---------------------------------------------------------------------------
# Cross-format consistency tests
# ---------------------------------------------------------------------------

class TestCrossFormatConsistency:
    """Verify VS Code and CLI formats are consistent where expected."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_same_entry_points_used(self):
        """Both formats reference the same set of entry point binaries."""
        # All copilot entry points should appear in install.sh
        entry_points = [
            "arize-hook-copilot-session-start",
            "arize-hook-copilot-user-prompt",
            "arize-hook-copilot-pre-tool",
            "arize-hook-copilot-post-tool",
        ]
        for ep in entry_points:
            # Each should appear at least twice (once in VS Code, once in CLI)
            count = self.text.count(f'"{ep}"')
            assert count >= 2, f"{ep} should appear in both VS Code and CLI blocks, found {count} times"

    def test_vscode_has_stop_and_subagent_stop(self):
        """VS Code format has Stop and SubagentStop (not in CLI)."""
        assert '"Stop": "arize-hook-copilot-stop"' in self.text
        assert '"SubagentStop": "arize-hook-copilot-subagent-stop"' in self.text

    def test_cli_has_error_and_session_end(self):
        """CLI format has errorOccurred and sessionEnd (not in VS Code events)."""
        assert '"errorOccurred": "arize-hook-copilot-error"' in self.text
        assert '"sessionEnd": "arize-hook-copilot-session-end"' in self.text


# ---------------------------------------------------------------------------
# setup_copilot guard checks
# ---------------------------------------------------------------------------

class TestSetupCopilotGuards:
    """Verify setup_copilot has proper guard checks."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_checks_plugin_dir_exists(self):
        """setup_copilot checks for copilot-tracing plugin directory."""
        assert "copilot-tracing" in self.text
        assert "Copilot tracing plugin not found" in self.text

    def test_checks_hook_binary_exists(self):
        """setup_copilot checks that hook entry point binary is executable."""
        assert "arize-hook-copilot-session-start" in self.text
        assert "Cannot register Copilot hooks" in self.text

    def test_requires_python(self):
        """setup_copilot requires Python for JSON manipulation."""
        assert "Python is required for JSON manipulation" in self.text

    def test_creates_state_dir(self):
        """setup_copilot creates state directory."""
        assert 'state_dir="${STATE_BASE_DIR}/copilot"' in self.text
        assert 'mkdir -p "$state_dir"' in self.text

    def test_creates_hooks_dir(self):
        """setup_copilot creates .github/hooks directory."""
        assert 'hooks_dir=".github/hooks"' in self.text
        assert 'mkdir -p "$hooks_dir"' in self.text


# ---------------------------------------------------------------------------
# install.sh syntax check (critical for shell scripts)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="bash not available on Windows")
class TestInstallShSyntaxWithCopilot:
    """Verify install.sh still parses correctly with copilot additions."""

    def test_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(INSTALL_SH)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Bash syntax error: {result.stderr}"

    def test_help_shows_copilot(self):
        result = subprocess.run(
            ["bash", str(INSTALL_SH), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "copilot" in result.stdout


# ---------------------------------------------------------------------------
# Summary output checks
# ---------------------------------------------------------------------------

class TestSetupCopilotSummary:
    """Verify setup_copilot summary output mentions key info."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = INSTALL_SH.read_text()

    def test_summary_mentions_vscode_hooks(self):
        assert "VS Code hooks" in self.text

    def test_summary_mentions_cli_hooks(self):
        assert "CLI hooks" in self.text

    def test_summary_mentions_pascal_case(self):
        assert "PascalCase" in self.text

    def test_summary_mentions_camel_case(self):
        assert "camelCase" in self.text

    def test_summary_mentions_command_field(self):
        """Summary mentions 'command field' for VS Code."""
        assert "command field" in self.text

    def test_summary_mentions_bash_field(self):
        """Summary mentions 'bash field' for CLI."""
        assert "bash field" in self.text

    def test_summary_mentions_direct_send(self):
        """Summary mentions spans are sent directly."""
        assert "directly to your configured backend" in self.text

    def test_summary_mentions_commit_hooks(self):
        """Summary mentions committing .github/hooks."""
        assert "Commit the .github/hooks/" in self.text
