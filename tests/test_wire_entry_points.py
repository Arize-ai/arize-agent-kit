"""Tests for wave 3: wire entry points to <harness>_tracing packages.

Verifies:
1. pyproject.toml entry points use <harness>_tracing.hooks.* paths (not core.hooks.*)
2. core/hooks/ directory no longer exists
3. No stale core.hooks or core.codex_buffer references in source files
4. DEVELOPMENT.md entry-point table references new module paths
5. .pre-commit-config.yaml uses underscore paths
6. All entry-point target modules and functions exist and are importable
7. Installed entry-point scripts reference new module paths
8. Copilot entry points included in pyproject.toml (all 8 hooks)
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 1. pyproject.toml entry points use new module paths
# ---------------------------------------------------------------------------

EXPECTED_HARNESS_ENTRY_POINTS = {
    # Claude Code hooks
    "arize-hook-session-start": "claude_code_tracing.hooks.handlers:session_start",
    "arize-hook-pre-tool-use": "claude_code_tracing.hooks.handlers:pre_tool_use",
    "arize-hook-post-tool-use": "claude_code_tracing.hooks.handlers:post_tool_use",
    "arize-hook-user-prompt-submit": "claude_code_tracing.hooks.handlers:user_prompt_submit",
    "arize-hook-stop": "claude_code_tracing.hooks.handlers:stop",
    "arize-hook-subagent-stop": "claude_code_tracing.hooks.handlers:subagent_stop",
    "arize-hook-notification": "claude_code_tracing.hooks.handlers:notification",
    "arize-hook-permission-request": "claude_code_tracing.hooks.handlers:permission_request",
    "arize-hook-session-end": "claude_code_tracing.hooks.handlers:session_end",
    # Codex hooks
    "arize-hook-codex-notify": "codex_tracing.hooks.handlers:notify",
    "arize-hook-codex-drain": "codex_tracing.hooks.handlers:drain_idle",
    # Codex proxy
    "arize-codex-proxy": "codex_tracing.hooks.proxy:main",
    # Codex buffer
    "arize-codex-buffer": "codex_tracing.codex_buffer_ctl:main",
    # Copilot hooks
    "arize-hook-copilot-session-start": "copilot_tracing.hooks.handlers:session_start",
    "arize-hook-copilot-user-prompt": "copilot_tracing.hooks.handlers:user_prompt_submitted",
    "arize-hook-copilot-pre-tool": "copilot_tracing.hooks.handlers:pre_tool_use",
    "arize-hook-copilot-post-tool": "copilot_tracing.hooks.handlers:post_tool_use",
    "arize-hook-copilot-stop": "copilot_tracing.hooks.handlers:stop",
    "arize-hook-copilot-error": "copilot_tracing.hooks.handlers:error_occurred",
    "arize-hook-copilot-session-end": "copilot_tracing.hooks.handlers:session_end",
    "arize-hook-copilot-subagent-stop": "copilot_tracing.hooks.handlers:subagent_stop",
    # Cursor hook
    "arize-hook-cursor": "cursor_tracing.hooks.handlers:main",
}

# Setup wizards stay on core.setup.*
EXPECTED_SETUP_ENTRY_POINTS = {
    "arize-setup-claude": "core.setup.claude:main",
    "arize-setup-codex": "core.setup.codex:main",
    "arize-setup-copilot": "core.setup.copilot:main",
    "arize-setup-cursor": "core.setup.cursor:main",
}


def _parse_pyproject_scripts():
    """Parse [project.scripts] from pyproject.toml."""
    content = (REPO_ROOT / "pyproject.toml").read_text()
    scripts = {}
    in_scripts = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts:
            if stripped.startswith("[") and stripped.endswith("]"):
                break
            if stripped.startswith("#") or not stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip('"')
            if key and value:
                scripts[key] = value
    return scripts


class TestPyprojectEntryPointsUpdated:
    """All hook/proxy/buffer entry points use <harness>_tracing.* paths."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.scripts = _parse_pyproject_scripts()
        self.pyproject_text = (REPO_ROOT / "pyproject.toml").read_text()

    @pytest.mark.parametrize("name,target", list(EXPECTED_HARNESS_ENTRY_POINTS.items()))
    def test_harness_entry_point(self, name, target):
        assert name in self.scripts, f"Missing entry point: {name}"
        assert self.scripts[name] == target, (
            f"{name}: expected '{target}', got '{self.scripts[name]}'"
        )

    @pytest.mark.parametrize("name,target", list(EXPECTED_SETUP_ENTRY_POINTS.items()))
    def test_setup_entry_point_unchanged(self, name, target):
        """arize-setup-* entry points still point at core.setup.*."""
        assert name in self.scripts, f"Missing setup entry point: {name}"
        assert self.scripts[name] == target

    def test_no_core_hooks_in_pyproject(self):
        """pyproject.toml must not reference core.hooks anywhere in entry points."""
        assert "core.hooks" not in self.pyproject_text

    def test_no_core_codex_buffer_ctl_in_pyproject(self):
        """pyproject.toml must not reference core.codex_buffer_ctl."""
        assert "core.codex_buffer_ctl" not in self.pyproject_text

    def test_total_entry_point_count(self):
        """Should have exactly 27 entry points (23 harness + 4 setup + arize-config)."""
        expected_count = len(EXPECTED_HARNESS_ENTRY_POINTS) + len(EXPECTED_SETUP_ENTRY_POINTS) + 1  # +1 for arize-config
        assert len(self.scripts) == expected_count, (
            f"Expected {expected_count} entry points, got {len(self.scripts)}: {sorted(self.scripts.keys())}"
        )


