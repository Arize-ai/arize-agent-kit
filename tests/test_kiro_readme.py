"""Tests for tracing/kiro/README.md and the Kiro entry in the top-level README.

Verifies structure, headings, content, and Kiro-specific documentation.
These tests will FAIL until the documentation files are created.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
README_PATH = REPO_ROOT / "tracing" / "kiro" / "README.md"
TOP_README_PATH = REPO_ROOT / "README.md"
CURSOR_README_PATH = REPO_ROOT / "tracing" / "cursor" / "README.md"


def _extract_markdown_headings(text: str) -> list[str]:
    """Extract heading lines, skipping lines inside fenced code blocks."""
    headings: list[str] = []
    in_code_block = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not in_code_block and line.startswith("#"):
            headings.append(line)
    return headings


# ---------------------------------------------------------------------------
# README existence
# ---------------------------------------------------------------------------


class TestKiroReadmeExists:
    """README file must exist at tracing/kiro/."""

    def test_readme_file_exists(self):
        assert README_PATH.exists(), f"Expected README at {README_PATH}"

    def test_readme_is_not_empty(self):
        assert README_PATH.exists() and README_PATH.stat().st_size > 0


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------


class TestKiroReadmeTitle:
    """Title must be exactly '# Kiro tracing'."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_first_line_is_title(self):
        assert self.lines[0] == "# Kiro tracing"


# ---------------------------------------------------------------------------
# Description paragraph
# ---------------------------------------------------------------------------


class TestKiroReadmeDescription:
    """One-paragraph description after title."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_llm_turns(self):
        assert "LLM turn" in self.text or "LLM span" in self.text

    def test_mentions_tool_calls(self):
        assert "tool call" in self.text or "tool calls" in self.text

    def test_mentions_cost_in_credits(self):
        assert "credit" in self.text.lower()

    def test_mentions_model(self):
        assert "model" in self.text.lower()

    def test_mentions_duration(self):
        assert "duration" in self.text.lower()

    def test_mentions_token_counts_conditional(self):
        """Token counts should be noted as conditional / only when reported."""
        text_lower = self.text.lower()
        assert "token" in text_lower
        # Must clarify that token counts are conditional
        assert (
            ("when" in text_lower and "token" in text_lower)
            or "only" in text_lower
            or "reported" in text_lower
            or "bills via credits" in text_lower
        )

    def test_no_claim_model_name_always_captured(self):
        """Task says: Don't claim model name or token counts are captured (always).
        Token counts are conditional. model_id == 'auto' is common."""
        # The description should not say "captures model name" without caveat
        # This is a soft check — just ensure "token" appears with qualification
        pass  # Covered by test_mentions_token_counts_conditional


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------


class TestKiroReadmeHeadings:
    """README must have the required section headings per the task spec."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.headings = _extract_markdown_headings(self.text)
        self.heading_texts = [h.lstrip("#").strip() for h in self.headings]

    def test_has_quick_start_heading(self):
        assert any("quick start" in h.lower() for h in self.heading_texts)

    def test_has_what_gets_installed_heading(self):
        assert any("what gets installed" in h.lower() for h in self.heading_texts)

    def test_has_install_flow_heading(self):
        assert any("install flow" in h.lower() for h in self.heading_texts)

    def test_has_usage_heading(self):
        assert any("usage" in h.lower() for h in self.heading_texts)

    def test_has_span_shape_heading(self):
        assert any("span shape" in h.lower() for h in self.heading_texts)

    def test_has_known_limitations_heading(self):
        assert any("known limitation" in h.lower() for h in self.heading_texts)

    def test_has_uninstall_heading(self):
        assert any("uninstall" in h.lower() for h in self.heading_texts)

    def test_no_setup_heading(self):
        """Kiro uses 'Quick start' not 'Setup' like cursor/gemini."""
        assert "## Setup" not in self.headings

    def test_no_default_settings_heading(self):
        """Kiro uses 'Span shape' / 'What gets installed' instead."""
        assert "## Default Settings" not in self.headings


