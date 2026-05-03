"""Final verification tests for the tracing/<harness> package rename.

Validates that the rename from top-level *_tracing/ packages to tracing/<harness>/
is complete and correct across:

1. Directory structure: all five harnesses under tracing/, old dirs gone
2. Python package importability for all five harnesses
3. Console-script entry points reference tracing.* or core.* modules
4. No leftover *_tracing references in source files
5. pyproject.toml configuration (packages.find, coverage, isort, entry points)
6. core/setup/*.py delegates use direct imports from tracing.<harness>
7. core/constants.py harness metadata unchanged by the rename
8. Skills and READMEs exist at new paths
9. install.sh / install.bat reference new tracing/ paths
10. .pre-commit-config.yaml references new paths
11. All handler modules expose the expected callable entry points
12. Marketplace plugin config unchanged
"""

from __future__ import annotations

import ast
import importlib
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# All five harnesses
ALL_HARNESSES = ["claude_code", "codex", "copilot", "cursor", "gemini"]
ALL_PACKAGES = [f"tracing.{h}" for h in ALL_HARNESSES]
OLD_PACKAGES = [
    "claude_code_tracing",
    "codex_tracing",
    "copilot_tracing",
    "cursor_tracing",
    "gemini_tracing",
]
OLD_DIRS_HYPHENATED = [
    "claude-code-tracing",
    "codex-tracing",
    "copilot-tracing",
    "cursor-tracing",
    "gemini-tracing",
]

# Harness names as used in config/constants (with hyphens)
HARNESS_NAMES = ["claude-code", "codex", "copilot", "cursor", "gemini"]


# ---------------------------------------------------------------------------
# 1. Directory structure
# ---------------------------------------------------------------------------


class TestDirectoryStructureComplete:
    """All five harnesses exist under tracing/; old directories are gone."""

    def test_tracing_package_init_exists(self):
        init = REPO_ROOT / "tracing" / "__init__.py"
        assert init.is_file(), "tracing/__init__.py must exist"

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_dir_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness).is_dir()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_init_py_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness / "__init__.py").is_file()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_constants_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness / "constants.py").is_file()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_install_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness / "install.py").is_file()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_hooks_dir_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness / "hooks").is_dir()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_hooks_init_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness / "hooks" / "__init__.py").is_file()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_hooks_handlers_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness / "hooks" / "handlers.py").is_file()

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_harness_hooks_adapter_exists(self, harness):
        assert (REPO_ROOT / "tracing" / harness / "hooks" / "adapter.py").is_file()

    @pytest.mark.parametrize("old_pkg", OLD_PACKAGES)
    def test_old_underscore_dir_does_not_exist(self, old_pkg):
        assert not (REPO_ROOT / old_pkg).exists(), f"Old {old_pkg}/ must not exist"

    @pytest.mark.parametrize("old_dir", OLD_DIRS_HYPHENATED)
    def test_old_hyphenated_dir_does_not_exist(self, old_dir):
        assert not (REPO_ROOT / old_dir).exists(), f"Old {old_dir}/ must not exist"


# ---------------------------------------------------------------------------
# 2. Python package importability
# ---------------------------------------------------------------------------


class TestAllHarnessesImportable:
    """All five harness packages and their key submodules are importable."""

    @pytest.mark.parametrize("pkg", ALL_PACKAGES)
    def test_package_importable(self, pkg):
        mod = importlib.import_module(pkg)
        assert mod is not None

    @pytest.mark.parametrize("pkg", ALL_PACKAGES)
    def test_constants_importable(self, pkg):
        mod = importlib.import_module(f"{pkg}.constants")
        assert hasattr(mod, "HARNESS_NAME")

    @pytest.mark.parametrize("pkg", ALL_PACKAGES)
    def test_install_importable(self, pkg):
        mod = importlib.import_module(f"{pkg}.install")
        assert hasattr(mod, "install")

    @pytest.mark.parametrize("pkg", ALL_PACKAGES)
    def test_hooks_handlers_importable(self, pkg):
        importlib.import_module(f"{pkg}.hooks.handlers")

    @pytest.mark.parametrize("pkg", ALL_PACKAGES)
    def test_hooks_adapter_importable(self, pkg):
        importlib.import_module(f"{pkg}.hooks.adapter")

    def test_top_level_tracing_import(self):
        """from tracing import claude_code, codex, copilot, cursor, gemini"""
        from tracing import claude_code, codex, copilot, cursor, gemini

        assert claude_code is not None
        assert codex is not None
        assert copilot is not None
        assert cursor is not None
        assert gemini is not None


