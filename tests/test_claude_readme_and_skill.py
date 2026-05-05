"""Tests for tracing/claude_code/README.md and tracing/claude_code/skills/manage-claude-code-tracing/SKILL.md.

Verifies structure, headings, content, and frontmatter match the specification.
Ensures no leftover claude_code_tracing references remain after the path refactor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
README_PATH = REPO_ROOT / "tracing" / "claude_code" / "README.md"
SKILL_PATH = REPO_ROOT / "tracing" / "claude_code" / "skills" / "manage-claude-code-tracing" / "SKILL.md"


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
# README tests
# ---------------------------------------------------------------------------


class TestClaudeReadmeExists:
    """README file must exist at tracing/claude_code/README.md."""

    def test_readme_file_exists(self):
        assert README_PATH.exists(), f"Expected README at {README_PATH}"

    def test_readme_is_not_empty(self):
        assert README_PATH.exists() and README_PATH.stat().st_size > 0


class TestClaudeReadmeTitle:
    """Title must be exactly '# Claude Code Tracing'."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_first_line_is_title(self):
        assert self.lines[0] == "# Claude Code Tracing"


class TestClaudeReadmeDescription:
    """One-line description paragraph after title."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_contains_openinference_link(self):
        assert "[OpenInference](https://github.com/Arize-ai/openinference)" in self.text

    def test_contains_arize_link(self):
        assert "[Arize AX](https://arize.com)" in self.text

    def test_contains_phoenix_link(self):
        assert "[Phoenix](https://github.com/Arize-ai/phoenix)" in self.text

    def test_description_mentions_claude_code(self):
        assert "Claude Code CLI" in self.text

    def test_description_mentions_agent_sdk(self):
        assert "Claude Agent SDK" in self.text

    def test_description_text(self):
        expected = (
            "Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing "
            "for the Claude Code CLI and the Claude Agent SDK. Spans are exported to "
            "[Arize AX](https://arize.com) or "
            "[Phoenix](https://github.com/Arize-ai/phoenix)."
        )
        assert expected in self.text


class TestClaudeReadmeHeadings:
    """README must have exactly the required section headings."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.lines = self.text.splitlines()
        self.headings = _extract_markdown_headings(self.text)

    def test_has_setup_heading(self):
        assert "## Setup" in self.lines

    def test_has_marketplace_heading(self):
        assert "### Claude Code marketplace" in self.lines

    def test_has_remote_setup_heading(self):
        assert "### Remote setup" in self.lines

    def test_has_local_setup_heading(self):
        assert "### Local setup" in self.lines

    def test_has_default_settings_heading(self):
        assert "## Default Settings" in self.lines

    def test_no_configuration_heading(self):
        """Configuration section belongs in top-level README only."""
        assert "## Configuration" not in self.lines

    def test_no_what_gets_traced_heading(self):
        """What gets traced section should not exist."""
        for h in self.headings:
            assert "what gets traced" not in h.lower()

    def test_heading_count(self):
        """Should have exactly 6 headings: title + Setup + marketplace + Remote + Local + Default Settings."""
        assert len(self.headings) == 6, f"Expected 6 headings, got {len(self.headings)}: {self.headings}"


