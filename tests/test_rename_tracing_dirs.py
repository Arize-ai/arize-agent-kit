"""Tests for the *-tracing → *_tracing directory rename (wave 1).

Verifies:
1. Directory structure: underscore dirs exist, hyphenated dirs don't
2. __init__.py files make each dir a valid Python package
3. All four packages and their constants/install submodules are importable
4. importlib shims are fully removed from install.py and core/setup/*.py
5. pyproject.toml packages.find includes the new package names
6. .pre-commit-config.yaml references underscore names
7. install.sh / install.bat map harness names to underscore dirs
8. harness_dir() backwards-compat: prefers underscore, falls back to hyphen
9. core/setup/*.py delegates via direct import, not importlib
10. No stale references to hyphenated dir names in Python source
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

HARNESS_PACKAGES = [
    "tracing.claude_code",
    "tracing.codex",
    "tracing.copilot",
    "tracing.cursor",
]


# ---------------------------------------------------------------------------
# 1. Directory structure
# ---------------------------------------------------------------------------


class TestDirectoryStructure:
    """Underscore directories exist; hyphenated directories do not."""

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_underscore_dir_exists(self, pkg):
        assert (REPO_ROOT / pkg.replace(".", "/")).is_dir(), f"{pkg}/ must exist"

    @pytest.mark.parametrize(
        "old_name",
        ["claude-code-tracing", "codex-tracing", "copilot-tracing", "cursor-tracing"],
    )
    def test_hyphenated_dir_does_not_exist(self, old_name):
        path = REPO_ROOT / old_name
        assert not path.is_dir(), f"Old directory {old_name}/ must not exist"

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_init_py_exists(self, pkg):
        init = REPO_ROOT / pkg.replace(".", "/") / "__init__.py"
        assert init.is_file(), f"{pkg}/__init__.py must exist"

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_constants_py_exists(self, pkg):
        assert (REPO_ROOT / pkg.replace(".", "/") / "constants.py").is_file()

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_install_py_exists(self, pkg):
        assert (REPO_ROOT / pkg.replace(".", "/") / "install.py").is_file()


# ---------------------------------------------------------------------------
# 2. Package importability
# ---------------------------------------------------------------------------


class TestPackageImportability:
    """All four packages and their key submodules are importable."""

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_package_importable(self, pkg):
        mod = importlib.import_module(pkg)
        assert mod is not None

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_constants_importable(self, pkg):
        mod = importlib.import_module(f"{pkg}.constants")
        assert hasattr(mod, "HARNESS_NAME")

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_install_importable(self, pkg):
        mod = importlib.import_module(f"{pkg}.install")
        assert hasattr(mod, "install")

    def test_claude_constants_values(self):
        from tracing.claude_code.constants import DISPLAY_NAME, HARNESS_NAME

        assert HARNESS_NAME == "claude-code"
        assert DISPLAY_NAME == "Claude Code"

    def test_codex_constants_values(self):
        from tracing.codex.constants import DISPLAY_NAME, HARNESS_NAME

        assert HARNESS_NAME == "codex"
        assert DISPLAY_NAME == "Codex CLI"

    def test_copilot_constants_values(self):
        from tracing.copilot.constants import HARNESS_NAME

        assert HARNESS_NAME == "copilot"

    def test_cursor_constants_values(self):
        from tracing.cursor.constants import DISPLAY_NAME, HARNESS_NAME

        assert HARNESS_NAME == "cursor"
        assert DISPLAY_NAME == "Cursor"


# ---------------------------------------------------------------------------
# 3. importlib shims removed
# ---------------------------------------------------------------------------


class TestImportlibShimsRemoved:
    """No install.py or core/setup/*.py uses importlib.util.spec_from_file_location."""

    FILES_TO_CHECK = [
        "tracing/claude_code/install.py",
        "tracing/codex/install.py",
        "tracing/copilot/install.py",
        "tracing/cursor/install.py",
        "core/setup/claude.py",
        "core/setup/codex.py",
        "core/setup/copilot.py",
        "core/setup/cursor.py",
    ]

    @pytest.mark.parametrize("relpath", FILES_TO_CHECK)
    def test_no_spec_from_file_location(self, relpath):
        text = (REPO_ROOT / relpath).read_text()
        assert "spec_from_file_location" not in text, f"{relpath} still uses importlib shim"

    @pytest.mark.parametrize("relpath", FILES_TO_CHECK)
    def test_no_module_from_spec(self, relpath):
        text = (REPO_ROOT / relpath).read_text()
        assert "module_from_spec" not in text, f"{relpath} still uses module_from_spec"

    @pytest.mark.parametrize("relpath", FILES_TO_CHECK)
    def test_no_exec_module(self, relpath):
        text = (REPO_ROOT / relpath).read_text()
        assert "exec_module" not in text, f"{relpath} still uses exec_module"

    def test_claude_install_no_sys_path_insert(self):
        text = (REPO_ROOT / "tracing" / "claude_code" / "install.py").read_text()
        assert "sys.path.insert" not in text

    def test_claude_setup_no_sys_path_insert(self):
        text = (REPO_ROOT / "core" / "setup" / "claude.py").read_text()
        assert "sys.path.insert" not in text


# ---------------------------------------------------------------------------
# 4. Clean absolute imports in install.py files
# ---------------------------------------------------------------------------


class TestAbsoluteImports:
    """Install modules use absolute imports from their package, not relative or shim."""

    def test_claude_install_imports_from_package(self):
        text = (REPO_ROOT / "tracing" / "claude_code" / "install.py").read_text()
        assert "from tracing.claude_code.constants import" in text
        assert (
            "from tracing.claude_code import constants" not in text
            or "from tracing.claude_code.constants import" in text
        )

    def test_codex_install_imports_from_package(self):
        text = (REPO_ROOT / "tracing" / "codex" / "install.py").read_text()
        assert "from tracing.codex.constants import" in text

    def test_copilot_install_imports_from_package(self):
        text = (REPO_ROOT / "tracing" / "copilot" / "install.py").read_text()
        assert "from tracing.copilot.constants import" in text

    def test_cursor_install_imports_from_package(self):
        text = (REPO_ROOT / "tracing" / "cursor" / "install.py").read_text()
        assert "from tracing.cursor.constants import" in text

    def test_codex_install_no_noqa_e402(self):
        """E402 noqa markers should be gone now that importlib block is removed."""
        text = (REPO_ROOT / "tracing" / "codex" / "install.py").read_text()
        assert "noqa: E402" not in text


# ---------------------------------------------------------------------------
# 5. core/setup/*.py delegation via direct import
# ---------------------------------------------------------------------------


class TestSetupDelegation:
    """core/setup/{codex,copilot,cursor}.py use direct imports, not importlib."""

    def test_codex_setup_imports_directly(self):
        text = (REPO_ROOT / "core" / "setup" / "codex.py").read_text()
        assert "from tracing.codex import install as _install_mod" in text
        assert "_load_codex_install" not in text
        assert "_get_codex_mod" not in text

    def test_copilot_setup_imports_directly(self):
        text = (REPO_ROOT / "core" / "setup" / "copilot.py").read_text()
        assert "from tracing.copilot import install as _install_mod" in text
        assert "_load_installer" not in text
        assert "_get_copilot_mod" not in text

    def test_cursor_setup_imports_directly(self):
        text = (REPO_ROOT / "core" / "setup" / "cursor.py").read_text()
        assert "from tracing.cursor import install as _install_mod" in text

    def test_claude_setup_imports_directly(self):
        text = (REPO_ROOT / "core" / "setup" / "claude.py").read_text()
        assert "from tracing.claude_code import install as _install_mod" in text

    def test_codex_setup_install_delegates(self):
        import core.setup.codex as setup_codex

        mock_mod = MagicMock()
        with patch.object(setup_codex, "_install_mod", mock_mod):
            setup_codex.install(with_skills=True)
            mock_mod.install.assert_called_once_with(with_skills=True)

    def test_codex_setup_uninstall_delegates(self):
        import core.setup.codex as setup_codex

        mock_mod = MagicMock()
        with patch.object(setup_codex, "_install_mod", mock_mod):
            setup_codex.uninstall()
            mock_mod.uninstall.assert_called_once()

    def test_copilot_setup_install_delegates(self):
        import core.setup.copilot as setup_copilot

        mock_mod = MagicMock()
        with patch.object(setup_copilot, "_install_mod", mock_mod):
            setup_copilot.install()
            mock_mod.install.assert_called_once()

    def test_copilot_setup_uninstall_delegates(self):
        import core.setup.copilot as setup_copilot

        mock_mod = MagicMock()
        with patch.object(setup_copilot, "_install_mod", mock_mod):
            setup_copilot.uninstall()
            mock_mod.uninstall.assert_called_once()

    def test_cursor_setup_run_delegates(self):
        import core.setup.cursor as setup_cursor

        mock_mod = MagicMock()
        with patch.object(setup_cursor, "_install_mod", mock_mod):
            setup_cursor._run()
            mock_mod.install.assert_called_once_with(with_skills=False)

    def test_claude_setup_run_delegates(self):
        """claude.py._run() delegates to _install_mod.install()."""
        import core.setup.claude as setup_claude

        mock_mod = MagicMock()
        with patch.object(setup_claude, "_install_mod", mock_mod):
            setup_claude._run()
            mock_mod.install.assert_called_once_with(with_skills=False)


# ---------------------------------------------------------------------------
# 6. pyproject.toml
# ---------------------------------------------------------------------------


class TestPyprojectToml:
    """pyproject.toml includes the new package names in packages.find."""

    @pytest.fixture
    def pyproject_text(self):
        return (REPO_ROOT / "pyproject.toml").read_text()

    def test_packages_find_includes_all(self, pyproject_text):
        assert (
            '"tracing*"' in pyproject_text or "tracing*" in pyproject_text
        ), "pyproject.toml packages.find must include tracing*"

    def test_packages_find_includes_core(self, pyproject_text):
        assert "core*" in pyproject_text

    def test_isort_known_first_party(self, pyproject_text):
        assert '"tracing"' in pyproject_text, "isort known_first_party should include tracing"

    def test_entry_points_updated(self, pyproject_text):
        """Entry points reference <harness>_tracing.hooks.* after wave 3."""
        assert "tracing.claude_code.hooks.handlers:session_start" in pyproject_text
        assert "tracing.codex.hooks.handlers:notify" in pyproject_text
        assert "tracing.copilot.hooks.handlers:session_start" in pyproject_text
        assert "tracing.cursor.hooks.handlers:main" in pyproject_text


# ---------------------------------------------------------------------------
# 7. .pre-commit-config.yaml
# ---------------------------------------------------------------------------


class TestPreCommitConfig:
    """Mypy hooks reference underscore package names."""

    @pytest.fixture
    def precommit_text(self):
        return (REPO_ROOT / ".pre-commit-config.yaml").read_text()

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_mypy_hook_references_underscore(self, precommit_text, pkg):
        pkg_path = pkg.replace(".", "/")
        assert f"^{pkg_path}/" in precommit_text, f".pre-commit-config.yaml mypy hook must reference ^{pkg_path}/"

    @pytest.mark.parametrize(
        "old_name",
        ["claude-code-tracing", "codex-tracing", "copilot-tracing", "cursor-tracing"],
    )
    def test_no_hyphenated_references(self, precommit_text, old_name):
        assert f"^{old_name}/" not in precommit_text


# ---------------------------------------------------------------------------
# 8. Shell router scripts
# ---------------------------------------------------------------------------


class TestShellRouterScripts:
    """install.sh and install.bat map harness names to underscore dirs."""

    @pytest.fixture
    def install_sh_text(self):
        return (REPO_ROOT / "install.sh").read_text()

    @pytest.fixture
    def install_bat_text(self):
        return (REPO_ROOT / "install.bat").read_text()

    @pytest.mark.parametrize(
        "harness,expected",
        [
            ("claude", "tracing/claude_code"),
            ("codex", "tracing/codex"),
            ("copilot", "tracing/copilot"),
            ("cursor", "tracing/cursor"),
        ],
    )
    def test_install_sh_mapping(self, install_sh_text, harness, expected):
        assert expected in install_sh_text

    @pytest.mark.parametrize(
        "harness,expected",
        [
            ("claude", "tracing\\claude_code"),
            ("codex", "tracing\\codex"),
            ("copilot", "tracing\\copilot"),
            ("cursor", "tracing\\cursor"),
        ],
    )
    def test_install_bat_mapping(self, install_bat_text, harness, expected):
        assert expected in install_bat_text

    @pytest.mark.parametrize(
        "old_name",
        ["claude-code-tracing", "codex-tracing", "copilot-tracing", "cursor-tracing"],
    )
    def test_install_sh_no_hyphenated(self, install_sh_text, old_name):
        assert old_name not in install_sh_text

    @pytest.mark.parametrize(
        "old_name",
        ["claude-code-tracing", "codex-tracing", "copilot-tracing", "cursor-tracing"],
    )
    def test_install_bat_no_hyphenated(self, install_bat_text, old_name):
        assert old_name not in install_bat_text


# ---------------------------------------------------------------------------
# 9. harness_dir() backwards-compat with old hyphenated names
# ---------------------------------------------------------------------------


class TestHarnessDirBackwardsCompat:
    """harness_dir() prefers underscore dirs but falls back to old hyphenated names."""

    @pytest.fixture
    def fake_install(self, tmp_path, monkeypatch):
        import core.setup as setup_mod

        monkeypatch.setattr(setup_mod, "INSTALL_DIR", tmp_path)
        return tmp_path

    def test_prefers_underscore_primary(self, fake_install):
        from core.setup import harness_dir

        (fake_install / "tracing" / "codex").mkdir(parents=True)
        assert harness_dir("codex") == fake_install / "tracing" / "codex"

    def test_prefers_underscore_over_hyphen(self, fake_install):
        from core.setup import harness_dir

        (fake_install / "tracing" / "codex").mkdir(parents=True)
        (fake_install / "codex-tracing").mkdir()
        # Should prefer underscore
        assert harness_dir("codex") == fake_install / "tracing" / "codex"

    def test_falls_back_to_hyphen_primary(self, fake_install):
        from core.setup import harness_dir

        (fake_install / "codex-tracing").mkdir()
        assert harness_dir("codex") == fake_install / "codex-tracing"

    def test_falls_back_to_hyphen_legacy(self, fake_install):
        from core.setup import harness_dir

        legacy = fake_install / "plugins" / "codex-tracing"
        legacy.mkdir(parents=True)
        assert harness_dir("codex") == legacy

    def test_underscore_legacy_before_hyphen_primary(self, fake_install):
        from core.setup import harness_dir

        (fake_install / "plugins" / "tracing" / "codex").mkdir(parents=True)
        (fake_install / "codex-tracing").mkdir()
        # underscore legacy should be preferred over hyphen primary
        assert harness_dir("codex") == fake_install / "plugins" / "tracing" / "codex"

    def test_default_uses_underscore(self, fake_install):
        from core.setup import harness_dir

        # Nothing exists — default to underscore primary
        result = harness_dir("codex")
        assert result == fake_install / "tracing" / "codex"
        assert "tracing" in result.parts

    def test_claude_code_harness_maps_correctly(self, fake_install):
        from core.setup import harness_dir

        (fake_install / "tracing" / "claude_code").mkdir(parents=True)
        assert harness_dir("claude-code") == fake_install / "tracing" / "claude_code"

    def test_claude_code_default_uses_underscore(self, fake_install):
        from core.setup import harness_dir

        result = harness_dir("claude-code")
        assert result == fake_install / "tracing" / "claude_code"


# ---------------------------------------------------------------------------
# 10. No stale hyphenated references in Python source files
# ---------------------------------------------------------------------------


class TestNoStaleHyphenatedReferences:
    """Python files that were updated should not reference old hyphenated dir names
    in imports or path constructions."""

    SETUP_FILES = [
        "core/setup/claude.py",
        "core/setup/codex.py",
        "core/setup/copilot.py",
        "core/setup/cursor.py",
    ]

    @pytest.mark.parametrize("relpath", SETUP_FILES)
    def test_no_hyphenated_path_construction(self, relpath):
        """Setup files should not construct paths like 'claude-code-tracing'."""
        text = (REPO_ROOT / relpath).read_text()
        for old in ["claude-code-tracing", "codex-tracing", "copilot-tracing", "cursor-tracing"]:
            # Check for string literals containing old dir names (path constructions)
            # but allow them in comments/docstrings only
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    assert (
                        old not in node.value
                    ), f"{relpath} contains string literal with old dir name '{old}': {node.value!r}"

    INSTALL_FILES = [
        "tracing/claude_code/install.py",
        "tracing/codex/install.py",
        "tracing/copilot/install.py",
        "tracing/cursor/install.py",
    ]

    @pytest.mark.parametrize("relpath", INSTALL_FILES)
    def test_install_files_no_hyphenated_imports(self, relpath):
        """Install files should not import from hyphenated module names."""
        text = (REPO_ROOT / relpath).read_text()
        assert (
            "import constants" not in text or "from" in text.split("import constants")[0].split("\n")[-1]
        ), f"{relpath} has bare 'import constants' (should use absolute import)"


# ---------------------------------------------------------------------------
# 11. Verify all install.py files parse cleanly
# ---------------------------------------------------------------------------


class TestInstallFilesSyntax:
    """All install.py files are valid Python that can be parsed by ast."""

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_install_py_parses(self, pkg):
        pkg_path = pkg.replace(".", "/")
        source = (REPO_ROOT / pkg_path / "install.py").read_text()
        tree = ast.parse(source, filename=f"{pkg_path}/install.py")
        assert tree is not None

    @pytest.mark.parametrize("pkg", HARNESS_PACKAGES)
    def test_constants_py_parses(self, pkg):
        pkg_path = pkg.replace(".", "/")
        source = (REPO_ROOT / pkg_path / "constants.py").read_text()
        tree = ast.parse(source, filename=f"{pkg_path}/constants.py")
        assert tree is not None
