#!/usr/bin/env python3
"""Arize Agent Kit — Cross-platform installer.

Usage:
    curl -sSL .../install.py | python3 - claude
    python3 install.py claude    # install claude-code harness
    python3 install.py codex     # install codex harness
    python3 install.py cursor    # install cursor harness
    python3 install.py update    # update existing installation
    python3 install.py uninstall # uninstall (prompts for confirmation)

Installs the arize-agent-kit repo, sets up the shared background collector/exporter,
and configures tracing for the specified harness.
Idempotent — safe to run multiple times.
"""

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import urllib.request
from pathlib import Path

# --- Constants (duplicated from core/constants.py since core isn't installed yet) ---
INSTALL_DIR = Path.home() / ".arize" / "harness"
CONFIG_FILE = INSTALL_DIR / "config.yaml"
VENV_DIR = INSTALL_DIR / "venv"
BIN_DIR = INSTALL_DIR / "bin"
PID_DIR = INSTALL_DIR / "run"
PID_FILE = PID_DIR / "collector.pid"
LOG_DIR = INSTALL_DIR / "logs"
COLLECTOR_LOG_FILE = LOG_DIR / "collector.log"
COLLECTOR_BIN = BIN_DIR / "arize-collector"
STATE_BASE_DIR = INSTALL_DIR / "state"

REPO_URL = "https://github.com/Arize-ai/arize-agent-kit.git"
INSTALL_BRANCH = os.environ.get("ARIZE_INSTALL_BRANCH", "main")
TARBALL_URL = (
    f"https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/{INSTALL_BRANCH}.tar.gz"
)

# Hook entry point names (match pyproject.toml [project.scripts])
CLAUDE_HOOK_EVENTS = {
    "SessionStart": "arize-hook-session-start",
    "UserPromptSubmit": "arize-hook-user-prompt-submit",
    "PreToolUse": "arize-hook-pre-tool-use",
    "PostToolUse": "arize-hook-post-tool-use",
    "Stop": "arize-hook-stop",
    "SubagentStop": "arize-hook-subagent-stop",
    "Notification": "arize-hook-notification",
    "PermissionRequest": "arize-hook-permission-request",
    "SessionEnd": "arize-hook-session-end",
}

CURSOR_HOOK_EVENTS = [
    "beforeSubmitPrompt",
    "afterAgentResponse",
    "afterAgentThought",
    "beforeShellExecution",
    "afterShellExecution",
    "beforeMCPExecution",
    "afterMCPExecution",
    "beforeReadFile",
    "afterFileEdit",
    "stop",
    "beforeTabFileRead",
    "afterTabFileEdit",
]

