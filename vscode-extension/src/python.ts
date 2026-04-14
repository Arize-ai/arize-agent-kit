import { execFile } from "child_process";
import { existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";

/** Minimum required Python version. */
const MIN_MAJOR = 3;
const MIN_MINOR = 9;

/** Base harness directory — mirrors core.constants.BASE_DIR. */
const HARNESS_DIR = join(homedir(), ".arize", "harness");

/** Venv directory — mirrors core.constants.VENV_DIR. */
const VENV_DIR = join(HARNESS_DIR, "venv");

// ---------------------------------------------------------------------------
// Python discovery
// ---------------------------------------------------------------------------

/**
 * Run `<candidate> --version` and return the parsed [major, minor] if the
 * candidate exists and is Python >= 3.9, otherwise null.
 */
function probeCandidate(candidate: string): Promise<[number, number] | null> {
  return new Promise((resolve) => {
    execFile(candidate, ["--version"], { timeout: 10_000 }, (err, stdout, stderr) => {
      if (err) {
        resolve(null);
        return;
      }
      // `python --version` prints to stdout (3.4+) or stderr (older).
      const output = (stdout || stderr || "").trim();
      const match = output.match(/Python\s+(\d+)\.(\d+)/);
      if (!match) {
        resolve(null);
        return;
      }
      const major = parseInt(match[1], 10);
      const minor = parseInt(match[2], 10);
      if (major === MIN_MAJOR && minor >= MIN_MINOR) {
        resolve([major, minor]);
      } else {
        resolve(null);
      }
    });
  });
}

/**
 * Locate a Python >= 3.9 interpreter on the system.
 *
 * Tries candidates in order:
 *   1. `python3`, `python` (resolved via PATH)
 *   2. Platform-specific well-known paths
 *
 * Returns the first valid path, or null if none found.
 */
export async function findPython(): Promise<string | null> {
  const candidates: string[] = ["python3", "python"];

  // Platform-specific well-known paths
  if (process.platform === "darwin") {
    candidates.push(
      "/opt/homebrew/bin/python3",
      "/usr/local/bin/python3",
      "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
    );
  } else if (process.platform === "win32") {
    candidates.push("py"); // Python Launcher for Windows
    const localAppData = process.env.LOCALAPPDATA;
    if (localAppData) {
      // Microsoft Store install
      candidates.push(join(localAppData, "Microsoft", "WindowsApps", "python3.exe"));
    }
  } else {
    // Linux
    candidates.push("/usr/bin/python3", "/usr/local/bin/python3");
  }

  for (const candidate of candidates) {
    const version = await probeCandidate(candidate);
    if (version !== null) {
      return candidate;
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// OS-specific install instructions
// ---------------------------------------------------------------------------

/**
 * Return an HTML string with OS-specific instructions for installing Python.
 */
export function getPythonInstallInstructions(): string {
  switch (process.platform) {
    case "darwin":
      return [
        "<p><strong>Install Python on macOS:</strong></p>",
        "<ul>",
        "<li>Via Homebrew: <code>brew install python@3</code></li>",
        '<li>Or download from <a href="https://www.python.org/downloads/">python.org</a></li>',
        "</ul>",
      ].join("\n");

    case "win32":
      return [
        "<p><strong>Install Python on Windows:</strong></p>",
        "<ul>",
        "<li>Via Microsoft Store: search for <em>Python 3</em></li>",
        '<li>Or download from <a href="https://www.python.org/downloads/">python.org</a></li>',
        "</ul>",
        '<p><em>Make sure to check "Add Python to PATH" during installation.</em></p>',
      ].join("\n");

    default:
      // Linux
      return [
        "<p><strong>Install Python on Linux:</strong></p>",
        "<ul>",
        "<li>Debian/Ubuntu: <code>sudo apt install python3 python3-venv</code></li>",
        "<li>Fedora: <code>sudo dnf install python3</code></li>",
        "<li>Arch: <code>sudo pacman -S python</code></li>",
        "</ul>",
      ].join("\n");
  }
}

// ---------------------------------------------------------------------------
// Venv helpers
// ---------------------------------------------------------------------------

/**
 * Check whether the Arize harness venv already exists.
 *
 * Returns true if the venv Python binary is present on disk.
 */
export function checkVenvExists(): boolean {
  const pythonBin =
    process.platform === "win32"
      ? join(VENV_DIR, "Scripts", "python.exe")
      : join(VENV_DIR, "bin", "python3");
  return existsSync(pythonBin);
}

/**
 * Return the absolute path to the `arize-install` entry point inside the
 * venv, or null if it does not exist.
 */
export function getArizeInstallPath(): string | null {
  const binName = process.platform === "win32" ? "arize-install.exe" : "arize-install";
  const binDir = process.platform === "win32" ? "Scripts" : "bin";
  const fullPath = join(VENV_DIR, binDir, binName);
  return existsSync(fullPath) ? fullPath : null;
}

/**
 * Return the absolute path to `arize-collector-ctl` inside the venv,
 * or null if it does not exist.
 */
export function getCollectorCtlPath(): string | null {
  const binName = process.platform === "win32" ? "arize-collector-ctl.exe" : "arize-collector-ctl";
  const binDir = process.platform === "win32" ? "Scripts" : "bin";
  const fullPath = join(VENV_DIR, binDir, binName);
  return existsSync(fullPath) ? fullPath : null;
}
