import { spawn } from "child_process";
import { join } from "path";
import * as vscode from "vscode";

import { checkVenvExists, getArizeInstallPath } from "./python";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InstallOptions {
  harness: string;
  backend: string;
  credentials: Record<string, string>;
  userId?: string;
  scope?: string;
}

export interface InstallResult {
  success: boolean;
  output: string;
  error?: string;
}

export interface StatusResult {
  collector: { running: boolean; port: number };
  backend: string;
  harnesses: Array<{ name: string; project: string }>;
}

/**
 * Return the platform-appropriate bootstrapper script name.
 * The extension bundles install.sh / install.bat in its root.
 */
function getBootstrapperPath(extensionRoot: string): string {
  const script = process.platform === "win32" ? "install.bat" : "install.sh";
  return join(extensionRoot, "..", script);
}

// ---------------------------------------------------------------------------
// Internal spawn helper
// ---------------------------------------------------------------------------

interface SpawnResult {
  code: number;
  stdout: string;
  stderr: string;
}

/**
 * Spawn a child process, streaming stdout/stderr through `onOutput`.
 *
 * Returns a promise that resolves when the process exits.
 */
function _spawn(
  cmd: string,
  args: string[],
  onOutput?: vscode.EventEmitter<string>,
): Promise<SpawnResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env },
      shell: process.platform === "win32",
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (data: Buffer) => {
      const text = data.toString();
      stdout += text;
      onOutput?.fire(text);
    });

    child.stderr.on("data", (data: Buffer) => {
      const text = data.toString();
      stderr += text;
      onOutput?.fire(text);
    });

    child.on("error", (err) => {
      reject(err);
    });

    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

// ---------------------------------------------------------------------------
// Standalone helper
// ---------------------------------------------------------------------------

/**
 * Run an `arize-install` sub-command and return the result.
 *
 * Convenience wrapper used by extension commands that don't need the full
 * InstallerBridge lifecycle (e.g. one-shot collector start/stop).
 */
export async function runInstallerCommand(
  arizeInstall: string,
  args: string[],
): Promise<SpawnResult> {
  return _spawn(arizeInstall, args);
}

// ---------------------------------------------------------------------------
// Installer bridge
// ---------------------------------------------------------------------------

export class InstallerBridge {
  /** Fires for every chunk of stdout/stderr output from child processes. */
  public readonly onOutput = new vscode.EventEmitter<string>();

  private readonly extensionRoot: string;

  constructor(extensionRoot: string) {
    this.extensionRoot = extensionRoot;
  }

  /**
   * Run a harness install.
   *
   * First-time (no venv): runs the bootstrapper shell script which creates
   * the venv, installs the package, then delegates to `arize-install`.
   *
   * Subsequent: calls `arize-install` directly with `--non-interactive`.
   */
  async runInstall(options: InstallOptions): Promise<InstallResult> {
    const arizeInstall = getArizeInstallPath();

    if (!checkVenvExists() || arizeInstall === null) {
      return this._bootstrapInstall(options);
    }
    return this._directInstall(arizeInstall, options);
  }

  /**
   * Uninstall a single harness (or all if harness is "all").
   */
  async runUninstall(harness: string): Promise<InstallResult> {
    const arizeInstall = getArizeInstallPath();
    if (arizeInstall === null) {
      return { success: false, output: "", error: "arize-install not found — is the package installed?" };
    }

    const args: string[] = ["uninstall", "--non-interactive"];
    if (harness === "all") {
      args.push("--all");
    } else {
      args.push("--harness", harness);
    }

    try {
      const result = await _spawn(arizeInstall, args, this.onOutput);
      return {
        success: result.code === 0,
        output: result.stdout,
        error: result.code !== 0 ? result.stderr || `Process exited with code ${result.code}` : undefined,
      };
    } catch (err) {
      return { success: false, output: "", error: String(err) };
    }
  }

  /**
   * Query installed status from `arize-install status`.
   * Returns parsed JSON output.
   */
  async getStatus(): Promise<StatusResult> {
    const arizeInstall = getArizeInstallPath();
    if (arizeInstall === null) {
      return { collector: { running: false, port: 4318 }, backend: "none", harnesses: [] };
    }

    try {
      const result = await _spawn(arizeInstall, ["status"]);
      if (result.code !== 0) {
        return { collector: { running: false, port: 4318 }, backend: "none", harnesses: [] };
      }
      return JSON.parse(result.stdout) as StatusResult;
    } catch {
      return { collector: { running: false, port: 4318 }, backend: "none", harnesses: [] };
    }
  }

  /**
   * Start or stop the OTLP collector.
   */
  async controlCollector(action: "start" | "stop"): Promise<boolean> {
    const arizeInstall = getArizeInstallPath();
    if (arizeInstall === null) {
      return false;
    }

    try {
      const result = await _spawn(arizeInstall, ["collector", action], this.onOutput);
      return result.code === 0;
    } catch {
      return false;
    }
  }

  // -------------------------------------------------------------------------
  // Private helpers
  // -------------------------------------------------------------------------

  /**
   * First-time install via bootstrapper script.
   * Downloads/creates the venv and package, then configures the harness.
   */
  private async _bootstrapInstall(options: InstallOptions): Promise<InstallResult> {
    const bootstrapper = getBootstrapperPath(this.extensionRoot);

    let cmd: string;
    let args: string[];

    if (process.platform === "win32") {
      cmd = "cmd.exe";
      args = ["/c", bootstrapper, options.harness];
    } else {
      cmd = "bash";
      args = [bootstrapper, options.harness];
    }

    // Append flags the bootstrapper forwards to arize-install
    args.push(...this._buildFlags(options));

    try {
      const result = await _spawn(cmd, args, this.onOutput);
      return {
        success: result.code === 0,
        output: result.stdout,
        error: result.code !== 0 ? result.stderr || `Process exited with code ${result.code}` : undefined,
      };
    } catch (err) {
      return { success: false, output: "", error: String(err) };
    }
  }

  /**
   * Subsequent install — venv already exists, call arize-install directly.
   */
  private async _directInstall(arizeInstall: string, options: InstallOptions): Promise<InstallResult> {
    const args = [options.harness, ...this._buildFlags(options)];

    try {
      const result = await _spawn(arizeInstall, args, this.onOutput);
      return {
        success: result.code === 0,
        output: result.stdout,
        error: result.code !== 0 ? result.stderr || `Process exited with code ${result.code}` : undefined,
      };
    } catch (err) {
      return { success: false, output: "", error: String(err) };
    }
  }

  /**
   * Build CLI flags from InstallOptions.
   *
   * Maps option fields to the flags accepted by `arize-install`:
   *   --backend, --api-key, --space-id, --otlp-endpoint,
   *   --phoenix-endpoint, --user-id, --scope, --non-interactive
   */
  private _buildFlags(options: InstallOptions): string[] {
    const flags: string[] = [];

    flags.push("--backend", options.backend);

    // Credential keys map directly to CLI flags
    const credentialMap: Record<string, string> = {
      apiKey: "--api-key",
      spaceId: "--space-id",
      otlpEndpoint: "--otlp-endpoint",
      phoenixEndpoint: "--phoenix-endpoint",
    };

    for (const [key, flag] of Object.entries(credentialMap)) {
      const value = options.credentials[key];
      if (value) {
        flags.push(flag, value);
      }
    }

    if (options.userId) {
      flags.push("--user-id", options.userId);
    }

    if (options.scope) {
      flags.push("--scope", options.scope);
    }

    flags.push("--non-interactive");

    return flags;
  }

  dispose(): void {
    this.onOutput.dispose();
  }
}
