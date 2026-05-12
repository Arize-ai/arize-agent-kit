"""Regression: run-hook must install from the resolved repo root when
plugin pyproject.toml is a symlink."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RUN_HOOK = REPO_ROOT / "tracing" / "claude_code" / "scripts" / "run-hook"


@pytest.fixture
def fake_plugin_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build:

        tmp_path/
          repo/
            pyproject.toml      (real file)
            core/
              __init__.py
            tracing/
              __init__.py
              claude_code/
                pyproject.toml  -> ../../pyproject.toml (symlink)
                scripts/run-hook (copy of the repo's run-hook)
          data/                 (CLAUDE_PLUGIN_DATA)

    Returns (plugin_root, data_dir, pip_log_path).
    """
    repo = tmp_path / "repo"
    (repo / "core").mkdir(parents=True)
    (repo / "core" / "__init__.py").write_text("")
    (repo / "tracing" / "claude_code" / "scripts").mkdir(parents=True)
    (repo / "tracing" / "__init__.py").write_text("")
    (repo / "tracing" / "claude_code" / "__init__.py").write_text("")
    real_pyproject = repo / "pyproject.toml"
    real_pyproject.write_text(
        '[project]\nname="fake"\nversion="0.0.0"\n' '[tool.setuptools.packages.find]\ninclude=["core*","tracing*"]\n'
    )
    plugin_dir = repo / "tracing" / "claude_code"
    (plugin_dir / "pyproject.toml").symlink_to(Path("../../pyproject.toml"))

    # Copy the real run-hook into our fake plugin layout
    shutil.copy(RUN_HOOK, plugin_dir / "scripts" / "run-hook")
    (plugin_dir / "scripts" / "run-hook").chmod(0o755)

    data = tmp_path / "data"
    pip_log = tmp_path / "pip-args.log"
    return plugin_dir, data, pip_log


def _install_stubs(venv_dir: Path, shim_dir: Path, pip_log: Path) -> None:
    """Set up a stub pip in the venv and a python shim that skips `venv` creation.

    The run-hook script runs ``python -m venv "$VENV_DIR"`` which would overwrite
    our stub pip with a real one. We place a python shim earlier on PATH that
    intercepts ``-m venv`` (no-op) but delegates everything else to real python3.
    """
    real_python = shutil.which("python3")
    assert real_python, "python3 must be on PATH to run this test"

    # Stub pip in venv/bin/pip — logs its args to pip_log
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "pip"
    stub.write_text("#!/bin/sh\n" f'echo "$@" >> "{pip_log}"\n' "exit 0\n")
    stub.chmod(0o755)

    # Python shim — intercepts `-m venv` so it doesn't overwrite our stubs
    shim_dir.mkdir(parents=True, exist_ok=True)
    for name in ("python3", "python"):
        py_shim = shim_dir / name
        py_shim.write_text(
            "#!/bin/sh\n"
            '# Intercept "python -m venv" so it does not overwrite stub pip\n'
            'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
            "    exit 0\n"
            "fi\n"
            f'exec "{real_python}" "$@"\n'
        )
        py_shim.chmod(0o755)


def test_runhook_installs_from_resolved_repo_root(fake_plugin_layout, tmp_path, monkeypatch):
    plugin_dir, data_dir, pip_log = fake_plugin_layout

    venv = data_dir / "venv"
    shim_dir = tmp_path / "shims"
    _install_stubs(venv, shim_dir, pip_log)

    data_dir.mkdir(exist_ok=True)

    # Put our shim dir first on PATH so the python shim intercepts venv creation
    real_python_dir = str(Path(shutil.which("python3")).parent)
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_dir)
    env["CLAUDE_PLUGIN_DATA"] = str(data_dir)
    env["PATH"] = f"{shim_dir}:{real_python_dir}:{env['PATH']}"

    result = subprocess.run(
        [str(plugin_dir / "scripts" / "run-hook"), "arize-hook-session-start"],
        input='{"hook_event_name":"SessionStart","session_id":"runhook-symlink-test","cwd":"/tmp"}',
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"run-hook crashed: stderr={result.stderr}"

    # Pip should have been invoked with the RESOLVED repo root, not the plugin dir
    logged = pip_log.read_text().strip() if pip_log.exists() else ""
    repo_root = plugin_dir.parent.parent.resolve()
    assert str(repo_root) in logged, f"pip was invoked with {logged!r} — expected the resolved repo root {repo_root}"
    assert (
        str(plugin_dir) not in logged
    ), f"pip was invoked with the plugin dir {plugin_dir} — should have resolved through the pyproject symlink"
