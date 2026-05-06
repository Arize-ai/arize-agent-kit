/**
 * Tests for build-wheel.js
 *
 * Mocks child_process, fs, and fs/promises so no Python is required.
 */

const path = require("path");
const { EventEmitter } = require("events");

// ── Track spawn / spawnSync calls ────────────────────────────────────────

let spawnSyncResults;
let spawnCallLog;
let spawnHandler;

jest.mock("child_process", () => ({
  spawnSync: jest.fn((...args) => {
    spawnCallLog.push({ type: "spawnSync", args });
    if (typeof spawnSyncResults === "function") return spawnSyncResults(...args);
    return { status: 1 };
  }),
  spawn: jest.fn((...args) => {
    spawnCallLog.push({ type: "spawn", args });
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    if (spawnHandler) return spawnHandler(child, args);
    // Default: succeed immediately
    process.nextTick(() => child.emit("close", 0));
    return child;
  }),
}));

// ── Mock fs/promises ─────────────────────────────────────────────────────

let readdirResult;
let readFileResult;
let writeFileCalls;

jest.mock("fs/promises", () => ({
  rm: jest.fn(() => Promise.resolve()),
  mkdir: jest.fn(() => Promise.resolve()),
  readdir: jest.fn(() => Promise.resolve(readdirResult || [])),
  readFile: jest.fn(() =>
    Promise.resolve(
      readFileResult ||
        '[project]\nname = "arize-harness-tracing"\nversion = "0.1.0"\n'
    )
  ),
  writeFile: jest.fn((...args) => {
    writeFileCalls.push(args);
    return Promise.resolve();
  }),
}));

jest.mock("fs", () => ({
  ...jest.requireActual("fs"),
  existsSync: jest.fn(() => true),
}));

// ── Import module under test AFTER mocks ─────────────────────────────────

const { main } = require("../build-wheel");

// ── Helpers ──────────────────────────────────────────────────────────────

const savedPlatform = process.platform;

function setPlatform(value) {
  Object.defineProperty(process, "platform", { value, configurable: true });
}

// ── Test suite ───────────────────────────────────────────────────────────

beforeEach(() => {
  spawnCallLog = [];
  writeFileCalls = [];
  readdirResult = ["arize_harness_tracing-0.1.0-py3-none-any.whl"];
  readFileResult = '[project]\nname = "arize-harness-tracing"\nversion = "0.1.0"\n';
  spawnSyncResults = (cmd) => {
    // First qualifying python candidate succeeds
    if (cmd === "python3" || cmd === "py") return { status: 0 };
    return { status: 1 };
  };
  spawnHandler = null;
  setPlatform(savedPlatform);
});

afterEach(() => {
  setPlatform(savedPlatform);
  jest.clearAllMocks();
});

describe("build-wheel main()", () => {
  test("succeeds when build produces exactly one .whl", async () => {
    const result = await main();

    expect(result.version).toBe("0.1.0");
    expect(result.wheelPath).toContain("arize_harness_tracing-0.1.0-py3-none-any.whl");

    // wheel.json was written
    expect(writeFileCalls.length).toBe(1);
    const [filePath, content] = writeFileCalls[0];
    expect(filePath).toContain("wheel.json");
    const parsed = JSON.parse(content);
    expect(parsed.filename).toBe("arize_harness_tracing-0.1.0-py3-none-any.whl");
    expect(parsed.version).toBe("0.1.0");
  });

  test("rejects when no .whl files exist after build", async () => {
    readdirResult = [];
    await expect(main()).rejects.toThrow(/no wheel/i);
  });

  test("rejects when multiple .whl files exist after build", async () => {
    readdirResult = ["a-0.1.0-py3-none-any.whl", "b-0.2.0-py3-none-any.whl"];
    await expect(main()).rejects.toThrow(/multiple/i);
  });

  test("rejects when no qualifying python is found", async () => {
    spawnSyncResults = () => ({ status: 1 });
    await expect(main()).rejects.toThrow(/No Python/);
  });

  test("Windows discovery tries py -3 first", async () => {
    setPlatform("win32");

    // Only py -3 succeeds
    spawnSyncResults = (cmd, args) => {
      if (cmd === "py" && args && args[0] === "-3") return { status: 0 };
      return { status: 1 };
    };

    await main();

    // The first spawnSync call should be for "py" with ["-3", ...]
    const syncCalls = spawnCallLog.filter((c) => c.type === "spawnSync");
    expect(syncCalls.length).toBeGreaterThan(0);
    expect(syncCalls[0].args[0]).toBe("py");
    expect(syncCalls[0].args[1][0]).toBe("-3");
  });
});