# ---------------------------------------------------------------------------
# 3. Console-script entry points
# ---------------------------------------------------------------------------


class TestConsoleScriptEntryPoints:
    """All arize-* entry points reference tracing.* or core.* modules."""

    @pytest.fixture(scope="class")
    def arize_entry_points(self):
        from importlib.metadata import entry_points

        return [ep for ep in entry_points(group="console_scripts") if ep.name.startswith("arize-")]

    def test_entry_points_exist(self, arize_entry_points):
        assert len(arize_entry_points) > 0, "No arize-* entry points found"

    def test_all_entry_points_use_new_paths(self, arize_entry_points):
        for ep in arize_entry_points:
            assert "tracing." in ep.value or "core." in ep.value, (
                f"Entry point {ep.name} -> {ep.value} does not use tracing.* or core.* path"
            )

    def test_no_entry_point_uses_old_paths(self, arize_entry_points):
        for ep in arize_entry_points:
            for old in OLD_PACKAGES:
                assert old not in ep.value, (
                    f"Entry point {ep.name} -> {ep.value} still references old package {old}"
                )

    def test_console_script_names_unchanged(self, arize_entry_points):
        """User-facing command names must not have changed."""
        names = {ep.name for ep in arize_entry_points}
        # Key hook names that must be preserved
        expected_hooks = [
            "arize-hook-session-start",
            "arize-hook-session-end",
            "arize-hook-codex-notify",
            "arize-hook-copilot-session-start",
            "arize-hook-cursor",
            "arize-hook-gemini-session-start",
            "arize-setup-claude",
            "arize-setup-codex",
            "arize-setup-copilot",
            "arize-setup-cursor",
            "arize-setup-gemini",
        ]
        for hook in expected_hooks:
            assert hook in names, f"Expected console script {hook!r} is missing"


# ---------------------------------------------------------------------------
# 4. No leftover *_tracing references in source files
# ---------------------------------------------------------------------------


class TestNoLeftoverOldReferences:
    """No source file references old *_tracing package names (except test assertions)."""

    SOURCE_GLOBS = ["*.py", "*.toml", "*.yml", "*.yaml", "*.json", "*.sh", "*.bat"]
    EXCLUDE_DIRS = {".workbench", "__pycache__", ".venv", "arize_agent_kit.egg-info"}

    def _source_files(self):
        for pattern in self.SOURCE_GLOBS:
            for p in REPO_ROOT.rglob(pattern):
                if any(excl in p.parts for excl in self.EXCLUDE_DIRS):
                    continue
                if "uv.lock" in p.name:
                    continue
                yield p

    @pytest.mark.parametrize("old_pkg", OLD_PACKAGES)
    def test_no_old_package_in_non_test_source(self, old_pkg):
        """Non-test source files must not reference old package names."""
        violations = []
        for filepath in self._source_files():
            if filepath.parent.name == "tests" or "/tests/" in str(filepath):
                continue
            text = filepath.read_text(errors="replace")
            if old_pkg in text:
                violations.append(str(filepath.relative_to(REPO_ROOT)))
        assert not violations, (
            f"Old package name {old_pkg!r} found in non-test files: {violations}"
        )


# ---------------------------------------------------------------------------
# 5. pyproject.toml configuration
# ---------------------------------------------------------------------------


