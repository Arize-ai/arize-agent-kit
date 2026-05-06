"""Tests for tracing/gemini/README.md and tracing/gemini/skills/manage-gemini-tracing/SKILL.md.

Verifies structure, headings, content, and frontmatter match the specification.
These tests will FAIL until the documentation files are created.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
README_PATH = REPO_ROOT / "tracing" / "gemini" / "README.md"
SKILL_PATH = REPO_ROOT / "tracing" / "gemini" / "skills" / "manage-gemini-tracing" / "SKILL.md"
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
# README tests
# ---------------------------------------------------------------------------


class TestGeminiReadmeExists:
    """README file must exist."""

    def test_readme_file_exists(self):
        assert README_PATH.exists(), f"Expected README at {README_PATH}"

    def test_readme_is_not_empty(self):
        assert README_PATH.exists() and README_PATH.stat().st_size > 0


class TestGeminiReadmeTitle:
    """Title must be exactly '# Gemini CLI Tracing'."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_first_line_is_title(self):
        assert self.lines[0] == "# Gemini CLI Tracing"


class TestGeminiReadmeDescription:
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

    def test_description_mentions_gemini_cli(self):
        assert "Gemini CLI sessions" in self.text

    def test_description_text(self):
        expected = (
            "Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing "
            "for Gemini CLI sessions. Spans are exported to "
            "[Arize AX](https://arize.com) or "
            "[Phoenix](https://github.com/Arize-ai/phoenix)."
        )
        assert expected in self.text


class TestGeminiReadmeHeadings:
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
        """What gets traced section should not exist."""
        headings = [line for line in self.lines if line.startswith("#")]
        for h in headings:
            assert "what gets traced" not in h.lower()

    def test_no_backend_setup_heading(self):
        headings = [line for line in self.lines if line.startswith("#")]
        for h in headings:
            assert "backend setup" not in h.lower()

    def test_no_why_hooks_heading(self):
        headings = [line for line in self.lines if line.startswith("#")]
        for h in headings:
            assert "why hooks" not in h.lower()

    def test_heading_count(self):
        """Should have exactly 5 headings: title + Setup + Remote setup + Local setup + Default Settings."""
        headings = _extract_markdown_headings(self.text)
        assert len(headings) == 5, f"Expected 5 headings, got {len(headings)}: {headings}"


class TestGeminiReadmeSetupSection:
    """Setup section content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_mentions_config_yaml(self):
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_settings_json(self):
        assert "~/.gemini/settings.json" in self.text

    def test_mentions_installer_prompts(self):
        assert "installer prompts" in self.text.lower() or "The installer prompts" in self.text

    def test_setup_paragraph_content(self):
        expected = (
            "The installer prompts for your backend (Phoenix or Arize AX) and project name, "
            "writes credentials to `~/.arize/harness/config.yaml`, and registers the hooks "
            "in `~/.gemini/settings.json`."
        )
        assert expected in self.text


class TestGeminiReadmeRemoteSetup:
    """Remote setup section with install/uninstall commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_curl_install_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-harness-tracing/main/install.sh | bash -s -- gemini"
            in self.text
        )

    def test_curl_uninstall_command(self):
        assert (
            "curl -sSL https://raw.githubusercontent.com/Arize-ai/arize-harness-tracing/main/install.sh | bash -s -- uninstall gemini"
            in self.text
        )

    def test_windows_iwr_command(self):
        assert (
            "iwr -useb https://raw.githubusercontent.com/Arize-ai/arize-harness-tracing/main/install.bat -OutFile $env:TEMP\\install.bat"
            in self.text
        )

    def test_windows_install_command(self):
        assert "& $env:TEMP\\install.bat gemini" in self.text

    def test_windows_uninstall_command(self):
        assert "& $env:TEMP\\install.bat uninstall gemini" in self.text

    def test_has_macos_linux_label(self):
        assert "macOS / Linux:" in self.text or "macOS / Linux" in self.text

    def test_has_windows_label(self):
        assert "Windows" in self.text


