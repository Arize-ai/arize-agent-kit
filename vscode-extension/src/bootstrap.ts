/**
 * Bootstrap module: ensures the arize-vscode-bridge binary exists on disk
 * by creating a venv and pip-installing the bundled wheel if needed.
 */

import { spawn, ChildProcess } from "child_process";
import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { homedir, platform } from "os";
import { findPython, findBridgeBinary } from "./python";

const IS_WIN = platform() === "win32";

// ── Public types ─────────────────────────────────────────────────────

export interface BootstrapResult {
  ok: boolean;
  /** Absolute path to the bridge binary when ok=true. */
  bridgePath?: string;
  /** Stable machine-readable code. */
  error?: EnsureBridgeError;
  /** Human-readable detail to render in the sidebar. */
  errorMessage?: string;
}

export type EnsureBridgeError =
  | "python_not_found"
  | "venv_create_failed"
  | "wheel_missing"
  | "pip_install_failed"
  | "ssl_fix_failed"
  | "binary_still_missing";

export interface EnsureBridgeOptions {
  /** Streams every spawned process's stdout/stderr. */
  onLog?: (level: "info" | "error", message: string) => void;
  /** Aborts the in-flight bootstrap. Propagates SIGTERM to children. */
  signal?: AbortSignal;
  /** Path containing python/wheel.json. Pass ctx.extensionPath. */
  extensionPath: string;
}

// ── macOS certifi stub ───────────────────────────────────────────────

interface MacOSCertifiFixOptions {
  venvDir: string;
  onLog?: (level: "info" | "error", message: string) => void;
  signal?: AbortSignal;
}

export type MacOSCertifiFixResult = { ok: true } | { ok: false; reason: string };

/**
 * Stub. Implemented by the macos-ssl-fix task. Until then it is a
 * no-op that always succeeds, so the bootstrap pipeline is testable
 * end-to-end on macOS without certifi.
 */
export async function applyMacOSCertifiFix(
  _opts: MacOSCertifiFixOptions,
): Promise<MacOSCertifiFixResult> {
  return { ok: true };
}

// ── Concurrency state ────────────────────────────────────────────────

let _inflight: Promise<BootstrapResult> | null = null;

/** Reset concurrency state between tests. */
export function _resetForTesting(): void {
  _inflight = null;
}

// ── Internal helpers ─────────────────────────────────────────────────

interface WheelJson {
  filename: string;
  version: string;
}

/**
 * Spawn a process and collect its stderr. Resolves with exit code and
 * trimmed stderr. Streams output through onLog. Honors AbortSignal.
 */
function runProcess(
  cmd: string,
  args: string[],
  onLog?: (level: "info" | "error", message: string) => void,
  signal?: AbortSignal,
): Promise<{ code: number; stderr: string }> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The operation was aborted.", "AbortError"));
      return;
    }

    const child: ChildProcess = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });

    let stderr = "";

    child.stdout?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      onLog?.("info", text);
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      stderr += text;
      onLog?.("error", text);
    });

    const onAbort = () => {
      child.kill("SIGTERM");
      reject(new DOMException("The operation was aborted.", "AbortError"));
    };

    signal?.addEventListener("abort", onAbort, { once: true });

    child.on("error", (err) => {
      signal?.removeEventListener("abort", onAbort);
      reject(err);
    });

    child.on("close", (code) => {
      signal?.removeEventListener("abort", onAbort);
      resolve({ code: code ?? 1, stderr: stderr.trim() });
    });
  });
}

// ── Main entry point ─────────────────────────────────────────────────

/**
 * Ensure the bridge binary exists on disk. Idempotent and safe to
 * call concurrently — a single in-flight bootstrap is shared across
 * callers within one process.
 */
export function ensureBridge(opts: EnsureBridgeOptions): Promise<BootstrapResult> {
  if (_inflight) {
    return _inflight;
  }

  const promise = doEnsureBridge(opts).finally(() => {
    _inflight = null;
  });
  _inflight = promise;
  return promise;
}

async function doEnsureBridge(opts: EnsureBridgeOptions): Promise<BootstrapResult> {
  const { onLog, signal, extensionPath } = opts;

  // Step 1: Already installed?
  const existing = await findBridgeBinary();
  if (existing) {
    return { ok: true, bridgePath: existing };
  }

  // Step 2: Find system Python
  const systemPython = await findPython();
  if (!systemPython) {
    return { ok: false, error: "python_not_found", errorMessage: "Python ≥ 3.9 not found on PATH." };
  }

  // Step 3: Create venv if absent
  const venvDir = join(homedir(), ".arize", "harness", "venv");
  if (!existsSync(venvDir)) {
    try {
      const result = await runProcess(systemPython, ["-m", "venv", venvDir], onLog, signal);
      if (result.code !== 0) {
        return { ok: false, error: "venv_create_failed", errorMessage: result.stderr || "venv creation failed." };
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw err;
      }
      return { ok: false, error: "venv_create_failed", errorMessage: String(err) };
    }
  }

  // Step 4: Read wheel.json
  const wheelJsonPath = join(extensionPath, "python", "wheel.json");
  let wheelJson: WheelJson;
  try {
    const raw = readFileSync(wheelJsonPath, "utf-8");
    wheelJson = JSON.parse(raw);
    if (!wheelJson.filename) {
      return { ok: false, error: "wheel_missing", errorMessage: "Bundled bridge wheel is missing." };
    }
  } catch {
    return { ok: false, error: "wheel_missing", errorMessage: "Bundled bridge wheel is missing." };
  }

  const wheelPath = join(extensionPath, "python", wheelJson.filename);
  if (!existsSync(wheelPath)) {
    return { ok: false, error: "wheel_missing", errorMessage: "Bundled bridge wheel is missing." };
  }

  // Step 5: Check pip in venv
  const venvPip = IS_WIN
    ? join(venvDir, "Scripts", "pip.exe")
    : join(venvDir, "bin", "pip");
  if (!existsSync(venvPip)) {
    return { ok: false, error: "venv_create_failed", errorMessage: `Pip not found in venv at ${venvPip}.` };
  }

  // Step 6: pip install the wheel
  try {
    const result = await runProcess(venvPip, ["install", "--quiet", wheelPath], onLog, signal);
    if (result.code !== 0) {
      return { ok: false, error: "pip_install_failed", errorMessage: result.stderr || "pip install failed." };
    }
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err;
    }
    return { ok: false, error: "pip_install_failed", errorMessage: String(err) };
  }

  // Step 7: macOS SSL cert fix
  if (process.platform === "darwin") {
    const certResult = await applyMacOSCertifiFix({ venvDir, onLog, signal });
    if (!certResult.ok) {
      return { ok: false, error: "ssl_fix_failed", errorMessage: certResult.reason };
    }
  }

  // Step 8: Verify bridge binary now exists
  const bridgePath = await findBridgeBinary();
  if (!bridgePath) {
    return { ok: false, error: "binary_still_missing", errorMessage: "Install completed but arize-vscode-bridge was not found." };
  }

  return { ok: true, bridgePath };
}