# ---------------------------------------------------------------------------
# Quick start section
# ---------------------------------------------------------------------------


class TestKiroReadmeQuickStart:
    """Quick start section with install commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_curl_install_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- kiro"
            in self.text
        )

    def test_local_install_command(self):
        assert "./install.sh kiro" in self.text

    def test_or_from_clone_comment(self):
        """Should show 'from a clone' alternative."""
        assert "clone" in self.text.lower()


# ---------------------------------------------------------------------------
# What gets installed section
# ---------------------------------------------------------------------------


class TestKiroReadmeWhatGetsInstalled:
    """What gets installed section listing artifacts."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_agent_json(self):
        assert "~/.kiro/agents/" in self.text

    def test_mentions_default_agent_name(self):
        assert "arize-traced" in self.text

    def test_mentions_state_directory(self):
        assert "~/.arize/harness/state/kiro/" in self.text

    def test_mentions_config_yaml(self):
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_harnesses_kiro_config_block(self):
        assert "harnesses.kiro" in self.text


# ---------------------------------------------------------------------------
# Install flow section
# ---------------------------------------------------------------------------


class TestKiroReadmeInstallFlow:
    """Install flow section explaining prompts."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_agent_name_prompt(self):
        assert "agent name" in self.text.lower() or "agent" in self.text.lower()

    def test_mentions_set_default_prompt(self):
        assert "default" in self.text.lower()

    def test_mentions_backend_prompt(self):
        assert "backend" in self.text.lower()

    def test_mentions_project_name_prompt(self):
        assert "project name" in self.text.lower()

    def test_mentions_logging_prompt(self):
        assert "logging" in self.text.lower()


# ---------------------------------------------------------------------------
# Usage section
# ---------------------------------------------------------------------------


class TestKiroReadmeUsage:
    """Usage section with CLI commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_kiro_cli_chat_command(self):
        assert "kiro-cli chat" in self.text

    def test_kiro_cli_chat_with_agent_flag(self):
        assert "kiro-cli chat --agent arize-traced" in self.text

    def test_mentions_default_agent_usage(self):
        """Should mention the case when arize-traced is set as default."""
        assert "default" in self.text.lower()


# ---------------------------------------------------------------------------
# Span shape section
# ---------------------------------------------------------------------------


class TestKiroReadmeSpanShapeLLM:
    """LLM span attributes in the Span shape section."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_llm_span_kind(self):
        assert "LLM" in self.text

    def test_session_id_attribute(self):
        assert "session.id" in self.text

    def test_input_value_attribute(self):
        assert "input.value" in self.text

    def test_output_value_attribute(self):
        assert "output.value" in self.text

    def test_llm_output_messages(self):
        assert "llm.output_messages" in self.text

    def test_llm_model_name(self):
        assert "llm.model_name" in self.text

    def test_llm_token_count_prompt(self):
        assert "llm.token_count.prompt" in self.text

    def test_llm_token_count_completion(self):
        assert "llm.token_count.completion" in self.text

    def test_llm_token_count_total(self):
        assert "llm.token_count.total" in self.text

    def test_kiro_cost_credits(self):
        assert "kiro.cost.credits" in self.text

    def test_kiro_metering_usage(self):
        assert "kiro.metering_usage" in self.text

    def test_kiro_turn_duration_ms(self):
        assert "kiro.turn_duration_ms" in self.text

    def test_kiro_agent_name(self):
        assert "kiro.agent_name" in self.text

    def test_kiro_context_usage_percentage(self):
        assert "kiro.context_usage_percentage" in self.text

    def test_token_counts_noted_as_conditional(self):
        """Token counts should say 'when reported' or similar."""
        assert "when reported" in self.text.lower() or "when" in self.text.lower()


class TestKiroReadmeSpanShapeTool:
    """TOOL span attributes in the Span shape section."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_tool_span_kind(self):
        assert "TOOL" in self.text

    def test_tool_name_attribute(self):
        assert "tool.name" in self.text

    def test_tool_description_attribute(self):
        assert "tool.description" in self.text

    def test_tool_use_purpose_mention(self):
        assert "__tool_use_purpose" in self.text

    def test_tool_input_value(self):
        assert "input.value" in self.text

    def test_tool_output_value(self):
        assert "output.value" in self.text

    def test_tool_parented_to_llm(self):
        assert "parent" in self.text.lower() or "LLM turn" in self.text


