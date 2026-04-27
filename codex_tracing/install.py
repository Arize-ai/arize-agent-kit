#!/usr/bin/env python3
"""Codex harness install / uninstall module.

Self-contained module that handles:
- Writing ~/.codex/arize-env.sh (env file)
- Updating ~/.codex/config.toml (TOML config with notify + otel exporter)
- Starting/stopping the codex buffer service
- Managing the shared config.yaml harness entry
- Symlinking skills
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from codex_tracing.codex_buffer_ctl import buffer_start, buffer_status, buffer_stop
from codex_tracing.constants import OTEL_ENDPOINT  # noqa: F401 — re-exported for backwards compat
from codex_tracing.constants import (
    BUFFER_PORT,
    CODEX_CONFIG_DIR,
    CODEX_CONFIG_FILE,
    CODEX_ENV_FILE,
    DISPLAY_NAME,
    HARNESS_BIN,
    HARNESS_HOME,
    HARNESS_NAME,
    NOTIFY_BIN_NAME,
)
from core.config import get_value, load_config
from core.setup import (
    CONFIG_FILE,
    dry_run,
    ensure_harness_installed,
    ensure_shared_runtime,
    info,
    merge_harness_entry,
    prompt_backend,
    prompt_project_name,
    prompt_user_id,
    remove_harness_entry,
    symlink_skills,
    unlink_skills,
    venv_bin,
    write_config,
)

# Try to import tomllib (3.11+), then tomli, then fall back to None
_tomllib = None
try:
    import tomllib as _tomllib  # type: ignore[no-redef]
except ImportError:
    try:
        import tomli as _tomllib  # type: ignore[no-redef]
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# TOML helpers
# ---------------------------------------------------------------------------


def _toml_load(path: Path) -> dict:
    """Load a TOML file into a dict. Falls back to line-based parsing.

    If the file is malformed (e.g. another tool wrote unquoted keys with
    `@` or `/`), fall back to the lenient line parser rather than crashing
    so install/uninstall can still proceed.
    """
    if not path.is_file():
        return {}
    text = path.read_text()
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except Exception:
            pass
    return _toml_line_parse(text)


def _toml_line_parse(text: str) -> dict:
    """Minimal TOML parser — handles flat keys and sections for our use case."""
    result: dict = {}
    current_section: dict = result
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Section header
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            keys = _toml_split_key_path(m.group(1))
            current_section = result
            for k in keys:
                if k not in current_section:
                    current_section[k] = {}
                current_section = current_section[k]
            continue
        # Key = value
        m = re.match(r"^([^=]+?)\s*=\s*(.+)$", line)
        if m:
            key = _toml_unkey(m.group(1).strip())
            val_raw = m.group(2).strip()
            # Handle array values like ["cmd"] or ['cmd']
            if val_raw.startswith("["):
                items = []
                for item in re.findall(r'"([^"]*)"|\'([^\']*)\'', val_raw):
                    items.append(item[0] or item[1])
                current_section[key] = items
            elif (val_raw.startswith('"') and val_raw.endswith('"')) or (
                val_raw.startswith("'") and val_raw.endswith("'")
            ):
                current_section[key] = val_raw[1:-1]
            elif val_raw.lower() in ("true", "false"):
                current_section[key] = val_raw.lower() == "true"
            else:
                try:
                    current_section[key] = int(val_raw)
                except ValueError:
                    current_section[key] = val_raw
    return result


def _toml_write(data: dict, path: Path) -> None:
    """Write a dict as TOML. Hand-rolled — no tomli-w dependency."""
    lines: list[str] = []
    _toml_write_section(data, [], lines)
    path.write_text("\n".join(lines) + "\n")


_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    """Quote a TOML key if it contains characters not allowed in bare keys."""
    if _BARE_KEY_RE.match(key):
        return key
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_unkey(key: str) -> str:
    """Inverse of _toml_key — strip quotes and unescape a TOML key."""
    if len(key) >= 2 and key.startswith('"') and key.endswith('"'):
        inner = key[1:-1]
        inner = inner.replace('\\"', '"')
        inner = inner.replace("\\\\", "\\")
        return inner
    return key


def _toml_split_key_path(path: str) -> list[str]:
    """Split a dotted TOML key path respecting quoted segments.

    Examples:
        'a.b.c' -> ['a', 'b', 'c']
        'mcp_servers."@scope/server"' -> ['mcp_servers', '@scope/server']
        'mcp_servers."a.b.c"' -> ['mcp_servers', 'a.b.c']
    """
    segments: list[str] = []
    buf: list[str] = []
    in_quotes = False
    escape = False
    for ch in path:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if in_quotes:
            if ch == "\\":
                buf.append(ch)
                escape = True
            elif ch == '"':
                buf.append(ch)
                in_quotes = False
            else:
                buf.append(ch)
        else:
            if ch == '"':
                buf.append(ch)
                in_quotes = True
            elif ch == ".":
                segments.append(_toml_unkey("".join(buf).strip()))
                buf = []
            else:
                buf.append(ch)
    # Flush remaining buffer
    segments.append(_toml_unkey("".join(buf).strip()))
    return segments


def _toml_write_section(data: dict, prefix: list[str], lines: list[str]) -> None:
    """Recursively write TOML sections."""
    # Write scalar/array keys first
    for key, val in data.items():
        if isinstance(val, dict):
            continue
        _toml_write_value(key, val, lines)

    # Then nested sections
    for key, val in data.items():
        if not isinstance(val, dict):
            continue
        section_path = prefix + [key]
        # Check if this section has direct scalar values
        has_scalars = any(not isinstance(v, dict) for v in val.values())
        if has_scalars or not val:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[{'.'.join(_toml_key(k) for k in section_path)}]")
        _toml_write_section(val, section_path, lines)


def _toml_write_value(key: str, val: object, lines: list[str]) -> None:
    """Write a single TOML key-value pair."""
    k = _toml_key(key)
    if isinstance(val, list):
        items = ", ".join(_toml_string_literal(v) for v in val)
        lines.append(f"{k} = [{items}]")
    elif isinstance(val, bool):
        lines.append(f"{k} = {'true' if val else 'false'}")
    elif isinstance(val, int):
        lines.append(f"{k} = {val}")
    else:
        lines.append(f"{k} = {_toml_string_literal(val)}")


def _toml_string_literal(val: object) -> str:
    """Render a string as a TOML literal '...' — no escape handling needed,
    which matches `_toml_line_parse` semantics and is safe for Windows paths
    with backslashes. Falls back to an escaped basic string if the value
    contains a single quote or newline (which literal strings cannot carry).
    """
    s = str(val)
    if "'" in s or "\n" in s or "\r" in s:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        return f'"{escaped}"'
    return f"'{s}'"


# ---------------------------------------------------------------------------
# Codex TOML config management
# ---------------------------------------------------------------------------


def _codex_toml_add(path: Path, notify_cmd: str, otel_endpoint: str) -> None:
    """Add notify command and otel exporter to codex config.toml. Idempotent."""
    if dry_run():
        info(f"would update {path} with notify and otel exporter")
        return

    data = _toml_load(path)

    # Set notify — array of commands
    existing_notify = data.get("notify", [])
    if not isinstance(existing_notify, list):
        existing_notify = [existing_notify] if existing_notify else []
    if notify_cmd not in existing_notify:
        existing_notify.append(notify_cmd)
    data["notify"] = existing_notify

    # Set otel exporter
    if "otel" not in data:
        data["otel"] = {}
    otel = data["otel"]
    if "exporter" not in otel:
        otel["exporter"] = {}
    otel["exporter"]["otlp-http"] = {
        "endpoint": otel_endpoint,
        "protocol": "json",
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    _toml_write(data, path)


def _codex_toml_remove(path: Path, notify_cmd: str, otel_endpoint: str) -> None:
    """Remove our notify command and otel exporter from codex config.toml. Idempotent."""
    if not path.is_file():
        return

    if dry_run():
        info(f"would revert {path}: remove notify={notify_cmd} and otel exporter")
        return

    data = _toml_load(path)
    changed = False

    # Remove our notify entry only if it matches
    existing_notify = data.get("notify", [])
    if isinstance(existing_notify, list) and notify_cmd in existing_notify:
        existing_notify.remove(notify_cmd)
        if existing_notify:
            data["notify"] = existing_notify
        else:
            del data["notify"]
        changed = True
    elif isinstance(existing_notify, str) and existing_notify == notify_cmd:
        del data["notify"]
        changed = True

    # Remove otel exporter only if it points at our endpoint
    if "otel" in data and "exporter" in data["otel"] and "otlp-http" in data["otel"]["exporter"]:
        otlp_http = data["otel"]["exporter"]["otlp-http"]
        if isinstance(otlp_http, dict) and otlp_http.get("endpoint") == otel_endpoint:
            del data["otel"]["exporter"]["otlp-http"]
            changed = True
            # Clean up empty parents
            if not data["otel"]["exporter"]:
                del data["otel"]["exporter"]
            if not data["otel"]:
                del data["otel"]

    if changed:
        _toml_write(data, path)


# ---------------------------------------------------------------------------
# Env file management
# ---------------------------------------------------------------------------


def _write_env_file(path: Path, user_id: str = "") -> None:
    """Write the codex env file with ARIZE env exports."""
    if dry_run():
        info(f"would write env file {path}")
        return

    lines = [
        "export ARIZE_TRACE_ENABLED=true",
        f"export ARIZE_CODEX_BUFFER_PORT={BUFFER_PORT}",
    ]
    if user_id:
        lines.append(f"export ARIZE_USER_ID={user_id}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _is_our_env_file(path: Path) -> bool:
    """Check if the env file is one we wrote (safe heuristic)."""
    if not path.is_file():
        return False
    try:
        text = path.read_text()
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        if len(lines) > 10:
            return False
        return all(re.match(r"^export ARIZE_", line) for line in lines)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Install / Uninstall
# ---------------------------------------------------------------------------


def install(with_skills: bool = False) -> None:
    """Install codex tracing harness."""
    if not ensure_harness_installed(DISPLAY_NAME, home_subdir=HARNESS_HOME, bin_name=HARNESS_BIN):
        info("Aborted.")
        return

    # 1. Ensure shared runtime directories
    ensure_shared_runtime()

    # 2. Prompt for credentials if needed; write harness entry
    config = load_config(str(CONFIG_FILE))
    existing_entry = get_value(config, f"harnesses.{HARNESS_NAME}")

    project_name = prompt_project_name("codex")
    collector = {"host": "127.0.0.1", "port": 4318}

    if existing_entry:
        info(f"Reusing existing backend: {existing_entry.get('target')}")
        # Preserve existing collector if present, otherwise set default
        existing_collector = existing_entry.get("collector")
        merge_harness_entry(HARNESS_NAME, project_name, collector=existing_collector or collector)
        user_id = get_value(config, "user_id") or ""
    else:
        existing_harnesses = config.get("harnesses", {}) if config else {}
        target, credentials = prompt_backend(existing_harnesses=existing_harnesses)
        user_id = prompt_user_id()
        if not dry_run():
            write_config(
                target=target,
                credentials=credentials,
                harness_name=HARNESS_NAME,
                project_name=project_name,
                user_id=user_id,
                collector=collector,
            )
        else:
            info("would write config.yaml with backend credentials")

    # 3. Ensure codex config dir exists
    if not dry_run():
        CODEX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    else:
        info(f"would create {CODEX_CONFIG_DIR}")

    # 4. Write env file
    _write_env_file(CODEX_ENV_FILE, user_id=user_id)

    # 5. Update codex config.toml — collector port from new path
    config = load_config(str(CONFIG_FILE))
    collector_port = get_value(config, f"harnesses.{HARNESS_NAME}.collector.port") or 4318
    otel_endpoint = f"http://127.0.0.1:{collector_port}/v1/logs"
    notify_cmd = str(venv_bin(NOTIFY_BIN_NAME))
    _codex_toml_add(CODEX_CONFIG_FILE, notify_cmd, otel_endpoint)
    info(f"Updated TOML config: {CODEX_CONFIG_FILE}")

    # 6. Start buffer service
    status, _, _ = buffer_status()
    if status == "running":
        info("Buffer service already running — skipping start")
    elif not dry_run():
        ok = buffer_start()
        if ok:
            info("Buffer service started")
        else:
            info("Warning: buffer service failed to start (you can start it later)")
    else:
        info("would start buffer service")

    # 7. Symlink skills
    if with_skills:
        symlink_skills(HARNESS_NAME)
        info("Symlinked skills")

    info("Codex tracing installed successfully")


def uninstall() -> None:
    """Uninstall codex tracing harness."""
    # 1. Stop buffer service
    if not dry_run():
        buffer_stop()
        info("Stopped buffer service")
    else:
        info("would stop buffer service")

    # 2. Revert codex config.toml
    config = load_config(str(CONFIG_FILE))
    collector_port = get_value(config, f"harnesses.{HARNESS_NAME}.collector.port") or 4318
    otel_endpoint = f"http://127.0.0.1:{collector_port}/v1/logs"
    notify_cmd = str(venv_bin(NOTIFY_BIN_NAME))
    _codex_toml_remove(CODEX_CONFIG_FILE, notify_cmd, otel_endpoint)
    info(f"Reverted TOML config: {CODEX_CONFIG_FILE}")

    # 3. Remove env file if it's ours
    if CODEX_ENV_FILE.is_file():
        if _is_our_env_file(CODEX_ENV_FILE):
            if dry_run():
                info(f"would remove {CODEX_ENV_FILE}")
            else:
                CODEX_ENV_FILE.unlink()
                info(f"Removed env file: {CODEX_ENV_FILE}")
        else:
            info(f"Skipping {CODEX_ENV_FILE} — does not look like our file")

    # 4. Remove harness entry
    remove_harness_entry(HARNESS_NAME)
    info("Removed codex harness entry from config.yaml")

    # 5. Unlink skills
    unlink_skills(HARNESS_NAME)
    info("Unlinked skills")

    info("Codex tracing uninstalled")


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------


def cli_main(argv: list[str] | None = None) -> None:
    """Parse argv and dispatch to install/uninstall."""
    if argv is None:
        argv = sys.argv
    if len(argv) < 2 or argv[1] not in ("install", "uninstall"):
        print(f"usage: {argv[0]} <install|uninstall> [--with-skills]", file=sys.stderr)
        sys.exit(1)

    action = argv[1]
    flags = argv[2:]

    if action == "install":
        install(with_skills="--with-skills" in flags)
    else:
        uninstall()


if __name__ == "__main__":
    try:
        cli_main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(1)