ARIZE_ENV_KEYS = [
    "ARIZE_TRACE_ENABLED",
    "PHOENIX_ENDPOINT",
    "PHOENIX_API_KEY",
    "ARIZE_API_KEY",
    "ARIZE_SPACE_ID",
    "ARIZE_OTLP_ENDPOINT",
    "ARIZE_PROJECT_NAME",
    "ARIZE_USER_ID",
    "ARIZE_DRY_RUN",
    "ARIZE_VERBOSE",
    "ARIZE_LOG_FILE",
]


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def _supports_color():
    """Check if the terminal supports ANSI color codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.name == "nt":
        return os.environ.get("TERM") == "xterm" or "WT_SESSION" in os.environ
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_USE_COLOR = _supports_color()


def colorize(code, text):
    if _USE_COLOR:
        return f"\033[{code}m{text}\033[0m"
    return text


def info(msg):
    print(f"{colorize('0;32', '[arize]')} {msg}")


def warn(msg):
    print(f"{colorize('1;33', '[arize]')} {msg}")


def err(msg):
    print(f"{colorize('0;31', '[arize]')} {msg}", file=sys.stderr)


def header(msg):
    print(f"\n{colorize('1;34', msg)}\n")


def confirm(prompt, default="n"):
    """Prompt for yes/no confirmation. Returns True for yes."""
    reply = _tty_input(prompt).strip()
    if not reply:
        return default.lower().startswith("y")
    return reply.lower().startswith("y")


def _tty_input(prompt):
    """Read input from the user, trying /dev/tty if stdin is piped."""
    if sys.stdin.isatty():
        return input(prompt)
    # Try /dev/tty for curl | python3 scenarios
    try:
        tty = open("/dev/tty", "r")
        sys.stdout.write(prompt)
        sys.stdout.flush()
        line = tty.readline().rstrip("\n")
        tty.close()
        return line
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Python discovery
# ---------------------------------------------------------------------------

def find_python():
    """Find a working Python >=3.9 interpreter. Returns path or None."""
    candidates = ["python3", "python"]
    # Common absolute paths
    candidates += [
        "/usr/bin/python3",
        "/usr/local/bin/python3",
        str(Path.home() / ".local" / "bin" / "python3"),
    ]
    # pyenv
    pyenv_shim = Path.home() / ".pyenv" / "shims" / "python3"
    if pyenv_shim.exists():
        candidates.append(str(pyenv_shim))
    # Homebrew (macOS)
    brew_python = Path("/opt/homebrew/bin/python3")
    if brew_python.exists():
        candidates.append(str(brew_python))
    # Conda
    try:
        result = subprocess.run(
            ["conda", "info", "--base"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            candidates.append(str(Path(result.stdout.strip()) / "bin" / "python3"))
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    for candidate in candidates:
        resolved = shutil.which(candidate) if not os.path.isabs(candidate) else candidate
        if not resolved or not os.path.isfile(resolved):
            continue
        try:
            result = subprocess.run(
                [resolved, "-c", "import sys; assert sys.version_info >= (3, 9)"],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                return resolved
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return None


# ---------------------------------------------------------------------------
# Venv python helpers
# ---------------------------------------------------------------------------

def _venv_python():
    """Return the path to the venv python executable, or None."""
    for candidate in [VENV_DIR / "bin" / "python", VENV_DIR / "Scripts" / "python.exe"]:
        if candidate.is_file():
            return str(candidate)
    return None


def _venv_bin(name):
    """Return the full path to a CLI entry point in the venv."""
    if os.name == "nt":
        return str(VENV_DIR / "Scripts" / f"{name}.exe")
    return str(VENV_DIR / "bin" / name)


def _venv_pip():
    """Return the path to pip in the venv."""
    for candidate in [VENV_DIR / "bin" / "pip", VENV_DIR / "Scripts" / "pip.exe"]:
        if candidate.is_file():
            return str(candidate)
    return None


# ---------------------------------------------------------------------------
# Config helpers (minimal — no yaml import at top level)
# ---------------------------------------------------------------------------

def _load_yaml():
    """Import yaml from the venv or system. Returns the module or None."""
    try:
        import yaml
        return yaml
    except ImportError:
        pass
    # Try venv python — add its site-packages temporarily
    vp = _venv_python()
    if vp:
        try:
            result = subprocess.run(
                [vp, "-c", "import yaml; print(yaml.__file__)"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                yaml_dir = str(Path(result.stdout.strip()).parent)
                sys.path.insert(0, yaml_dir)
                try:
                    import yaml
                    return yaml
                except ImportError:
                    # Import failed — clean up the path we added
                    try:
                        sys.path.remove(yaml_dir)
                    except ValueError:
                        pass
        except subprocess.SubprocessError:
            pass
    return None


def _cfg_get(key):
    """Get a dotted config key value. Returns string or empty string."""
    vp = _venv_python()
    if not vp or not CONFIG_FILE.is_file():
        return ""
    try:
        result = subprocess.run(
            [vp, str(INSTALL_DIR / "core" / "config.py"), "get", key],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except subprocess.SubprocessError:
        return ""


def _cfg_set(key, value):
    """Set a dotted config key value."""
    vp = _venv_python()
    if not vp:
        return
    try:
        subprocess.run(
            [vp, str(INSTALL_DIR / "core" / "config.py"), "set", key, str(value)],
            capture_output=True, timeout=5,
        )
    except subprocess.SubprocessError:
        pass


def _cfg_delete(key):
    """Delete a dotted config key."""
    vp = _venv_python()
    if not vp:
        return
    try:
        subprocess.run(
            [vp, str(INSTALL_DIR / "core" / "config.py"), "delete", key],
            capture_output=True, timeout=5,
        )
    except subprocess.SubprocessError:
        pass


# ---------------------------------------------------------------------------
# Repository download
# ---------------------------------------------------------------------------

def install_repo(branch=None, tarball_url=None):
    """Clone the repo or download tarball into INSTALL_DIR."""
    branch = branch or INSTALL_BRANCH
    tarball_url = tarball_url or TARBALL_URL
    git_dir = INSTALL_DIR / ".git"

    if git_dir.is_dir():
        info(f"Repository already installed at {INSTALL_DIR}")
        info("Pulling latest changes...")
        try:
            subprocess.run(
                ["git", "-C", str(INSTALL_DIR), "pull", "--ff-only"],
                capture_output=True, check=True, timeout=60,
            )
            return
        except (subprocess.SubprocessError, FileNotFoundError):
            warn("git pull failed — re-cloning")
            shutil.rmtree(INSTALL_DIR, ignore_errors=True)

    if INSTALL_DIR.is_dir() and not git_dir.is_dir():
        info("Existing non-git install found — removing for fresh clone")
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)

    if shutil.which("git"):
        info("Cloning arize-agent-kit...")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch,
                 REPO_URL, str(INSTALL_DIR)],
                capture_output=True, check=True, timeout=120,
            )
            return
        except (subprocess.SubprocessError, FileNotFoundError):
            warn("git clone failed — falling back to tarball")

    _install_repo_tarball(tarball_url)


def _install_repo_tarball(tarball_url=None):
    """Download and extract the repo tarball."""
    tarball_url = tarball_url or TARBALL_URL
    info("Downloading arize-agent-kit tarball...")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz")
    try:
        os.close(tmp_fd)
        urllib.request.urlretrieve(tarball_url, tmp_path)
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tmp_path, "r:gz") as tf:
            # Strip the top-level directory (arize-agent-kit-main/)
            members = tf.getmembers()
            prefix = ""
            if members:
                prefix = members[0].name.split("/")[0] + "/"
            for member in members:
                if member.name == prefix.rstrip("/"):
                    continue
                member.name = member.name[len(prefix):]
                if not member.name:
                    continue
                # Guard against path traversal (CVE-2007-4559)
                resolved = (INSTALL_DIR / member.name).resolve()
                if not str(resolved).startswith(str(INSTALL_DIR.resolve())):
                    warn(f"Skipping suspicious tarball member: {member.name}")
                    continue
                tf.extract(member, INSTALL_DIR)
        info(f"Extracted to {INSTALL_DIR}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Venv setup
# ---------------------------------------------------------------------------

def setup_venv(python_cmd, backend_target):
    """Create an isolated venv and install the package.

    Installs core + pyyaml via ``pip install .``, plus gRPC deps for Arize AX.
    Idempotent: skips if venv already has required packages.
    """
    # Check if existing venv is already good
    vp = _venv_python()
    if vp:
        check_cmd = "import yaml"
        if backend_target == "arize":
            check_cmd = "import yaml; import grpc; import opentelemetry"
        try:
            r = subprocess.run([vp, "-c", check_cmd], capture_output=True, timeout=10)
            if r.returncode == 0:
                info("Collector venv already has required packages")
                return True
        except subprocess.SubprocessError:
            pass

    info("Creating collector venv...")
    try:
        subprocess.run(
            [python_cmd, "-m", "venv", str(VENV_DIR)],
            capture_output=True, check=True, timeout=60,
        )
    except subprocess.SubprocessError as e:
        err(f"Failed to create venv with {python_cmd}")
        err("You may need to install the venv module: apt install python3-venv (Debian/Ubuntu)")
        return False

    pip = _venv_pip()
    if not pip:
        err("pip not found in venv")
        return False

    # Install the package (core + pyyaml + CLI entry points)
    info("Installing arize-agent-kit into collector venv...")
    try:
        subprocess.run(
            [pip, "install", "--quiet", str(INSTALL_DIR)],
            capture_output=True, check=True, timeout=300,
        )
    except subprocess.SubprocessError:
        err("Failed to install arize-agent-kit package")
        return False

    # Install Arize AX extras if needed
    if backend_target == "arize":
        info("Installing Arize AX dependencies (opentelemetry-proto, grpcio)...")
        try:
            subprocess.run(
                [pip, "install", "--quiet", "opentelemetry-proto", "grpcio"],
                capture_output=True, check=True, timeout=300,
            )
        except subprocess.SubprocessError:
            warn("Failed to install Arize AX dependencies — gRPC export may not work")

    info(f"Collector venv ready at {VENV_DIR}")
    return True


# ---------------------------------------------------------------------------
# Config writing
# ---------------------------------------------------------------------------

def write_config(backend_target, credentials, harness_name, collector_port=4318):
    """Write the shared config.yaml.

    If config already exists, only adds the harness entry.
    """
    yaml = _load_yaml()

    if CONFIG_FILE.is_file() and yaml:
        # Existing config — just add harness
        try:
            with open(CONFIG_FILE) as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            config = {}
        if harness_name:
            config.setdefault("harnesses", {})[harness_name] = {
                "project_name": harness_name,
            }
            fd = os.open(str(CONFIG_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
            info(f"Added harness '{harness_name}' to {CONFIG_FILE}")
        return

    # Fresh config — write full YAML
    config = {
        "collector": {
            "host": "127.0.0.1",
            "port": collector_port,
        },
        "backend": {
            "target": backend_target,
            "phoenix": {
                "endpoint": credentials.get("phoenix_endpoint", "http://localhost:6006"),
                "api_key": credentials.get("phoenix_api_key", ""),
            },
            "arize": {
                "endpoint": credentials.get("arize_endpoint", "otlp.arize.com:443"),
                "api_key": credentials.get("arize_api_key", ""),
                "space_id": credentials.get("arize_space_id", ""),
            },
        },
        "harnesses": {},
    }
    if harness_name:
        config["harnesses"][harness_name] = {"project_name": harness_name}

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    if yaml:
        fd = os.open(str(CONFIG_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    else:
        # Fallback: write YAML manually (no pyyaml available yet)
        lines = [
            f'collector:',
            f'  host: "127.0.0.1"',
            f'  port: {collector_port}',
            f'backend:',
            f'  target: "{backend_target}"',
            f'  phoenix:',
            f'    endpoint: "{credentials.get("phoenix_endpoint", "http://localhost:6006")}"',
            f'    api_key: "{credentials.get("phoenix_api_key", "")}"',
            f'  arize:',
            f'    endpoint: "{credentials.get("arize_endpoint", "otlp.arize.com:443")}"',
            f'    api_key: "{credentials.get("arize_api_key", "")}"',
            f'    space_id: "{credentials.get("arize_space_id", "")}"',
            f'harnesses:',
        ]
        if harness_name:
            lines.append(f'  {harness_name}:')
            lines.append(f'    project_name: "{harness_name}"')
        # When no harness, 'harnesses:' on its own line is valid YAML for empty mapping
        fd = os.open(str(CONFIG_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")

    info(f"Wrote shared config to {CONFIG_FILE} (backend={backend_target}, harness={harness_name or 'none'})")


# ---------------------------------------------------------------------------
# Collector lifecycle
# ---------------------------------------------------------------------------

def _is_process_alive(pid):
    """Check if a process is alive."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except (AttributeError, OSError):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _health_check(host="127.0.0.1", port=4318, timeout=2.0):
    """Return True if the collector health endpoint responds."""
    try:
        url = f"http://{host}:{port}/health"
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def stop_collector():
    """Stop the collector process."""
    if not PID_FILE.is_file():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return

    if _is_process_alive(pid):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=5)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        # Wait for exit
        for _ in range(50):
            time.sleep(0.1)
            if not _is_process_alive(pid):
                break

    try:
        PID_FILE.unlink()
    except OSError:
        pass