# ---------------------------------------------------------------------------
# 2. core/hooks/ directory deleted
# ---------------------------------------------------------------------------


class TestCoreHooksDeleted:
    """core/hooks/ directory must not exist after wave 3."""

    def test_core_hooks_dir_does_not_exist(self):
        assert not (REPO_ROOT / "core" / "hooks").exists(), "core/hooks/ must be deleted"

    def test_core_hooks_init_does_not_exist(self):
        assert not (REPO_ROOT / "core" / "hooks" / "__init__.py").exists()


# ---------------------------------------------------------------------------
# 3. No stale references in source files
# ---------------------------------------------------------------------------


class TestNoStaleCoreHooksReferences:
    """No Python, TOML, YAML, JSON, or Markdown files reference old core.hooks paths."""

    EXTENSIONS = ["*.py", "*.toml", "*.yaml", "*.yml", "*.json"]

    def _collect_files(self):
        files = []
        for ext in self.EXTENSIONS:
            files.extend(REPO_ROOT.rglob(ext))
        # Exclude .venv, __pycache__, and this test file itself
        this_file = Path(__file__).resolve()
        return [
            f for f in files
            if ".venv" not in str(f)
            and "__pycache__" not in str(f)
            and f.resolve() != this_file
        ]

    def test_no_core_hooks_dot_import(self):
        """No file uses 'core.hooks.' as an import/reference."""
        for f in self._collect_files():
            content = f.read_text()
            if "core.hooks." in content:
                assert False, f"{f.relative_to(REPO_ROOT)}: still references 'core.hooks.'"

    def test_no_core_codex_buffer_dot_import(self):
        """No file uses 'core.codex_buffer' as an import/reference."""
        for f in self._collect_files():
            content = f.read_text()
            if "core.codex_buffer" in content:
                assert False, f"{f.relative_to(REPO_ROOT)}: still references 'core.codex_buffer'"

    def test_no_core_slash_hooks_in_md(self):
        """No markdown file references 'core/hooks/'."""
        for f in REPO_ROOT.rglob("*.md"):
            if ".venv" in str(f):
                continue
            content = f.read_text()
            if "core/hooks/" in content:
                assert False, f"{f.relative_to(REPO_ROOT)}: still references 'core/hooks/'"

    def test_no_core_slash_codex_buffer_in_md(self):
        """No markdown file references 'core/codex_buffer'."""
        for f in REPO_ROOT.rglob("*.md"):
            if ".venv" in str(f):
                continue
            content = f.read_text()
            if "core/codex_buffer" in content:
                assert False, f"{f.relative_to(REPO_ROOT)}: still references 'core/codex_buffer'"


# ---------------------------------------------------------------------------
# 4. DEVELOPMENT.md updated
# ---------------------------------------------------------------------------


