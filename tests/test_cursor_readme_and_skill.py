"""Tests for tracing/cursor/README.md and tracing/cursor/skills/manage-cursor-tracing/SKILL.md.

Verifies structure, headings, content, and frontmatter match the specification.
Ensures no leftover cursor_tracing references and that the path-only refactor
is correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
README_PATH = REPO_ROOT / "tracing" / "cursor" / "README.md"
SKILL_PATH = REPO_ROOT / "tracing" / "cursor" / "skills" / "manage-cursor-tracing" / "SKILL.md"
COPILOT_README_PATH = REPO_ROOT / "tracing" / "copilot" / "README.md"
COPILOT_SKILL_PATH = REPO_ROOT / "tracing" / "copilot" / "skills" / "manage-copilot-tracing" / "SKILL.md"


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
# No leftover old path references
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# README tests
# ---------------------------------------------------------------------------


class TestCursorReadmeExists:
    """README file must exist at the new tracing/cursor/ location."""

    def test_readme_file_exists(self):
        assert README_PATH.exists(), f"Expected README at {README_PATH}"

    def test_readme_is_not_empty(self):
        assert README_PATH.exists() and README_PATH.stat().st_size > 0

    def test_old_readme_does_not_exist(self):
        old_path = REPO_ROOT / "cursor_tracing" / "README.md"
        assert not old_path.exists(), f"Old README still exists at {old_path}"


class TestCursorReadmeTitle:
    """Title must be exactly '# Cursor IDE Tracing'."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_first_line_is_title(self):
        assert self.lines[0] == "# Cursor IDE Tracing"


class TestCursorReadmeDescription:
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

    def test_description_mentions_cursor(self):
        assert "Cursor IDE" in self.text or "Cursor CLI" in self.text

    def test_description_text(self):
        expected = (
            "Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing "
            "for the Cursor IDE and Cursor CLI. Spans are exported to "
            "[Arize AX](https://arize.com) or "
            "[Phoenix](https://github.com/Arize-ai/phoenix)."
        )
        assert expected in self.text


class TestCursorReadmeHeadings:
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
        """Configuration section belongs in top-level README only."""
        assert "## Configuration" not in self.lines

    def test_no_what_gets_traced_heading(self):
        """What gets traced section should not exist in condensed README."""
        headings = _extract_markdown_headings(self.text)
        for h in headings:
            assert "what gets traced" not in h.lower()

    def test_no_backend_setup_heading(self):
        headings = _extract_markdown_headings(self.text)
        for h in headings:
            assert "backend setup" not in h.lower()

    def test_heading_count(self):
        """Should have exactly 5 headings: title + Setup + Remote setup + Local setup + Default Settings."""
        headings = _extract_markdown_headings(self.text)
        assert len(headings) == 5, f"Expected 5 headings, got {len(headings)}: {headings}"


class TestCursorReadmeSetupSection:
    """Setup section content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_config_yaml(self):
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_hooks_json(self):
        assert ".cursor/hooks.json" in self.text

    def test_mentions_installer_prompts(self):
        assert "The installer prompts" in self.text

    def test_setup_paragraph_content(self):
        expected = (
            "The installer prompts for your backend (Phoenix or Arize AX) and project name, "
            "writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks "
            "in `.cursor/hooks.json`."
        )
        assert expected in self.text


class TestCursorReadmeRemoteSetup:
    """Remote setup section with install/uninstall commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_curl_install_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.sh | bash -s -- cursor"
            in self.text
        )

    def test_curl_uninstall_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.sh | bash -s -- uninstall cursor"
            in self.text
        )

    def test_windows_iwr_command(self):
        assert (
            "iwr -useb https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat -OutFile $env:TEMP\\install.bat"
            in self.text
        )

    def test_windows_install_command(self):
        assert "& $env:TEMP\\install.bat cursor" in self.text

    def test_windows_uninstall_command(self):
        assert "& $env:TEMP\\install.bat uninstall cursor" in self.text

    def test_has_macos_linux_label(self):
        assert "macOS / Linux:" in self.text

    def test_has_windows_label(self):
        assert "Windows" in self.text