def start_collector():
    """Start the collector using collector_ctl entry point or direct python."""
    collector_port = 4318
    port_str = _cfg_get("collector.port")
    if port_str:
        try:
            collector_port = int(port_str)
        except ValueError:
            pass

    # Check if already running
    if _health_check(port=collector_port):
        info("Shared collector is already running")
        return True

    # Clean stale PID file
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text().strip())
            if not _is_process_alive(pid):
                PID_FILE.unlink()
        except (ValueError, OSError):
            try:
                PID_FILE.unlink()
            except OSError:
                pass

    # Try the venv entry point first
    ctl = _venv_bin("arize-collector-ctl")
    if Path(ctl).is_file():
        try:
            result = subprocess.run(
                [ctl, "start"], capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                info(f"Shared collector started (listening on 127.0.0.1:{collector_port})")
                return True
        except subprocess.SubprocessError:
            pass

    # Fallback: launch collector.py directly
    collector_py = INSTALL_DIR / "core" / "collector.py"
    vp = _venv_python()
    if not vp or not collector_py.is_file():
        warn("Could not find collector runtime — collector will not start")
        return False

    PID_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    info("Starting shared collector...")
    log_fd = open(COLLECTOR_LOG_FILE, "a")
    try:
        kwargs = {"stdout": log_fd, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([vp, str(collector_py)], **kwargs)
    except Exception as e:
        err(f"Failed to launch collector: {e}")
        log_fd.close()
        return False
    log_fd.close()

    # Wait for health
    for _ in range(30):
        time.sleep(0.1)
        if _health_check(port=collector_port):
            info(f"Shared collector started (listening on 127.0.0.1:{collector_port})")
            return True

    if _is_process_alive(proc.pid):
        warn("Collector did not become healthy within 3 seconds")
        warn(f"Check logs at {COLLECTOR_LOG_FILE} for details")
        return True

    warn("Failed to start collector (process exited)")
    return False


# ---------------------------------------------------------------------------
# Collector launcher script
# ---------------------------------------------------------------------------

def write_collector_launcher(python_cmd):
    """Write a Python launcher script for the collector.

    Uses a Python shebang instead of bash, so no shell dependency is needed.
    """
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    launcher_python = _venv_python() or python_cmd
    collector_src = INSTALL_DIR / "core" / "collector.py"

    if os.name == "nt":
        launcher = COLLECTOR_BIN.with_suffix(".cmd")
        launcher.write_text(
            f'@echo off\r\n"{launcher_python}" "{collector_src}" %*\r\n'
        )
    else:
        COLLECTOR_BIN.write_text(
            f"#!{launcher_python}\n"
            f"# Arize Agent Kit — shared collector launcher\n"
            f"# Auto-generated by install.py. Do not edit manually.\n"
            f"import runpy, sys\n"
            f'sys.argv[0] = {str(collector_src)!r}\n'
            f'runpy.run_path({str(collector_src)!r}, run_name="__main__")\n'
        )
        COLLECTOR_BIN.chmod(0o755)

    info(f"Installed collector launcher at {COLLECTOR_BIN}")


# ---------------------------------------------------------------------------
# Backend credential collection
# ---------------------------------------------------------------------------

def collect_backend_credentials():
    """Interactively collect backend configuration.

    Returns (backend_target, credentials, collector_port).
    """
    phoenix_endpoint = "http://localhost:6006"
    phoenix_api_key = ""
    arize_api_key = ""
    arize_space_id = ""
    arize_endpoint = "otlp.arize.com:443"
    collector_port = 4318
    backend_target = ""

    # Detect from environment
    if os.environ.get("ARIZE_API_KEY") and os.environ.get("ARIZE_SPACE_ID"):
        backend_target = "arize"
        arize_api_key = os.environ["ARIZE_API_KEY"]
        arize_space_id = os.environ["ARIZE_SPACE_ID"]
        if os.environ.get("ARIZE_OTLP_ENDPOINT"):
            arize_endpoint = os.environ["ARIZE_OTLP_ENDPOINT"]
    elif os.environ.get("PHOENIX_ENDPOINT"):
        backend_target = "phoenix"
        phoenix_endpoint = os.environ["PHOENIX_ENDPOINT"]
        if os.environ.get("PHOENIX_API_KEY"):
            phoenix_api_key = os.environ["PHOENIX_API_KEY"]

    # Interactive prompt if not detected
    can_prompt = sys.stdin.isatty() or _can_open_tty()
    if not backend_target and can_prompt:
        print()
        print("  Choose a tracing backend:")
        print()
        print("    1) Phoenix (self-hosted)")
        print("    2) Arize AX (cloud)")
        print()
        choice = _tty_input("  Backend [1/2]: ").strip()
        if choice in ("1", "phoenix"):
            backend_target = "phoenix"
            ep = _tty_input(f"  Phoenix endpoint [{phoenix_endpoint}]: ").strip()
            if ep:
                phoenix_endpoint = ep
            phoenix_api_key = _tty_input("  Phoenix API key (blank if none): ").strip()
        elif choice in ("2", "arize"):
            backend_target = "arize"
            arize_api_key = _tty_input("  Arize API key: ").strip()
            if not arize_api_key:
                err("Arize API key is required")
                sys.exit(1)
            arize_space_id = _tty_input("  Arize space ID: ").strip()
            if not arize_space_id:
                err("Arize space ID is required")
                sys.exit(1)
            ep = _tty_input(f"  Arize OTLP endpoint [{arize_endpoint}]: ").strip()
            if ep:
                arize_endpoint = ep
        else:
            err(f"Invalid choice: {choice}")
            sys.exit(1)

        print()
        port_str = _tty_input(f"  Collector port [{collector_port}]: ").strip()
        if port_str:
            try:
                collector_port = int(port_str)
            except ValueError:
                warn(f"Invalid port '{port_str}', using default {collector_port}")

    # Non-interactive fallback
    if not backend_target:
        if not can_prompt:
            print()
            warn("No backend credentials detected and no interactive terminal available.")
            warn("To configure Arize AX, re-run with env vars:")
            warn("  ARIZE_API_KEY=... ARIZE_SPACE_ID=... python3 install.py claude")
            warn(f"Defaulting to Phoenix at {phoenix_endpoint}")
            print()
        backend_target = "phoenix"
        info(f"Backend: Phoenix at {phoenix_endpoint}")

    credentials = {
        "phoenix_endpoint": phoenix_endpoint,
        "phoenix_api_key": phoenix_api_key,
        "arize_api_key": arize_api_key,
        "arize_space_id": arize_space_id,
        "arize_endpoint": arize_endpoint,
    }
    return backend_target, credentials, collector_port


def _can_open_tty():
    """Check if /dev/tty is available for interactive input."""
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
        os.close(fd)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Shared collector setup (orchestrates venv, config, launcher, start)
# ---------------------------------------------------------------------------

def setup_shared_collector(harness_name):
    """Set up the shared background collector for the given harness."""
    header("Setting up shared background collector")

    # Ensure directories
    for d in [BIN_DIR, PID_DIR, LOG_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Check for existing backend config
    existing_backend = ""
    if CONFIG_FILE.is_file():
        existing_backend = _cfg_get("backend.target")
        if not existing_backend:
            # Peek at YAML with regex (venv may not exist yet)
            try:
                text = CONFIG_FILE.read_text()
                m = re.search(r"target:\s*[\"']?(\w+)", text)
                if m:
                    existing_backend = m.group(1)
            except OSError:
                pass

    if existing_backend:
        backend_target = existing_backend
        credentials = {}
        collector_port = 4318
        info(f"Existing backend config found ({existing_backend}) — adding harness entry")
    else:
        backend_target, credentials, collector_port = collect_backend_credentials()

    # Find Python
    python_cmd = find_python()
    if not python_cmd:
        warn("No Python 3.9+ interpreter found")
        warn("Install Python 3 and re-run the installer to start the collector")
        # Still write config if needed
        if not existing_backend:
            write_config(backend_target, credentials, harness_name, collector_port)
        return backend_target
    info(f"Found Python: {python_cmd}")

    # Check collector source exists
    collector_src = INSTALL_DIR / "core" / "collector.py"
    if not collector_src.is_file():
        warn(f"Collector source not found at {collector_src} — collector will not start")
        if not existing_backend:
            write_config(backend_target, credentials, harness_name, collector_port)
        return backend_target

    # Set up venv
    if not setup_venv(python_cmd, backend_target):
        warn("Collector venv setup failed — config.py and Arize AX export may not work")

    # Write/update config
    if existing_backend:
        # Just add harness entry via config.py
        if harness_name:
            vp = _venv_python()
            if vp:
                _cfg_set(f"harnesses.{harness_name}.project_name", harness_name)
                info(f"Added harness '{harness_name}' to {CONFIG_FILE}")
            else:
                warn(f"Could not add harness '{harness_name}' to config — venv not available")
    else:
        write_config(backend_target, credentials, harness_name, collector_port)

    # Write launcher and start
    write_collector_launcher(python_cmd)
    start_collector()
    return backend_target


# ---------------------------------------------------------------------------
# Claude Code harness setup
# ---------------------------------------------------------------------------

def setup_claude():
    """Configure tracing hooks for Claude Code."""
    header("Setting up Arize tracing for Claude Code")

    plugin_dir = INSTALL_DIR / "claude-code-tracing"
    if not plugin_dir.is_dir():
        plugin_dir = INSTALL_DIR / "plugins" / "claude-code-tracing"
    if not plugin_dir.is_dir():
        err(f"Claude Code tracing plugin not found in {INSTALL_DIR}")
        sys.exit(1)
    info(f"Plugin installed at: {plugin_dir}")

    # --- Write hooks to ~/.claude/settings.json ---
    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_file = claude_dir / "settings.json"

    if settings_file.is_file():
        try:
            settings = json.loads(settings_file.read_text())
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        settings = {}

    # Add plugin reference
    plugins = settings.setdefault("plugins", [])
    plugin_path_str = str(plugin_dir)
    has_plugin = any(
        (isinstance(p, str) and p == plugin_path_str)
        or (isinstance(p, dict) and p.get("path") == plugin_path_str)
        for p in plugins
    )
    if not has_plugin:
        plugins.append({"type": "local", "path": plugin_path_str})
        info(f"Added plugin to {settings_file}")
    else:
        info(f"Plugin already registered in {settings_file}")

    # Write hooks — use venv entry point paths
    hooks = settings.setdefault("hooks", {})
    for event, entry_point in CLAUDE_HOOK_EVENTS.items():
        hook_cmd = _venv_bin(entry_point)
        event_hooks = hooks.setdefault(event, [])
        # Check if already registered
        already = False
        for entry in event_hooks:
            for h in entry.get("hooks", []):
                if h.get("command", "") == hook_cmd:
                    already = True
                    break
            if already:
                break
        if not already:
            event_hooks.append({"hooks": [{"type": "command", "command": hook_cmd}]})

    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    info(f"Registered tracing hooks in {settings_file}")

    # Summary
    print()
    print(f"  Claude Agent SDK:")
    print()
    print("    Pass the plugin path when launching your agent:")
    print()
    print("      import {{ Agent }} from '@anthropic-ai/agent-sdk';")
    print()
    print("      const agent = new Agent({{")
    print(f"        plugins: ['{plugin_dir}'],")
    print("        // ... other options")
    print("      }});")
    print()
    print(f"  Tracing:")
    print()
    print("    The shared background collector is already running and will export")
    print("    spans to your configured backend automatically.")
    print()
    print(f"    View collector logs:     tail -f {COLLECTOR_LOG_FILE}")
    print()
    info("Setup complete! Test with: ARIZE_DRY_RUN=true claude")


# ---------------------------------------------------------------------------
# Cursor harness setup
# ---------------------------------------------------------------------------

def setup_cursor():
    """Configure tracing hooks for Cursor IDE."""
    header("Setting up Arize tracing for Cursor IDE")

    plugin_dir = INSTALL_DIR / "cursor-tracing"
    if not plugin_dir.is_dir():
        plugin_dir = INSTALL_DIR / "plugins" / "cursor-tracing"
    if not plugin_dir.is_dir():
        err(f"Cursor tracing plugin not found in {INSTALL_DIR}")
        sys.exit(1)
    info(f"Plugin installed at: {plugin_dir}")

    cursor_dir = Path.home() / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    state_dir = STATE_BASE_DIR / "cursor"
    state_dir.mkdir(parents=True, exist_ok=True)

    hooks_file = cursor_dir / "hooks.json"
    hook_cmd = _venv_bin("arize-hook-cursor")

    if hooks_file.is_file():
        try:
            hooks_data = json.loads(hooks_file.read_text())
        except (json.JSONDecodeError, OSError):
            hooks_data = {"version": 1, "hooks": {}}
        # Backup
        backup = hooks_file.with_suffix(".json.bak")
        shutil.copy2(hooks_file, backup)
    else:
        hooks_data = {"version": 1, "hooks": {}}

    hooks = hooks_data.setdefault("hooks", {})
    for event in CURSOR_HOOK_EVENTS:
        event_list = hooks.setdefault(event, [])
        if not any(h.get("command") == hook_cmd for h in event_list):
            event_list.append({"command": hook_cmd})

    hooks_file.write_text(json.dumps(hooks_data, indent=2) + "\n")
    info(f"{'Merged Arize hooks into' if hooks_file.exists() else 'Created'} {hooks_file}")

    # Read collector port
    collector_port = _cfg_get("collector.port") or "4318"

    print()
    print("  Cursor tracing setup complete!")
    print()
    print("  What was configured:")
    print()
    print(f"    - Cursor hooks.json at {hooks_file}")
    print(f"      (12 hook events routing to {hook_cmd})")
    print(f"    - State directory at {state_dir}")
    print()
    print("  Next steps:")
    print()
    print("    1. Restart Cursor IDE to pick up the new hooks")
    print("    2. Start a conversation — spans will appear in your configured backend")
    print()
    info("Setup complete!")


# ---------------------------------------------------------------------------
# Codex harness setup
# ---------------------------------------------------------------------------

def _detect_shell_profile():
    """Find the user's active shell profile."""
    for name in [".zshrc", ".bashrc", ".bash_profile"]:
        path = Path.home() / name
        if path.is_file():
            return path
    return None


def _discover_real_codex():
    """Find the actual codex binary (not our proxy)."""
    proxy_path = Path.home() / ".local" / "bin" / "codex"
    current = shutil.which("codex")
    if not current:
        return None
    if str(Path(current).resolve()) == str(proxy_path.resolve()) and proxy_path.is_file():
        # Read the REAL_CODEX path from the proxy script
        try:
            text = proxy_path.read_text()
            m = re.search(r'^REAL_CODEX="([^"]*)"', text, re.MULTILINE)
            if m:
                current = m.group(1)
        except OSError:
            return None
    if current and os.path.isfile(current) and os.access(current, os.X_OK):
        return current
    return None


def setup_codex():
    """Configure tracing for Codex CLI."""
    header("Setting up Arize tracing for Codex CLI")

    plugin_dir = INSTALL_DIR / "codex-tracing"
    if not plugin_dir.is_dir():
        plugin_dir = INSTALL_DIR / "plugins" / "codex-tracing"
    if not plugin_dir.is_dir():
        err(f"Codex tracing plugin not found in {INSTALL_DIR}")
        sys.exit(1)
    info(f"Plugin installed at: {plugin_dir}")

    codex_config_dir = Path.home() / ".codex"
    codex_config = codex_config_dir / "config.toml"
    env_file = codex_config_dir / "arize-env.sh"
    notify_cmd = _venv_bin("arize-hook-codex-notify")

    codex_config_dir.mkdir(parents=True, exist_ok=True)
    if not codex_config.is_file():
        codex_config.touch()

    # --- 1. Configure notify hook ---
    notify_line = f'notify = ["{notify_cmd}"]'
    config_text = codex_config.read_text()

    if re.search(r"^notify\s*=", config_text, re.MULTILINE):
        config_text = re.sub(r"^notify\s*=.*$", notify_line, config_text, flags=re.MULTILINE)
        codex_config.write_text(config_text)
        info("Updated existing notify hook in config.toml")
    else:
        # Find first section header to insert before
        section_match = re.search(r"^\[", config_text, re.MULTILINE)
        if section_match:
            pos = section_match.start()
            config_text = (
                config_text[:pos]
                + f"\n# Arize tracing — OpenInference spans per turn\n{notify_line}\n\n"
                + config_text[pos:]
            )
            codex_config.write_text(config_text)
        else:
            with open(codex_config, "a") as f:
                f.write(f"\n# Arize tracing — OpenInference spans per turn\n{notify_line}\n")
        info("Added notify hook to config.toml")

    # --- 2. Write env file template ---
    if not env_file.is_file():
        fd = os.open(str(env_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(textwrap.dedent("""\
                # Arize Codex tracing environment
                # Source this file in your shell profile or export vars before running codex.
                #
                # Uncomment and set the variables for your backend:

                # Common
                export ARIZE_TRACE_ENABLED=true
                # export ARIZE_PROJECT_NAME=codex
                # export ARIZE_USER_ID=

                # Phoenix (self-hosted)
                # export PHOENIX_ENDPOINT=http://localhost:6006

                # Arize AX (cloud)
                # export ARIZE_API_KEY=
                # export ARIZE_SPACE_ID=
            """))
        info(f"Created env file template at {env_file}")
    else:
        info(f"Env file already exists at {env_file}")

    # --- 3. Configure OTLP exporter in config.toml ---
    collector_port = _cfg_get("collector.port") or "4318"

    config_text = codex_config.read_text()

    # Remove old [otel] section if present
    config_text = re.sub(
        r"\n*# Arize shared collector[^\n]*\n\[otel\].*?(?=\n\[[^\]o]|\Z)",
        "",
        config_text,
        flags=re.DOTALL,
    )
    # Also remove bare [otel] sections
    config_text = re.sub(
        r"\n*\[otel\].*?(?=\n\[[^\]o]|\Z)",
        "",
        config_text,
        flags=re.DOTALL,
    )

    # Add new [otel] section
    config_text += textwrap.dedent(f"""

        # Arize shared collector -- captures Codex events for rich span trees
        [otel]
        [otel.exporter.otlp-http]
        endpoint = "http://127.0.0.1:{collector_port}/v1/logs"
        protocol = "json"
    """).lstrip("\n")
    codex_config.write_text(config_text)
    info(f"Added [otel] exporter pointing to shared collector (port {collector_port})")

    # --- 4. Install codex proxy wrapper ---
    proxy_dir = Path.home() / ".local" / "bin"
    proxy_path = proxy_dir / "codex"
    proxy_backup = proxy_dir / "codex.arize-backup"
    proxy_template = plugin_dir / "scripts" / "codex_proxy.sh"

    real_codex_bin = _discover_real_codex()
    if not real_codex_bin:
        warn("Could not find codex binary — skipping proxy install")
    else:
        proxy_dir.mkdir(parents=True, exist_ok=True)
        if proxy_path.is_file():
            try:
                text = proxy_path.read_text()
                if "ARIZE_CODEX_PROXY" not in text:
                    shutil.copy2(proxy_path, proxy_backup)
                    info(f"Backed up existing {proxy_path} to {proxy_backup}")
            except OSError:
                pass

        if proxy_template.is_file():
            template = proxy_template.read_text()
            template = template.replace("__REAL_CODEX__", real_codex_bin)
            template = template.replace("__ARIZE_ENV_FILE__", str(env_file))
            template = template.replace(
                "__SHARED_COLLECTOR_CTL__",
                _venv_bin("arize-collector-ctl"),
            )
            proxy_path.write_text(template)
            proxy_path.chmod(0o755)
            info(f"Installed codex proxy to {proxy_path}")
        else:
            # No template — install Python proxy if available
            py_proxy = _venv_bin("arize-codex-proxy")
            if Path(py_proxy).is_file():
                # Write a shell wrapper that calls the Python proxy
                wrapper = (
                    f"#!/bin/bash\n"
                    f'REAL_CODEX="{real_codex_bin}"\n'
                    f'ARIZE_CODEX_PROXY=true\n'
                    f'exec "{py_proxy}" "$@"\n'
                )
                proxy_path.write_text(wrapper)
                proxy_path.chmod(0o755)
                info(f"Installed codex proxy to {proxy_path}")

    # --- 5. PATH management ---
    # Clean up old collector auto-start lines
    for profile_name in [".zshrc", ".bashrc"]:
        profile = Path.home() / profile_name
        if profile.is_file():
            try:
                text = profile.read_text()
                if "collector_ctl.sh" in text:
                    lines = text.splitlines()
                    lines = [
                        line for line in lines
                        if not re.search(r"arize-codex.*collector_ctl|collector_ensure|event_buffer_ensure", line)
                    ]
                    profile.write_text("\n".join(lines) + "\n")
                    info(f"Removed old collector auto-start from {profile.name}")
            except OSError:
                pass

    # Offer to add ~/.local/bin to PATH
    if sys.stdin.isatty() and real_codex_bin:
        add = _tty_input("  Ensure ~/.local/bin is prepended in your shell profile for the codex proxy? [Y/n]: ").strip()
        if (not add or add.lower().startswith("y")):
            shell_profile = _detect_shell_profile()
            if shell_profile:
                marker = "# Arize Codex tracing - prepend ~/.local/bin for codex proxy"
                try:
                    text = shell_profile.read_text()
                    if marker not in text:
                        with open(shell_profile, "a") as f:
                            f.write(f"\n{marker}\n")
                            f.write('export PATH="$HOME/.local/bin:$PATH"\n')
                        info(f"Added PATH update to {shell_profile.name}")
                    else:
                        info(f"PATH update already present in {shell_profile.name}")
                except OSError:
                    pass

    # Summary
    print()
    print("  Codex tracing setup complete!")
    print()
    print("  What was configured:")
    print()
    print("    - Notify hook in ~/.codex/config.toml")
    print(f"    - OTLP exporter in ~/.codex/config.toml (port {collector_port})")
    if real_codex_bin:
        print(f"    - Codex proxy wrapper at {proxy_path}")
        print(f"      (real codex: {real_codex_bin})")
    print(f"    - Env file template at {env_file}")
    print()
    print(f"    View collector logs:     tail -f {COLLECTOR_LOG_FILE}")
    print()
    info("Setup complete! Test with: ARIZE_DRY_RUN=true codex")


# ---------------------------------------------------------------------------
# Skills installation
# ---------------------------------------------------------------------------

def install_skills(harness):
    """Symlink harness skills into .agents/skills/ in the current directory."""
    skills_src = INSTALL_DIR / f"{harness}-tracing" / "skills"
    if not skills_src.is_dir():
        warn(f"No skills found for {harness} at {skills_src}")
        return

    target_dir = Path(".agents") / "skills"
    target_dir.mkdir(parents=True, exist_ok=True)

    for skill_dir in skills_src.iterdir():
        if not skill_dir.is_dir():
            continue
        link = target_dir / skill_dir.name
        if link.is_symlink():
            link.unlink()
        elif link.is_dir():
            warn(f"Skipping {skill_dir.name}: {link} already exists and is not a symlink")
            continue
        link.symlink_to(skill_dir)
        info(f"Linked skill: {link} -> {skill_dir}")


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_install(branch=None, tarball_url=None):
    """Update the installed arize-agent-kit to latest."""
    header("Updating arize-agent-kit")

    if not INSTALL_DIR.is_dir():
        err(f"arize-agent-kit is not installed at {INSTALL_DIR}")
        err("Run install first: install.py claude, install.py codex, or install.py cursor")
        sys.exit(1)

    stop_collector()

    git_dir = INSTALL_DIR / ".git"
    if git_dir.is_dir():
        info("Pulling latest changes...")
        try:
            subprocess.run(
                ["git", "-C", str(INSTALL_DIR), "pull", "--ff-only"],
                capture_output=True, check=True, timeout=60,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            warn("Fast-forward pull failed — re-cloning")
            shutil.rmtree(INSTALL_DIR, ignore_errors=True)
            install_repo(branch=branch, tarball_url=tarball_url)
    else:
        info("No git repo found — re-downloading")
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        install_repo(branch=branch, tarball_url=tarball_url)

    # Re-install package and restart
    collector_src = INSTALL_DIR / "core" / "collector.py"
    if collector_src.is_file():
        python_cmd = _venv_python() or find_python()
        if python_cmd:
            # Re-install package to pick up changes
            pip = _venv_pip()
            if pip:
                info("Reinstalling package...")
                try:
                    subprocess.run(
                        [pip, "install", "--quiet", str(INSTALL_DIR)],
                        capture_output=True, check=True, timeout=300,
                    )
                except subprocess.SubprocessError:
                    warn("Package reinstall failed")

            write_collector_launcher(python_cmd)
        else:
            warn("No Python found — collector will not start")
            return

    start_collector()
    info("Update complete! Re-run 'install.py claude', 'install.py codex', or 'install.py cursor' to reconfigure harness settings.")


# ---------------------------------------------------------------------------
# Uninstall helpers
# ---------------------------------------------------------------------------

def _cleanup_claude_config():
    """Remove Claude tracing configuration."""
    settings_file = Path.home() / ".claude" / "settings.json"
    plugin_dir = str(INSTALL_DIR / "claude-code-tracing")
    legacy_plugin_dir = str(INSTALL_DIR / "plugins" / "claude-code-tracing")

    if settings_file.is_file():
        try:
            settings = json.loads(settings_file.read_text())
        except (json.JSONDecodeError, OSError):
            return

        changed = False

        # Remove plugin references
        plugins = settings.get("plugins", [])
        new_plugins = [
            p for p in plugins
            if not (
                (isinstance(p, str) and p in (plugin_dir, legacy_plugin_dir))
                or (isinstance(p, dict) and p.get("path") in (plugin_dir, legacy_plugin_dir))
            )
        ]
        if len(new_plugins) != len(plugins):
            if confirm(f"  Remove Arize Claude plugin path from {settings_file}? [y/N]: ", "n"):
                settings["plugins"] = new_plugins
                changed = True
                info(f"Removed Arize Claude plugin path from {settings_file}")

        # Remove Arize tracing hooks
        hooks = settings.get("hooks", {})
        has_arize_hooks = False
        for event, entries in hooks.items():
            for entry in entries:
                for h in entry.get("hooks", []):
                    cmd = h.get("command", "")
                    if "arize" in cmd or "claude-code-tracing" in cmd:
                        has_arize_hooks = True
                        break

        if has_arize_hooks:
            if confirm(f"  Remove Arize tracing hooks from {settings_file}? [y/N]: ", "n"):
                new_hooks = {}
                for event, entries in hooks.items():
                    filtered = []
                    for entry in entries:
                        entry_hooks = [
                            h for h in entry.get("hooks", [])
                            if not ("arize" in h.get("command", "") or "claude-code-tracing" in h.get("command", ""))
                        ]
                        if entry_hooks:
                            entry["hooks"] = entry_hooks
                            filtered.append(entry)
                    if filtered:
                        new_hooks[event] = filtered
                settings["hooks"] = new_hooks
                if not new_hooks:
                    del settings["hooks"]
                changed = True
                info(f"Removed Arize tracing hooks from {settings_file}")

        # Remove env keys
        env = settings.get("env", {})
        arize_keys_present = [k for k in ARIZE_ENV_KEYS if k in env]
        if arize_keys_present:
            if confirm(f"  Remove Arize env keys from {settings_file}? [y/N]: ", "n"):
                for k in ARIZE_ENV_KEYS:
                    env.pop(k, None)
                changed = True
                info(f"Removed Arize env keys from {settings_file}")

        if changed:
            settings_file.write_text(json.dumps(settings, indent=2) + "\n")

    # Remove Claude state directory
    state_dir = STATE_BASE_DIR / "claude-code"
    if state_dir.is_dir():
        if confirm(f"  Remove Claude runtime state at {state_dir}? [Y/n]: ", "y"):
            shutil.rmtree(state_dir)
            info(f"Removed {state_dir}")


def _uninstall_codex():
    """Remove Codex tracing configuration."""
    info("Removing Codex tracing configuration...")

    codex_config_dir = Path.home() / ".codex"
    codex_config = codex_config_dir / "config.toml"
    proxy_dir = Path.home() / ".local" / "bin"
    proxy_path = proxy_dir / "codex"
    proxy_backup = proxy_dir / "codex.arize-backup"

    # Remove notify hook from config.toml
    if codex_config.is_file():
        try:
            text = codex_config.read_text()
            # Remove Arize comment line and notify lines that reference arize
            new_text = re.sub(r"^# Arize tracing[^\n]*\n", "", text, flags=re.MULTILINE)
            new_text = re.sub(r"^notify\s*=.*arize.*\n?", "", new_text, flags=re.MULTILINE)

            # Remove [otel] section pointing at localhost collector
            new_text = re.sub(
                r"\n*# Arize shared collector[^\n]*\n\[otel\].*?(?=\n\[[^\]o]|\Z)",
                "",
                new_text,
                flags=re.DOTALL,
            )
            new_text = re.sub(
                r"\n*\[otel\].*?endpoint\s*=\s*\"http://127\.0\.0\.1:\d+/v1/logs\".*?(?=\n\[[^\]o]|\Z)",
                "",
                new_text,
                flags=re.DOTALL,
            )

            codex_config.write_text(new_text)
            info("Cleaned up config.toml")
        except OSError:
            pass

    # Remove proxy
    if proxy_path.is_file():
        try:
            text = proxy_path.read_text()
            if "ARIZE_CODEX_PROXY" in text or "arize" in text.lower():
                proxy_path.unlink()
                info(f"Removed codex proxy from {proxy_path}")
        except OSError:
            pass
    if proxy_backup.is_file():
        try:
            shutil.move(str(proxy_backup), str(proxy_path))
            proxy_path.chmod(0o755)
            info(f"Restored previous codex wrapper to {proxy_path}")
        except OSError:
            pass

    # Clean up PATH injection from shell profiles
    for profile_name in [".zshrc", ".bashrc", ".bash_profile"]:
        profile = Path.home() / profile_name
        if profile.is_file():
            try:
                text = profile.read_text()
                if "prepend ~/.local/bin for codex proxy" in text:
                    lines = text.splitlines()
                    lines = [
                        line for line in lines
                        if "Arize Codex tracing - prepend" not in line
                        and 'export PATH="$HOME/.local/bin:$PATH"' not in line
                    ]
                    profile.write_text("\n".join(lines) + "\n")
                    info(f"Removed PATH update from {profile.name}")
                if "collector_ctl.sh" in text:
                    lines = text.splitlines()
                    lines = [
                        line for line in lines
                        if not re.search(r"arize-codex.*collector_ctl|collector_ensure|event_buffer_ensure", line)
                    ]
                    profile.write_text("\n".join(lines) + "\n")
                    info(f"Removed collector auto-start from {profile.name}")
            except OSError:
                pass

    # Remove state and env file
    state_dir = STATE_BASE_DIR / "codex"
    if state_dir.is_dir():
        shutil.rmtree(state_dir)
        info("Cleaned up Codex state directory")

    env_file = codex_config_dir / "arize-env.sh"
    if env_file.is_file():
        env_file.unlink()
        info(f"Removed {env_file}")

    # Remove harness entry from config
    _cfg_delete("harnesses.codex")
    info("Codex tracing cleanup complete.")


def _uninstall_cursor():
    """Remove Cursor tracing configuration."""
    info("Removing Cursor tracing configuration...")

    hooks_file = Path.home() / ".cursor" / "hooks.json"
    hook_cmd = _venv_bin("arize-hook-cursor")
    # Also check for bash-style hook commands
    bash_hook_cmd = f"bash {INSTALL_DIR}/cursor-tracing/hooks/hook-handler.sh"

    if hooks_file.is_file():
        try:
            hooks_data = json.loads(hooks_file.read_text())
            hooks = hooks_data.get("hooks", {})
            new_hooks = {}
            for event, entries in hooks.items():
                filtered = [
                    h for h in entries
                    if h.get("command") not in (hook_cmd, bash_hook_cmd)
                    and "arize" not in h.get("command", "").lower()
                ]
                if filtered:
                    new_hooks[event] = filtered
            hooks_data["hooks"] = new_hooks

            if not new_hooks:
                hooks_file.unlink()
                info(f"Removed {hooks_file} (no hooks remaining)")
            else:
                hooks_file.write_text(json.dumps(hooks_data, indent=2) + "\n")
                info(f"Removed Arize hooks from {hooks_file} (other hooks preserved)")
        except (json.JSONDecodeError, OSError):
            pass

    # Remove state directory
    state_dir = STATE_BASE_DIR / "cursor"
    if state_dir.is_dir():
        shutil.rmtree(state_dir)
        info(f"Removed {state_dir}")

    _cfg_delete("harnesses.cursor")
    info("Cursor tracing cleanup complete.")


def uninstall():
    """Full uninstall."""
    header("Uninstalling arize-agent-kit")

    # Stop collector
    info("Stopping shared collector...")
    stop_collector()

    # Clean up each harness
    codex_dir = INSTALL_DIR / "codex-tracing"
    codex_config = Path.home() / ".codex"
    if codex_dir.is_dir() or codex_config.is_dir():
        _uninstall_codex()

    cursor_dir = INSTALL_DIR / "cursor-tracing"
    cursor_hooks = Path.home() / ".cursor" / "hooks.json"
    cursor_state = STATE_BASE_DIR / "cursor"
    if cursor_dir.is_dir() or cursor_hooks.is_file() or cursor_state.is_dir():
        _uninstall_cursor()

    info("Checking Claude tracing configuration...")
    _cleanup_claude_config()

    # Remove shared runtime
    info("Removing shared collector runtime...")
    for f in [COLLECTOR_BIN, PID_FILE, COLLECTOR_LOG_FILE]:
        try:
            f.unlink()
        except OSError:
            pass

    if VENV_DIR.is_dir():
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        info("Removed collector venv")

    # Remove empty directories
    for d in [BIN_DIR, PID_DIR, LOG_DIR]:
        try:
            d.rmdir()
        except OSError:
            pass

    # Remove config and install directory
    try:
        CONFIG_FILE.unlink()
        info(f"Removed {CONFIG_FILE}")
    except OSError:
        pass

    if INSTALL_DIR.is_dir():
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        info(f"Removed {INSTALL_DIR}")
    else:
        info(f"Repository checkout already absent at {INSTALL_DIR}")

    print()
    print("  The following may need manual cleanup:")
    print()
    print("  - Claude Agent SDK: remove any hardcoded local plugin path from your application code")
    print("  - Claude Code marketplace installs are managed separately by Claude")
    print("  - Shell profile: remove any manual 'source ~/.codex/arize-env.sh' lines you added")
    print()
    info("Uninstall complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Arize Agent Kit — Cross-platform installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python3 install.py claude
              python3 install.py codex
              python3 install.py cursor
              python3 install.py update
              python3 install.py uninstall
        """),
    )
    parser.add_argument(
        "command",
        choices=["claude", "codex", "cursor", "update", "uninstall"],
        help="action to perform",
    )
    parser.add_argument(
        "--with-skills",
        action="store_true",
        help="symlink setup skills into .agents/skills/ in the current directory",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="install from a specific git branch (default: main)",
    )
    args = parser.parse_args()

    branch = args.branch or INSTALL_BRANCH
    tarball_url = f"https://github.com/Arize-ai/arize-agent-kit/archive/refs/heads/{branch}.tar.gz"

    if args.command == "claude":
        install_repo(branch=branch, tarball_url=tarball_url)
        setup_shared_collector("claude-code")
        setup_claude()
        if args.with_skills:
            install_skills("claude-code")

    elif args.command == "codex":
        install_repo(branch=branch, tarball_url=tarball_url)
        setup_shared_collector("codex")
        setup_codex()
        if args.with_skills:
            install_skills("codex")

    elif args.command == "cursor":
        install_repo(branch=branch, tarball_url=tarball_url)
        setup_shared_collector("cursor")
        setup_cursor()
        if args.with_skills:
            install_skills("cursor")

    elif args.command == "update":
        update_install(branch=branch, tarball_url=tarball_url)

    elif args.command == "uninstall":
        uninstall()


if __name__ == "__main__":
    main()
