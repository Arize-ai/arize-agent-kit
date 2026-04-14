/**
 * VSCode extension uninstall hook.
 *
 * Runs `arize-install uninstall --purge --non-interactive` to fully clean up
 * the harness directory when the extension is uninstalled.
 */
import { execFileSync } from "child_process";
import { existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";

const VENV_DIR = join(homedir(), ".arize", "harness", "venv");

function getArizeInstallPath(): string | null {
  const binName = process.platform === "win32" ? "arize-install.exe" : "arize-install";
  const binDir = process.platform === "win32" ? "Scripts" : "bin";
  const fullPath = join(VENV_DIR, binDir, binName);
  return existsSync(fullPath) ? fullPath : null;
}

function getCollectorCtlPath(): string | null {
  const binName = process.platform === "win32" ? "arize-collector-ctl.exe" : "arize-collector-ctl";
  const binDir = process.platform === "win32" ? "Scripts" : "bin";
  const fullPath = join(VENV_DIR, binDir, binName);
  return existsSync(fullPath) ? fullPath : null;
}

try {
  // Stop the collector first
  const ctlPath = getCollectorCtlPath();
  if (ctlPath) {
    try {
      execFileSync(ctlPath, ["stop"], { timeout: 10_000 });
    } catch {
      // Collector may already be stopped
    }
  }

  // Run full purge
  const installPath = getArizeInstallPath();
  if (installPath) {
    execFileSync(installPath, ["uninstall", "--purge", "--non-interactive"], {
      timeout: 30_000,
    });
  }
} catch {
  // Best-effort cleanup — don't block uninstall on failure
}