class TestDevelopmentMdUpdated:
    """DEVELOPMENT.md entry-point table and architecture references use new paths."""

    @pytest.fixture
    def dev_md(self):
        return (REPO_ROOT / "DEVELOPMENT.md").read_text()

    def test_entry_point_table_has_new_claude_path(self, dev_md):
        assert "claude_code_tracing.hooks.handlers:session_start" in dev_md

    def test_entry_point_table_has_new_codex_path(self, dev_md):
        assert "codex_tracing.hooks.handlers:notify" in dev_md

    def test_entry_point_table_has_new_cursor_path(self, dev_md):
        assert "cursor_tracing.hooks.handlers:main" in dev_md

    def test_entry_point_table_has_new_codex_buffer_path(self, dev_md):
        assert "codex_tracing.codex_buffer_ctl:main" in dev_md

    def test_entry_point_table_has_new_codex_proxy_path(self, dev_md):
        assert "codex_tracing.hooks.proxy:main" in dev_md

    def test_adapter_module_reference(self, dev_md):
        """Architecture section references <harness>_tracing/hooks/adapter.py."""
        assert "<harness>_tracing/hooks/adapter.py" in dev_md

    def test_import_example_updated(self, dev_md):
        """Import example uses <harness>_tracing.hooks.adapter."""
        assert "<harness>_tracing.hooks.adapter" in dev_md

    def test_no_core_hooks_reference_in_dev_md(self, dev_md):
        """No 'core.hooks' or 'core/hooks' patterns in DEVELOPMENT.md."""
        assert "core.hooks" not in dev_md
        assert "core/hooks" not in dev_md

    def test_no_core_codex_buffer_in_dev_md(self, dev_md):
        assert "core.codex_buffer" not in dev_md
        assert "core/codex_buffer" not in dev_md

    def test_codex_buffer_path_reference(self, dev_md):
        """The buffer service reference uses codex_tracing/ path."""
        assert "codex_tracing/codex_buffer.py" in dev_md


# ---------------------------------------------------------------------------
# 5. .pre-commit-config.yaml uses underscore paths
# ---------------------------------------------------------------------------


class TestPreCommitConfigUpdated:
    """Mypy hook file regexes use underscore package names."""

    @pytest.fixture
    def config_text(self):
        return (REPO_ROOT / ".pre-commit-config.yaml").read_text()

    @pytest.mark.parametrize("pkg", [
        "claude_code_tracing",
        "codex_tracing",
        "copilot_tracing",
        "cursor_tracing",
    ])
    def test_underscore_mypy_regex(self, config_text, pkg):
        assert f"^{pkg}/" in config_text

    @pytest.mark.parametrize("old", [
        "claude-code-tracing",
        "codex-tracing",
        "copilot-tracing",
        "cursor-tracing",
    ])
    def test_no_hyphenated_mypy_regex(self, config_text, old):
        assert f"^{old}/" not in config_text


# ---------------------------------------------------------------------------
# 6. Entry-point target modules and functions exist
# ---------------------------------------------------------------------------


class TestEntryPointTargetsExist:
    """All entry-point target modules exist on disk and define the referenced callable."""

    @pytest.mark.parametrize("target", list(EXPECTED_HARNESS_ENTRY_POINTS.values()))
    def test_target_module_file_exists(self, target):
        module_path, func_name = target.split(":")
        file_path = REPO_ROOT / module_path.replace(".", "/")
        file_path = file_path.with_suffix(".py")
        assert file_path.is_file(), f"Module file not found: {file_path.relative_to(REPO_ROOT)}"

    @pytest.mark.parametrize("target", list(EXPECTED_HARNESS_ENTRY_POINTS.values()))
    def test_target_function_defined(self, target):
        """The function is defined (via AST parsing) in the target module."""
        module_path, func_name = target.split(":")
        file_path = REPO_ROOT / module_path.replace(".", "/")
        file_path = file_path.with_suffix(".py")
        source = file_path.read_text()
        tree = ast.parse(source)
        func_names = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]
        assert func_name in func_names, (
            f"Function '{func_name}' not found in {file_path.relative_to(REPO_ROOT)}"
        )

    @pytest.mark.parametrize("target", list(EXPECTED_HARNESS_ENTRY_POINTS.values()))
    def test_target_importable(self, target):
        """The module is importable and the function is callable."""
        module_path, func_name = target.split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name, None)
        assert fn is not None, f"{func_name} not found in {module_path}"
        assert callable(fn), f"{module_path}:{func_name} is not callable"


