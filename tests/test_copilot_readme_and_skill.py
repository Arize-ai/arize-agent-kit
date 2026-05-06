"""Tests for tracing/copilot/README.md and tracing/copilot/skills/manage-copilot-tracing/SKILL.md.

Verifies structure, headings, content, frontmatter, and absence of stale
``copilot_tracing`` path references after the package-layout refactor.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
README_PATH = REPO_ROOT / "tracing" / "copilot" / "README.md"
SKILL_PATH = REPO_ROOT / "tracing" / "copilot" / "skills" / "manage-copilot-tracing" / "SKILL.md"

# The old package name that must NOT appear anywhere after the refactor.
OLD_PKG = "copilot_tracing"


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
# README — existence and basic structure
# ---------------------------------------------------------------------------


class TestCopilotReadmeExists:
    """README file must exist at the new path."""

    def test_readme_file_exists(self):
        assert README_PATH.exists(), f"Expected README at {README_PATH}"

    def test_readme_is_not_empty(self):
        assert README_PATH.stat().st_size > 0

    def test_old_path_does_not_exist(self):
        old = REPO_ROOT / "copilot_tracing" / "README.md"
        assert not old.exists(), f"Stale README still at old path {old}"


# ---------------------------------------------------------------------------
# README — title
# ---------------------------------------------------------------------------


class TestCopilotReadmeTitle:
    """Title must be exactly '# GitHub Copilot Tracing'."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_first_line_is_title(self):
        assert self.lines[0] == "# GitHub Copilot Tracing"


# ---------------------------------------------------------------------------
# README — description paragraph
# ---------------------------------------------------------------------------


class TestCopilotReadmeDescription:
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

    def test_description_mentions_copilot(self):
        assert "GitHub Copilot" in self.text

    def test_description_text(self):
        expected = (
            "Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing "
            "for GitHub Copilot in VS Code. Spans are exported to "
            "[Arize AX](https://arize.com) or "
            "[Phoenix](https://github.com/Arize-ai/phoenix)."
        )
        assert expected in self.text


# ---------------------------------------------------------------------------
# README — section headings
# ---------------------------------------------------------------------------


class TestCopilotReadmeHeadings:
    """README must have exactly the required section headings."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_has_setup_heading(self):
        assert "## Setup" in self.lines

    def test_has_remote_setup_heading(self):
        assert "### Remote setup" in self.lines

    def test_has_local_setup_heading(self):
        assert "### Local setup" in self.lines

    def test_has_default_settings_heading(self):
        assert "## Default Settings" in self.lines

    def test_no_configuration_heading(self):
        assert "## Configuration" not in self.lines

    def test_no_what_gets_traced_heading(self):
        headings = [line for line in self.lines if line.startswith("#")]
        for h in headings:
            assert "what gets traced" not in h.lower()

    def test_no_backend_setup_heading(self):
        headings = [line for line in self.lines if line.startswith("#")]
        for h in headings:
            assert "backend setup" not in h.lower()

    def test_heading_count(self):
        """Should have exactly 5 headings: title + Setup + Remote setup + Local setup + Default Settings."""
        headings = _extract_markdown_headings(self.text)
        assert len(headings) == 5, f"Expected 5 headings, got {len(headings)}: {headings}"


# ---------------------------------------------------------------------------
# README — Setup section content
# ---------------------------------------------------------------------------


class TestCopilotReadmeSetupSection:
    """Setup section content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_config_yaml(self):
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_github_hooks(self):
        assert ".github/hooks/" in self.text

    def test_mentions_installer_prompts(self):
        assert "The installer prompts" in self.text

    def test_setup_paragraph_content(self):
        expected = (
            "The installer prompts for your backend (Phoenix or Arize AX) and project name, "
            "writes credentials to `~/.arize/harness/config.yaml`, and registers "
            "Copilot Chat hooks at `.github/hooks/hooks.json`."
        )
        assert expected in self.text


# ---------------------------------------------------------------------------
# README — Remote setup
# ---------------------------------------------------------------------------