class TestPyprojectConfig:
    """pyproject.toml is correctly configured for the new layout."""

    @pytest.fixture(scope="class")
    def text(self):
        return (REPO_ROOT / "pyproject.toml").read_text()

    def test_packages_find_includes_tracing(self, text):
        assert '"tracing*"' in text or "'tracing*'" in text

    def test_packages_find_includes_core(self, text):
        assert '"core*"' in text or "'core*'" in text

    def test_coverage_source_includes_tracing(self, text):
        assert '"tracing"' in text

    def test_isort_known_first_party_includes_tracing(self, text):
        assert '"tracing"' in text

    def test_pytest_cov_includes_tracing(self, text):
        assert "--cov=tracing" in text

    def test_no_old_package_names_in_packages_find(self, text):
        for old in OLD_PACKAGES:
            # Check setuptools packages.find doesn't reference old names
            assert f'"{old}*"' not in text, f"pyproject.toml packages.find still references {old}"

    @pytest.mark.parametrize(
        "script_name,module_path",
        [
            ("arize-hook-session-start", "tracing.claude_code.hooks.handlers:session_start"),
            ("arize-hook-codex-notify", "tracing.codex.hooks.handlers:notify"),
            ("arize-hook-copilot-session-start", "tracing.copilot.hooks.handlers:session_start"),
            ("arize-hook-cursor", "tracing.cursor.hooks.handlers:main"),
            ("arize-hook-gemini-session-start", "tracing.gemini.hooks.handlers:session_start"),
            ("arize-codex-buffer", "tracing.codex.codex_buffer_ctl:main"),
            ("arize-setup-claude", "core.setup.claude:main"),
            ("arize-setup-gemini", "core.setup.gemini:main"),
        ],
    )
    def test_entry_point_in_pyproject(self, text, script_name, module_path):
        assert f'{script_name} = "{module_path}"' in text


# ---------------------------------------------------------------------------
# 6. core/setup/*.py delegation
# ---------------------------------------------------------------------------


class TestSetupDelegationAllHarnesses:
    """All five core/setup/*.py files import from tracing.<harness>."""

    @pytest.mark.parametrize(
        "setup_file,import_path",
        [
            ("core/setup/claude.py", "from tracing.claude_code import install as _install_mod"),
            ("core/setup/codex.py", "from tracing.codex import install as _install_mod"),
            ("core/setup/copilot.py", "from tracing.copilot import install as _install_mod"),
            ("core/setup/cursor.py", "from tracing.cursor import install as _install_mod"),
            ("core/setup/gemini.py", "from tracing.gemini import install as _install_mod"),
        ],
    )
    def test_setup_imports_from_tracing(self, setup_file, import_path):
        text = (REPO_ROOT / setup_file).read_text()
        assert import_path in text, f"{setup_file} missing import: {import_path}"

    @pytest.mark.parametrize(
        "setup_file",
        [
            "core/setup/claude.py",
            "core/setup/codex.py",
            "core/setup/copilot.py",
            "core/setup/cursor.py",
            "core/setup/gemini.py",
        ],
    )
    def test_setup_no_importlib_shim(self, setup_file):
        text = (REPO_ROOT / setup_file).read_text()
        assert "spec_from_file_location" not in text
        assert "module_from_spec" not in text
        assert "exec_module" not in text

    @pytest.mark.parametrize(
        "setup_file",
        [
            "core/setup/claude.py",
            "core/setup/codex.py",
            "core/setup/copilot.py",
            "core/setup/cursor.py",
            "core/setup/gemini.py",
        ],
    )
    def test_setup_no_old_package_references(self, setup_file):
        text = (REPO_ROOT / setup_file).read_text()
        for old in OLD_PACKAGES:
            assert old not in text, f"{setup_file} still references {old}"


# ---------------------------------------------------------------------------
# 7. core/constants.py unchanged
# ---------------------------------------------------------------------------