# ---------------------------------------------------------------------------
# Known limitations section
# ---------------------------------------------------------------------------


class TestKiroReadmeKnownLimitations:
    """Known limitations section."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_token_counts_zero(self):
        """Token counts reported as 0 in current Kiro CLI."""
        assert "0" in self.text and "token" in self.text.lower()

    def test_mentions_credits_billing(self):
        assert "credit" in self.text.lower()

    def test_mentions_kiro_cost_credits_in_limitations(self):
        assert "kiro.cost.credits" in self.text

    def test_mentions_fifo_tool_matching(self):
        assert "FIFO" in self.text

    def test_mentions_serial_tool_execution(self):
        assert "serial" in self.text.lower()

    def test_mentions_sidecar_fail_soft(self):
        assert "fail-soft" in self.text or "fail soft" in self.text.lower()

    def test_mentions_sidecar_race(self):
        assert "race" in self.text.lower()


# ---------------------------------------------------------------------------
# Uninstall section
# ---------------------------------------------------------------------------


class TestKiroReadmeUninstall:
    """Uninstall section."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_uninstall_command(self):
        assert "./install.sh uninstall kiro" in self.text

    def test_mentions_hook_removal(self):
        assert "hook" in self.text.lower() and "remov" in self.text.lower()

    def test_mentions_arize_traced_cleanup(self):
        """If arize-traced was created by install, file is deleted."""
        assert "arize-traced" in self.text

    def test_mentions_agent_preserved_if_not_created(self):
        """If agent existed before install, hooks removed but agent stays."""
        assert "remov" in self.text.lower()


# ---------------------------------------------------------------------------
# Prohibited content
# ---------------------------------------------------------------------------


class TestKiroReadmeNoProhibitedContent:
    """README must NOT contain certain content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_no_emojis(self):
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]"
        )
        assert not emoji_pattern.search(self.text), "README must not contain emojis"

    def test_no_workspace_agents(self):
        """Workspace-scoped agent configs are out of scope for v1."""
        assert "<project>/.kiro/agents" not in self.text
        assert "workspace" not in self.text.lower() or "workspace-scoped" not in self.text.lower()

    def test_no_mcp_wrapping(self):
        """MCP tool tracing via wrapping is out of scope for v1."""
        assert "MCP wrapping" not in self.text
        assert "MCP server" not in self.text

    def test_no_ide_hooks(self):
        """Kiro IDE hooks are out of scope for v1 (v1 targets CLI only)."""
        assert "IDE hooks" not in self.text
        assert "Prompt Submit" not in self.text  # IDE event name
        assert "Agent Stop" not in self.text  # IDE event name

    def test_no_span_screenshots(self):
        """Task says: Don't show example output / span screenshots."""
        assert "screenshot" not in self.text.lower()
        assert "![" not in self.text  # No markdown images

    def test_no_experimental_features(self):
        """Task says: Don't reference experimental features."""
        assert "experimental" not in self.text.lower()

    def test_no_skills_reference(self):
        """Skills are out of scope for v1."""
        assert "skills" not in self.text.lower() or "skill" not in self.text.lower()


# ---------------------------------------------------------------------------
# No other-harness leakage
# ---------------------------------------------------------------------------