class TestGeminiReadmeLocalSetup:
    """Local setup section with git clone and install commands."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_git_clone_command(self):
        assert "git clone https://github.com/Arize-ai/arize-harness-tracing.git" in self.text

    def test_cd_command(self):
        assert "cd arize-harness-tracing" in self.text

    def test_local_install_command(self):
        assert "./install.sh gemini" in self.text

    def test_local_uninstall_command(self):
        assert "./install.sh uninstall gemini" in self.text

    def test_windows_local_install(self):
        assert "install.bat gemini" in self.text

    def test_windows_local_uninstall(self):
        assert "install.bat uninstall gemini" in self.text


class TestGeminiReadmeDefaultSettings:
    """Default Settings table content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_harness_key(self):
        assert "`gemini`" in self.text

    def test_project_name_default(self):
        # The table should show project name as gemini
        assert "gemini" in self.text

    def test_phoenix_endpoint(self):
        assert "`http://localhost:6006`" in self.text

    def test_arize_endpoint(self):
        assert "`otlp.arize.com:443`" in self.text

    def test_hook_config_file(self):
        assert "`~/.gemini/settings.json`" in self.text

    def test_all_eight_events_listed(self):
        events = [
            "SessionStart",
            "SessionEnd",
            "BeforeAgent",
            "AfterAgent",
            "BeforeModel",
            "AfterModel",
            "BeforeTool",
            "AfterTool",
        ]
        for event in events:
            assert event in self.text, f"Missing event '{event}' in Default Settings table"

    def test_state_directory(self):
        assert "`~/.arize/harness/state/gemini/`" in self.text

    def test_log_file(self):
        assert "`~/.arize/harness/logs/gemini.log`" in self.text

    def test_table_has_setting_and_default_columns(self):
        assert "| Setting" in self.text and "| Default" in self.text


class TestGeminiReadmeNoProhibitedContent:
    """README must NOT contain certain sections/content."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_no_emojis(self):
        # Check for common emoji unicode ranges
        import re

        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]"
        )
        assert not emoji_pattern.search(self.text), "README must not contain emojis"

    def test_no_logging_block_discussion(self):
        assert "logging:" not in self.text or "logging" not in self.text.split("## Default Settings")[0]

    def test_no_configuration_section(self):
        assert "## Configuration" not in self.text

    def test_no_what_gets_traced(self):
        assert "What gets traced" not in self.text and "what gets traced" not in self.text


class TestGeminiReadmeMirrorsCopilot:
    """Structural comparison with copilot README."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.gemini_text = README_PATH.read_text()
        self.copilot_text = COPILOT_README_PATH.read_text()

    def test_same_heading_levels(self):
        """Both READMEs should use the same heading level structure."""
        gemini_headings = _extract_markdown_headings(self.gemini_text)
        copilot_headings = _extract_markdown_headings(self.copilot_text)
        gemini_levels = [h.split(" ")[0] for h in gemini_headings]
        copilot_levels = [h.split(" ")[0] for h in copilot_headings]
        assert (
            gemini_levels == copilot_levels
        ), f"Heading levels differ.\nGemini: {gemini_levels}\nCopilot: {copilot_levels}"

    def test_same_section_names_except_harness_specific(self):
        """Section names should match except for harness-specific terms."""
        gemini_headings = _extract_markdown_headings(self.gemini_text)
        # Compare everything except title and Default Settings (which have different values)
        # Setup, Remote setup, Local setup should be identical
        assert "## Setup" in gemini_headings
        assert "### Remote setup" in gemini_headings
        assert "### Local setup" in gemini_headings
        assert "## Default Settings" in gemini_headings


# ---------------------------------------------------------------------------
# SKILL.md tests
# ---------------------------------------------------------------------------


class TestGeminiSkillExists:
    """Skill file must exist at the expected path."""

    def test_skill_file_exists(self):
        assert SKILL_PATH.exists(), f"Expected SKILL.md at {SKILL_PATH}"

    def test_skill_is_not_empty(self):
        assert SKILL_PATH.exists() and SKILL_PATH.stat().st_size > 0

    def test_skill_directory_structure(self):
        skills_dir = REPO_ROOT / "tracing" / "gemini" / "skills" / "manage-gemini-tracing"
        assert skills_dir.is_dir(), f"Expected directory at {skills_dir}"


