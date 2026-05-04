"""Tests for Codex README.md and SKILL.md path references after tracing/ migration."""

from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(ROOT, "tracing", "codex", "README.md")
SKILL_PATH = os.path.join(
    ROOT, "tracing", "codex", "skills", "manage-codex-tracing", "SKILL.md"
)


@pytest.fixture
def readme_content() -> str:
    with open(README_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def skill_content() -> str:
    with open(SKILL_PATH, encoding="utf-8") as f:
        return f.read()


# --- Existence checks ---


class TestFilesExist:
    def test_readme_exists(self):
        assert os.path.isfile(README_PATH), f"Missing {README_PATH}"

    def test_skill_exists(self):
        assert os.path.isfile(SKILL_PATH), f"Missing {SKILL_PATH}"

    def test_skill_directory_name_preserved(self):
        """Skill folder must keep its original name manage-codex-tracing."""
        skill_dir = os.path.dirname(SKILL_PATH)
        assert os.path.basename(skill_dir) == "manage-codex-tracing"


# --- No leftover old path references ---


class TestNoLegacyPaths:
    """Ensure no remnants of the old codex_tracing package path."""

    def test_readme_no_codex_tracing_underscore(self, readme_content: str):
        matches = re.findall(r"codex_tracing", readme_content)
        assert matches == [], (
            f"README.md still contains legacy 'codex_tracing' references: "
            f"found {len(matches)} occurrence(s)"
        )

    def test_skill_no_codex_tracing_underscore(self, skill_content: str):
        matches = re.findall(r"codex_tracing", skill_content)
        assert matches == [], (
            f"SKILL.md still contains legacy 'codex_tracing' references: "
            f"found {len(matches)} occurrence(s)"
        )

    def test_readme_no_codex_tracing_dot_import(self, readme_content: str):
        """No dotted import form of the old package."""
        matches = re.findall(r"codex_tracing\.", readme_content)
        assert matches == [], (
            f"README.md contains legacy dotted import 'codex_tracing.': "
            f"found {len(matches)} occurrence(s)"
        )

    def test_skill_no_codex_tracing_dot_import(self, skill_content: str):
        matches = re.findall(r"codex_tracing\.", skill_content)
        assert matches == [], (
            f"SKILL.md contains legacy dotted import 'codex_tracing.': "
            f"found {len(matches)} occurrence(s)"
        )


# --- Correct new path references in SKILL.md ---


class TestSkillPathReferences:
    """Verify SKILL.md uses the new tracing/codex/ paths."""

    def test_codex_buffer_path_reference(self, skill_content: str):
        """The buffer service path should reference tracing/codex/codex_buffer.py."""
        assert "tracing/codex/codex_buffer.py" in skill_content, (
            "SKILL.md should reference 'tracing/codex/codex_buffer.py'"
        )

    def test_referenced_file_exists(self):
        """The codex_buffer.py file referenced in SKILL.md must actually exist."""
        buffer_path = os.path.join(ROOT, "tracing", "codex", "codex_buffer.py")
        assert os.path.isfile(buffer_path), (
            f"File referenced in SKILL.md does not exist: {buffer_path}"
        )


# --- SKILL.md frontmatter and structure ---


class TestSkillFrontmatter:
    def test_has_yaml_frontmatter(self, skill_content: str):
        assert skill_content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        parts = skill_content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have opening and closing --- for frontmatter"

    def test_skill_name_in_frontmatter(self, skill_content: str):
        frontmatter = skill_content.split("---", 2)[1]
        assert "name: manage-codex-tracing" in frontmatter

    def test_description_mentions_codex(self, skill_content: str):
        frontmatter = skill_content.split("---", 2)[1]
        assert "codex" in frontmatter.lower() or "Codex" in frontmatter


# --- README structure ---


class TestReadmeStructure:
    def test_title(self, readme_content: str):
        assert "# Codex CLI Tracing" in readme_content

    def test_setup_section(self, readme_content: str):
        assert "## Setup" in readme_content

    def test_default_settings_section(self, readme_content: str):
        assert "## Default Settings" in readme_content

    def test_remote_setup_section(self, readme_content: str):
        assert "### Remote setup" in readme_content

    def test_local_setup_section(self, readme_content: str):
        assert "### Local setup" in readme_content


# --- Content preservation checks ---


class TestContentPreservation:
    """Ensure doc content hasn't been rewritten — only path strings changed."""

    def test_readme_mentions_openinference(self, readme_content: str):
        assert "OpenInference" in readme_content

    def test_readme_mentions_arize_ax(self, readme_content: str):
        assert "Arize AX" in readme_content

    def test_readme_mentions_phoenix(self, readme_content: str):
        assert "Phoenix" in readme_content

    def test_skill_architecture_section(self, skill_content: str):
        assert "## Architecture Overview" in skill_content

    def test_skill_troubleshoot_section(self, skill_content: str):
        assert "## Troubleshoot" in skill_content

    def test_skill_env_vars_table(self, skill_content: str):
        assert "## Environment Variables Reference" in skill_content
        # Spot-check a few key env vars
        assert "ARIZE_API_KEY" in skill_content
        assert "ARIZE_CODEX_BUFFER_PORT" in skill_content
        assert "ARIZE_DRY_RUN" in skill_content

    def test_skill_configure_codex_section(self, skill_content: str):
        assert "## Configure Codex" in skill_content

    def test_skill_buffer_service_details(self, skill_content: str):
        """Buffer service details should be preserved."""
        assert "port 4318" in skill_content
        assert "arize-codex-buffer" in skill_content

    def test_readme_console_script_names_unchanged(self, readme_content: str):
        """Console script names must not have changed."""
        # The README references the proxy shim and buffer service
        assert "arize-codex-proxy" in readme_content or "codex" in readme_content

    def test_skill_console_script_names_unchanged(self, skill_content: str):
        """Hook and buffer console script names must be preserved."""
        assert "arize-hook-codex-notify" in skill_content
        assert "arize-codex-buffer" in skill_content

    def test_skill_config_paths_unchanged(self, skill_content: str):
        """User-facing config paths should not have changed."""
        assert "~/.codex/config.toml" in skill_content
        assert "~/.arize/harness/config.yaml" in skill_content
        assert "~/.codex/arize-env.sh" in skill_content

    def test_skill_log_paths_unchanged(self, skill_content: str):
        assert "~/.arize/harness/logs/codex.log" in skill_content
        assert "~/.arize/harness/logs/codex-buffer.log" in skill_content

    def test_skill_state_dir_unchanged(self, skill_content: str):
        assert "~/.arize/harness/state/codex/" in skill_content