class TestCopilotReadmeRemoteSetup:
    """Remote setup section with install/uninstall commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_curl_install_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-harness-tracing/main/install.sh | bash -s -- copilot"
            in self.text
        )

    def test_curl_uninstall_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-harness-tracing/main/install.sh | bash -s -- uninstall copilot"
            in self.text
        )

    def test_windows_iwr_command(self):
        assert (
            "iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-harness-tracing/main/install.bat -OutFile $env:TEMP\\install.bat"
            in self.text
        )

    def test_windows_install_command(self):
        assert "& $env:TEMP\\install.bat copilot" in self.text

    def test_windows_uninstall_command(self):
        assert "& $env:TEMP\\install.bat uninstall copilot" in self.text

    def test_has_macos_linux_label(self):
        assert "macOS / Linux:" in self.text

    def test_has_windows_label(self):
        assert "Windows" in self.text


# ---------------------------------------------------------------------------
# README — Local setup
# ---------------------------------------------------------------------------


class TestCopilotReadmeLocalSetup:
    """Local setup section with git clone and install commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_git_clone_command(self):
        assert "git clone https://github.com/Arize-ai/arize-harness-tracing.git" in self.text

    def test_cd_command(self):
        assert "cd arize-harness-tracing" in self.text

    def test_local_install_command(self):
        assert "./install.sh copilot" in self.text

    def test_local_uninstall_command(self):
        assert "./install.sh uninstall copilot" in self.text

    def test_windows_local_install(self):
        assert "install.bat copilot" in self.text

    def test_windows_local_uninstall(self):
        assert "install.bat uninstall copilot" in self.text


# ---------------------------------------------------------------------------
# README — Default Settings table
# ---------------------------------------------------------------------------


class TestCopilotReadmeDefaultSettings:
    """Default Settings table content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_harness_key(self):
        assert "`copilot`" in self.text

    def test_phoenix_endpoint(self):
        assert "`http://localhost:6006`" in self.text

    def test_arize_endpoint(self):
        assert "`otlp.arize.com:443`" in self.text

    def test_hook_events(self):
        events = [
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "SubagentStop",
        ]
        for event in events:
            assert event in self.text, f"Missing event '{event}' in Default Settings"

    def test_state_directory(self):
        assert "`~/.arize/harness/state/copilot/`" in self.text

    def test_log_file(self):
        assert "`~/.arize/harness/logs/copilot.log`" in self.text

    def test_table_has_setting_and_default_columns(self):
        assert "| Setting" in self.text and "| Default" in self.text


# ---------------------------------------------------------------------------
# README — no prohibited content
# ---------------------------------------------------------------------------


class TestCopilotReadmeNoProhibitedContent:
    """README must NOT contain certain sections/content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_no_emojis(self):
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]"
        )
        assert not emoji_pattern.search(self.text), "README must not contain emojis"


# ---------------------------------------------------------------------------
# SKILL.md — existence
# ---------------------------------------------------------------------------


class TestCopilotSkillExists:
    """Skill file must exist at the expected path."""

    def test_skill_file_exists(self):
        assert SKILL_PATH.exists(), f"Expected SKILL.md at {SKILL_PATH}"

    def test_skill_is_not_empty(self):
        assert SKILL_PATH.stat().st_size > 0

    def test_skill_directory_structure(self):
        skills_dir = REPO_ROOT / "tracing" / "copilot" / "skills" / "manage-copilot-tracing"
        assert skills_dir.is_dir(), f"Expected directory at {skills_dir}"

    def test_old_skill_path_does_not_exist(self):
        old = REPO_ROOT / "copilot_tracing" / "skills" / "manage-copilot-tracing" / "SKILL.md"
        assert not old.exists(), f"Stale SKILL.md still at old path {old}"


# ---------------------------------------------------------------------------
# SKILL.md — frontmatter
# ---------------------------------------------------------------------------


def _extract_frontmatter(text: str) -> str:
    """Extract text between the two --- delimiters."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return ""
    closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if closing is None:
        return ""
    return "\n".join(lines[1:closing])


class TestCopilotSkillFrontmatter:
    """Skill must have valid YAML frontmatter."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()
        self.lines = self.text.splitlines()
        self.frontmatter = _extract_frontmatter(self.text)

    def test_starts_with_frontmatter_delimiter(self):
        assert self.lines[0] == "---"

    def test_has_closing_frontmatter_delimiter(self):
        closing_indices = [i for i, line in enumerate(self.lines) if line == "---" and i > 0]
        assert len(closing_indices) >= 1, "Missing closing --- for frontmatter"

    def test_frontmatter_has_name_field(self):
        assert "name:" in self.frontmatter

    def test_frontmatter_name_value(self):
        assert "name: manage-copilot-tracing" in self.frontmatter

    def test_frontmatter_has_description_field(self):
        assert "description:" in self.frontmatter

    def test_description_triggers_on_setup_copilot_tracing(self):
        assert "set up copilot tracing" in self.frontmatter.lower()

    def test_description_triggers_on_configure_arize_for_copilot(self):
        assert "configure arize for copilot" in self.frontmatter.lower()

    def test_description_triggers_on_configure_phoenix_for_copilot(self):
        assert "configure phoenix for copilot" in self.frontmatter.lower()

    def test_description_triggers_on_enable_copilot_tracing(self):
        assert "enable copilot tracing" in self.frontmatter.lower()

    def test_description_triggers_on_setup_copilot_tracing_slug(self):
        assert "setup-copilot-tracing" in self.frontmatter

    def test_description_mentions_arize_or_phoenix_observability(self):
        assert "Arize" in self.frontmatter or "Phoenix" in self.frontmatter