class TestCursorReadmeLocalSetup:
    """Local setup section with git clone and install commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_git_clone_command(self):
        assert "git clone https://github.com/Arize-ai/coding-harness-tracing.git" in self.text

    def test_cd_command(self):
        assert "cd coding-harness-tracing" in self.text

    def test_local_install_command(self):
        assert "./install.sh cursor" in self.text

    def test_local_uninstall_command(self):
        assert "./install.sh uninstall cursor" in self.text

    def test_windows_local_install(self):
        assert "install.bat cursor" in self.text

    def test_windows_local_uninstall(self):
        assert "install.bat uninstall cursor" in self.text


class TestCursorReadmeDefaultSettings:
    """Default Settings table content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_harness_key(self):
        assert "`cursor`" in self.text

    def test_project_name_default(self):
        assert "cursor" in self.text

    def test_phoenix_endpoint(self):
        assert "`http://localhost:6006`" in self.text

    def test_arize_endpoint(self):
        assert "`otlp.arize.com:443`" in self.text

    def test_hook_config_file(self):
        assert "`.cursor/hooks.json`" in self.text

    def test_ide_hook_events_listed(self):
        """All IDE hook events must appear in the Default Settings table."""
        ide_events = [
            "sessionStart",
            "sessionEnd",
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
            "postToolUse",
            "stop",
        ]
        for event in ide_events:
            assert event in self.text, f"Missing IDE event '{event}' in Default Settings table"

    def test_cli_hook_events_listed(self):
        """CLI hook events must appear."""
        # CLI events are a subset — verify they're mentioned as CLI events
        assert "CLI hook events" in self.text

    def test_state_directory(self):
        assert "`~/.arize/harness/state/cursor/`" in self.text

    def test_log_file(self):
        assert "`~/.arize/harness/logs/cursor.log`" in self.text

    def test_table_has_setting_and_default_columns(self):
        assert "| Setting" in self.text and "| Default" in self.text


class TestCursorReadmeNoProhibitedContent:
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
        headings = _extract_markdown_headings(self.text)
        for h in headings:
            assert "what gets traced" not in h.lower()


