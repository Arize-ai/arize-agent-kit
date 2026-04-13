/**
 * Tests for vscode-extension/src/extension.ts (activation task)
 * Validates: activate/deactivate lifecycle, command registration,
 * sidebar provider registration, status bar creation/polling,
 * command handler behavior, and module integration.
 *
 * Run: node test/extension.test.js
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

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
console.log("\n[Source file validation]");

const extSrc = fs.readFileSync(path.join(ROOT, "src", "extension.ts"), "utf8");

assert("extension.ts exists", fs.existsSync(path.join(ROOT, "src", "extension.ts")));
assert("exports activate function", extSrc.includes("export async function activate"));
assert("exports deactivate function", extSrc.includes("export function deactivate"));
assert("activate is async", extSrc.includes("export async function activate"));
assert("deactivate is sync", extSrc.includes("export function deactivate(): void"));

// ---------------------------------------------------------------------------
// 1. Import validation — extension.ts imports all required modules
// ---------------------------------------------------------------------------
console.log("\n[Import validation]");

assert("imports findPython from ./python", extSrc.includes('import { findPython, getArizeInstallPath } from "./python"'));
assert("imports SidebarProvider from ./sidebar", extSrc.includes('import { SidebarProvider } from "./sidebar"'));
assert("imports openWizard from ./wizard", extSrc.includes('import { openWizard } from "./wizard"'));
assert("imports runInstallerCommand from ./installer", extSrc.includes('import { runInstallerCommand } from "./installer"'));
assert("imports status bar helpers from ./status", extSrc.includes('import { createStatusBarItem, updateStatusBar, StatusBarState } from "./status"'));
assert("imports vscode", extSrc.includes('import * as vscode from "vscode"'));

// ---------------------------------------------------------------------------
// 2. Command registration validation
// ---------------------------------------------------------------------------
console.log("\n[Command registration]");

assert("registers arize.setup command", extSrc.includes('registerCommand("arize.setup"'));
assert("registers arize.reconfigure command", extSrc.includes('registerCommand("arize.reconfigure"'));
assert("registers arize.startCollector command", extSrc.includes('registerCommand("arize.startCollector"'));
assert("registers arize.stopCollector command", extSrc.includes('registerCommand("arize.stopCollector"'));
assert("commands pushed to subscriptions", extSrc.includes("context.subscriptions.push"));

// ---------------------------------------------------------------------------
// 3. Sidebar provider registration
// ---------------------------------------------------------------------------
console.log("\n[Sidebar provider registration]");

assert("creates SidebarProvider", extSrc.includes("new SidebarProvider(context.extensionUri)"));
assert("registers webview view provider", extSrc.includes('registerWebviewViewProvider("arize-sidebar"'));
assert("sidebar pushed to subscriptions", (extSrc.match(/context\.subscriptions\.push/g) || []).length >= 2);

// ---------------------------------------------------------------------------
// 4. Status bar creation and lifecycle
// ---------------------------------------------------------------------------
console.log("\n[Status bar lifecycle]");

assert("calls createStatusBarItem", extSrc.includes("createStatusBarItem()"));
assert("status bar pushed to subscriptions", extSrc.includes("context.subscriptions.push(statusBarItem)"));
assert("deactivate disposes statusBarItem", extSrc.includes("statusBarItem.dispose()"));
assert("deactivate sets statusBarItem undefined", extSrc.includes("statusBarItem = undefined"));

// ---------------------------------------------------------------------------
// 5. Python detection on activation
// ---------------------------------------------------------------------------
console.log("\n[Python detection on activation]");

assert("calls findPython in activate", extSrc.includes("pythonPath = await findPython()"));
assert("shows warning when Python not found", extSrc.includes("showWarningMessage"));
assert("sets PythonRequired state when no Python", extSrc.includes("StatusBarState.PythonRequired"));

// ---------------------------------------------------------------------------
// 6. Polling logic
// ---------------------------------------------------------------------------
console.log("\n[Polling logic]");

assert("startPolling function defined", extSrc.includes("function startPolling()"));
assert("stopPolling function defined", extSrc.includes("function stopPolling()"));
assert("refreshStatusBar function defined", extSrc.includes("function refreshStatusBar()"));
assert("polling uses 30-second interval", extSrc.includes("30_000") || extSrc.includes("30000"));
assert("startPolling called in activate", extSrc.includes("startPolling()"));
assert("stopPolling called in deactivate", extSrc.includes("stopPolling()"));
assert("refreshStatusBar calls getArizeInstallPath", extSrc.includes("getArizeInstallPath()"));
assert("refreshStatusBar checks running status", extSrc.includes('output.includes("running")'));
assert("refreshStatusBar sets Running state", extSrc.includes("StatusBarState.Running"));
assert("refreshStatusBar sets Stopped state", extSrc.includes("StatusBarState.Stopped"));
assert("refreshStatusBar sets NotConfigured on error", extSrc.includes("StatusBarState.NotConfigured"));
assert("clearInterval in stopPolling", extSrc.includes("clearInterval(pollingInterval)"));

// ---------------------------------------------------------------------------
// 7. Command handler logic — setup & reconfigure
// ---------------------------------------------------------------------------
console.log("\n[Command handlers — setup & reconfigure]");

assert("handleSetup defined", extSrc.includes("async function handleSetup"));
assert("handleReconfigure defined", extSrc.includes("async function handleReconfigure"));
assert("handleSetup checks pythonPath", extSrc.includes("if (!pythonPath)"));
assert("handleSetup calls findPython if needed", extSrc.includes("pythonPath = await findPython()"));
assert("handleSetup shows error when no Python", extSrc.includes("showErrorMessage"));
assert("handleSetup calls openWizard", extSrc.includes("openWizard(context)"));
assert("handleReconfigure calls openWizard with prefill", extSrc.includes("openWizard(context, { prefill: true })"));

// ---------------------------------------------------------------------------
// 8. Command handler logic — collector start/stop
// ---------------------------------------------------------------------------
console.log("\n[Command handlers — collector start/stop]");

assert("handleStartCollector defined", extSrc.includes("async function handleStartCollector"));
assert("handleStopCollector defined", extSrc.includes("async function handleStopCollector"));
assert("start checks for installPath", extSrc.includes("if (!installPath)"));
assert("start calls runInstallerCommand with collector start", extSrc.includes('["collector", "start"]'));
assert("stop calls runInstallerCommand with collector stop", extSrc.includes('["collector", "stop"]'));
assert("start shows success message", extSrc.includes('"Arize: Collector started."'));
assert("stop shows success message", extSrc.includes('"Arize: Collector stopped."'));
assert("start handles error", extSrc.includes("Failed to start collector"));
assert("stop handles error", extSrc.includes("Failed to stop collector"));
assert("start refreshes status bar on success", extSrc.includes("refreshStatusBar()"));

// ---------------------------------------------------------------------------
// 9. TypeScript compilation
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
assert("tsc --noEmit passes", tscOk);

// ---------------------------------------------------------------------------
// 10. Build and load the bundle with comprehensive mock
// ---------------------------------------------------------------------------
console.log("\n[Bundle loading with mock]");

// Build fresh
try {
  execSync("npm run build", { cwd: ROOT, stdio: "pipe" });
  assert("build succeeds", true);
} catch (e) {
  assert("build succeeds", false);
  printSummary();
  process.exit(1);
}

assert("dist/extension.js exists after build", fs.existsSync(path.join(ROOT, "dist/extension.js")));

const bundle = fs.readFileSync(path.join(ROOT, "dist/extension.js"), "utf8");

// Verify key identifiers in bundle
assert("bundle contains arize.setup", bundle.includes("arize.setup"));
assert("bundle contains arize.reconfigure", bundle.includes("arize.reconfigure"));
assert("bundle contains arize.startCollector", bundle.includes("arize.startCollector"));
assert("bundle contains arize.stopCollector", bundle.includes("arize.stopCollector"));
assert("bundle contains arize-sidebar", bundle.includes("arize-sidebar"));
assert("bundle contains StatusBarState values", bundle.includes("notConfigured") && bundle.includes("pythonRequired") && bundle.includes("running") && bundle.includes("stopped"));
assert("bundle contains collector start/stop args", bundle.includes("collector"));
assert("bundle contains 30s polling interval", bundle.includes("30000") || bundle.includes("30_000") || bundle.includes("3e4"));

// ---------------------------------------------------------------------------
// 11. Load bundle and test activate/deactivate with rich mock
// ---------------------------------------------------------------------------
console.log("\n[Activate/deactivate with rich mock]");

const mockVscodePath = path.join(ROOT, "test", "_mock_vscode_ext.js");
const registeredCommands = {};
const disposables = [];
let infoMessages = [];
let errorMessages = [];
let warningMessages = [];
let createdStatusBarItems = [];
let registeredViewProviders = {};

fs.writeFileSync(mockVscodePath, `
const registeredCommands = {};
const disposables = [];
const infoMessages = [];
const errorMessages = [];
const warningMessages = [];
const createdStatusBarItems = [];
const registeredViewProviders = {};

module.exports = {
  window: {
    showInformationMessage: (msg) => { infoMessages.push(msg); return Promise.resolve(); },
    showErrorMessage: (msg) => { errorMessages.push(msg); return Promise.resolve(); },
    showWarningMessage: (msg) => { warningMessages.push(msg); return Promise.resolve(); },
    createStatusBarItem: (alignment, priority) => {
      const item = {
        alignment, priority,
        text: "", tooltip: "", command: "",
        show: () => {},
        hide: () => {},
        dispose: () => { item._disposed = true; },
        _disposed: false,
      };
      createdStatusBarItems.push(item);
      return item;
    },
    registerWebviewViewProvider: (viewId, provider) => {
      registeredViewProviders[viewId] = provider;
      return { dispose: () => {} };
    },
    createWebviewPanel: (viewType, title, showOptions, options) => ({
      webview: { html: "", options: {} },
      dispose: () => {},
    }),
  },
  commands: {
    registerCommand: (cmd, cb) => {
      registeredCommands[cmd] = cb;
      const disposable = { dispose: () => {} };
      disposables.push(disposable);
      return disposable;
    },
  },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ViewColumn: { One: 1 },
  Uri: {
    file: (f) => ({ fsPath: f, scheme: "file" }),
    joinPath: (uri, ...segments) => ({ fsPath: require("path").join(uri.fsPath, ...segments) }),
  },
  // Expose state for test assertions
  _test: {
    get registeredCommands() { return registeredCommands; },
    get disposables() { return disposables; },
    get infoMessages() { return infoMessages; },
    get errorMessages() { return errorMessages; },
    get warningMessages() { return warningMessages; },
    get createdStatusBarItems() { return createdStatusBarItems; },
    get registeredViewProviders() { return registeredViewProviders; },
    reset: () => {
      Object.keys(registeredCommands).forEach(k => delete registeredCommands[k]);
      disposables.length = 0;
      infoMessages.length = 0;
      errorMessages.length = 0;
      warningMessages.length = 0;
      createdStatusBarItems.length = 0;
      Object.keys(registeredViewProviders).forEach(k => delete registeredViewProviders[k]);
    },
  },
};
`);

// Monkey-patch require to intercept "vscode"
const Module = require("module");
const origResolve = Module._resolveFilename;
Module._resolveFilename = function(request, ...args) {
  if (request === "vscode") return mockVscodePath;
  return origResolve.call(this, request, ...args);
};

let ext, vscodeMock;
try {
  // Clear all relevant caches
  Object.keys(require.cache).forEach(k => {
    if (k.includes("dist/extension") || k.includes("_mock_vscode")) {
      delete require.cache[k];
    }
  });
  ext = require(path.join(ROOT, "dist/extension.js"));
  vscodeMock = require(mockVscodePath);
  assert("bundle loads successfully", true);
} catch (e) {
  assert("bundle loads successfully", false);
  console.log("    Load error:", e.message);
}

if (ext && vscodeMock) {
  assert("activate is exported", typeof ext.activate === "function");
  assert("deactivate is exported", typeof ext.deactivate === "function");

  // Test activate
  const testState = vscodeMock._test;
  testState.reset();

  const mockContext = {
    subscriptions: [],
    extensionUri: { fsPath: ROOT, scheme: "file" },
  };

  // activate is async; we test the synchronous parts
  const activatePromise = ext.activate(mockContext);

  // Since findPython is async and real (will find Python on this system),
  // the command registrations happen synchronously before await
  assert("commands registered synchronously", Object.keys(testState.registeredCommands).length === 4);
  assert("arize.setup command registered", "arize.setup" in testState.registeredCommands);
  assert("arize.reconfigure command registered", "arize.reconfigure" in testState.registeredCommands);
  assert("arize.startCollector command registered", "arize.startCollector" in testState.registeredCommands);
  assert("arize.stopCollector command registered", "arize.stopCollector" in testState.registeredCommands);

  assert("sidebar provider registered", "arize-sidebar" in testState.registeredViewProviders);
  assert("status bar item created", testState.createdStatusBarItems.length === 1);

  const statusItem = testState.createdStatusBarItems[0];
  assert("status bar has command arize.setup", statusItem.command === "arize.setup");
  assert("status bar item is not disposed", !statusItem._disposed);

  // subscriptions: 4 commands + 1 sidebar + 1 status bar = 6
  assert("context has 6 subscriptions", mockContext.subscriptions.length === 6);

  // Wait for activation to complete (Python detection)
  activatePromise.then(() => {
    // After activation completes, deactivate
    ext.deactivate();
    assert("deactivate runs without error", true);

    // Verify status bar disposed
    assert("status bar disposed after deactivate", statusItem._disposed);

    // Test command handler callbacks are functions
    assert("arize.setup handler is function", typeof testState.registeredCommands["arize.setup"] === "function");
    assert("arize.reconfigure handler is function", typeof testState.registeredCommands["arize.reconfigure"] === "function");
    assert("arize.startCollector handler is function", typeof testState.registeredCommands["arize.startCollector"] === "function");
    assert("arize.stopCollector handler is function", typeof testState.registeredCommands["arize.stopCollector"] === "function");

    // ---------------------------------------------------------------------------
    // 12. Test status.ts module directly
    // ---------------------------------------------------------------------------
    console.log("\n[status.ts module]");

    const statusSrc = fs.readFileSync(path.join(ROOT, "src", "status.ts"), "utf8");

    assert("StatusBarState enum has NotConfigured", statusSrc.includes('NotConfigured = "notConfigured"'));
    assert("StatusBarState enum has PythonRequired", statusSrc.includes('PythonRequired = "pythonRequired"'));
    assert("StatusBarState enum has Running", statusSrc.includes('Running = "running"'));
    assert("StatusBarState enum has Stopped", statusSrc.includes('Stopped = "stopped"'));

    assert("createStatusBarItem exported", statusSrc.includes("export function createStatusBarItem"));
    assert("updateStatusBar exported", statusSrc.includes("export function updateStatusBar"));

    // Verify status labels use correct codicons
    assert("NotConfigured uses circle-slash icon", statusSrc.includes("$(circle-slash)"));
    assert("PythonRequired uses warning icon", statusSrc.includes("$(warning)"));
    assert("Running uses pulse icon", statusSrc.includes("$(pulse)"));
    assert("Stopped uses debug-stop icon", statusSrc.includes("$(debug-stop)"));

    assert("status bar alignment Right", statusSrc.includes("StatusBarAlignment.Right"));
    assert("status bar priority 50", statusSrc.includes("50"));
    assert("createStatusBarItem calls show()", statusSrc.includes("item.show()"));
    assert("createStatusBarItem sets command", statusSrc.includes('item.command = "arize.setup"'));

    // ---------------------------------------------------------------------------
    // 13. Test installer.ts module
    // ---------------------------------------------------------------------------
    console.log("\n[installer.ts module]");

    const installerSrc = fs.readFileSync(path.join(ROOT, "src", "installer.ts"), "utf8");

    assert("runInstallerCommand exported", installerSrc.includes("export function runInstallerCommand"));
    assert("uses execFile", installerSrc.includes('import { execFile } from "child_process"'));
    assert("returns Promise<string>", installerSrc.includes("Promise<string>"));
    assert("has 30s timeout", installerSrc.includes("timeout: 30_000") || installerSrc.includes("timeout: 30000"));
    assert("rejects on error", installerSrc.includes("reject("));
    assert("resolves stdout on success", installerSrc.includes("resolve(stdout)"));
    assert("uses stderr for error message", installerSrc.includes("stderr"));

    // ---------------------------------------------------------------------------
    // 14. Test sidebar.ts module
    // ---------------------------------------------------------------------------
    console.log("\n[sidebar.ts module]");

    const sidebarSrc = fs.readFileSync(path.join(ROOT, "src", "sidebar.ts"), "utf8");

    assert("SidebarProvider exported", sidebarSrc.includes("export class SidebarProvider"));
    assert("implements WebviewViewProvider", sidebarSrc.includes("WebviewViewProvider"));
    assert("resolveWebviewView method", sidebarSrc.includes("resolveWebviewView"));
    assert("enables scripts in webview", sidebarSrc.includes("enableScripts: true"));
    assert("sets localResourceRoots", sidebarSrc.includes("localResourceRoots"));
    assert("returns valid HTML", sidebarSrc.includes("<!DOCTYPE html>"));

    // ---------------------------------------------------------------------------
    // 15. Test wizard.ts module
    // ---------------------------------------------------------------------------
    console.log("\n[wizard.ts module]");

    const wizardSrc = fs.readFileSync(path.join(ROOT, "src", "wizard.ts"), "utf8");

    assert("openWizard exported", wizardSrc.includes("export function openWizard"));
    assert("WizardOptions interface exported", wizardSrc.includes("export interface WizardOptions"));
    assert("prefill option defined", wizardSrc.includes("prefill?: boolean"));
    assert("creates webview panel", wizardSrc.includes("createWebviewPanel"));
    assert("panel type is arize-wizard", wizardSrc.includes('"arize-wizard"'));
    assert("panel title is Arize: Setup Wizard", wizardSrc.includes('"Arize: Setup Wizard"'));
    assert("uses ViewColumn.One", wizardSrc.includes("ViewColumn.One"));
    assert("enables scripts", wizardSrc.includes("enableScripts: true"));
    assert("prefill adds note in HTML", wizardSrc.includes("Pre-filling from existing configuration"));
    assert("generates valid HTML", wizardSrc.includes("<!DOCTYPE html>"));

    // ---------------------------------------------------------------------------
    // 16. Integration: sidebar provider resolveWebviewView
    // ---------------------------------------------------------------------------
    console.log("\n[Sidebar integration]");

    const sidebarProvider = testState.registeredViewProviders["arize-sidebar"];
    assert("sidebar provider is an object", typeof sidebarProvider === "object");

    if (sidebarProvider && typeof sidebarProvider.resolveWebviewView === "function") {
      const mockWebviewView = {
        webview: { options: {}, html: "" },
      };
      try {
        sidebarProvider.resolveWebviewView(mockWebviewView, {}, { isCancellationRequested: false });
        assert("resolveWebviewView runs without error", true);
        assert("webview html is set", mockWebviewView.webview.html.length > 0);
        assert("webview html is valid HTML", mockWebviewView.webview.html.includes("<!DOCTYPE html>"));
        assert("webview scripts enabled", mockWebviewView.webview.options.enableScripts === true);
      } catch (e) {
        assert("resolveWebviewView runs without error", false);
        console.log("    Error:", e.message);
      }
    }

    // ---------------------------------------------------------------------------
    // 17. Module-level state
    // ---------------------------------------------------------------------------
    console.log("\n[Module state management]");

    assert("statusBarItem is module-level", extSrc.includes("let statusBarItem: vscode.StatusBarItem | undefined"));
    assert("pollingInterval is module-level", extSrc.includes("let pollingInterval: ReturnType<typeof setInterval> | undefined"));
    assert("pythonPath is module-level", extSrc.includes("let pythonPath: string | null = null"));
    assert("deactivate nullifies pollingInterval", extSrc.includes("pollingInterval = undefined"));

    // ---------------------------------------------------------------------------
    // 18. Error handling patterns
    // ---------------------------------------------------------------------------
    console.log("\n[Error handling patterns]");

    assert("collector start catches errors", extSrc.includes("catch (err: unknown)"));
    assert("error type checked with instanceof", extSrc.includes("err instanceof Error"));
    assert("fallback to String(err)", extSrc.includes("String(err)"));
    assert("refreshStatusBar catches promise errors", extSrc.includes(".catch(()"));
    assert("refreshStatusBar null-checks statusBarItem", extSrc.includes("if (!statusBarItem)"));

    // Cleanup
    Module._resolveFilename = origResolve;
    try { fs.unlinkSync(mockVscodePath); } catch (e) {}

    printSummary();
    process.exit(failed > 0 ? 1 : 0);
  }).catch((e) => {
    Module._resolveFilename = origResolve;
    try { fs.unlinkSync(mockVscodePath); } catch (e2) {}
    console.log("  FAIL: activate() threw:", e.message);
    failed++;
    printSummary();
    process.exit(1);
  });
} else {
  Module._resolveFilename = origResolve;
  try { fs.unlinkSync(mockVscodePath); } catch (e) {}
  printSummary();
  process.exit(failed > 0 ? 1 : 0);
}