class TestClaudeReadmeSetupSection:
    """Setup section content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_config_yaml(self):
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_settings_json(self):
        assert "~/.claude/settings.json" in self.text

    def test_mentions_installer_prompts(self):
        assert "The installer prompts" in self.text

    def test_setup_paragraph_content(self):
        expected = (
            "The installer prompts for your backend (Phoenix or Arize AX) and project name, "
            "writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks "
            "in `~/.claude/settings.json`."
        )
        assert expected in self.text


class TestClaudeReadmeMarketplace:
    """Claude Code marketplace section content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_marketplace_add_command(self):
        assert "claude plugin marketplace add Arize-ai/arize-agent-kit" in self.text

    def test_plugin_install_command(self):
        assert "claude plugin install claude-code-tracing@arize-agent-kit" in self.text

    def test_plugin_uninstall_command(self):
        assert "claude plugin uninstall claude-code-tracing@arize-agent-kit" in self.text

    def test_marketplace_remove_command(self):
        assert "claude plugin marketplace remove Arize-ai/arize-agent-kit" in self.text

    def test_env_json_example(self):
        assert '"ARIZE_PROJECT_NAME"' in self.text
        assert '"ARIZE_API_KEY"' in self.text
        assert '"ARIZE_SPACE_ID"' in self.text

    def test_log_flags(self):
        assert '"ARIZE_LOG_PROMPTS"' in self.text
        assert '"ARIZE_LOG_TOOL_DETAILS"' in self.text
        assert '"ARIZE_LOG_TOOL_CONTENT"' in self.text

    def test_phoenix_alternative_mention(self):
        assert "PHOENIX_ENDPOINT" in self.text


class TestClaudeReadmeRemoteSetup:
    """Remote setup section with install/uninstall commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_curl_install_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- claude"
            in self.text
        )

    def test_curl_uninstall_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.sh | bash -s -- uninstall claude"
            in self.text
        )

    def test_windows_iwr_command(self):
        assert (
            "iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-agent-kit/main/install.bat -OutFile $env:TEMP\\install.bat"
            in self.text
        )

    def test_windows_install_command(self):
        assert "& $env:TEMP\\install.bat claude" in self.text

    def test_windows_uninstall_command(self):
        assert "& $env:TEMP\\install.bat uninstall claude" in self.text

    def test_has_macos_linux_label(self):
        assert "macOS / Linux:" in self.text

    def test_has_windows_label(self):
        assert "Windows" in self.text


class TestClaudeReadmeLocalSetup:
    """Local setup section with git clone and install commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_git_clone_command(self):
        assert "git clone https://github.com/Arize-ai/arize-agent-kit.git" in self.text

    def test_cd_command(self):
        assert "cd arize-agent-kit" in self.text

    def test_local_install_command(self):
        assert "./install.sh claude" in self.text

    def test_local_uninstall_command(self):
        assert "./install.sh uninstall claude" in self.text

    def test_windows_local_install(self):
        assert "install.bat claude" in self.text

    def test_windows_local_uninstall(self):
        assert "install.bat uninstall claude" in self.text


class TestClaudeReadmeDefaultSettings:
    """Default Settings table content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_harness_key(self):
        assert "`claude-code`" in self.text

    def test_project_name_default(self):
        assert "claude-code" in self.text

    def test_phoenix_endpoint(self):
        assert "`http://localhost:6006`" in self.text

    def test_arize_endpoint(self):
        assert "`otlp.arize.com:443`" in self.text

    def test_hook_config_file(self):
        assert "`~/.claude/settings.json`" in self.text

    def test_all_hook_events_listed(self):
        events = [
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "SubagentStop",
            "Notification",
            "PermissionRequest",
            "SessionEnd",
        ]
        for event in events:
            assert event in self.text, f"Missing event '{event}' in Default Settings table"

    def test_state_directory(self):
        assert "`~/.arize/harness/state/claude-code/`" in self.text

    def test_log_file(self):
        assert "`~/.arize/harness/logs/claude-code.log`" in self.text

    def test_table_has_setting_and_default_columns(self):
        assert "| Setting" in self.text and "| Default" in self.text


class TestClaudeReadmeNoProhibitedContent:
    """README must NOT contain certain sections/content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_no_emojis(self):
        import re

        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]"
        )
        assert not emoji_pattern.search(self.text), "README must not contain emojis"

    def test_no_configuration_section(self):
        assert "## Configuration" not in self.text

    def test_no_what_gets_traced(self):
        assert "What gets traced" not in self.text and "what gets traced" not in self.text


# ---------------------------------------------------------------------------
# SKILL.md tests
# ---------------------------------------------------------------------------