class TestGeminiSkillFrontmatter:
    """Skill must have valid YAML frontmatter."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()
        self.lines = self.text.splitlines()

    def test_starts_with_frontmatter_delimiter(self):
        assert self.lines[0] == "---"

    def test_has_closing_frontmatter_delimiter(self):
        # Find second --- after line 0
        closing_indices = [i for i, line in enumerate(self.lines) if line == "---" and i > 0]
        assert len(closing_indices) >= 1, "Missing closing --- for frontmatter"

    def test_frontmatter_has_name_field(self):
        frontmatter = self._extract_frontmatter()
        assert "name:" in frontmatter

    def test_frontmatter_name_value(self):
        frontmatter = self._extract_frontmatter()
        assert "name: manage-gemini-tracing" in frontmatter

    def test_frontmatter_has_description_field(self):
        frontmatter = self._extract_frontmatter()
        assert "description:" in frontmatter

    def test_description_triggers_on_setup_gemini_tracing(self):
        frontmatter = self._extract_frontmatter()
        assert "set up gemini tracing" in frontmatter.lower()

    def test_description_triggers_on_configure_arize_for_gemini(self):
        frontmatter = self._extract_frontmatter()
        assert "configure Arize for Gemini" in frontmatter or "configure arize for gemini" in frontmatter.lower()

    def test_description_triggers_on_configure_phoenix_for_gemini(self):
        frontmatter = self._extract_frontmatter()
        assert "configure Phoenix for Gemini" in frontmatter or "configure phoenix for gemini" in frontmatter.lower()

    def test_description_triggers_on_enable_gemini_tracing(self):
        frontmatter = self._extract_frontmatter()
        assert "enable gemini tracing" in frontmatter.lower()

    def test_description_triggers_on_setup_gemini_tracing_slug(self):
        frontmatter = self._extract_frontmatter()
        assert "setup-gemini-tracing" in frontmatter

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


class TestGeminiSkillContent:
    """Skill content must teach users how to manage gemini tracing."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_mentions_settings_json_verification(self):
        """Must teach verifying harness is installed via settings.json."""
        assert "~/.gemini/settings.json" in self.text

    def test_mentions_config_yaml_verification(self):
        """Must teach verifying config.yaml has gemini block."""
        assert "~/.arize/harness/config.yaml" in self.text

    def test_mentions_arize_trace_enabled_env_var(self):
        """Must teach toggling tracing on/off."""
        assert "ARIZE_TRACE_ENABLED" in self.text

    def test_mentions_log_file_tailing(self):
        """Must teach tailing the log file."""
        assert "~/.arize/harness/logs/gemini.log" in self.text

    def test_mentions_install_command(self):
        """Must teach reinstalling."""
        assert "./install.sh gemini" in self.text

    def test_mentions_uninstall_command(self):
        """Must teach uninstalling."""
        assert "./install.sh uninstall gemini" in self.text

    def test_mentions_hook_name_arize_tracing(self):
        """Settings.json entries use name 'arize-tracing'."""
        assert "arize-tracing" in self.text

    def test_mentions_eight_hook_entries(self):
        """Must reference all 8 hook events."""
        assert "8" in self.text

    def test_mentions_harnesses_gemini_block(self):
        """Must reference harnesses.gemini in config."""
        assert "harnesses.gemini" in self.text


class TestGeminiSkillDecisionTree:
    """Skill must follow a decision-tree workflow matching copilot skill."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()
        self.headings = [line for line in self.text.splitlines() if line.startswith("#")]

    def test_has_platform_question(self):
        """Decision tree should address which platform (Gemini CLI only)."""
        assert "Gemini CLI" in self.text

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


class TestGeminiSkillGeminiSpecific:
    """Skill must use Gemini-specific references, not Copilot ones."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_no_github_hooks_path(self):
        """Must not reference .github/hooks/ (copilot-specific)."""
        assert ".github/hooks/" not in self.text

    def test_no_vs_code_copilot_reference(self):
        """Must not reference VS Code Copilot."""
        assert "VS Code Copilot" not in self.text

    def test_no_copilot_cli_reference(self):
        """Must not reference Copilot CLI."""
        assert "Copilot CLI" not in self.text

    def test_references_gemini_cli(self):
        assert "Gemini CLI" in self.text

    def test_references_gemini_settings_json(self):
        assert "~/.gemini/settings.json" in self.text


class TestGeminiSkillNoCopilotLeakage:
    """Ensure no copilot-specific content leaked into gemini skill."""

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

    def test_no_arize_hook_copilot_commands(self):
        """Must not reference arize-hook-copilot-* commands."""
        assert "arize-hook-copilot" not in self.text

    def test_no_hooks_json_reference(self):
        """Must not reference hooks.json (copilot CLI format)."""
        assert "hooks.json" not in self.text


class TestGeminiSkillNoEmojis:
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


