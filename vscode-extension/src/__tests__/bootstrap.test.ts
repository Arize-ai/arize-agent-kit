/**
 * Tests for bootstrap.ts (ensureBridge).
 */

// ── Mocks must be declared before any require/import of the mocked modules ──

jest.mock("../python", () => ({
  findPython: jest.fn(),
  findBridgeBinary: jest.fn(),
}));

const mockSpawn = jest.fn();
jest.mock("child_process", () => ({
  spawn: mockSpawn,
  execFile: jest.fn(),
}));

const mockExistsSync = jest.fn();
const mockReadFileSync = jest.fn();
jest.mock("fs", () => ({
  existsSync: mockExistsSync,
  readFileSync: mockReadFileSync,
}));

import { EventEmitter } from "events";
import { findPython, findBridgeBinary } from "../python";
import { ensureBridge, BootstrapResult, EnsureBridgeOptions } from "../bootstrap";

const mockFindPython = findPython as jest.MockedFunction<typeof findPython>;
const mockFindBridgeBinary = findBridgeBinary as jest.MockedFunction<typeof findBridgeBinary>;

// ── Helpers ──────────────────────────────────────────────────────────

/** Create a fake ChildProcess that completes with a given code and stderr. */
function fakeSpawn(exitCode: number, stderr = "") {
  const child = new EventEmitter() as any;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = jest.fn();
  child.stdin = null;

  mockSpawn.mockReturnValueOnce(child);

  // Schedule the events asynchronously so callers can wire up listeners.
  setImmediate(() => {
    if (stderr) {
      child.stderr.emit("data", Buffer.from(stderr));
    }
    child.emit("close", exitCode);
  });

  return child;
}

function defaultOpts(overrides: Partial<EnsureBridgeOptions> = {}): EnsureBridgeOptions {
  return {
    extensionPath: "/ext",
    ...overrides,
  };
}

const WHEEL_JSON = JSON.stringify({ filename: "arize_harness_tracing-0.1.0-py3-none-any.whl", version: "0.1.0" });

// ── Reset mocks between tests ────────────────────────────────────────

beforeEach(() => {
  jest.clearAllMocks();
  mockFindBridgeBinary.mockResolvedValue(null);
  mockFindPython.mockResolvedValue(null);
  mockExistsSync.mockReturnValue(false);
  mockReadFileSync.mockImplementation(() => {
    throw new Error("ENOENT");
  });
});

// ── Tests ────────────────────────────────────────────────────────────