class TestCoreConstantsUnchanged:
    """Harness metadata in core/constants.py was not altered by the rename."""

    def test_all_harness_keys_present(self):
        from core.constants import HARNESSES

        for name in HARNESS_NAMES:
            assert name in HARNESSES, f"Missing harness key: {name}"

    @pytest.mark.parametrize(
        "harness_name,expected_service",
        [
            ("claude-code", "claude-code"),
            ("codex", "codex"),
            ("copilot", "copilot"),
            ("cursor", "cursor"),
            ("gemini", "gemini"),
        ],
    )
    def test_service_name_unchanged(self, harness_name, expected_service):
        from core.constants import HARNESSES

        assert HARNESSES[harness_name]["service_name"] == expected_service

    @pytest.mark.parametrize(
        "harness_name,expected_subdir",
        [
            ("claude-code", "claude-code"),
            ("codex", "codex"),
            ("copilot", "copilot"),
            ("cursor", "cursor"),
            ("gemini", "gemini"),
        ],
    )
    def test_state_subdir_unchanged(self, harness_name, expected_subdir):
        from core.constants import HARNESSES

        assert HARNESSES[harness_name]["state_subdir"] == expected_subdir


# ---------------------------------------------------------------------------
# 8. Skills and READMEs at new paths
# ---------------------------------------------------------------------------


class TestSkillsAndReadmes:
    """Skills and READMEs exist at new paths under tracing/<harness>/."""

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_readme_exists(self, harness):
        readme = REPO_ROOT / "tracing" / harness / "README.md"
        assert readme.is_file(), f"README.md missing at tracing/{harness}/"

    SKILL_DIRS = {
        "claude_code": "manage-claude-code-tracing",
        "codex": "manage-codex-tracing",
        "copilot": "manage-copilot-tracing",
        "cursor": "manage-cursor-tracing",
        "gemini": "manage-gemini-tracing",
    }

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_skill_md_exists(self, harness):
        skill_dir = self.SKILL_DIRS[harness]
        skill = REPO_ROOT / "tracing" / harness / "skills" / skill_dir / "SKILL.md"
        assert skill.is_file(), f"SKILL.md missing at tracing/{harness}/skills/{skill_dir}/"

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_skill_dir_name_unchanged(self, harness):
        """Skill folder names keep their original names (not renamed)."""
        skill_dir = self.SKILL_DIRS[harness]
        assert (REPO_ROOT / "tracing" / harness / "skills" / skill_dir).is_dir()


# ---------------------------------------------------------------------------
# 9. Shell router scripts
# ---------------------------------------------------------------------------


class TestShellRouterScriptsComplete:
    """install.sh and install.bat reference tracing/<harness> paths."""

    @pytest.fixture(scope="class")
    def install_sh(self):
        return (REPO_ROOT / "install.sh").read_text()

    @pytest.fixture(scope="class")
    def install_bat(self):
        return (REPO_ROOT / "install.bat").read_text()

    @pytest.mark.parametrize(
        "expected",
        ["tracing/claude_code", "tracing/codex", "tracing/copilot", "tracing/cursor", "tracing/gemini"],
    )
    def test_install_sh_new_paths(self, install_sh, expected):
        assert expected in install_sh, f"install.sh missing path: {expected}"

    # Note: install.bat does not yet include gemini (pre-existing gap)
    @pytest.mark.parametrize(
        "expected",
        [
            "tracing\\claude_code",
            "tracing\\codex",
            "tracing\\copilot",
            "tracing\\cursor",
        ],
    )
    def test_install_bat_new_paths(self, install_bat, expected):
        assert expected in install_bat, f"install.bat missing path: {expected}"

    @pytest.mark.parametrize("old_dir", OLD_DIRS_HYPHENATED)
    def test_install_sh_no_old_dirs(self, install_sh, old_dir):
        assert old_dir not in install_sh

    @pytest.mark.parametrize("old_dir", OLD_DIRS_HYPHENATED)
    def test_install_bat_no_old_dirs(self, install_bat, old_dir):
        assert old_dir not in install_bat

    @pytest.mark.parametrize("old_pkg", OLD_PACKAGES)
    def test_install_sh_no_old_underscore_dirs(self, install_sh, old_pkg):
        # Old top-level underscore dirs like "claude_code_tracing/"
        assert f"{old_pkg}/" not in install_sh
        assert f"{old_pkg}\\" not in install_sh


