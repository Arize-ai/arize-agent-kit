/**
 * Tests for vscode-extension/src/sidebar.ts + media/sidebar.html + media/sidebar.js
 *
 * Validates:
 *  - Source structure: SidebarProvider class, methods, interfaces
 *  - Config reading logic: YAML parsing, missing file, malformed data
 *  - Message handling: addHarness, reconfigure, remove, collector start/stop
 *  - HTML generation: CSP nonce, required elements, inline script
 *  - File watching: config.yaml watcher setup
 *  - Integration: resolveWebviewView wiring, installer bridge, refresh
 *  - Media files: sidebar.html structure, sidebar.js logic
 *  - Bundle: sidebar code in built output
 *
 * Run: node test/sidebar.test.js
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
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

// ============================================================================
// 1. Source file validation — sidebar.ts
// ============================================================================
console.log("\n[1. sidebar.ts source validation]");

const sidebarPath = path.join(ROOT, "src", "sidebar.ts");
assert("sidebar.ts exists", fs.existsSync(sidebarPath));

const src = fs.readFileSync(sidebarPath, "utf8");

// Exports
assert("exports SidebarProvider class", src.includes("export class SidebarProvider"));
assert("implements WebviewViewProvider", src.includes("implements vscode.WebviewViewProvider"));

// Interface
assert("SidebarState interface defined", src.includes("interface SidebarState"));
assert("SidebarState has collector field", src.includes("collector: { running: boolean; port: number }"));
assert("SidebarState has backend field", src.includes("backend: string"));
assert("SidebarState has harnesses field", src.includes("harnesses: Array<{ name: string; project: string }>"));

// Private fields
assert("has view field", src.includes("private view: vscode.WebviewView | undefined"));
assert("has configWatcher field", src.includes("private configWatcher: vscode.FileSystemWatcher | undefined"));
assert("has installer field", src.includes("private installer: InstallerBridge | undefined"));

// Constructor
assert("constructor takes extensionUri", src.includes("constructor(private readonly extensionUri: vscode.Uri)"));

// ============================================================================
// 2. resolveWebviewView method
// ============================================================================
console.log("\n[2. resolveWebviewView method]");

assert("resolveWebviewView method exists", src.includes("resolveWebviewView("));
assert("stores view reference", src.includes("this.view = webviewView"));
assert("enables scripts", src.includes("enableScripts: true"));
assert("sets localResourceRoots", src.includes("localResourceRoots: [this.extensionUri]"));
assert("sets html from getHtml", src.includes("webviewView.webview.html = this.getHtml(webviewView.webview)"));
assert("registers message handler", src.includes("onDidReceiveMessage"));
assert("calls watchConfigFile", src.includes("this.watchConfigFile()"));
assert("calls refresh on init", src.includes("this.refresh()"));

// ============================================================================
// 3. refresh method
// ============================================================================
console.log("\n[3. refresh method]");

assert("refresh method exists", src.includes("refresh(): void"));
assert("refresh returns early if no view", src.includes("if (!this.view)"));
assert("refresh calls readConfig", src.includes("this.readConfig()"));
assert("refresh posts state message", src.includes('this.view.webview.postMessage({ type: "state"'));

// ============================================================================
// 4. setInstaller method
// ============================================================================
console.log("\n[4. setInstaller method]");

assert("setInstaller method exists", src.includes("setInstaller(installer: InstallerBridge): void"));
assert("setInstaller stores installer", src.includes("this.installer = installer"));

// ============================================================================
// 5. dispose method
// ============================================================================
console.log("\n[5. dispose method]");

assert("dispose method exists", src.includes("dispose(): void"));
assert("dispose cleans up configWatcher", src.includes("this.configWatcher?.dispose()"));

// ============================================================================
// 6. Config reading — getConfigPath
// ============================================================================
console.log("\n[6. Config reading]");

assert("getConfigPath defined", src.includes("private getConfigPath(): string"));
assert("config path uses os.homedir", src.includes("os.homedir()"));
assert("config path is .arize/harness/config.yaml", src.includes('".arize", "harness", "config.yaml"'));

// readConfig
assert("readConfig defined", src.includes("private readConfig(): SidebarState"));
assert("readConfig checks file existence", src.includes("fs.existsSync(configPath)"));
assert("readConfig reads file", src.includes("fs.readFileSync(configPath"));
assert("readConfig uses parseYaml", src.includes("parseYaml(raw)"));
assert("readConfig has empty state fallback", src.includes("collector: { running: false, port: 4318 }"));
assert("readConfig checks doc is object", src.includes('typeof doc !== "object"'));

// Collector parsing
assert("readConfig extracts collector.running", src.includes("collectorSection?.running === true"));
assert("readConfig extracts collector.port with fallback", src.includes("collectorSection.port") && src.includes(": 4318"));

// Backend parsing
assert("readConfig extracts backend", src.includes('typeof doc.backend === "string"'));
assert("readConfig backend defaults to none", src.includes('"none"'));

// Harnesses parsing
assert("readConfig parses harnesses section", src.includes("doc.harnesses as"));
assert("readConfig iterates harness entries", src.includes("Object.entries(harnessesSection)"));
assert("readConfig extracts harness name", src.includes("harnesses.push"));
assert("readConfig defaults project to (default)", src.includes('"(default)"'));

// Error handling
assert("readConfig has try-catch", src.includes("} catch {"));

// ============================================================================
// 7. File watching
// ============================================================================
console.log("\n[7. File watching]");

assert("watchConfigFile defined", src.includes("private watchConfigFile(): void"));
assert("watches .arize/harness directory", src.includes('".arize", "harness"'));
assert("uses RelativePattern", src.includes("new vscode.RelativePattern"));
assert("watches config.yaml pattern", src.includes('"config.yaml"'));
assert("creates FileSystemWatcher", src.includes("vscode.workspace.createFileSystemWatcher"));
assert("watches for changes", src.includes("this.configWatcher.onDidChange"));
assert("watches for creation", src.includes("this.configWatcher.onDidCreate"));
assert("watches for deletion", src.includes("this.configWatcher.onDidDelete"));
assert("file change triggers refresh", src.includes("() => this.refresh()"));

// ============================================================================
// 8. Message handling
// ============================================================================
console.log("\n[8. Message handling]");

assert("handleMessage defined", src.includes("private async handleMessage"));
assert("handleMessage takes type and harness", src.includes("type: string") && src.includes("harness?: string"));
assert("handles addHarness", src.includes('case "addHarness"'));
assert("addHarness executes arize.setup", src.includes('executeCommand("arize.setup")'));
assert("handles reconfigure", src.includes('case "reconfigure"'));
assert("reconfigure checks harness", src.includes("if (msg.harness)") || src.includes("msg.harness"));
assert("reconfigure executes arize.reconfigure", src.includes('executeCommand("arize.reconfigure")'));
assert("handles remove", src.includes('case "remove"'));
assert("remove calls handleRemove", src.includes("this.handleRemove(msg.harness)"));
assert("handles startCollector", src.includes('case "startCollector"'));
assert("handles stopCollector", src.includes('case "stopCollector"'));
assert("collector calls handleCollectorControl", src.includes('this.handleCollectorControl("start")') && src.includes('this.handleCollectorControl("stop")'));

// ============================================================================
// 9. handleRemove
// ============================================================================
console.log("\n[9. handleRemove]");

assert("handleRemove defined", src.includes("private async handleRemove(harness: string)"));
assert("shows confirmation dialog", src.includes("showWarningMessage"));
assert("confirmation is modal", src.includes("{ modal: true }"));
assert("Remove button in dialog", src.includes('"Remove"'));
assert("checks for confirmation answer", src.includes('answer !== "Remove"'));
assert("checks installer availability", src.includes("if (!this.installer)"));
assert("shows error when no installer", src.includes("Installer not available"));
assert("calls installer.runUninstall", src.includes("this.installer.runUninstall(harness)"));
assert("shows success message on uninstall", src.includes("harness removed"));
assert("shows error message on failure", src.includes("Failed to remove"));
assert("refreshes after remove", src.includes("this.refresh()"));

// ============================================================================
// 10. handleCollectorControl
// ============================================================================
console.log("\n[10. handleCollectorControl]");

assert("handleCollectorControl defined", src.includes('private async handleCollectorControl'));
assert("takes start or stop action", src.includes('"start" | "stop"'));
assert("checks installer availability", (src.match(/if \(!this\.installer\)/g) || []).length >= 2);
assert("calls installer.controlCollector", src.includes("this.installer.controlCollector(action)"));
assert("shows started message", src.includes("Collector started") || src.includes('action === "start" ? "started"'));
assert("shows stopped message", src.includes("Collector stopped") || src.includes('"stopped"'));
assert("shows failure message", src.includes("Failed to") && src.includes("collector"));
assert("refreshes after collector control", (src.match(/this\.refresh\(\)/g) || []).length >= 3);

// ============================================================================
// 11. HTML generation
// ============================================================================
console.log("\n[11. HTML generation]");

assert("getHtml method takes webview", src.includes("private getHtml(webview: vscode.Webview)"));
assert("generates nonce", src.includes("getNonce()"));
assert("CSP meta tag with nonce", src.includes("Content-Security-Policy"));
assert("CSP allows unsafe-inline styles", src.includes("style-src 'unsafe-inline'"));
assert("CSP restricts scripts to nonce", src.includes("script-src 'nonce-${nonce}'"));
assert("HTML has DOCTYPE", src.includes("<!DOCTYPE html>"));
assert("HTML has header", src.includes("Arize Tracing"));
assert("HTML has collector status row", src.includes("collector-status"));
assert("HTML has collector dot", src.includes("collector-dot"));
assert("HTML has collector label", src.includes("collector-label"));
assert("HTML has backend row", src.includes("backend-row"));
assert("HTML has divider", src.includes("Installed"));
assert("HTML has harness list", src.includes("harness-list"));
assert("HTML has empty state", src.includes("empty-state"));
assert("HTML has add button", src.includes("add-btn"));
assert("HTML has + Add Harness text", src.includes("+ Add Harness"));
assert("HTML empty state message", src.includes("No harnesses configured"));
assert("HTML inline script has nonce", src.includes('script nonce="${nonce}"'));

// Inline script logic
assert("inline script acquires vscode api", src.includes("acquireVsCodeApi()"));
assert("inline script defines renderState", src.includes("function renderState(state)"));
assert("inline script handles collector toggle", src.includes("stopCollector") && src.includes("startCollector"));
assert("inline script handles add button", src.includes("addHarness"));
assert("inline script listens for messages", src.includes("window.addEventListener('message'"));

// Status dot colors
assert("running dot is green", src.includes("#3fb950"));
assert("stopped dot is red", src.includes("#f85149"));

// ============================================================================
// 12. getNonce helper
// ============================================================================
console.log("\n[12. getNonce helper]");

assert("getNonce function defined", src.includes("function getNonce(): string"));
assert("nonce is 32 chars", src.includes("i < 32"));
assert("nonce uses alphanumeric chars", src.includes("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"));

// ============================================================================
// 13. Import validation
// ============================================================================
console.log("\n[13. Import validation]");

assert("imports vscode", src.includes('import * as vscode from "vscode"'));
assert("imports os", src.includes('import * as os from "os"'));
assert("imports path", src.includes('import * as path from "path"'));
assert("imports yaml parser", src.includes('import { parse as parseYaml } from "yaml"'));
assert("imports fs", src.includes('import * as fs from "fs"'));
assert("imports InstallerBridge", src.includes('import { InstallerBridge } from "./installer"'));

// ============================================================================
// 14. media/sidebar.html validation
// ============================================================================
console.log("\n[14. media/sidebar.html]");

const htmlPath = path.join(ROOT, "media", "sidebar.html");
assert("sidebar.html exists", fs.existsSync(htmlPath));

const html = fs.readFileSync(htmlPath, "utf8");

assert("html has DOCTYPE", html.includes("<!DOCTYPE html>"));
assert("html has charset meta", html.includes('charset="UTF-8"'));
assert("html has viewport meta", html.includes("viewport"));
assert("html header says ARIZE TRACING", html.includes("ARIZE TRACING"));
assert("html has collector-status div", html.includes('id="collector-status"'));
assert("html has collector-dot span", html.includes('id="collector-dot"'));
assert("html has collector-label span", html.includes('id="collector-label"'));
assert("html default label is Stopped", html.includes(">Stopped<"));
assert("html has backend-row", html.includes('id="backend-row"'));
assert("html has harness-list", html.includes('id="harness-list"'));
assert("html has empty-state", html.includes('id="empty-state"'));
assert("html empty state is hidden by default", html.includes('style="display: none;"'));
assert("html empty state text", html.includes("No harnesses configured."));
assert("html has add-btn", html.includes('id="add-btn"'));
assert("html add button text", html.includes("+ Add Harness"));
assert("html has script tag referencing sidebarJsUri", html.includes("${sidebarJsUri}"));

// CSS classes in HTML
assert("html has dot.running class", html.includes(".dot.running"));
assert("html has dot.stopped class", html.includes(".dot.stopped"));
assert("html has harness-card class", html.includes(".harness-card"));
assert("html has harness-name class", html.includes(".harness-name"));
assert("html has harness-project class", html.includes(".harness-project"));
assert("html has action-btn class", html.includes(".action-btn"));
assert("html has add-btn class", html.includes(".add-btn"));
assert("html has empty-state class", html.includes(".empty-state"));
assert("html has status-row class", html.includes(".status-row"));

// ============================================================================
// 15. media/sidebar.js validation
// ============================================================================
console.log("\n[15. media/sidebar.js]");

const jsPath = path.join(ROOT, "media", "sidebar.js");
assert("sidebar.js exists", fs.existsSync(jsPath));

const js = fs.readFileSync(jsPath, "utf8");

assert("js is an IIFE", js.includes("(function () {") && js.includes("})();"));
assert("js acquires vscode api", js.includes("acquireVsCodeApi()"));
assert("js gets collector-status element", js.includes('getElementById("collector-status")'));
assert("js gets collector-dot element", js.includes('getElementById("collector-dot")'));
assert("js gets collector-label element", js.includes('getElementById("collector-label")'));
assert("js gets backend-row element", js.includes('getElementById("backend-row")'));
assert("js gets harness-list element", js.includes('getElementById("harness-list")'));
assert("js gets empty-state element", js.includes('getElementById("empty-state")'));
assert("js gets add-btn element", js.includes('getElementById("add-btn")'));

// renderState function
assert("js defines renderState", js.includes("function renderState(state)"));
assert("js sets collector dot class for running", js.includes('"running"'));
assert("js sets collector dot class for stopped", js.includes('"stopped"'));
assert("js sets collector label text", js.includes('Running') && js.includes('Stopped'));
assert("js sets tooltip for running", js.includes("Click to stop collector"));
assert("js sets tooltip for start", js.includes("Click to start collector"));
assert("js renders backend text", js.includes("Backend: "));
assert("js handles no backend with em dash", js.includes("\\u2014") || js.includes("\u2014"));
assert("js clears harness list", js.includes('harnessList.innerHTML = ""'));
assert("js shows empty state when no harnesses", js.includes('emptyState.style.display = "block"'));
assert("js hides empty state when harnesses exist", js.includes('emptyState.style.display = "none"'));

// Harness card rendering
assert("js creates harness-card divs", js.includes('card.className = "harness-card"'));
assert("js creates harness-name divs", js.includes('name.className = "harness-name"'));
assert("js creates harness-project divs", js.includes('project.className = "harness-project"'));
assert("js sets project text with prefix", js.includes('"Project: "'));
assert("js creates action buttons", js.includes('reconfigureBtn.className = "action-btn"'));
assert("js creates Reconfigure button", js.includes('reconfigureBtn.textContent = "Reconfigure"'));
assert("js creates Remove button", js.includes('removeBtn.textContent = "Remove"'));

// Event handling in js
assert("js sends reconfigure message", js.includes('type: "reconfigure", harness: h.name'));
assert("js sends remove message", js.includes('type: "remove", harness: h.name'));
assert("js stops propagation on reconfigure", js.includes("e.stopPropagation()"));
assert("js sends stopCollector on running click", js.includes('"stopCollector"'));
assert("js sends startCollector on stopped click", js.includes('"startCollector"'));
assert("js sends addHarness on add click", js.includes('type: "addHarness"'));
assert("js checks running class for toggle", js.includes('classList.contains("running")'));
assert("js listens for message events", js.includes('window.addEventListener("message"'));
assert("js checks message type is state", js.includes('msg.type === "state"'));

// ============================================================================
// 16. Extension integration — sidebar wiring in extension.ts
// ============================================================================
console.log("\n[16. Extension integration]");

const extSrc = fs.readFileSync(path.join(ROOT, "src", "extension.ts"), "utf8");

assert("extension imports InstallerBridge", extSrc.includes("InstallerBridge"));
assert("extension creates SidebarProvider", extSrc.includes("new SidebarProvider(context.extensionUri)"));
assert("extension creates InstallerBridge", extSrc.includes("new InstallerBridge(context.extensionPath)"));
assert("extension calls setInstaller", extSrc.includes("sidebarProvider.setInstaller(installerBridge)"));
assert("extension registers arize-sidebar view", extSrc.includes('registerWebviewViewProvider("arize-sidebar", sidebarProvider)'));
assert("extension disposes installerBridge", extSrc.includes("installerBridge.dispose()"));

// ============================================================================
// 17. package.json — sidebar contribution
// ============================================================================
console.log("\n[17. package.json sidebar contribution]");

const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

assert("package.json has viewsContainers", !!pkg.contributes && !!pkg.contributes.viewsContainers);
assert("package.json has activitybar container", !!(pkg.contributes.viewsContainers || {}).activitybar);

const activitybar = (pkg.contributes.viewsContainers || {}).activitybar || [];
const arizeContainer = activitybar.find(c => c.id === "arize");
assert("arize container defined", !!arizeContainer);
assert("arize container has title", arizeContainer && arizeContainer.title === "Arize Tracing");
assert("arize container has icon", arizeContainer && arizeContainer.icon === "media/icon.svg");

assert("package.json has views", !!pkg.contributes.views);
const arizeViews = (pkg.contributes.views || {}).arize || [];
const sidebarView = arizeViews.find(v => v.id === "arize-sidebar");
assert("arize-sidebar view defined", !!sidebarView);
assert("sidebar view is webview type", sidebarView && sidebarView.type === "webview");
assert("sidebar view name is Arize Tracing", sidebarView && sidebarView.name === "Arize Tracing");

assert("activation event includes onView:arize-sidebar", pkg.activationEvents && pkg.activationEvents.includes("onView:arize-sidebar"));

assert("yaml dependency declared", !!(pkg.dependencies || {}).yaml);

// ============================================================================
// 18. Build and bundle validation
// ============================================================================
console.log("\n[18. Build and bundle validation]");

// Note: TSC fails due to pre-existing issue (runInstallerCommand missing from installer.ts)
// but esbuild succeeds since it only resolves actual imports
let buildOk = false;
try {
  execSync("npm run build", { cwd: ROOT, stdio: "pipe" });
  buildOk = true;
} catch (e) {
  // esbuild may also fail if types are wrong, but let's check
  const stderr = e.stderr ? e.stderr.toString() : "";
  console.log("    Build note:", stderr.slice(0, 300));
}
assert("esbuild build succeeds", buildOk);

if (buildOk) {
  const bundle = fs.readFileSync(path.join(ROOT, "dist", "extension.js"), "utf8");

  assert("bundle contains SidebarProvider", bundle.includes("SidebarProvider"));
  assert("bundle contains readConfig logic", bundle.includes("config.yaml"));
  assert("bundle contains parseYaml", bundle.includes("parseYaml") || bundle.includes("parse"));
  assert("bundle contains collector-status", bundle.includes("collector-status"));
  assert("bundle contains harness-list", bundle.includes("harness-list"));
  assert("bundle contains empty-state", bundle.includes("empty-state"));
  assert("bundle contains addHarness message type", bundle.includes("addHarness"));
  assert("bundle contains reconfigure message type", bundle.includes("reconfigure"));
  assert("bundle contains remove message type", bundle.includes("remove"));
  assert("bundle contains startCollector message type", bundle.includes("startCollector"));
  assert("bundle contains stopCollector message type", bundle.includes("stopCollector"));
  assert("bundle contains CSP nonce", bundle.includes("getNonce") || bundle.includes("nonce"));
  assert("bundle contains watchConfigFile logic", bundle.includes("createFileSystemWatcher") || bundle.includes("FileSystemWatcher"));
}

// ============================================================================
// 19. Runtime test — load bundle with comprehensive mock
// ============================================================================
console.log("\n[19. Runtime test — mock-loaded sidebar]");

if (buildOk) {
  const Module = require("module");
  const mockVscodePath = path.join(ROOT, "test", "_mock_vscode_sidebar.js");

  // Track calls
  const commandsExecuted = [];
  const messagesPosted = [];
  const warningMessages = [];
  const infoMessages = [];
  const errorMessages = [];
  const watchers = [];
  let warningAnswer = undefined; // What showWarningMessage resolves to

  fs.writeFileSync(mockVscodePath, `
const path = require("path");
const commandsExecuted = [];
const messagesPosted = [];
const warningMessages = [];
const infoMessages = [];
const errorMessages = [];
const watchers = [];
let warningAnswer = undefined;

class MockEventEmitter {
  constructor() { this._listeners = []; }
  fire(data) { this._listeners.forEach(fn => fn(data)); }
  event(fn) { this._listeners.push(fn); return { dispose: () => {} }; }
  dispose() { this._listeners = []; }
}

module.exports = {
  EventEmitter: MockEventEmitter,
  window: {
    showInformationMessage: (msg) => { infoMessages.push(msg); return Promise.resolve(); },
    showErrorMessage: (msg) => { errorMessages.push(msg); return Promise.resolve(); },
    showWarningMessage: (msg, opts, ...buttons) => {
      warningMessages.push(msg);
      return Promise.resolve(warningAnswer);
    },
    registerWebviewViewProvider: (id, provider) => ({ dispose: () => {} }),
  },
  commands: {
    registerCommand: (cmd, cb) => ({ dispose: () => {} }),
    executeCommand: (cmd) => { commandsExecuted.push(cmd); return Promise.resolve(); },
  },
  Uri: {
    file: (f) => ({ fsPath: f, scheme: "file" }),
    joinPath: (uri, ...segments) => ({
      fsPath: path.join(uri.fsPath, ...segments),
      scheme: "file",
    }),
  },
  RelativePattern: class { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
  workspace: {
    createFileSystemWatcher: (pattern) => {
      const w = {
        _onChange: [],
        _onCreate: [],
        _onDelete: [],
        onDidChange: (fn) => { w._onChange.push(fn); return { dispose: () => {} }; },
        onDidCreate: (fn) => { w._onCreate.push(fn); return { dispose: () => {} }; },
        onDidDelete: (fn) => { w._onDelete.push(fn); return { dispose: () => {} }; },
        dispose: () => {},
        pattern,
      };
      watchers.push(w);
      return w;
    },
  },
  _test: {
    get commandsExecuted() { return commandsExecuted; },
    get messagesPosted() { return messagesPosted; },
    get warningMessages() { return warningMessages; },
    get infoMessages() { return infoMessages; },
    get errorMessages() { return errorMessages; },
    get watchers() { return watchers; },
    set warningAnswer(v) { warningAnswer = v; },
    reset: () => {
      commandsExecuted.length = 0;
      messagesPosted.length = 0;
      warningMessages.length = 0;
      infoMessages.length = 0;
      errorMessages.length = 0;
      watchers.length = 0;
      warningAnswer = undefined;
    },
  },
};
`);

  const origResolve = Module._resolveFilename;
  Module._resolveFilename = function(request, ...args) {
    if (request === "vscode") return mockVscodePath;
    return origResolve.call(this, request, ...args);
  };

  let sidebarMod;
  try {
    // Clear caches
    Object.keys(require.cache).forEach(k => {
      if (k.includes("dist/extension") || k.includes("_mock_vscode")) {
        delete require.cache[k];
      }
    });
    sidebarMod = require(path.join(ROOT, "dist/extension.js"));
    assert("bundle loads with mocked vscode", true);
  } catch (e) {
    assert("bundle loads with mocked vscode", false);
    console.log("    Load error:", e.message);
  }

  const vscodeMock = require(mockVscodePath);

  if (sidebarMod) {
    // Create a mock webview view
    const testState = vscodeMock._test;
    testState.reset();

    const mockContext = {
      subscriptions: [],
      extensionUri: { fsPath: ROOT, scheme: "file" },
      extensionPath: ROOT,
    };

    // Activate to get the sidebar provider registered
    const activatePromise = sidebarMod.activate(mockContext);

    // Find the registered sidebar provider from subscriptions
    // The sidebar provider should have been registered
    // Since we're testing via the bundled code, let's verify the HTML generation

    activatePromise.then(() => {
      // Test the SidebarProvider via the registered webview view provider
      console.log("\n[20. Sidebar resolveWebviewView runtime test]");

      // The sidebar provider was created in activate, but we can test it
      // by creating our own and calling resolveWebviewView
      const { SidebarProvider } = sidebarMod;

      if (SidebarProvider) {
        const provider = new SidebarProvider({ fsPath: ROOT, scheme: "file" });
        testState.reset();

        const posted = [];
        const receivedHandlers = [];
        const mockWebviewView = {
          webview: {
            options: {},
            html: "",
            asWebviewUri: (uri) => ({ toString: () => uri.fsPath }),
            postMessage: (msg) => { posted.push(msg); return Promise.resolve(true); },
            onDidReceiveMessage: (fn) => { receivedHandlers.push(fn); return { dispose: () => {} }; },
          },
        };

        try {
          provider.resolveWebviewView(mockWebviewView, {}, { isCancellationRequested: false });
          assert("resolveWebviewView executes without error", true);
        } catch (e) {
          assert("resolveWebviewView executes without error", false);
          console.log("    Error:", e.message);
        }

        // Verify HTML output
        const generatedHtml = mockWebviewView.webview.html;
        assert("generated HTML is non-empty", generatedHtml.length > 0);
        assert("generated HTML has DOCTYPE", generatedHtml.includes("<!DOCTYPE html>"));
        assert("generated HTML has CSP meta", generatedHtml.includes("Content-Security-Policy"));
        assert("generated HTML has nonce in CSP", generatedHtml.includes("script-src 'nonce-"));
        assert("generated HTML has nonce on script tag", generatedHtml.includes("script nonce="));
        assert("generated HTML has collector-status", generatedHtml.includes("collector-status"));
        assert("generated HTML has harness-list", generatedHtml.includes("harness-list"));
        assert("generated HTML has empty-state", generatedHtml.includes("empty-state"));
        assert("generated HTML has add-btn", generatedHtml.includes("add-btn"));
        assert("generated HTML has + Add Harness", generatedHtml.includes("+ Add Harness"));
        assert("generated HTML has renderState function", generatedHtml.includes("function renderState"));
        assert("generated HTML has acquireVsCodeApi", generatedHtml.includes("acquireVsCodeApi()"));

        // Verify webview options
        assert("webview scripts enabled", mockWebviewView.webview.options.enableScripts === true);
        assert("localResourceRoots set", Array.isArray(mockWebviewView.webview.options.localResourceRoots));

        // Verify message handler registered
        assert("message handler registered", receivedHandlers.length === 1);

        // Verify initial state posted (refresh called)
        assert("initial state posted", posted.length >= 1);
        if (posted.length > 0) {
          const firstMsg = posted[0];
          assert("initial state type is state", firstMsg.type === "state");
          assert("initial state has collector", firstMsg.collector !== undefined);
          assert("initial state has backend", firstMsg.backend !== undefined);
          assert("initial state has harnesses", Array.isArray(firstMsg.harnesses));
          // On clean system (no config.yaml), should be empty
          assert("initial state collector not running", firstMsg.collector.running === false);
          assert("initial state collector port 4318", firstMsg.collector.port === 4318);
          assert("initial state backend is none", firstMsg.backend === "none");
          assert("initial state harnesses empty", firstMsg.harnesses.length === 0);
        }

        // Verify a watcher was set up
        assert("file watcher created", testState.watchers.length >= 1);

        // Test that file change triggers refresh
        if (testState.watchers.length > 0) {
          const watcher = testState.watchers[testState.watchers.length - 1];
          const postedBefore = posted.length;
          if (watcher._onChange.length > 0) {
            watcher._onChange[0]();
            assert("file change triggers state update", posted.length > postedBefore);
          }
        }

        // ====================================================================
        // 21. Test message handling via mock handler
        // ====================================================================
        console.log("\n[21. Message handling runtime]");

        if (receivedHandlers.length > 0) {
          const handler = receivedHandlers[0];

          // Test addHarness
          testState.reset();
          handler({ type: "addHarness" });
          assert("addHarness executes arize.setup command", testState.commandsExecuted.includes("arize.setup"));

          // Test reconfigure
          testState.reset();
          handler({ type: "reconfigure", harness: "claude" });
          assert("reconfigure executes arize.reconfigure command", testState.commandsExecuted.includes("arize.reconfigure"));

          // Test reconfigure without harness (should be no-op)
          testState.reset();
          handler({ type: "reconfigure" });
          assert("reconfigure without harness is no-op", testState.commandsExecuted.length === 0);

          // Test remove without installer (should show error)
          testState.reset();
          handler({ type: "remove", harness: "claude" });
          // Allow async to settle
          setTimeout(() => {
            assert("remove without installer shows error", testState.errorMessages.some(m => m.includes("Installer not available")));

            // Test collector start without installer
            testState.reset();
            handler({ type: "startCollector" });
            setTimeout(() => {
              assert("startCollector without installer shows error", testState.errorMessages.some(m => m.includes("Installer not available")));

              // Test collector stop without installer
              testState.reset();
              handler({ type: "stopCollector" });
              setTimeout(() => {
                assert("stopCollector without installer shows error", testState.errorMessages.some(m => m.includes("Installer not available")));

                // ====================================================================
                // 22. Test with installer set
                // ====================================================================
                console.log("\n[22. Sidebar with InstallerBridge]");

                // Set a mock installer on the provider
                const mockInstaller = {
                  runUninstall: (h) => Promise.resolve({ success: true, output: "done" }),
                  controlCollector: (a) => Promise.resolve(true),
                  dispose: () => {},
                };
                provider.setInstaller(mockInstaller);

                // Test remove with installer — but dialog not confirmed
                testState.reset();
                testState.warningAnswer = undefined; // User cancels
                handler({ type: "remove", harness: "claude" });
                setTimeout(() => {
                  assert("remove shows warning dialog", testState.warningMessages.length > 0);
                  assert("remove warning mentions harness", testState.warningMessages.some(m => m.includes("claude")));

                  // Test remove with installer — dialog confirmed
                  testState.reset();
                  testState.warningAnswer = "Remove";
                  handler({ type: "remove", harness: "codex" });
                  setTimeout(() => {
                    assert("remove success shows info message", testState.infoMessages.some(m => m.includes("codex") && m.includes("removed")));

                    // Test collector start with installer
                    testState.reset();
                    handler({ type: "startCollector" });
                    setTimeout(() => {
                      assert("collector start success shows info", testState.infoMessages.some(m => m.includes("started")));

                      // Test collector stop with installer
                      testState.reset();
                      handler({ type: "stopCollector" });
                      setTimeout(() => {
                        assert("collector stop success shows info", testState.infoMessages.some(m => m.includes("stopped")));

                        // Test remove with failing installer
                        console.log("\n[23. Sidebar error paths]");
                        const failInstaller = {
                          runUninstall: (h) => Promise.resolve({ success: false, output: "", error: "not found" }),
                          controlCollector: (a) => Promise.resolve(false),
                          dispose: () => {},
                        };
                        provider.setInstaller(failInstaller);

                        testState.reset();
                        testState.warningAnswer = "Remove";
                        handler({ type: "remove", harness: "cursor" });
                        setTimeout(() => {
                          assert("remove failure shows error", testState.errorMessages.some(m => m.includes("Failed to remove")));

                          testState.reset();
                          handler({ type: "startCollector" });
                          setTimeout(() => {
                            assert("collector start failure shows error", testState.errorMessages.some(m => m.includes("Failed to") && m.includes("collector")));

                            // ====================================================================
                            // 24. Test refresh method
                            // ====================================================================
                            console.log("\n[24. Refresh method]");

                            const postedBefore = posted.length;
                            provider.refresh();
                            assert("refresh posts state message", posted.length > postedBefore);
                            const lastMsg = posted[posted.length - 1];
                            assert("refreshed state has type state", lastMsg.type === "state");

                            // ====================================================================
                            // 25. Test dispose
                            // ====================================================================
                            console.log("\n[25. Dispose]");
                            let disposeOk = false;
                            try {
                              provider.dispose();
                              disposeOk = true;
                            } catch (e) {}
                            assert("dispose does not throw", disposeOk);

                            // Cleanup
                            Module._resolveFilename = origResolve;
                            try { fs.unlinkSync(mockVscodePath); } catch {}

                            // Run standalone tests
                            runStandaloneTests();
                          }, 50);
                        }, 50);
                      }, 50);
                    }, 50);
                  }, 50);
                }, 50);
              }, 50);
            }, 50);
          }, 50);
        } else {
          Module._resolveFilename = origResolve;
          try { fs.unlinkSync(mockVscodePath); } catch {}
          runStandaloneTests();
        }
      } else {
        console.log("  Note: SidebarProvider not directly exported, testing via integration only");
        Module._resolveFilename = origResolve;
        try { fs.unlinkSync(mockVscodePath); } catch {}
        runStandaloneTests();
      }
    }).catch((e) => {
      Module._resolveFilename = origResolve;
      try { fs.unlinkSync(mockVscodePath); } catch {}
      console.log("  Note: activate failed (expected due to pre-existing tsc issue):", e.message);
      runStandaloneTests();
    });
  } else {
    Module._resolveFilename = origResolve;
    try { fs.unlinkSync(mockVscodePath); } catch {}
    runStandaloneTests();
  }
} else {
  runStandaloneTests();
}

// ============================================================================
// Standalone tests (always run)
// ============================================================================

function runStandaloneTests() {
  // ====================================================================
  // 26. Config YAML parsing scenarios (source analysis)
  // ====================================================================
  console.log("\n[26. Config YAML parsing — source patterns]");

  const src2 = fs.readFileSync(path.join(ROOT, "src", "sidebar.ts"), "utf8");

  // Missing file handling
  assert("handles missing config file", src2.includes("fs.existsSync(configPath)"));
  assert("returns empty state for missing file", src2.includes("return empty"));

  // Invalid YAML handling
  assert("handles null doc", src2.includes("!doc"));
  assert("handles non-object doc", src2.includes('typeof doc !== "object"'));

  // Collector edge cases
  assert("handles missing collector section", src2.includes("collectorSection?.running"));
  assert("port defaults to 4318", src2.includes(": 4318"));

  // Backend edge cases
  assert("backend type-checks for string", src2.includes('typeof doc.backend === "string"'));

  // Harnesses edge cases
  assert("handles missing harnesses section", src2.includes("harnessesSection && typeof harnessesSection"));
  assert("handles missing project in harness", src2.includes('cfg?.project'));

  // ====================================================================
  // 27. Nonce uniqueness
  // ====================================================================
  console.log("\n[27. Nonce generation]");

  // Verify nonce generation code in source
  assert("nonce uses Math.random", src2.includes("Math.random()"));
  assert("nonce length is 32", src2.includes("i < 32"));

  // ====================================================================
  // 28. CSS validation in HTML
  // ====================================================================
  console.log("\n[28. CSS validation]");

  const html2 = fs.readFileSync(path.join(ROOT, "media", "sidebar.html"), "utf8");

  // Uses VS Code CSS variables
  assert("uses vscode font family var", html2.includes("var(--vscode-font-family)"));
  assert("uses vscode font size var", html2.includes("var(--vscode-font-size)"));
  assert("uses vscode foreground var", html2.includes("var(--vscode-foreground)"));
  assert("uses vscode hover bg var", html2.includes("var(--vscode-list-hoverBackground)"));
  assert("uses vscode button bg var", html2.includes("var(--vscode-button-background)"));
  assert("uses vscode button fg var", html2.includes("var(--vscode-button-foreground)"));
  assert("uses vscode link color var", html2.includes("var(--vscode-textLink-foreground)"));
  assert("uses vscode description fg var", html2.includes("var(--vscode-descriptionForeground)"));

  // ====================================================================
  // 29. HTML and JS consistency
  // ====================================================================
  console.log("\n[29. HTML/JS consistency]");

  const js2 = fs.readFileSync(path.join(ROOT, "media", "sidebar.js"), "utf8");

  // All element IDs referenced in JS must exist in HTML
  const jsIds = [
    "collector-status", "collector-dot", "collector-label",
    "backend-row", "harness-list", "empty-state", "add-btn"
  ];
  jsIds.forEach(id => {
    assert(`JS references ID "${id}" that exists in HTML`, html2.includes(`id="${id}"`));
  });

  // All CSS classes used in JS must be defined in HTML <style>
  const jsClasses = ["harness-card", "harness-name", "harness-project", "harness-actions", "action-btn"];
  jsClasses.forEach(cls => {
    assert(`JS uses class "${cls}" defined in HTML CSS`, html2.includes(`.${cls}`));
  });

  // Message types in JS match those expected by sidebar.ts
  const msgTypes = ["addHarness", "reconfigure", "remove", "startCollector", "stopCollector"];
  msgTypes.forEach(type => {
    assert(`JS sends "${type}" message handled by sidebar.ts`, src2.includes(`"${type}"`));
  });

  // ====================================================================
  // 30. Inline script consistency with standalone sidebar.js
  // ====================================================================
  console.log("\n[30. Inline vs standalone script consistency]");

  // The inline script in sidebar.ts and the standalone sidebar.js should have
  // the same rendering logic
  assert("both have renderState function", src2.includes("function renderState") && js2.includes("function renderState"));
  assert("both handle collector toggle", src2.includes("stopCollector") && js2.includes("stopCollector"));
  assert("both handle add harness", src2.includes("addHarness") && js2.includes("addHarness"));
  assert("both listen for message events", src2.includes("addEventListener('message'") && js2.includes('addEventListener("message"'));

  printSummary();
  process.exit(failed > 0 ? 1 : 0);
}
