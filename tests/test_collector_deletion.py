#!/usr/bin/env python3
"""Tests for the delete-collector task.

Validates that:
- core/collector.py and core/collector_ctl.py have been deleted from the repo
- No production code (core/) still imports from the deleted modules
- The replacement module (core/codex_buffer_ctl.py) exists
- The deleted files are tracked as deletions in git
"""

import ast
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CORE_DIR = REPO_ROOT / "core"

DELETED_FILES = [
    "core/collector.py",
    "core/collector_ctl.py",
]

DELETED_MODULES = [
    "core.collector",
    "core.collector_ctl",
]


class TestCollectorFilesDeleted:
    """Verify the old collector source files no longer exist in the repo."""

    @pytest.mark.parametrize("rel_path", DELETED_FILES)
    def test_file_does_not_exist(self, rel_path):
        full_path = REPO_ROOT / rel_path
        assert not full_path.exists(), (
            f"{rel_path} should have been deleted but still exists"
        )

    def test_git_tracks_deletions(self):
        """Git should show the collector files as deleted relative to main."""
        result = subprocess.run(
            ["git", "diff", "--name-status", "main", "--", "core/collector.py", "core/collector_ctl.py"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        # Each deleted file should appear as "D\tcore/collector*.py"
        deleted = [l for l in lines if l.startswith("D")]
        assert len(deleted) == 2, (
            f"Expected 2 git deletions, got: {lines}"
        )


class TestNoStaleImportsInCore:
    """Verify no production code under core/ imports from deleted modules."""

    @staticmethod
    def _collect_python_files():
        """Collect all .py files under core/."""
        return sorted(CORE_DIR.rglob("*.py"))

    @staticmethod
    def _extract_imports(filepath):
        """Parse a Python file and return all imported module names."""
        source = filepath.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            return []

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports

    def test_no_core_file_imports_collector(self):
        """No .py file under core/ should import from core.collector."""
        violations = []
        for pyfile in self._collect_python_files():
            rel = pyfile.relative_to(REPO_ROOT)
            for mod in self._extract_imports(pyfile):
                if mod in DELETED_MODULES:
                    violations.append(f"{rel} imports {mod}")
        if violations:
            pytest.fail(
                "Production code still imports deleted collector modules:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

    def test_no_core_file_has_collector_string_import(self):
        """Double-check with text search for any import references."""
        violations = []
        for pyfile in self._collect_python_files():
            rel = pyfile.relative_to(REPO_ROOT)
            content = pyfile.read_text(encoding="utf-8")
            for line_no, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "from core.collector_ctl " in line or "import core.collector_ctl" in line:
                    violations.append(f"{rel}:{line_no}: {stripped}")
                # Match core.collector but not core.collector_ctl
                elif ("from core.collector " in line or "import core.collector " in line
                      or line.rstrip().endswith("import core.collector")):
                    violations.append(f"{rel}:{line_no}: {stripped}")
        if violations:
            pytest.fail(
                "Production code still references deleted collector modules:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )


class TestReplacementExists:
    """Verify the replacement codex_buffer_ctl module is in place."""

    def test_codex_buffer_ctl_exists(self):
        assert (CORE_DIR / "codex_buffer_ctl.py").is_file(), (
            "core/codex_buffer_ctl.py should exist as the replacement for collector_ctl.py"
        )

    def test_codex_buffer_ctl_has_main(self):
        """The replacement module should define a main() function."""
        source = (CORE_DIR / "codex_buffer_ctl.py").read_text()
        tree = ast.parse(source)
        func_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert "main" in func_names, (
            "codex_buffer_ctl.py should have a main() entry point"
        )

    def test_codex_buffer_py_exists(self):
        """The codex_buffer.py server module should exist."""
        assert (CORE_DIR / "codex_buffer.py").is_file(), (
            "core/codex_buffer.py should exist as the replacement for collector.py"
        )