# ---------------------------------------------------------------------------
# 10. .pre-commit-config.yaml
# ---------------------------------------------------------------------------


class TestPreCommitConfigComplete:
    """Pre-commit config references tracing/ paths."""

    # Note: .pre-commit-config.yaml has mypy hooks for 4 harnesses but not
    # gemini (pre-existing gap — gemini was added after the mypy hooks).
    PRECOMMIT_HARNESSES = ["claude_code", "codex", "copilot", "cursor"]

    @pytest.fixture(scope="class")
    def text(self):
        return (REPO_ROOT / ".pre-commit-config.yaml").read_text()

    @pytest.mark.parametrize("harness", PRECOMMIT_HARNESSES)
    def test_references_new_paths(self, text, harness):
        assert f"^tracing/{harness}/" in text, (
            f".pre-commit-config.yaml missing ^tracing/{harness}/"
        )

    @pytest.mark.parametrize("old_dir", OLD_DIRS_HYPHENATED)
    def test_no_old_hyphenated_refs(self, text, old_dir):
        assert f"^{old_dir}/" not in text


# ---------------------------------------------------------------------------
# 11. Handler entry-point callables exist
# ---------------------------------------------------------------------------


class TestHandlerCallablesExist:
    """All handler functions referenced by entry points are importable and callable."""

    HANDLER_FUNCTIONS = {
        "tracing.claude_code.hooks.handlers": [
            "session_start",
            "pre_tool_use",
            "post_tool_use",
            "user_prompt_submit",
            "stop",
            "subagent_stop",
            "stop_failure",
            "notification",
            "permission_request",
            "session_end",
        ],
        "tracing.codex.hooks.handlers": ["notify", "drain_idle"],
        "tracing.copilot.hooks.handlers": [
            "session_start",
            "user_prompt_submitted",
            "pre_tool_use",
            "post_tool_use",
            "stop",
            "error_occurred",
            "session_end",
            "subagent_stop",
        ],
        "tracing.cursor.hooks.handlers": ["main"],
        "tracing.gemini.hooks.handlers": [
            "session_start",
            "session_end",
            "before_agent",
            "after_agent",
            "before_model",
            "after_model",
            "before_tool",
            "after_tool",
        ],
    }

    @pytest.mark.parametrize(
        "module_path,func_names",
        list(HANDLER_FUNCTIONS.items()),
        ids=list(HANDLER_FUNCTIONS.keys()),
    )
    def test_handler_functions_exist(self, module_path, func_names):
        mod = importlib.import_module(module_path)
        for fn_name in func_names:
            fn = getattr(mod, fn_name, None)
            assert fn is not None, f"{module_path}.{fn_name} not found"
            assert callable(fn), f"{module_path}.{fn_name} is not callable"


# ---------------------------------------------------------------------------
# 12. Marketplace plugin config unchanged
# ---------------------------------------------------------------------------


class TestMarketplacePluginUnchanged:
    """The Claude Code marketplace plugin config was not altered."""

    @pytest.fixture(scope="class")
    def marketplace(self):
        return json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())

    def test_plugin_name(self, marketplace):
        assert marketplace["plugins"][0]["name"] == "claude-code-tracing"

    def test_plugin_source_unchanged(self, marketplace):
        # Source path should still be ./claude-code-tracing (not renamed)
        assert marketplace["plugins"][0]["source"] == "./claude-code-tracing"


# ---------------------------------------------------------------------------
# 13. All install.py files use absolute imports from tracing.<harness>
# ---------------------------------------------------------------------------