# ---------------------------------------------------------------------------
# 7. Installed entry-point scripts reference new paths
# ---------------------------------------------------------------------------


class TestInstalledScripts:
    """The generated scripts in .venv/bin/ import from the new module paths."""

    VENV_BIN = REPO_ROOT / ".venv" / "bin"

    @pytest.mark.parametrize("script,expected_import", [
        ("arize-hook-session-start", "from claude_code_tracing.hooks.handlers import session_start"),
        ("arize-codex-buffer", "from codex_tracing.codex_buffer_ctl import main"),
        ("arize-hook-codex-notify", "from codex_tracing.hooks.handlers import notify"),
        ("arize-codex-proxy", "from codex_tracing.hooks.proxy import main"),
        ("arize-hook-cursor", "from cursor_tracing.hooks.handlers import main"),
        ("arize-hook-copilot-session-start", "from copilot_tracing.hooks.handlers import session_start"),
    ])
    def test_installed_script_import(self, script, expected_import):
        script_path = self.VENV_BIN / script
        if not script_path.exists():
            pytest.skip(f"{script} not installed in .venv/bin/")
        content = script_path.read_text()
        assert expected_import in content, (
            f"Script {script} does not import from new path. Content:\n{content}"
        )

    @pytest.mark.parametrize("script", [
        "arize-hook-session-start",
        "arize-hook-codex-notify",
        "arize-codex-proxy",
        "arize-codex-buffer",
        "arize-hook-cursor",
        "arize-hook-copilot-session-start",
    ])
    def test_installed_script_no_core_hooks(self, script):
        script_path = self.VENV_BIN / script
        if not script_path.exists():
            pytest.skip(f"{script} not installed in .venv/bin/")
        content = script_path.read_text()
        assert "core.hooks" not in content, (
            f"Script {script} still references core.hooks"
        )


# ---------------------------------------------------------------------------
# 8. Hooks directories exist in harness packages
# ---------------------------------------------------------------------------


class TestHooksDirsInHarnessPackages:
    """Each harness package has a hooks/ subdirectory with expected files."""

    @pytest.mark.parametrize("pkg,expected_files", [
        ("claude_code_tracing", ["__init__.py", "adapter.py", "handlers.py"]),
        ("codex_tracing", ["__init__.py", "adapter.py", "handlers.py", "proxy.py"]),
        ("copilot_tracing", ["__init__.py", "adapter.py", "handlers.py"]),
        ("cursor_tracing", ["__init__.py", "adapter.py", "handlers.py"]),
    ])
    def test_hooks_dir_has_expected_files(self, pkg, expected_files):
        hooks_dir = REPO_ROOT / pkg / "hooks"
        assert hooks_dir.is_dir(), f"{pkg}/hooks/ must exist"
        for fname in expected_files:
            assert (hooks_dir / fname).is_file(), f"{pkg}/hooks/{fname} must exist"

    def test_codex_buffer_files_in_codex_tracing(self):
        """codex_buffer.py and codex_buffer_ctl.py live in codex_tracing/."""
        assert (REPO_ROOT / "codex_tracing" / "codex_buffer.py").is_file()
        assert (REPO_ROOT / "codex_tracing" / "codex_buffer_ctl.py").is_file()

    def test_codex_buffer_not_in_core(self):
        """codex_buffer files must NOT exist in core/."""
        assert not (REPO_ROOT / "core" / "codex_buffer.py").exists()
        assert not (REPO_ROOT / "core" / "codex_buffer_ctl.py").exists()


# ---------------------------------------------------------------------------
# 9. Coverage omit updated
# ---------------------------------------------------------------------------


class TestCoverageConfig:
    """pyproject.toml coverage omit uses codex_tracing/ path."""

    def test_coverage_omit_path(self):
        text = (REPO_ROOT / "pyproject.toml").read_text()
        assert "codex_tracing/codex_buffer.py" in text
        assert "core/codex_buffer.py" not in text