class TestCursorReadmeMirrorsCopilot:
    """Structural comparison with copilot README — same heading levels."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cursor_text = README_PATH.read_text()
        self.copilot_text = COPILOT_README_PATH.read_text()

    def test_same_heading_levels(self):
        """Both READMEs should use the same heading level structure."""
        cursor_headings = _extract_markdown_headings(self.cursor_text)
        copilot_headings = _extract_markdown_headings(self.copilot_text)
        cursor_levels = [h.split(" ")[0] for h in cursor_headings]
        copilot_levels = [h.split(" ")[0] for h in copilot_headings]
        assert (
            cursor_levels == copilot_levels
        ), f"Heading levels differ.\nCursor: {cursor_levels}\nCopilot: {copilot_levels}"

    def test_same_section_names_except_harness_specific(self):
        """Section names should match except for harness-specific terms."""
        cursor_headings = _extract_markdown_headings(self.cursor_text)
        assert "## Setup" in cursor_headings
        assert "### Remote setup" in cursor_headings
        assert "### Local setup" in cursor_headings
        assert "## Default Settings" in cursor_headings


# ---------------------------------------------------------------------------
# SKILL.md tests
# ---------------------------------------------------------------------------


class TestCursorSkillExists:
    """Skill file must exist at the expected path."""

    def test_skill_file_exists(self):
        assert SKILL_PATH.exists(), f"Expected SKILL.md at {SKILL_PATH}"

    def test_skill_is_not_empty(self):
        assert SKILL_PATH.exists() and SKILL_PATH.stat().st_size > 0

    def test_skill_directory_structure(self):
        skills_dir = REPO_ROOT / "tracing" / "cursor" / "skills" / "manage-cursor-tracing"
        assert skills_dir.is_dir(), f"Expected directory at {skills_dir}"

    def test_old_skill_does_not_exist(self):
        old_path = REPO_ROOT / "cursor_tracing" / "skills" / "manage-cursor-tracing" / "SKILL.md"
        assert not old_path.exists(), f"Old SKILL.md still exists at {old_path}"


class TestCursorSkillFrontmatter:
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
        assert "name: manage-cursor-tracing" in frontmatter

    def test_frontmatter_has_description_field(self):
        frontmatter = self._extract_frontmatter()
        assert "description:" in frontmatter

    def test_description_triggers_on_setup_cursor_tracing(self):
        frontmatter = self._extract_frontmatter()
        assert "set up cursor tracing" in frontmatter.lower()

    def test_description_triggers_on_configure_arize_for_cursor(self):
        frontmatter = self._extract_frontmatter()
        assert "configure arize for cursor" in frontmatter.lower()

    def test_description_triggers_on_configure_phoenix_for_cursor(self):
        frontmatter = self._extract_frontmatter()
        assert "configure phoenix for cursor" in frontmatter.lower()

    def test_description_triggers_on_enable_cursor_tracing(self):
        frontmatter = self._extract_frontmatter()
        assert "enable cursor tracing" in frontmatter.lower()

    def test_description_triggers_on_setup_cursor_tracing_slug(self):
        frontmatter = self._extract_frontmatter()
        assert "setup-cursor-tracing" in frontmatter

    def test_description_mentions_arize_or_phoenix_observability(self):
        frontmatter = self._extract_frontmatter()
        assert "Arize" in frontmatter or "Phoenix" in frontmatter

    def _extract_frontmatter(self) -> str:
        """Extract text between the two --- delimiters."""
        lines = self.lines
        if lines[0] != "---":
            return ""
        closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
        if closing is None:
            return ""
        return "\n".join(lines[1:closing])


class TestCursorSkillContent:
    """Skill content must teach users how to manage cursor tracing."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_mentions_hooks_json_for_cursor(self):
        """Must teach verifying harness is installed via .cursor/hooks.json."""
        assert ".cursor/hooks.json" in self.text

    def test_mentions_config_yaml_verification(self):
        """Must teach verifying config.yaml has cursor block."""
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_log_file_tailing(self):
        """Must teach tailing the log file."""
        assert "~/.arize/harness/logs/cursor.log" in self.text

    def test_mentions_installer(self):
        """Must reference the installer for setup."""
        assert "installer" in self.text.lower()

    def test_mentions_arize_hook_cursor(self):
        """Must reference the arize-hook-cursor command."""
        assert "arize-hook-cursor" in self.text

    def test_mentions_harnesses_cursor_block(self):
        """Must reference harnesses.cursor in config."""
        assert "harnesses.cursor" in self.text

    def test_mentions_cursor_project_name(self):
        """Config examples should use cursor as project name."""
        assert "project_name: cursor" in self.text or 'project_name: "cursor"' in self.text

    def test_mentions_dry_run(self):
        """Must mention ARIZE_DRY_RUN for testing."""
        assert "ARIZE_DRY_RUN" in self.text

    def test_mentions_verbose(self):
        """Must mention ARIZE_VERBOSE for debug output."""
        assert "ARIZE_VERBOSE" in self.text