# ---------------------------------------------------------------------------
# SKILL.md — content
# ---------------------------------------------------------------------------


class TestCopilotSkillContent:
    """Skill content must teach users how to manage copilot tracing."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_mentions_github_hooks(self):
        """Must teach configuring hooks."""
        assert ".github/hooks/" in self.text

    def test_mentions_config_yaml_verification(self):
        """Must teach verifying config.yaml."""
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_log_file_tailing(self):
        """Must teach tailing the log file."""
        assert "~/.arize/harness/logs/copilot.log" in self.text

    def test_mentions_dry_run(self):
        """Must mention ARIZE_DRY_RUN."""
        assert "ARIZE_DRY_RUN" in self.text

    def test_mentions_verbose(self):
        """Must mention ARIZE_VERBOSE."""
        assert "ARIZE_VERBOSE" in self.text

    def test_mentions_harnesses_copilot_block(self):
        """Must reference harnesses.copilot in config."""
        assert "harnesses.copilot" in self.text or "harnesses:\n  copilot:" in self.text


# ---------------------------------------------------------------------------
# SKILL.md — decision tree / sections
# ---------------------------------------------------------------------------


class TestCopilotSkillDecisionTree:
    """Skill must follow a decision-tree workflow."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()
        self.headings = [line for line in self.text.splitlines() if line.startswith("#")]

    def test_has_platform_question(self):
        """Decision tree should address Copilot platforms."""
        assert "VS Code Copilot" in self.text or "Copilot CLI" in self.text

    def test_has_credentials_question(self):
        assert "credentials" in self.text.lower()

    def test_has_configure_section(self):
        heading_text = " ".join(self.headings).lower()
        assert "configure" in heading_text

    def test_has_validate_or_confirm_section(self):
        heading_text = " ".join(self.headings).lower()
        assert "validate" in heading_text or "confirm" in heading_text or "verify" in heading_text

    def test_has_troubleshoot_section(self):
        heading_text = " ".join(self.headings).lower()
        assert "troubleshoot" in heading_text


# ---------------------------------------------------------------------------
# SKILL.md — hook events documented
# ---------------------------------------------------------------------------


class TestCopilotSkillHookEvents:
    """Skill must document hook events."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_hook_events_documented(self):
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStop"):
            assert event in self.text, f"Missing event '{event}' in SKILL.md"

    def test_pre_tool_permission_response_documented(self):
        """Must document the permission response format."""
        assert "permissionDecision" in self.text


# ---------------------------------------------------------------------------
# SKILL.md — no emojis
# ---------------------------------------------------------------------------


class TestCopilotSkillNoEmojis:
    """Skill must not contain emojis."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_no_emojis(self):
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]"
        )
        assert not emoji_pattern.search(self.text), "SKILL.md must not contain emojis"


# ---------------------------------------------------------------------------
# Cross-check: README and SKILL heading structure mirrors gemini
# ---------------------------------------------------------------------------


GEMINI_README_PATH = REPO_ROOT / "tracing" / "gemini" / "README.md"


class TestCopilotReadmeMirrorsGeminiStructure:
    """Both harness READMEs should use the same heading level structure."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.copilot_text = README_PATH.read_text()
        self.gemini_text = GEMINI_README_PATH.read_text()

    def test_same_heading_levels(self):
        copilot_headings = _extract_markdown_headings(self.copilot_text)
        gemini_headings = _extract_markdown_headings(self.gemini_text)
        copilot_levels = [h.split(" ")[0] for h in copilot_headings]
        gemini_levels = [h.split(" ")[0] for h in gemini_headings]
        assert (
            copilot_levels == gemini_levels
        ), f"Heading levels differ.\nCopilot: {copilot_levels}\nGemini: {gemini_levels}"

    def test_same_section_names_except_harness_specific(self):
        copilot_headings = _extract_markdown_headings(self.copilot_text)
        assert "## Setup" in copilot_headings
        assert "### Remote setup" in copilot_headings
        assert "### Local setup" in copilot_headings
        assert "## Default Settings" in copilot_headings
