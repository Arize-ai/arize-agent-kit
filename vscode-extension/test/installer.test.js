/**
 * Tests for vscode-extension/src/installer.ts
 * Validates InstallerBridge: command construction, path selection,
 * first-time vs subsequent install, flag building, error handling.
 *
 * Run: node test/installer.test.js
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");
const Module = require("module");
const { EventEmitter } = require("events");

const ROOT = path.resolve(__dirname, "..");
let passed = 0;
let failed = 0;

function assert(name, condition) {
  if (condition) {
    passed++;
    console.log(`  PASS: ${name}`);
  } else {
    failed++;
    console.log(`  FAIL: ${name}`);
  }
}

function printSummary() {
  console.log(`\n========================================`);
  console.log(`Total: ${passed + failed} | Passed: ${passed} | Failed: ${failed}`);
  console.log(`========================================\n`);
}

// ---------------------------------------------------------------------------
// 0. Source file validation
// ---------------------------------------------------------------------------
console.log("\n[Source validation]");

const srcPath = path.join(ROOT, "src", "installer.ts");
assert("src/installer.ts exists", fs.existsSync(srcPath));

const src = fs.readFileSync(srcPath, "utf8");
assert("exports InstallerBridge class", src.includes("export class InstallerBridge"));
assert("exports InstallOptions interface", src.includes("export interface InstallOptions"));
assert("exports InstallResult interface", src.includes("export interface InstallResult"));
assert("exports StatusResult interface", src.includes("export interface StatusResult"));

// ---------------------------------------------------------------------------
// 1. TypeScript compilation
// ---------------------------------------------------------------------------
console.log("\n[TypeScript compilation]");
let tscOk = false;
try {
  execSync("npx tsc --noEmit", { cwd: ROOT, stdio: "pipe" });
  tscOk = true;
} catch (e) {
  const stderr = e.stderr ? e.stderr.toString() : "";
  console.log("    tsc errors:", stderr.slice(0, 500));
}
assert("tsc --noEmit passes (installer.ts compiles)", tscOk);

// ---------------------------------------------------------------------------
// 2. Static source analysis
// ---------------------------------------------------------------------------
console.log("\n[Static source analysis]");

// Spawn helper
assert("uses child_process.spawn", src.includes('import { spawn } from "child_process"'));
assert("_spawn function defined", src.includes("function _spawn"));
assert("_spawn returns Promise<SpawnResult>", src.includes("Promise<SpawnResult>"));
assert("streams stdout via onOutput.fire", src.includes("onOutput.fire(text)"));
assert("captures stderr", src.includes("stderr += text"));

// Platform-aware paths
assert("checks win32 for bootstrapper", src.includes('process.platform === "win32"'));
assert("install.bat for Windows", src.includes('"install.bat"'));
assert("install.sh for Unix", src.includes('"install.sh"'));

// InstallerBridge methods
assert("runInstall method", src.includes("async runInstall(options: InstallOptions)"));
assert("runUninstall method", src.includes("async runUninstall(harness: string)"));
assert("getStatus method", src.includes("async getStatus()"));
assert("controlCollector method", src.includes('async controlCollector(action: "start" | "stop")'));
assert("dispose method", src.includes("dispose(): void"));

// Flag building
assert("_buildFlags maps apiKey to --api-key", src.includes('apiKey: "--api-key"'));
assert("_buildFlags maps spaceId to --space-id", src.includes('spaceId: "--space-id"'));
assert("_buildFlags maps otlpEndpoint to --otlp-endpoint", src.includes('otlpEndpoint: "--otlp-endpoint"'));
assert("_buildFlags maps phoenixEndpoint to --phoenix-endpoint", src.includes('phoenixEndpoint: "--phoenix-endpoint"'));
assert("_buildFlags adds --backend", src.includes('"--backend", options.backend'));
assert("_buildFlags adds --user-id", src.includes('"--user-id", options.userId'));
assert("_buildFlags adds --scope", src.includes('"--scope", options.scope'));
assert("_buildFlags adds --non-interactive", src.includes('"--non-interactive"'));

// Install path selection
assert("checks venv existence for path selection", src.includes("checkVenvExists()"));
assert("calls _bootstrapInstall when no venv", src.includes("this._bootstrapInstall(options)"));
assert("calls _directInstall when venv exists", src.includes("this._directInstall(arizeInstall, options)"));

// Uninstall
assert("uninstall passes --all for harness=all", src.includes('"--all"'));
assert("uninstall passes --harness flag", src.includes('"--harness", harness'));

// Status
assert("getStatus parses JSON", src.includes("JSON.parse(result.stdout)"));
assert("getStatus returns default on failure", src.includes('backend: "none"'));

// Error handling
assert("handles spawn errors in runUninstall", src.includes("catch (err)"));
assert("returns false from controlCollector on failure", src.includes("return false"));

// ---------------------------------------------------------------------------
// 3. Build the module for runtime testing
// ---------------------------------------------------------------------------
console.log("\n[Build for testing]");

const buildOutDir = path.join(ROOT, "test", "_build");
try {
  execSync(
    `npx esbuild src/installer.ts --bundle --outfile=test/_build/installer.js --format=cjs --platform=node --external:vscode`,
    { cwd: ROOT, stdio: "pipe" }
  );
  assert("esbuild compiles installer.ts", true);
} catch (e) {
  assert("esbuild compiles installer.ts", false);
  console.log("Build failed:", e.stderr ? e.stderr.toString().slice(0, 500) : e.message);
  printSummary();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// 4. Load with mocked vscode + child_process + python
// ---------------------------------------------------------------------------
console.log("\n[Module loading with mocks]");

// Track all spawn calls for verification
let spawnCalls = [];
let mockSpawnBehavior = { code: 0, stdout: "", stderr: "" };
let mockSpawnError = null;

// Create a mock child process
function createMockChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();

  // Schedule output delivery and close
  process.nextTick(() => {
    if (mockSpawnError) {
      child.emit("error", mockSpawnError);
      return;
    }
    if (mockSpawnBehavior.stdout) {
      child.stdout.emit("data", Buffer.from(mockSpawnBehavior.stdout));
    }
    if (mockSpawnBehavior.stderr) {
      child.stderr.emit("data", Buffer.from(mockSpawnBehavior.stderr));
    }
    child.emit("close", mockSpawnBehavior.code);
  });

  return child;
}

// Mock vscode
const mockVscodePath = path.join(ROOT, "test", "_mock_vscode_installer.js");
fs.writeFileSync(mockVscodePath, `
class MockEventEmitter {
  constructor() { this._listeners = []; }
  fire(data) { this._listeners.forEach(fn => fn(data)); }
  event(fn) { this._listeners.push(fn); return { dispose: () => {} }; }
  dispose() { this._listeners = []; }
}
module.exports = {
  EventEmitter: MockEventEmitter,
  window: { showInformationMessage: () => {} },
  commands: { registerCommand: () => ({ dispose: () => {} }) },
};
`);

// Intercept require() for vscode
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...args) {
  if (request === "vscode") return mockVscodePath;
  return origResolve.call(this, request, ...args);
};

// Patch child_process.spawn after loading
let installerMod;
try {
  delete require.cache[path.join(buildOutDir, "installer.js")];
  installerMod = require(path.join(buildOutDir, "installer.js"));
  assert("installer module loads with mocked vscode", true);
} catch (e) {
  assert("installer module loads with mocked vscode", false);
  console.log("Load error:", e.message);
  Module._resolveFilename = origResolve;
  printSummary();
  process.exit(1);
}

// Now we need to monkey-patch child_process.spawn in the loaded module.
// Since esbuild bundles the require, we need to patch it at the module level.
// The bundle will have captured the spawn reference. Let's patch it via the
// child_process module directly.
const child_process = require("child_process");
const originalSpawn = child_process.spawn;
child_process.spawn = function mockSpawn(cmd, args, opts) {
  spawnCalls.push({ cmd, args, opts });
  return createMockChild();
};

// Also need to mock checkVenvExists and getArizeInstallPath from python.ts
// Since these are bundled, we need to re-build with injection.
// Alternative: build installer.ts with python.ts externalized and mock it.

// Let's take a different approach — rebuild with a shim that we control.
child_process.spawn = originalSpawn; // restore temporarily
Module._resolveFilename = origResolve; // restore temporarily

// Create a mock python module
const mockPythonPath = path.join(ROOT, "test", "_mock_python.ts");
fs.writeFileSync(mockPythonPath, `
let _venvExists = false;
let _installPath: string | null = null;

export function checkVenvExists(): boolean { return _venvExists; }
export function getArizeInstallPath(): string | null { return _installPath; }

// Test helpers to control mock behavior
export function _setVenvExists(v: boolean): void { _venvExists = v; }
export function _setInstallPath(p: string | null): void { _installPath = p; }
`);

// Create a wrapper that imports installer with our mock python
const shimPath = path.join(ROOT, "test", "_installer_shim.ts");
fs.writeFileSync(shimPath, `
export { InstallerBridge } from "../src/installer";
export type { InstallOptions, InstallResult, StatusResult } from "../src/installer";
`);

// Build with an alias plugin to redirect ./python to our mock
// Actually, esbuild doesn't have alias easily. Let's use a different approach:
// copy installer.ts, modify the import, build that.
const installerSrc = fs.readFileSync(srcPath, "utf8");
const patchedSrc = installerSrc.replace(
  'import { checkVenvExists, getArizeInstallPath } from "./python";',
  'import { checkVenvExists, getArizeInstallPath, _setVenvExists, _setInstallPath } from "./mock_python";'
);
const patchedInstallerPath = path.join(ROOT, "test", "_patched_installer.ts");
const mockPythonSrcPath = path.join(ROOT, "test", "mock_python.ts");

fs.writeFileSync(patchedInstallerPath, patchedSrc);
fs.writeFileSync(mockPythonSrcPath, `
let _venvExists = false;
let _installPath: string | null = null;

export function checkVenvExists(): boolean { return _venvExists; }
export function getArizeInstallPath(): string | null { return _installPath; }
export function _setVenvExists(v: boolean): void { _venvExists = v; }
export function _setInstallPath(p: string | null): void { _installPath = p; }
`);

// Also need to export the mock controls from the patched installer
const patchedSrcWithExports = patchedSrc + `
export { _setVenvExists, _setInstallPath } from "./mock_python";
`;
fs.writeFileSync(patchedInstallerPath, patchedSrcWithExports);

try {
  execSync(
    `npx esbuild test/_patched_installer.ts --bundle --outfile=test/_build/installer_testable.js --format=cjs --platform=node --external:vscode`,
    { cwd: ROOT, stdio: "pipe" }
  );
  assert("esbuild compiles patched installer", true);
} catch (e) {
  assert("esbuild compiles patched installer", false);
  console.log("Build failed:", e.stderr ? e.stderr.toString().slice(0, 500) : e.message);
  printSummary();
  process.exit(1);
}

// Load with mocks
Module._resolveFilename = function (request, ...args) {
  if (request === "vscode") return mockVscodePath;
  return origResolve.call(this, request, ...args);
};

let mod;
try {
  delete require.cache[path.join(buildOutDir, "installer_testable.js")];
  mod = require(path.join(buildOutDir, "installer_testable.js"));
  assert("patched installer loads", true);
} catch (e) {
  assert("patched installer loads", false);
  console.log("Load error:", e.message);
  Module._resolveFilename = origResolve;
  printSummary();
  process.exit(1);
}

assert("InstallerBridge is exported", typeof mod.InstallerBridge === "function");
assert("_setVenvExists is exported", typeof mod._setVenvExists === "function");
assert("_setInstallPath is exported", typeof mod._setInstallPath === "function");

// Now patch child_process.spawn for all tests
child_process.spawn = function mockSpawn(cmd, args, opts) {
  spawnCalls.push({ cmd, args, opts });
  return createMockChild();
};

// ---------------------------------------------------------------------------
// 5. Test InstallerBridge constructor and onOutput
// ---------------------------------------------------------------------------
console.log("\n[InstallerBridge construction]");

const bridge = new mod.InstallerBridge("/fake/extension/root");
assert("bridge is an instance of InstallerBridge", bridge instanceof mod.InstallerBridge);
assert("bridge.onOutput exists", bridge.onOutput !== undefined);
assert("bridge.onOutput.fire is a function", typeof bridge.onOutput.fire === "function");

// ---------------------------------------------------------------------------
// 6. Test runInstall — first-time (no venv)
// ---------------------------------------------------------------------------
console.log("\n[runInstall — first-time bootstrap]");

async function testBootstrapInstall() {
  // Reset mocks
  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "Install complete", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(false);
  mod._setInstallPath(null);

  const result = await bridge.runInstall({
    harness: "claude",
    backend: "arize",
    credentials: { apiKey: "test-key", spaceId: "space-123" },
    userId: "user@test.com",
    scope: "project",
  });

  assert("bootstrap: result.success is true", result.success === true);
  assert("bootstrap: result.output contains stdout", result.output.includes("Install complete"));
  assert("bootstrap: result.error is undefined", result.error === undefined);

  // Verify spawn was called
  assert("bootstrap: spawn was called once", spawnCalls.length === 1);

  const call = spawnCalls[0];
  // On macOS/Linux, should call bash with install.sh
  if (process.platform === "win32") {
    assert("bootstrap win32: cmd is cmd.exe", call.cmd === "cmd.exe");
    assert("bootstrap win32: args start with /c", call.args[0] === "/c");
    assert("bootstrap win32: bootstrapper is install.bat", call.args[1].includes("install.bat"));
  } else {
    assert("bootstrap unix: cmd is bash", call.cmd === "bash");
    assert("bootstrap unix: first arg is install.sh path", call.args[0].includes("install.sh"));
  }

  // Verify harness is passed as positional arg
  const argsStr = call.args.join(" ");
  assert("bootstrap: harness claude in args", argsStr.includes("claude"));
  assert("bootstrap: --backend arize in args", argsStr.includes("--backend arize"));
  assert("bootstrap: --api-key in args", argsStr.includes("--api-key test-key"));
  assert("bootstrap: --space-id in args", argsStr.includes("--space-id space-123"));
  assert("bootstrap: --user-id in args", argsStr.includes("--user-id user@test.com"));
  assert("bootstrap: --scope in args", argsStr.includes("--scope project"));
  assert("bootstrap: --non-interactive in args", argsStr.includes("--non-interactive"));
}

// ---------------------------------------------------------------------------
// 7. Test runInstall — subsequent (venv exists)
// ---------------------------------------------------------------------------
async function testDirectInstall() {
  console.log("\n[runInstall — direct install (venv exists)]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "Configured", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const result = await bridge.runInstall({
    harness: "codex",
    backend: "phoenix",
    credentials: { phoenixEndpoint: "http://localhost:6006" },
  });

  assert("direct: result.success is true", result.success === true);
  assert("direct: spawn called once", spawnCalls.length === 1);

  const call = spawnCalls[0];
  assert("direct: cmd is arize-install path", call.cmd === "/fake/venv/bin/arize-install");
  assert("direct: first arg is harness name", call.args[0] === "codex");
  assert("direct: --non-interactive in args", call.args.includes("--non-interactive"));
  assert("direct: --backend phoenix", call.args.includes("--backend") && call.args[call.args.indexOf("--backend") + 1] === "phoenix");
  assert("direct: --phoenix-endpoint in args", call.args.includes("--phoenix-endpoint") && call.args[call.args.indexOf("--phoenix-endpoint") + 1] === "http://localhost:6006");

  // No apiKey or spaceId should be present
  assert("direct: no --api-key (not provided)", !call.args.includes("--api-key"));
  assert("direct: no --space-id (not provided)", !call.args.includes("--space-id"));
  assert("direct: no --user-id (not provided)", !call.args.includes("--user-id"));
  assert("direct: no --scope (not provided)", !call.args.includes("--scope"));
}

// ---------------------------------------------------------------------------
// 8. Test runInstall — failure
// ---------------------------------------------------------------------------
async function testInstallFailure() {
  console.log("\n[runInstall — process failure]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 1, stdout: "", stderr: "Error: bad config" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const result = await bridge.runInstall({
    harness: "cursor",
    backend: "arize",
    credentials: {},
  });

  assert("failure: result.success is false", result.success === false);
  assert("failure: result.error contains stderr", result.error && result.error.includes("Error: bad config"));
}

// ---------------------------------------------------------------------------
// 9. Test runInstall — spawn error
// ---------------------------------------------------------------------------
async function testInstallSpawnError() {
  console.log("\n[runInstall — spawn error]");

  spawnCalls = [];
  mockSpawnError = new Error("ENOENT: command not found");
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const result = await bridge.runInstall({
    harness: "claude",
    backend: "arize",
    credentials: {},
  });

  assert("spawn error: result.success is false", result.success === false);
  assert("spawn error: result.error contains error message", result.error && result.error.includes("ENOENT"));
}

// ---------------------------------------------------------------------------
// 10. Test runUninstall
// ---------------------------------------------------------------------------
async function testUninstall() {
  console.log("\n[runUninstall — single harness]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "Uninstalled claude", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const result = await bridge.runUninstall("claude");

  assert("uninstall: result.success is true", result.success === true);
  assert("uninstall: spawn called once", spawnCalls.length === 1);

  const call = spawnCalls[0];
  assert("uninstall: cmd is arize-install", call.cmd === "/fake/venv/bin/arize-install");
  assert("uninstall: first arg is 'uninstall'", call.args[0] === "uninstall");
  assert("uninstall: --non-interactive in args", call.args.includes("--non-interactive"));
  assert("uninstall: --harness claude", call.args.includes("--harness") && call.args[call.args.indexOf("--harness") + 1] === "claude");
  assert("uninstall: no --all flag", !call.args.includes("--all"));
}

async function testUninstallAll() {
  console.log("\n[runUninstall — all harnesses]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "Uninstalled all", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const result = await bridge.runUninstall("all");

  assert("uninstall-all: result.success is true", result.success === true);
  const call = spawnCalls[0];
  assert("uninstall-all: --all flag present", call.args.includes("--all"));
  assert("uninstall-all: no --harness flag", !call.args.includes("--harness"));
}

async function testUninstallNoInstall() {
  console.log("\n[runUninstall — arize-install not found]");

  spawnCalls = [];
  mod._setVenvExists(false);
  mod._setInstallPath(null);

  const result = await bridge.runUninstall("claude");

  assert("uninstall-missing: result.success is false", result.success === false);
  assert("uninstall-missing: error mentions not found", result.error && result.error.includes("not found"));
  assert("uninstall-missing: spawn not called", spawnCalls.length === 0);
}

// ---------------------------------------------------------------------------
// 11. Test getStatus
// ---------------------------------------------------------------------------
async function testGetStatus() {
  console.log("\n[getStatus — success]");

  const statusJson = JSON.stringify({
    collector: { running: true, port: 4318 },
    backend: "arize",
    harnesses: [{ name: "claude", project: "my-project" }],
  });

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: statusJson, stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const status = await bridge.getStatus();

  assert("status: collector.running is true", status.collector.running === true);
  assert("status: collector.port is 4318", status.collector.port === 4318);
  assert("status: backend is arize", status.backend === "arize");
  assert("status: one harness", status.harnesses.length === 1);
  assert("status: harness name is claude", status.harnesses[0].name === "claude");

  const call = spawnCalls[0];
  assert("status: calls arize-install status", call.args[0] === "status");
}

async function testGetStatusFailure() {
  console.log("\n[getStatus — failure returns defaults]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 1, stdout: "", stderr: "err" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const status = await bridge.getStatus();

  assert("status-fail: collector.running is false", status.collector.running === false);
  assert("status-fail: collector.port is 4318", status.collector.port === 4318);
  assert("status-fail: backend is none", status.backend === "none");
  assert("status-fail: harnesses is empty", status.harnesses.length === 0);
}

async function testGetStatusNoInstall() {
  console.log("\n[getStatus — no arize-install returns defaults]");

  spawnCalls = [];
  mod._setVenvExists(false);
  mod._setInstallPath(null);

  const status = await bridge.getStatus();

  assert("status-missing: returns defaults", status.backend === "none");
  assert("status-missing: spawn not called", spawnCalls.length === 0);
}

async function testGetStatusInvalidJson() {
  console.log("\n[getStatus — invalid JSON returns defaults]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "not json {{{", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const status = await bridge.getStatus();

  assert("status-badjson: returns defaults", status.backend === "none");
  assert("status-badjson: collector not running", status.collector.running === false);
}

// ---------------------------------------------------------------------------
// 12. Test controlCollector
// ---------------------------------------------------------------------------
async function testControlCollector() {
  console.log("\n[controlCollector — start]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const startResult = await bridge.controlCollector("start");
  assert("collector-start: returns true", startResult === true);

  const call = spawnCalls[0];
  assert("collector-start: args are [collector, start]", call.args[0] === "collector" && call.args[1] === "start");
}

async function testControlCollectorStop() {
  console.log("\n[controlCollector — stop]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const stopResult = await bridge.controlCollector("stop");
  assert("collector-stop: returns true", stopResult === true);

  const call = spawnCalls[0];
  assert("collector-stop: args are [collector, stop]", call.args[0] === "collector" && call.args[1] === "stop");
}

async function testControlCollectorFailure() {
  console.log("\n[controlCollector — failure]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 1, stdout: "", stderr: "failed" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const result = await bridge.controlCollector("start");
  assert("collector-fail: returns false", result === false);
}

async function testControlCollectorNoInstall() {
  console.log("\n[controlCollector — no arize-install]");

  spawnCalls = [];
  mod._setVenvExists(false);
  mod._setInstallPath(null);

  const result = await bridge.controlCollector("start");
  assert("collector-missing: returns false", result === false);
  assert("collector-missing: spawn not called", spawnCalls.length === 0);
}

// ---------------------------------------------------------------------------
// 13. Test output streaming
// ---------------------------------------------------------------------------
async function testOutputStreaming() {
  console.log("\n[Output streaming]");

  const bridge2 = new mod.InstallerBridge("/fake/ext");
  const outputChunks = [];
  bridge2.onOutput.event((text) => outputChunks.push(text));

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "line1\nline2", stderr: "warn" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  await bridge2.controlCollector("start");

  assert("streaming: received stdout", outputChunks.some(c => c.includes("line1")));
  assert("streaming: received stderr", outputChunks.some(c => c.includes("warn")));

  bridge2.dispose();
}

// ---------------------------------------------------------------------------
// 14. Test _buildFlags with minimal options
// ---------------------------------------------------------------------------
async function testMinimalFlags() {
  console.log("\n[_buildFlags — minimal options]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  await bridge.runInstall({
    harness: "claude",
    backend: "arize",
    credentials: {},
  });

  const call = spawnCalls[0];
  assert("minimal: --backend arize present", call.args.includes("--backend"));
  assert("minimal: --non-interactive present", call.args.includes("--non-interactive"));
  assert("minimal: no --api-key (empty credentials)", !call.args.includes("--api-key"));
  assert("minimal: no --space-id (empty credentials)", !call.args.includes("--space-id"));
  assert("minimal: no --user-id (not provided)", !call.args.includes("--user-id"));
  assert("minimal: no --scope (not provided)", !call.args.includes("--scope"));
}

// ---------------------------------------------------------------------------
// 15. Test _buildFlags with OTLP endpoint
// ---------------------------------------------------------------------------
async function testOtlpFlags() {
  console.log("\n[_buildFlags — OTLP endpoint]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  await bridge.runInstall({
    harness: "cursor",
    backend: "otlp",
    credentials: { otlpEndpoint: "http://collector:4318" },
  });

  const call = spawnCalls[0];
  const args = call.args;
  const otlpIdx = args.indexOf("--otlp-endpoint");
  assert("otlp: --otlp-endpoint present", otlpIdx !== -1);
  assert("otlp: endpoint value correct", otlpIdx !== -1 && args[otlpIdx + 1] === "http://collector:4318");
}

// ---------------------------------------------------------------------------
// 16. Test bootstrapper path construction
// ---------------------------------------------------------------------------
async function testBootstrapperPath() {
  console.log("\n[Bootstrapper path]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 0, stdout: "", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(false);
  mod._setInstallPath(null);

  await bridge.runInstall({
    harness: "claude",
    backend: "arize",
    credentials: {},
  });

  const call = spawnCalls[0];
  if (process.platform === "win32") {
    assert("path: bootstrapper is install.bat", call.args[1].endsWith("install.bat"));
  } else {
    assert("path: bootstrapper path is under extension parent", call.args[0].includes("install.sh"));
    assert("path: bootstrapper uses parent of extensionRoot", call.args[0].includes(path.join("/fake/extension", "install.sh")));
  }
}

// ---------------------------------------------------------------------------
// 17. Test dispose
// ---------------------------------------------------------------------------
async function testDispose() {
  console.log("\n[dispose]");

  const bridge3 = new mod.InstallerBridge("/fake/ext");
  // Should not throw
  let disposeOk = false;
  try {
    bridge3.dispose();
    disposeOk = true;
  } catch (e) {
    disposeOk = false;
  }
  assert("dispose does not throw", disposeOk);
}

// ---------------------------------------------------------------------------
// 18. Test exit code fallback (null code → 1)
// ---------------------------------------------------------------------------
console.log("\n[_spawn edge cases — source analysis]");
assert("null exit code defaults to 1", src.includes("code ?? 1"));
assert("stdio configured as ignore/pipe/pipe", src.includes('"ignore", "pipe", "pipe"'));
assert("env is spread from process.env", src.includes("...process.env"));

// ---------------------------------------------------------------------------
// 19. Test uninstall failure code path
// ---------------------------------------------------------------------------
async function testUninstallFailure() {
  console.log("\n[runUninstall — process failure]");

  spawnCalls = [];
  mockSpawnBehavior = { code: 2, stdout: "", stderr: "" };
  mockSpawnError = null;
  mod._setVenvExists(true);
  mod._setInstallPath("/fake/venv/bin/arize-install");

  const result = await bridge.runUninstall("claude");

  assert("uninstall-fail: success is false", result.success === false);
  assert("uninstall-fail: error has exit code message", result.error && result.error.includes("code 2"));
}

// ---------------------------------------------------------------------------
// Run all async tests sequentially
// ---------------------------------------------------------------------------
(async () => {
  try {
    await testBootstrapInstall();
    await testDirectInstall();
    await testInstallFailure();
    await testInstallSpawnError();
    await testUninstall();
    await testUninstallAll();
    await testUninstallNoInstall();
    await testGetStatus();
    await testGetStatusFailure();
    await testGetStatusNoInstall();
    await testGetStatusInvalidJson();
    await testControlCollector();
    await testControlCollectorStop();
    await testControlCollectorFailure();
    await testControlCollectorNoInstall();
    await testOutputStreaming();
    await testMinimalFlags();
    await testOtlpFlags();
    await testBootstrapperPath();
    await testDispose();
    await testUninstallFailure();
  } catch (e) {
    console.log("\n  UNEXPECTED ERROR:", e.message);
    console.log(e.stack);
    failed++;
  } finally {
    // Restore
    child_process.spawn = originalSpawn;
    Module._resolveFilename = origResolve;

    // Cleanup temp files
    try { fs.unlinkSync(mockVscodePath); } catch {}
    try { fs.unlinkSync(mockPythonSrcPath); } catch {}
    try { fs.unlinkSync(patchedInstallerPath); } catch {}
    try { fs.unlinkSync(shimPath); } catch {}
    try { fs.unlinkSync(path.join(ROOT, "test", "_mock_python.ts")); } catch {}

    printSummary();
    process.exit(failed > 0 ? 1 : 0);
  }
})();