class TestCursorSkillDecisionTree:
    """Skill must follow a decision-tree workflow."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()
        self.headings = [line for line in self.text.splitlines() if line.startswith("#")]

    def test_has_credentials_question(self):
        """Decision tree should ask about existing credentials."""
        assert "credentials" in self.text.lower()

    def test_has_configure_section(self):
        """Must have a configure section."""
        heading_text = " ".join(self.headings).lower()
        assert "configure" in heading_text

    def test_has_verify_or_validate_section(self):
        """Must have a verify/validate section."""
        heading_text = " ".join(self.headings).lower()
        assert "verify" in heading_text or "validate" in heading_text or "confirm" in heading_text

    def test_has_troubleshoot_section(self):
        """Must have a troubleshoot section."""
        heading_text = " ".join(self.headings).lower()
        assert "troubleshoot" in heading_text

    def test_has_phoenix_setup_section(self):
        """Must have a Set Up Phoenix section."""
        heading_text = " ".join(self.headings).lower()
        assert "phoenix" in heading_text

    def test_has_arize_ax_setup_section(self):
        """Must have a Set Up Arize AX section."""
        heading_text = " ".join(self.headings).lower()
        assert "arize ax" in heading_text


class TestCursorSkillCursorSpecific:
    """Skill must use Cursor-specific references, not other harness ones."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_references_cursor_hooks_json(self):
        """Must reference .cursor/hooks.json."""
        assert ".cursor/hooks.json" in self.text

    def test_no_github_hooks_path(self):
        """Must not reference .github/hooks/ (copilot-specific)."""
        assert ".github/hooks/" not in self.text

    def test_no_vs_code_copilot_reference(self):
        """Must not reference VS Code Copilot."""
        assert "VS Code Copilot" not in self.text

    def test_no_copilot_cli_reference(self):
        """Must not reference Copilot CLI."""
        assert "Copilot CLI" not in self.text

    def test_no_gemini_settings_json(self):
        """Must not reference ~/.gemini/settings.json."""
        assert "~/.gemini/settings.json" not in self.text

    def test_no_claude_settings_json(self):
        """Must not reference ~/.claude/settings.json."""
        assert "~/.claude/settings.json" not in self.text

    def test_references_cursor_state_dir(self):
        """Must reference state/cursor/ directory."""
        assert "state/cursor" in self.text


class TestCursorSkillNoLeakage:
    """Ensure no other-harness-specific content leaked into cursor skill."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_no_copilot_in_name_field(self):
        """Frontmatter name must not contain 'copilot'."""
        lines = self.text.splitlines()
        closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), len(lines))
        frontmatter = "\n".join(lines[1:closing])
        name_line = [line for line in frontmatter.splitlines() if line.startswith("name:")]
        assert len(name_line) == 1
        assert "copilot" not in name_line[0]

    def test_no_gemini_in_name_field(self):
        """Frontmatter name must not contain 'gemini'."""
        lines = self.text.splitlines()
        closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), len(lines))
        frontmatter = "\n".join(lines[1:closing])
        name_line = [line for line in frontmatter.splitlines() if line.startswith("name:")]
        assert len(name_line) == 1
        assert "gemini" not in name_line[0]

    def test_no_arize_hook_copilot_commands(self):
        """Must not reference arize-hook-copilot-* commands."""
        assert "arize-hook-copilot" not in self.text

    def test_no_arize_hook_gemini_commands(self):
        """Must not reference arize-hook-gemini commands."""
        assert "arize-hook-gemini" not in self.text

    def test_no_arize_hook_claude_commands(self):
        """Must not reference arize-hook-session-start (claude-specific)."""
        assert "arize-hook-session-start" not in self.text

    def test_no_arize_hook_codex_commands(self):
        """Must not reference arize-hook-codex commands."""
        assert "arize-hook-codex" not in self.text


class TestCursorSkillNoEmojis:
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


class TestCursorSkillMirrorsCopilotStructure:
    """Skill should mirror the copilot skill's H2 section structure."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cursor_text = SKILL_PATH.read_text()
        self.copilot_text = COPILOT_SKILL_PATH.read_text()

    def _extract_h2_headings(self, text: str) -> list[str]:
        return [line for line in text.splitlines() if line.startswith("## ")]

    def test_same_h2_section_count(self):
        """Cursor skill should have same number of H2 sections as copilot skill."""
        cursor_h2 = self._extract_h2_headings(self.cursor_text)
        copilot_h2 = self._extract_h2_headings(self.copilot_text)
        assert len(cursor_h2) == len(copilot_h2), (
            f"H2 count differs. Cursor: {len(cursor_h2)} ({cursor_h2}), " f"Copilot: {len(copilot_h2)} ({copilot_h2})"
        )

    def test_matching_h2_section_names(self):
        """H2 section names should match (with Copilot->Cursor substitutions)."""
        cursor_h2 = self._extract_h2_headings(self.cursor_text)
        copilot_h2 = self._extract_h2_headings(self.copilot_text)

        def normalize(heading: str) -> str:
            return heading.lower().replace("copilot", "HARNESS").replace("cursor", "HARNESS")

        cursor_normalized = [normalize(h) for h in cursor_h2]
        copilot_normalized = [normalize(h) for h in copilot_h2]
        assert cursor_normalized == copilot_normalized, (
            f"H2 headings differ after normalization.\n" f"Cursor: {cursor_h2}\nCopilot: {copilot_h2}"
        )