describe("ensureBridge", () => {
  it("returns ok when findBridgeBinary resolves on first call", async () => {
    mockFindBridgeBinary.mockResolvedValueOnce("/usr/bin/arize-vscode-bridge");

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({ ok: true, bridgePath: "/usr/bin/arize-vscode-bridge" });
    expect(mockSpawn).not.toHaveBeenCalled();
    expect(mockFindPython).not.toHaveBeenCalled();
  });

  it("returns python_not_found when findPython returns null", async () => {
    mockFindPython.mockResolvedValueOnce(null);

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({
      ok: false,
      error: "python_not_found",
      errorMessage: "Python ≥ 3.9 not found on PATH.",
    });
    expect(mockSpawn).not.toHaveBeenCalled();
  });

  it("creates venv when venvDir does not exist", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    // venvDir does not exist -> first existsSync returns false
    // pip exists -> second existsSync returns true
    // wheel.json readable
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("pip")) return true;
      if (typeof p === "string" && p.includes(".whl")) return true;
      return false;
    });
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    // venv creation succeeds
    fakeSpawn(0);
    // pip install succeeds
    fakeSpawn(0);

    // After install, bridge is found
    mockFindBridgeBinary.mockResolvedValueOnce(null).mockResolvedValueOnce("/home/user/.arize/harness/venv/bin/arize-vscode-bridge");

    const result = await ensureBridge(defaultOpts());

    expect(result.ok).toBe(true);
    // First spawn call is venv creation
    expect(mockSpawn).toHaveBeenCalledTimes(2);
    const venvCall = mockSpawn.mock.calls[0];
    expect(venvCall[0]).toBe("/usr/bin/python3");
    expect(venvCall[1]).toEqual(expect.arrayContaining(["-m", "venv"]));
  });

  it("returns wheel_missing when wheel.json is absent", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    // venv already exists
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("venv")) return true;
      if (typeof p === "string" && p.includes("pip")) return true;
      return false;
    });
    // readFileSync throws (file missing)
    mockReadFileSync.mockImplementation(() => {
      throw new Error("ENOENT");
    });

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({
      ok: false,
      error: "wheel_missing",
      errorMessage: "Bundled bridge wheel is missing.",
    });
  });

  it("returns wheel_missing when wheel file is absent on disk", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("venv")) return true;
      if (typeof p === "string" && p.includes("pip")) return true;
      // wheel file does not exist
      if (typeof p === "string" && p.includes(".whl")) return false;
      return false;
    });
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({
      ok: false,
      error: "wheel_missing",
      errorMessage: "Bundled bridge wheel is missing.",
    });
  });

  it("returns pip_install_failed when pip exits non-zero", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("venv")) return true;
      if (typeof p === "string" && p.includes("pip")) return true;
      if (typeof p === "string" && p.includes(".whl")) return true;
      return false;
    });
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    // pip install fails
    fakeSpawn(1, "  Could not find wheel  \n");

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({
      ok: false,
      error: "pip_install_failed",
      errorMessage: "Could not find wheel",
    });
  });

  it("re-calls findBridgeBinary after successful install and propagates bridgePath", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("venv")) return true;
      if (typeof p === "string" && p.includes("pip")) return true;
      if (typeof p === "string" && p.includes(".whl")) return true;
      return false;
    });
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    // pip install succeeds
    fakeSpawn(0);

    // First call (step 1) returns null; second call (step 8) returns path
    mockFindBridgeBinary
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce("/home/user/.arize/harness/venv/bin/arize-vscode-bridge");

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({ ok: true, bridgePath: "/home/user/.arize/harness/venv/bin/arize-vscode-bridge" });
    expect(mockFindBridgeBinary).toHaveBeenCalledTimes(2);
  });

  it("returns binary_still_missing when bridge not found after install", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("venv")) return true;
      if (typeof p === "string" && p.includes("pip")) return true;
      if (typeof p === "string" && p.includes(".whl")) return true;
      return false;
    });
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    // pip install succeeds
    fakeSpawn(0);

    // Bridge still not found after install
    mockFindBridgeBinary.mockResolvedValue(null);

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({
      ok: false,
      error: "binary_still_missing",
      errorMessage: "Install completed but arize-vscode-bridge was not found.",
    });
  });

  it("concurrent calls share one underlying invocation", async () => {
    mockFindPython.mockResolvedValue("/usr/bin/python3");
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("venv")) return true;
      if (typeof p === "string" && p.includes("pip")) return true;
      if (typeof p === "string" && p.includes(".whl")) return true;
      return false;
    });
    mockReadFileSync.mockReturnValue(WHEEL_JSON);

    // pip install succeeds
    fakeSpawn(0);

    mockFindBridgeBinary
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce("/bridge");

    const [r1, r2] = await Promise.all([
      ensureBridge(defaultOpts()),
      ensureBridge(defaultOpts()),
    ]);

    expect(r1).toEqual(r2);
    // findPython called only once (shared invocation)
    expect(mockFindPython).toHaveBeenCalledTimes(1);
  });

  it("abort signal kills child process and throws AbortError", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    mockExistsSync.mockReturnValue(false);
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    const ac = new AbortController();

    // Create a child that does not auto-close — we'll abort it
    const child = new EventEmitter() as any;
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = jest.fn();
    child.stdin = null;
    mockSpawn.mockReturnValueOnce(child);

    const promise = ensureBridge(defaultOpts({ signal: ac.signal }));

    // Give event loop time to spawn
    await new Promise((r) => setImmediate(r));

    ac.abort();

    await expect(promise).rejects.toThrow("aborted");
    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
  });

  it("returns venv_create_failed when pip is missing in venv", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    mockExistsSync.mockImplementation((p: string) => {
      // venv directory exists
      if (typeof p === "string" && p.endsWith("venv")) return true;
      // pip does NOT exist
      if (typeof p === "string" && p.includes("pip")) return false;
      if (typeof p === "string" && p.includes(".whl")) return true;
      return false;
    });
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    const result = await ensureBridge(defaultOpts());

    expect(result.ok).toBe(false);
    expect(result.error).toBe("venv_create_failed");
    expect(result.errorMessage).toContain("Pip not found");
  });

  it("returns venv_create_failed when venv spawn exits non-zero", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    // venvDir doesn't exist
    mockExistsSync.mockReturnValue(false);

    fakeSpawn(1, "Error: ensurepip not available");

    const result = await ensureBridge(defaultOpts());

    expect(result).toEqual({
      ok: false,
      error: "venv_create_failed",
      errorMessage: "Error: ensurepip not available",
    });
  });

  it("streams onLog callbacks for spawned processes", async () => {
    mockFindPython.mockResolvedValueOnce("/usr/bin/python3");
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === "string" && p.includes("venv")) return true;
      if (typeof p === "string" && p.includes("pip")) return true;
      if (typeof p === "string" && p.includes(".whl")) return true;
      return false;
    });
    mockReadFileSync.mockReturnValueOnce(WHEEL_JSON);

    // pip install succeeds but emits output
    const child = new EventEmitter() as any;
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = jest.fn();
    child.stdin = null;
    mockSpawn.mockReturnValueOnce(child);

    mockFindBridgeBinary
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce("/bridge");

    const logs: Array<{ level: string; message: string }> = [];

    const promise = ensureBridge(
      defaultOpts({
        onLog: (level, message) => logs.push({ level, message }),
      }),
    );

    await new Promise((r) => setImmediate(r));
    child.stdout.emit("data", Buffer.from("Installing..."));
    child.stderr.emit("data", Buffer.from("WARNING: something"));
    child.emit("close", 0);

    const result = await promise;
    expect(result.ok).toBe(true);
    expect(logs).toEqual(
      expect.arrayContaining([
        { level: "info", message: "Installing..." },
        { level: "error", message: "WARNING: something" },
      ]),
    );
  });
});