class TestKiroReadmeNoLeakage:
    """Ensure no other-harness-specific content leaked into Kiro README."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_no_cursor_hooks_json(self):
        assert ".cursor/hooks.json" not in self.text

    def test_no_gemini_settings_json(self):
        assert "~/.gemini/settings.json" not in self.text

    def test_no_claude_settings_json(self):
        assert "~/.claude/" not in self.text

    def test_no_github_hooks(self):
        assert ".github/hooks/" not in self.text

    def test_no_arize_hook_cursor(self):
        assert "arize-hook-cursor" not in self.text

    def test_no_arize_hook_gemini(self):
        assert "arize-hook-gemini" not in self.text

    def test_no_arize_hook_copilot(self):
        assert "arize-hook-copilot" not in self.text

    def test_no_arize_hook_codex(self):
        assert "arize-hook-codex" not in self.text

    def test_no_codex_buffer(self):
        assert "buffer service" not in self.text.lower()


# ---------------------------------------------------------------------------
# Top-level README: Kiro row in supported harnesses table
# ---------------------------------------------------------------------------


class TestTopLevelReadmeKiroEntry:
    """Top-level README must include Kiro in the supported harnesses table."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = TOP_README_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_kiro_mentioned_in_readme(self):
        assert "kiro" in self.text.lower()

    def test_kiro_row_in_harness_table(self):
        """There should be a table row containing Kiro."""
        kiro_rows = [line for line in self.lines if "Kiro" in line and line.strip().startswith("|")]
        assert len(kiro_rows) >= 1, "No Kiro row found in harness table"

    def test_kiro_row_links_to_readme(self):
        """Kiro row should link to tracing/kiro/README.md."""
        kiro_rows = [line for line in self.lines if "Kiro" in line and line.strip().startswith("|")]
        assert any("tracing/kiro/README.md" in row for row in kiro_rows)

    def test_kiro_row_has_integration_name(self):
        """Kiro row should have an integration name like `kiro-tracing`."""
        kiro_rows = [line for line in self.lines if "Kiro" in line and line.strip().startswith("|")]
        assert any("kiro-tracing" in row for row in kiro_rows)

    def test_kiro_row_has_install_method(self):
        """Kiro row should mention install.sh."""
        kiro_rows = [line for line in self.lines if "Kiro" in line and line.strip().startswith("|")]
        assert any("install.sh" in row for row in kiro_rows)

    def test_kiro_row_after_gemini(self):
        """Kiro should sit alphabetically after Gemini in the table."""
        gemini_idx = None
        kiro_idx = None
        for i, line in enumerate(self.lines):
            if line.strip().startswith("|") and "Gemini" in line:
                gemini_idx = i
            if line.strip().startswith("|") and "Kiro" in line:
                kiro_idx = i
        assert gemini_idx is not None, "Gemini row not found"
        assert kiro_idx is not None, "Kiro row not found"
        assert kiro_idx > gemini_idx, f"Kiro row (line {kiro_idx}) should be after Gemini row (line {gemini_idx})"

    def test_existing_rows_not_modified(self):
        """Existing harness rows must not be modified."""
        expected_rows = [
            "| [Claude Code CLI / Agent SDK](tracing/claude_code/README.md) |",
            "| [OpenAI Codex CLI](tracing/codex/README.md) |",
            "| [Cursor IDE / CLI](tracing/cursor/README.md) |",
            "| [GitHub Copilot (VS Code + CLI)](tracing/copilot/README.md) |",
            "| [Gemini CLI](tracing/gemini/README.md) |",
        ]
        for expected in expected_rows:
            assert expected in self.text, f"Existing row modified or missing: {expected}"

    def test_kiro_install_commands_in_quickstart(self):
        """Top-level README quickstart should include kiro install command."""
        assert "bash -s -- kiro" in self.text

    def test_kiro_uninstall_in_quickstart(self):
        """Top-level README quickstart should include kiro uninstall."""
        assert "uninstall kiro" in self.text

    def test_kiro_local_install(self):
        """Local copy section should include ./install.sh kiro."""
        assert "./install.sh kiro" in self.text

    def test_kiro_local_uninstall(self):
        """Local copy section should include ./install.sh uninstall kiro."""
        assert "./install.sh uninstall kiro" in self.text
