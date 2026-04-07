#!/usr/bin/env python3
"""Tests for doc-fixes task.

Validates:
- COLLECTOR_ARCHITECTURE.md exists and has required content
- All COLLECTOR_ARCHITECTURE.md links resolve to a real file
- No references to deleted scripts/setup.py remain
- Harness READMEs reference CLI entry points for setup
- Directory structure sections are updated (no hooks/*.sh, no scripts/)
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# Files that reference COLLECTOR_ARCHITECTURE.md
COLLECTOR_ARCH_REFERRERS = [
    "README.md",
    "DEVELOPMENT.md",
    "claude-code-tracing/README.md",
    "codex-tracing/README.md",
    "cursor-tracing/README.md",
]


class TestCollectorArchitectureExists:
    """COLLECTOR_ARCHITECTURE.md must exist and be well-formed."""

    def test_file_exists(self):
        path = REPO_ROOT / "COLLECTOR_ARCHITECTURE.md"
        assert path.exists(), "COLLECTOR_ARCHITECTURE.md does not exist"

    def test_file_not_empty(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert len(content.strip()) > 100, "COLLECTOR_ARCHITECTURE.md is too short"

    def test_under_150_lines(self):
        lines = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text().splitlines()
        assert len(lines) <= 150, f"COLLECTOR_ARCHITECTURE.md is {len(lines)} lines, should be <=150"

    def test_has_title(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert content.startswith("# "), "Should start with a markdown heading"

    def test_covers_what_collector_does(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text().lower()
        assert "http" in content and "span" in content, "Should describe HTTP server and spans"

    def test_covers_start_stop(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert "collector_ctl" in content or "collector-ctl" in content, \
            "Should reference collector_ctl for lifecycle management"

    def test_covers_config_path(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert "config.yaml" in content, "Should reference config.yaml"

    def test_covers_api_endpoints(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert "/v1/spans" in content, "Should document /v1/spans endpoint"
        assert "/health" in content, "Should document /health endpoint"
        assert "/drain/" in content, "Should document /drain endpoint"

    def test_covers_pid_file(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert "collector.pid" in content, "Should document PID file location"

    def test_covers_log_file(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert "collector.log" in content, "Should document log file location"

    def test_mentions_phoenix_and_arize(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text().lower()
        assert "phoenix" in content, "Should mention Phoenix backend"
        assert "arize" in content, "Should mention Arize backend"


class TestCollectorArchitectureLinksResolve:
    """All links to COLLECTOR_ARCHITECTURE.md in the repo must resolve."""

    @pytest.mark.parametrize("referrer", COLLECTOR_ARCH_REFERRERS)
    def test_referrer_links_to_collector_arch(self, referrer):
        """Each known referrer should contain a link to COLLECTOR_ARCHITECTURE.md."""
        path = REPO_ROOT / referrer
        if not path.exists():
            pytest.skip(f"{referrer} does not exist")
        content = path.read_text()
        assert "COLLECTOR_ARCHITECTURE.md" in content, \
            f"{referrer} should reference COLLECTOR_ARCHITECTURE.md"

    @pytest.mark.parametrize("referrer", COLLECTOR_ARCH_REFERRERS)
    def test_collector_arch_link_resolves(self, referrer):
        """The relative link from each referrer should resolve to the actual file."""
        path = REPO_ROOT / referrer
        if not path.exists():
            pytest.skip(f"{referrer} does not exist")
        content = path.read_text()
        # Extract markdown links: [text](path/to/COLLECTOR_ARCHITECTURE.md)
        # Use [^)]+ to avoid matching across nested parentheses
        link_pattern = re.compile(r'\[[^\]]*\]\(([^)]*COLLECTOR_ARCHITECTURE\.md)\)')
        matches = link_pattern.findall(content)
        assert matches, f"{referrer} has no markdown link to COLLECTOR_ARCHITECTURE.md"
        for link in matches:
            resolved = (path.parent / link).resolve()
            assert resolved.exists(), \
                f"{referrer}: link '{link}' does not resolve (expected {resolved})"


class TestNoScriptsSetupReferences:
    """No references to the old scripts/setup.py should remain in harness READMEs."""

    HARNESS_READMES = [
        "claude-code-tracing/README.md",
        "codex-tracing/README.md",
        "cursor-tracing/README.md",
    ]

    @pytest.mark.parametrize("readme", HARNESS_READMES)
    def test_no_scripts_setup_py(self, readme):
        content = (REPO_ROOT / readme).read_text()
        assert "scripts/setup.py" not in content, \
            f"{readme} still references scripts/setup.py"

    @pytest.mark.parametrize("readme", HARNESS_READMES)
    def test_no_scripts_directory_in_listing(self, readme):
        """Directory structure sections should not list a scripts/ directory."""
        content = (REPO_ROOT / readme).read_text()
        # Look for scripts/ in directory listing context (indented lines)
        lines = content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("scripts/"):
                # Make sure it's in a directory listing (preceded by indented lines)
                assert False, \
                    f"{readme}:{i+1}: still lists scripts/ in directory structure"


class TestHarnessReadmesUseCliEntryPoints:
    """Harness READMEs should reference arize-setup-* CLI entry points."""

    def test_claude_readme_uses_arize_setup_claude(self):
        content = (REPO_ROOT / "claude-code-tracing" / "README.md").read_text()
        assert "arize-setup-claude" in content, \
            "Claude README should reference arize-setup-claude"

    def test_codex_readme_uses_arize_setup_codex(self):
        content = (REPO_ROOT / "codex-tracing" / "README.md").read_text()
        assert "arize-setup-codex" in content, \
            "Codex README should reference arize-setup-codex"

    def test_cursor_readme_uses_arize_setup_cursor(self):
        content = (REPO_ROOT / "cursor-tracing" / "README.md").read_text()
        assert "arize-setup-cursor" in content, \
            "Cursor README should reference arize-setup-cursor"

    def test_claude_readme_mentions_setup_module(self):
        """Claude README should note that setup lives in core/setup/claude.py."""
        content = (REPO_ROOT / "claude-code-tracing" / "README.md").read_text()
        assert "core/setup/claude.py" in content, \
            "Claude README should reference core/setup/claude.py"

    def test_codex_readme_mentions_setup_module(self):
        content = (REPO_ROOT / "codex-tracing" / "README.md").read_text()
        assert "core/setup/codex.py" in content, \
            "Codex README should reference core/setup/codex.py"

    def test_cursor_readme_mentions_setup_module(self):
        content = (REPO_ROOT / "cursor-tracing" / "README.md").read_text()
        assert "core/setup/cursor.py" in content, \
            "Cursor README should reference core/setup/cursor.py"


class TestNoDeletedBashScriptReferences:
    """No references to deleted bash scripts should remain in documentation."""

    ALL_DOCS = [
        "README.md",
        "DEVELOPMENT.md",
        "COLLECTOR_ARCHITECTURE.md",
        "claude-code-tracing/README.md",
        "codex-tracing/README.md",
        "cursor-tracing/README.md",
    ]

    @pytest.mark.parametrize("doc", ALL_DOCS)
    def test_no_hooks_sh_references(self, doc):
        """No references to hooks/*.sh files."""
        path = REPO_ROOT / doc
        if not path.exists():
            pytest.skip(f"{doc} does not exist")
        content = path.read_text()
        pattern = re.compile(r'hooks/\w+\.sh')
        matches = pattern.findall(content)
        assert not matches, f"{doc} still references bash hook scripts: {matches}"

    @pytest.mark.parametrize("doc", ALL_DOCS)
    def test_no_python_scripts_setup_py(self, doc):
        """No 'python ... scripts/setup.py' invocations."""
        path = REPO_ROOT / doc
        if not path.exists():
            pytest.skip(f"{doc} does not exist")
        content = path.read_text()
        assert "python" not in content or "scripts/setup.py" not in content, \
            f"{doc} still has 'python scripts/setup.py' invocation"


class TestCollectorArchitectureSourceFiles:
    """COLLECTOR_ARCHITECTURE.md should reference the correct source files."""

    def test_references_collector_py(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert "core/collector.py" in content

    def test_references_collector_ctl_py(self):
        content = (REPO_ROOT / "COLLECTOR_ARCHITECTURE.md").read_text()
        assert "core/collector_ctl.py" in content