class TestInstallAbsoluteImports:
    """All install.py files use absolute imports from tracing.<harness>.constants."""

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_install_imports_constants(self, harness):
        text = (REPO_ROOT / "tracing" / harness / "install.py").read_text()
        assert f"from tracing.{harness}.constants import" in text, (
            f"tracing/{harness}/install.py missing absolute import of constants"
        )

    @pytest.mark.parametrize("harness", ALL_HARNESSES)
    def test_install_parses_cleanly(self, harness):
        source = (REPO_ROOT / "tracing" / harness / "install.py").read_text()
        tree = ast.parse(source, filename=f"tracing/{harness}/install.py")
        assert tree is not None


# ---------------------------------------------------------------------------
# 14. All Python files in tracing/ parse cleanly
# ---------------------------------------------------------------------------


class TestAllTracingPythonParses:
    """Every .py file under tracing/ is valid Python."""

    @staticmethod
    def _all_py_files():
        return list((REPO_ROOT / "tracing").rglob("*.py"))

    def test_all_py_files_parse(self):
        for py_file in self._all_py_files():
            source = py_file.read_text()
            try:
                ast.parse(source, filename=str(py_file))
            except SyntaxError as e:
                pytest.fail(f"Syntax error in {py_file.relative_to(REPO_ROOT)}: {e}")

    def test_at_least_30_py_files(self):
        """Sanity check: there should be many .py files in tracing/."""
        count = len(self._all_py_files())
        assert count >= 30, f"Expected >= 30 .py files in tracing/, found {count}"


# ---------------------------------------------------------------------------
# 15. Harness HARNESS_NAME constants match expected values
# ---------------------------------------------------------------------------


class TestHarnessNameConstants:
    """Each harness constants.py has the correct HARNESS_NAME."""

    @pytest.mark.parametrize(
        "harness,expected_name",
        [
            ("claude_code", "claude-code"),
            ("codex", "codex"),
            ("copilot", "copilot"),
            ("cursor", "cursor"),
            ("gemini", "gemini"),
        ],
    )
    def test_harness_name(self, harness, expected_name):
        mod = importlib.import_module(f"tracing.{harness}.constants")
        assert mod.HARNESS_NAME == expected_name


# ---------------------------------------------------------------------------
# 16. Cross-check: entry points in pyproject.toml match importlib.metadata
# ---------------------------------------------------------------------------


class TestEntryPointConsistency:
    """Entry points declared in pyproject.toml are actually installed."""

    @pytest.fixture(scope="class")
    def pyproject_scripts(self):
        """Parse [project.scripts] from pyproject.toml."""
        content = (REPO_ROOT / "pyproject.toml").read_text()
        scripts = {}
        in_scripts = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "[project.scripts]":
                in_scripts = True
                continue
            if in_scripts and stripped.startswith("["):
                break
            if in_scripts and "=" in stripped and not stripped.startswith("#"):
                name, _, value = stripped.partition("=")
                scripts[name.strip()] = value.strip().strip('"')
        return scripts

    @pytest.fixture(scope="class")
    def installed_scripts(self):
        from importlib.metadata import entry_points

        return {ep.name: ep.value for ep in entry_points(group="console_scripts") if ep.name.startswith("arize-")}

    def test_all_pyproject_scripts_installed(self, pyproject_scripts, installed_scripts):
        for name, value in pyproject_scripts.items():
            assert name in installed_scripts, f"pyproject.toml script {name!r} not in installed metadata"
            assert installed_scripts[name] == value, (
                f"Mismatch for {name}: pyproject.toml={value}, installed={installed_scripts[name]}"
            )

    def test_script_count_matches(self, pyproject_scripts, installed_scripts):
        assert len(pyproject_scripts) == len(installed_scripts), (
            f"Script count mismatch: pyproject.toml has {len(pyproject_scripts)}, "
            f"installed has {len(installed_scripts)}"
        )