# ---------------------------------------------------------------------------
# Hook event consistency tests (README vs SKILL)
# ---------------------------------------------------------------------------


class TestCursorHookEventConsistency:
    """Verify hook events are consistent between README and SKILL."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.readme_text = README_PATH.read_text()
        self.skill_text = SKILL_PATH.read_text()

    def test_session_start_in_both(self):
        assert "sessionStart" in self.readme_text
        assert "sessionStart" in self.skill_text or "Session Start" in self.skill_text

    def test_session_end_in_both(self):
        assert "sessionEnd" in self.readme_text
        assert "sessionEnd" in self.skill_text or "Session End" in self.skill_text

    def test_arize_hook_cursor_command_in_skill(self):
        """SKILL should reference the arize-hook-cursor command."""
        assert "arize-hook-cursor" in self.skill_text

    def test_hooks_json_in_both(self):
        """Both docs should reference .cursor/hooks.json."""
        assert ".cursor/hooks.json" in self.readme_text
        assert ".cursor/hooks.json" in self.skill_text


# ---------------------------------------------------------------------------
# Directory structure tests
# ---------------------------------------------------------------------------


class TestCursorDirectoryStructure:
    """Verify the tracing/cursor/ directory has the expected layout."""

    def test_tracing_init_exists(self):
        init = REPO_ROOT / "tracing" / "__init__.py"
        assert init.exists(), "tracing/__init__.py must exist"

    def test_cursor_init_exists(self):
        init = REPO_ROOT / "tracing" / "cursor" / "__init__.py"
        assert init.exists(), "tracing/cursor/__init__.py must exist"

    def test_cursor_constants_exists(self):
        f = REPO_ROOT / "tracing" / "cursor" / "constants.py"
        assert f.exists(), "tracing/cursor/constants.py must exist"

    def test_cursor_hooks_dir_exists(self):
        d = REPO_ROOT / "tracing" / "cursor" / "hooks"
        assert d.is_dir(), "tracing/cursor/hooks/ must exist"

    def test_cursor_hooks_init_exists(self):
        f = REPO_ROOT / "tracing" / "cursor" / "hooks" / "__init__.py"
        assert f.exists(), "tracing/cursor/hooks/__init__.py must exist"

    def test_cursor_hooks_adapter_exists(self):
        f = REPO_ROOT / "tracing" / "cursor" / "hooks" / "adapter.py"
        assert f.exists(), "tracing/cursor/hooks/adapter.py must exist"

    def test_cursor_hooks_handlers_exists(self):
        f = REPO_ROOT / "tracing" / "cursor" / "hooks" / "handlers.py"
        assert f.exists(), "tracing/cursor/hooks/handlers.py must exist"

    def test_cursor_install_exists(self):
        f = REPO_ROOT / "tracing" / "cursor" / "install.py"
        assert f.exists(), "tracing/cursor/install.py must exist"

    def test_cursor_skills_dir_exists(self):
        d = REPO_ROOT / "tracing" / "cursor" / "skills" / "manage-cursor-tracing"
        assert d.is_dir(), "tracing/cursor/skills/manage-cursor-tracing/ must exist"

    def test_old_cursor_tracing_dir_does_not_exist(self):
        old = REPO_ROOT / "cursor_tracing"
        assert not old.exists(), f"Old cursor_tracing/ directory still exists at {old}"