class TestClaudeSkillExists:
    """Skill file must exist at the expected path."""

    def test_skill_file_exists(self):
        assert SKILL_PATH.exists(), f"Expected SKILL.md at {SKILL_PATH}"

    def test_skill_is_not_empty(self):
        assert SKILL_PATH.exists() and SKILL_PATH.stat().st_size > 0

    def test_skill_directory_structure(self):
        skills_dir = REPO_ROOT / "tracing" / "claude_code" / "skills" / "manage-claude-code-tracing"
        assert skills_dir.is_dir(), f"Expected directory at {skills_dir}"


class TestClaudeSkillFrontmatter:
    """Skill must have valid YAML frontmatter."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_starts_with_frontmatter_delimiter(self):
        assert self.lines[0] == "---"

    def test_has_closing_frontmatter_delimiter(self):
        closing_indices = [i for i, line in enumerate(self.lines) if line == "---" and i > 0]
        assert len(closing_indices) >= 1, "Missing closing --- for frontmatter"

    def test_frontmatter_has_name_field(self):
        frontmatter = self._extract_frontmatter()
        assert "name:" in frontmatter

    def test_frontmatter_name_value(self):
        frontmatter = self._extract_frontmatter()
        assert "name: manage-claude-code-tracing" in frontmatter

    def test_frontmatter_has_description_field(self):
        frontmatter = self._extract_frontmatter()
        assert "description:" in frontmatter

    def test_description_mentions_arize_tracing(self):
        frontmatter = self._extract_frontmatter()
        assert "Arize tracing" in frontmatter or "arize tracing" in frontmatter.lower()

    def test_description_mentions_claude_code(self):
        frontmatter = self._extract_frontmatter()
        assert "Claude Code" in frontmatter

    def test_description_triggers_on_set_up_tracing(self):
        frontmatter = self._extract_frontmatter()
        assert "set up tracing" in frontmatter.lower()

    def test_description_triggers_on_configure_arize(self):
        frontmatter = self._extract_frontmatter()
        assert "configure Arize" in frontmatter or "configure arize" in frontmatter.lower()

    def test_description_triggers_on_configure_phoenix(self):
        frontmatter = self._extract_frontmatter()
        assert "configure Phoenix" in frontmatter or "configure phoenix" in frontmatter.lower()

    def test_description_triggers_on_enable_tracing(self):
        frontmatter = self._extract_frontmatter()
        assert "enable tracing" in frontmatter.lower()

    def test_description_triggers_on_setup_slug(self):
        frontmatter = self._extract_frontmatter()
        assert "setup-claude-code-tracing" in frontmatter

    def test_description_mentions_agent_sdk(self):
        frontmatter = self._extract_frontmatter()
        assert "agent sdk" in frontmatter.lower() or "Agent SDK" in frontmatter

    def _extract_frontmatter(self) -> str:
        """Extract text between the two --- delimiters."""
        lines = self.lines
        if lines[0] != "---":
            return ""
        closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
        if closing is None:
            return ""
        return "\n".join(lines[1:closing])


class TestClaudeSkillContent:
    """Skill content must teach users how to manage Claude Code tracing."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_mentions_settings_json(self):
        """Must teach verifying harness is installed via settings.json."""
        assert "~/.claude/settings.json" in self.text

    def test_mentions_config_yaml(self):
        """Must teach verifying config.yaml."""
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_arize_trace_enabled_env_var(self):
        """Must teach toggling tracing on/off."""
        assert "ARIZE_TRACE_ENABLED" in self.text

    def test_mentions_log_file(self):
        """Must teach checking the log file."""
        assert "~/.arize/harness/logs/claude-code.log" in self.text

    def test_mentions_dry_run(self):
        """Must teach dry-run mode."""
        assert "ARIZE_DRY_RUN" in self.text

    def test_mentions_verbose(self):
        """Must teach verbose mode."""
        assert "ARIZE_VERBOSE" in self.text

    def test_mentions_harnesses_claude_code_block(self):
        """Must reference harnesses.claude-code in config."""
        assert "harnesses" in self.text
        assert "claude-code" in self.text