class TestGeminiSkillMirrorsCopilotStructure:
    """Skill should mirror the copilot skill's H2 section structure."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.gemini_text = SKILL_PATH.read_text()
        self.copilot_text = COPILOT_SKILL_PATH.read_text()

    def _extract_h2_headings(self, text: str) -> list[str]:
        return [line for line in text.splitlines() if line.startswith("## ")]

    def test_same_h2_section_count(self):
        """Gemini skill should have same number of H2 sections as copilot skill."""
        gemini_h2 = self._extract_h2_headings(self.gemini_text)
        copilot_h2 = self._extract_h2_headings(self.copilot_text)
        assert len(gemini_h2) == len(copilot_h2), (
            f"H2 count differs. Gemini: {len(gemini_h2)} ({gemini_h2}), " f"Copilot: {len(copilot_h2)} ({copilot_h2})"
        )

    def test_matching_h2_section_names(self):
        """H2 section names should match (with Copilot->Gemini substitutions)."""
        gemini_h2 = self._extract_h2_headings(self.gemini_text)
        copilot_h2 = self._extract_h2_headings(self.copilot_text)

        # Normalize: replace harness-specific terms for comparison
        def normalize(heading: str) -> str:
            return heading.lower().replace("copilot", "HARNESS").replace("gemini", "HARNESS")

        gemini_normalized = [normalize(h) for h in gemini_h2]
        copilot_normalized = [normalize(h) for h in copilot_h2]
        assert gemini_normalized == copilot_normalized, (
            f"H2 headings differ after normalization.\n" f"Gemini: {gemini_h2}\nCopilot: {copilot_h2}"
        )


# ---------------------------------------------------------------------------
# File-existence verification (paths under tracing/gemini/)
# ---------------------------------------------------------------------------


class TestGeminiFilesAtNewLocation:
    """Verify files exist at their tracing/gemini/ location."""

    def test_readme_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "README.md").exists()

    def test_skill_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "skills" / "manage-gemini-tracing" / "SKILL.md").exists()

    def test_init_py_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "__init__.py").exists()

    def test_constants_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "constants.py").exists()

    def test_hooks_init_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "hooks" / "__init__.py").exists()

    def test_adapter_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "hooks" / "adapter.py").exists()

    def test_handlers_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "hooks" / "handlers.py").exists()

    def test_install_at_tracing_gemini(self):
        assert (REPO_ROOT / "tracing" / "gemini" / "install.py").exists()

    def test_tracing_init_exists(self):
        assert (REPO_ROOT / "tracing" / "__init__.py").exists()


class TestGeminiSkillFolderNamePreserved:
    """Skill folder must keep its original name 'manage-gemini-tracing'."""

    def test_skill_folder_name(self):
        skill_dir = REPO_ROOT / "tracing" / "gemini" / "skills" / "manage-gemini-tracing"
        assert skill_dir.is_dir()

    def test_skill_frontmatter_name_unchanged(self):
        text = SKILL_PATH.read_text()
        lines = text.splitlines()
        closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), len(lines))
        frontmatter = "\n".join(lines[1:closing])
        assert "name: manage-gemini-tracing" in frontmatter


class TestGeminiReadmePreservedContent:
    """Verify documentation content was preserved (not rewritten) during path refactor."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = README_PATH.read_text()

    def test_log_file_path_unchanged(self):
        """Log file path must stay as gemini.log, not be rewritten."""
        assert "`~/.arize/harness/logs/gemini.log`" in self.text

    def test_state_dir_unchanged(self):
        assert "`~/.arize/harness/state/gemini/`" in self.text

    def test_settings_json_path_unchanged(self):
        assert "`~/.gemini/settings.json`" in self.text

    def test_harness_key_unchanged(self):
        assert "| Harness key | `gemini` |" in self.text

    def test_project_name_unchanged(self):
        assert "| Project name | `gemini` |" in self.text


class TestGeminiSkillPreservedContent:
    """Verify skill content was preserved during path refactor."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = SKILL_PATH.read_text()

    def test_dry_run_env_var(self):
        assert "ARIZE_DRY_RUN" in self.text

    def test_verbose_env_var(self):
        assert "ARIZE_VERBOSE" in self.text

    def test_user_id_env_var(self):
        assert "ARIZE_USER_ID" in self.text

    def test_phoenix_setup_section(self):
        assert "## Set Up Phoenix" in self.text

    def test_arize_ax_setup_section(self):
        assert "## Set Up Arize AX" in self.text

    def test_configure_settings_section(self):
        assert "## Configure Settings" in self.text

    def test_hook_events_section(self):
        assert "## Hook Events" in self.text

    def test_troubleshoot_section(self):
        assert "## Troubleshoot" in self.text

    def test_all_eight_hook_events_in_table(self):
        events = [
            "SessionStart",
            "SessionEnd",
            "BeforeAgent",
            "AfterAgent",
            "BeforeModel",
            "AfterModel",
            "BeforeTool",
            "AfterTool",
        ]
        for event in events:
            assert f"`{event}`" in self.text, f"Missing event '{event}' in hook events table"

    def test_hook_cli_entry_point_referenced(self):
        assert "arize-hook-gemini" in self.text

    def test_project_name_default_gemini(self):
        assert 'defaults to `"gemini"`' in self.text or "project_name: gemini" in self.text