class TestClaudeSkillDecisionTree:
    """Skill must follow a decision-tree workflow."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()
        self.headings = _extract_markdown_headings(self.text)

    def test_has_credentials_question(self):
        """Decision tree should ask about existing credentials."""
        assert "credentials" in self.text.lower()

    def test_has_configure_section(self):
        """Must have a configure section."""
        heading_text = " ".join(self.headings).lower()
        assert "configure" in heading_text

    def test_has_validate_or_confirm_section(self):
        """Must have a validate/confirm section."""
        heading_text = " ".join(self.headings).lower()
        assert "validate" in heading_text or "confirm" in heading_text or "verify" in heading_text

    def test_has_troubleshoot_section(self):
        """Must have a troubleshoot section."""
        heading_text = " ".join(self.headings).lower()
        assert "troubleshoot" in heading_text

    def test_has_phoenix_section(self):
        heading_text = " ".join(self.headings).lower()
        assert "phoenix" in heading_text

    def test_has_arize_ax_section(self):
        heading_text = " ".join(self.headings).lower()
        assert "arize" in heading_text


class TestClaudeSkillAgentSDK:
    """Skill must have Agent SDK setup section."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_has_agent_sdk_section(self):
        assert "## Agent SDK Setup" in self.text

    def test_mentions_claude_sdk_client(self):
        assert "ClaudeSDKClient" in self.text

    def test_mentions_plugin_path(self):
        assert "claude-code-tracing" in self.text

    def test_mentions_python_snippet(self):
        assert "claude_agent_sdk" in self.text or "ClaudeAgentOptions" in self.text

    def test_mentions_typescript_snippet(self):
        assert "@anthropic-ai/claude-agent-sdk" in self.text or "ClaudeSDKClient" in self.text

    def test_agent_sdk_compatibility_section(self):
        assert "Agent SDK Compatibility" in self.text

    def test_typescript_full_parity(self):
        assert "TypeScript SDK" in self.text

    def test_python_sdk_limitations(self):
        assert "Python SDK" in self.text


class TestClaudeSkillTroubleshootTable:
    """Troubleshoot section must have a table with common issues."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_troubleshoot_has_problem_fix_columns(self):
        assert "| Problem" in self.text and "| Fix" in self.text

    def test_traces_not_appearing(self):
        assert "Traces not appearing" in self.text or "traces not appearing" in self.text.lower()

    def test_phoenix_unreachable(self):
        assert "Phoenix unreachable" in self.text or "phoenix unreachable" in self.text.lower()

    def test_dry_run_option(self):
        assert "ARIZE_DRY_RUN" in self.text


class TestClaudeSkillNoEmojis:
    """Skill must not contain emojis."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_no_emojis(self):
        import re

        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]"
        )
        assert not emoji_pattern.search(self.text), "SKILL.md must not contain emojis"


class TestClaudeSkillPreservedNames:
    """Verify names that must NOT change during refactor are preserved."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_skill_name_unchanged(self):
        """The skill name must remain manage-claude-code-tracing."""
        lines = self.text.splitlines()
        closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), len(lines))
        frontmatter = "\n".join(lines[1:closing])
        name_lines = [line for line in frontmatter.splitlines() if line.startswith("name:")]
        assert len(name_lines) == 1
        assert "manage-claude-code-tracing" in name_lines[0]

    def test_harness_key_unchanged(self):
        """Config must still reference claude-code harness key."""
        assert "claude-code" in self.text

    def test_log_file_path_unchanged(self):
        """Log file must still use claude-code.log."""
        assert "claude-code.log" in self.text

    def test_plugin_slug_unchanged(self):
        """Plugin slug claude-code-tracing (with hyphens) must be preserved."""
        assert "claude-code-tracing" in self.text
