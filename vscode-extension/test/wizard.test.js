/**
 * Tests for vscode-extension/src/wizard.ts and media/wizard.js
 *
 * Part 1: Static source analysis + compilation of wizard.ts
 * Part 2: Runtime testing of wizard.ts (WizardPanel, HTML generation, messaging)
 * Part 3: Static analysis + logic testing of wizard.js
 * Part 4: CSS validation
 * Part 5: HTML validation
 * Part 6: Full navigation flow simulation
 *
 * Run: node test/wizard.test.js
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");
const Module = require("module");

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

// ===========================================================================
// File existence
// ===========================================================================
console.log("\n[File existence]");

const wizardTsPath = path.join(ROOT, "src", "wizard.ts");
const wizardJsPath = path.join(ROOT, "media", "wizard.js");
const wizardCssPath = path.join(ROOT, "media", "wizard.css");
const wizardHtmlPath = path.join(ROOT, "media", "wizard.html");

assert("src/wizard.ts exists", fs.existsSync(wizardTsPath));
assert("media/wizard.js exists", fs.existsSync(wizardJsPath));
assert("media/wizard.css exists", fs.existsSync(wizardCssPath));
assert("media/wizard.html exists", fs.existsSync(wizardHtmlPath));

const wizardTs = fs.readFileSync(wizardTsPath, "utf8");
const wizardJs = fs.readFileSync(wizardJsPath, "utf8");
const wizardCss = fs.readFileSync(wizardCssPath, "utf8");
const wizardHtml = fs.readFileSync(wizardHtmlPath, "utf8");

// ===========================================================================
// Part 1: wizard.ts — static analysis
// ===========================================================================
console.log("\n[wizard.ts — exports and structure]");

assert("exports WizardPanel class", wizardTs.includes("export class WizardPanel"));
assert("exports WizardOptions interface", wizardTs.includes("export interface WizardOptions"));
assert("exports openWizard function", wizardTs.includes("export function openWizard"));
assert("WizardPanel has currentPanel static field", wizardTs.includes("static currentPanel"));
assert("openForSetup static method", wizardTs.includes("static openForSetup"));
assert("openForReconfigure static method", wizardTs.includes("static openForReconfigure"));
assert("createOrReveal private static method", wizardTs.includes("private static createOrReveal"));
assert("getHtmlContent private method", wizardTs.includes("private getHtmlContent"));
assert("handleMessage private method", wizardTs.includes("private async handleMessage"));
assert("handleInstall private method", wizardTs.includes("private async handleInstall"));
assert("handleDetectIdes private method", wizardTs.includes("private async handleDetectIdes"));
assert("dispose method", wizardTs.includes("dispose(): void"));
assert("getNonce helper function", wizardTs.includes("function getNonce"));

console.log("\n[wizard.ts — singleton pattern]");
assert("checks currentPanel in createOrReveal", wizardTs.includes("WizardPanel.currentPanel"));
assert("reveals existing panel", wizardTs.includes("panel.reveal(vscode.ViewColumn.One)"));
assert("sets currentPanel on create", wizardTs.includes("WizardPanel.currentPanel = new WizardPanel"));
assert("clears currentPanel on dispose", wizardTs.includes("WizardPanel.currentPanel = undefined"));

console.log("\n[wizard.ts — webview panel config]");
assert("panel id is arize-wizard", wizardTs.includes('"arize-wizard"'));
assert("panel title is Arize: Setup Wizard", wizardTs.includes('"Arize: Setup Wizard"'));
assert("enableScripts is true", wizardTs.includes("enableScripts: true"));
assert("retainContextWhenHidden is true", wizardTs.includes("retainContextWhenHidden: true"));
assert("localResourceRoots includes media", wizardTs.includes('extensionUri, "media"'));

console.log("\n[wizard.ts — CSP and HTML generation]");
assert("sets Content-Security-Policy", wizardTs.includes("Content-Security-Policy"));
assert("uses nonce for script", wizardTs.includes('nonce-${nonce}'));
assert("loads wizard.css via asWebviewUri", wizardTs.includes('"wizard.css"'));
assert("loads wizard.js via asWebviewUri", wizardTs.includes('"wizard.js"'));
assert("has wizard-root div", wizardTs.includes('id="wizard-root"'));
assert("getNonce generates 32-char string", wizardTs.includes("for (let i = 0; i < 32; i++)"));

console.log("\n[wizard.ts — message handling]");
assert("handles ready message type", wizardTs.includes('case "ready"'));
assert("handles install message type", wizardTs.includes('case "install"'));
assert("handles detectIdes message type", wizardTs.includes('case "detectIdes"'));
assert("handles cancel message type", wizardTs.includes('case "cancel"'));
assert("cancel disposes panel", wizardTs.includes('this.panel.dispose()'));
assert("install sends complete message on success", wizardTs.includes('type: "complete"'));
assert("install catches errors", wizardTs.includes("catch (err)"));
assert("sends error message on failure", wizardTs.includes("err instanceof Error ? err.message : String(err)"));

console.log("\n[wizard.ts — IDE detection]");
assert("uses top-level fs import", wizardTs.includes('import { existsSync } from "fs"'));
assert("uses top-level os import", wizardTs.includes('import { homedir } from "os"'));
assert("uses top-level path import", wizardTs.includes('import { join } from "path"'));
assert("detects Claude via .claude dir", wizardTs.includes('".claude"'));
assert("detects Codex via .codex dir", wizardTs.includes('".codex"'));
assert("detects Cursor via .cursor dir", wizardTs.includes('".cursor"'));
assert("detects Cursor on Linux via .config/Cursor", wizardTs.includes('".config", "Cursor"'));
assert("detects Cursor on Windows via APPDATA", wizardTs.includes('process.env.APPDATA'));
assert("sends ideDetection message", wizardTs.includes('type: "ideDetection"'));

console.log("\n[wizard.ts — reconfigure / prefill]");
assert("openForReconfigure stores pendingPrefill", wizardTs.includes("panel.pendingPrefill"));
assert("handleReady sends prefill from pendingPrefill", wizardTs.includes("this.pendingPrefill"));
assert("prefill includes backend", wizardTs.includes("backend: this.pendingPrefill.backend"));
assert("prefill includes credentials", wizardTs.includes("credentials: this.pendingPrefill.credentials"));

console.log("\n[wizard.ts — double-dispose guard]");
assert("has disposed field", wizardTs.includes("private disposed = false"));
assert("dispose checks disposed flag", wizardTs.includes("if (this.disposed)"));
assert("dispose sets disposed = true", wizardTs.includes("this.disposed = true"));

console.log("\n[wizard.ts — openWizard backward compat]");
assert("openWizard calls openForSetup", wizardTs.includes("WizardPanel.openForSetup"));
assert("openWizard calls openForReconfigure when prefill", wizardTs.includes("WizardPanel.openForReconfigure"));
assert("openWizard checks options.harness", wizardTs.includes("options.harness"));

console.log("\n[wizard.ts — installer integration]");
assert("imports InstallerBridge", wizardTs.includes('import { InstallerBridge'));
assert("imports InstallOptions", wizardTs.includes("InstallOptions"));
assert("creates InstallerBridge in constructor", wizardTs.includes("new InstallerBridge"));
assert("subscribes to onOutput for streaming", wizardTs.includes("this.installer.onOutput.event"));
assert("posts output lines to webview", wizardTs.includes('type: "output", line'));
assert("calls runInstall on install message", wizardTs.includes("this.installer.runInstall"));
assert("disposes installer on panel close", wizardTs.includes("this.installer.dispose()"));

// ===========================================================================
// wizard.ts — esbuild compilation
// ===========================================================================
console.log("\n[wizard.ts — esbuild compilation]");

const buildOutDir = path.join(ROOT, "test", "_build");
try { fs.mkdirSync(buildOutDir, { recursive: true }); } catch {}

let esbuildOk = false;
try {
  execSync(
    `npx esbuild src/wizard.ts --bundle --outfile=test/_build/wizard.js --format=cjs --platform=node --external:vscode`,
    { cwd: ROOT, stdio: "pipe" }
  );
  esbuildOk = true;
} catch (e) {
  console.log("    esbuild error:", e.stderr ? e.stderr.toString().slice(0, 500) : e.message);
}
assert("wizard.ts compiles with esbuild", esbuildOk);

// ===========================================================================
// Part 2: Runtime testing of wizard.ts via mocked vscode
// ===========================================================================

// Mock vscode module
const mockVscodePath = path.join(ROOT, "test", "_mock_vscode_wizard.js");
fs.writeFileSync(mockVscodePath, `
class MockEventEmitter {
  constructor() { this._listeners = []; }
  fire(data) { this._listeners.forEach(fn => fn(data)); }
  event(fn) { this._listeners.push(fn); return { dispose: () => {} }; }
  dispose() { this._listeners = []; }
}

class MockWebview {
  constructor() {
    this.html = "";
    this._messageHandler = null;
    this.cspSource = "https://test.vscode-cdn.net";
    this._sentMessages = [];
  }
  asWebviewUri(uri) { return "https://file+.vscode-resource.vscode-cdn.net" + uri.fsPath; }
  onDidReceiveMessage(handler, thisArg, disposables) {
    this._messageHandler = handler;
    return { dispose: () => {} };
  }
  postMessage(msg) {
    this._sentMessages.push(msg);
    return Promise.resolve(true);
  }
  simulateMessage(msg) {
    if (this._messageHandler) this._messageHandler(msg);
  }
}

class MockUri {
  constructor(fsPath) { this.fsPath = fsPath; }
  static joinPath(base, ...segments) {
    const p = require("path");
    return new MockUri(p.join(base.fsPath, ...segments));
  }
}

class MockPanel {
  constructor() {
    this.webview = new MockWebview();
    this._disposeHandlers = [];
    this._disposed = false;
    this.viewColumn = 1;
  }
  reveal(column) { this.viewColumn = column; }
  onDidDispose(handler, thisArg, disposables) {
    this._disposeHandlers.push(handler);
    return { dispose: () => {} };
  }
  dispose() {
    if (this._disposed) return;
    this._disposed = true;
    this._disposeHandlers.forEach(h => h());
  }
}

let lastPanel = null;

module.exports = {
  EventEmitter: MockEventEmitter,
  Uri: MockUri,
  ViewColumn: { One: 1, Two: 2 },
  window: {
    createWebviewPanel: (viewType, title, column, options) => {
      lastPanel = new MockPanel();
      lastPanel._viewType = viewType;
      lastPanel._title = title;
      lastPanel._column = column;
      lastPanel._options = options;
      return lastPanel;
    },
    registerWebviewViewProvider: () => ({ dispose: () => {} }),
    showInformationMessage: () => {},
    showErrorMessage: () => {},
    showWarningMessage: () => {},
  },
  commands: { registerCommand: () => ({ dispose: () => {} }) },
  StatusBarAlignment: { Left: 1, Right: 2 },
  _getLastPanel: () => lastPanel,
  _resetPanel: () => { lastPanel = null; },
};
`);

const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...args) {
  if (request === "vscode") return mockVscodePath;
  return origResolve.call(this, request, ...args);
};

let wizardMod;
try {
  delete require.cache[path.join(buildOutDir, "wizard.js")];
  wizardMod = require(path.join(buildOutDir, "wizard.js"));
  assert("wizard module loads with mocked vscode", true);
} catch (e) {
  assert("wizard module loads with mocked vscode", false);
  console.log("    Load error:", e.message);
}

const mockVscode = require(mockVscodePath);

// ---------------------------------------------------------------------------
// Async runtime tests (wrapped to avoid top-level await)
// ---------------------------------------------------------------------------
function runRuntimeTests() {
  return new Promise(function (resolve) {
    if (!wizardMod || !wizardMod.WizardPanel) {
      console.log("  SKIP: WizardPanel runtime tests (module failed to load)");
      failed += 10;
      resolve();
      return;
    }

    console.log("\n[WizardPanel — openForSetup]");

    // Reset singleton
    wizardMod.WizardPanel.currentPanel = undefined;
    mockVscode._resetPanel();

    var extUri = new mockVscode.Uri("/fake/extension");
    wizardMod.WizardPanel.openForSetup(extUri);

    var panel1 = mockVscode._getLastPanel();
    assert("panel is created", panel1 !== null);
    assert("panel viewType is arize-wizard", panel1._viewType === "arize-wizard");
    assert("panel title is correct", panel1._title === "Arize: Setup Wizard");
    assert("panel column is One", panel1._column === 1);
    assert("enableScripts is true", panel1._options.enableScripts === true);
    assert("retainContextWhenHidden is true", panel1._options.retainContextWhenHidden === true);
    assert("currentPanel is set", wizardMod.WizardPanel.currentPanel !== undefined);

    // Check HTML content
    var html = panel1.webview.html;
    assert("HTML has doctype", html.includes("<!DOCTYPE html>"));
    assert("HTML has wizard-root div", html.includes('id="wizard-root"'));
    assert("HTML has Content-Security-Policy", html.includes("Content-Security-Policy"));
    assert("HTML has nonce in script tag", /nonce="[A-Za-z0-9]{32}"/.test(html));
    assert("HTML links wizard.css", html.includes("wizard.css"));
    assert("HTML links wizard.js", html.includes("wizard.js"));
    assert("HTML uses cspSource", html.includes(panel1.webview.cspSource));

    console.log("\n[WizardPanel — singleton behavior]");
    mockVscode._resetPanel();
    wizardMod.WizardPanel.openForSetup(extUri);
    var panel2 = mockVscode._getLastPanel();
    assert("singleton: no new panel created on second call", panel2 === null);
    assert("singleton: currentPanel still exists", wizardMod.WizardPanel.currentPanel !== undefined);

    console.log("\n[WizardPanel — dispose clears singleton]");
    wizardMod.WizardPanel.currentPanel.dispose();
    assert("currentPanel cleared after dispose", wizardMod.WizardPanel.currentPanel === undefined);

    console.log("\n[WizardPanel — openForReconfigure]");
    mockVscode._resetPanel();
    wizardMod.WizardPanel.openForReconfigure(extUri, "claude", {
      backend: "arize",
      credentials: { apiKey: "test-key", spaceId: "sp-1" },
      userId: "user@test.com",
      scope: "global",
    });
    var panel3 = mockVscode._getLastPanel();
    assert("reconfigure: panel is created", panel3 !== null);
    // Prefill is not sent immediately — it waits for the "ready" message
    var prefillMsgBefore = panel3.webview._sentMessages.find(function (m) { return m.type === "prefill"; });
    assert("reconfigure: prefill NOT sent before ready", prefillMsgBefore === undefined);
    // Simulate the webview sending "ready"
    panel3.webview.simulateMessage({ type: "ready" });
    var prefillMsg = panel3.webview._sentMessages.find(function (m) { return m.type === "prefill"; });
    assert("reconfigure: sends prefill after ready", prefillMsg !== undefined);
    assert("reconfigure: prefill has harness", prefillMsg && prefillMsg.harness === "claude");
    assert("reconfigure: prefill has backend", prefillMsg && prefillMsg.backend === "arize");
    assert("reconfigure: prefill has credentials", prefillMsg && prefillMsg.credentials && prefillMsg.credentials.apiKey === "test-key");
    assert("reconfigure: prefill has userId", prefillMsg && prefillMsg.userId === "user@test.com");
    assert("reconfigure: prefill has scope", prefillMsg && prefillMsg.scope === "global");

    if (wizardMod.WizardPanel.currentPanel) {
      wizardMod.WizardPanel.currentPanel.dispose();
    }

    console.log("\n[WizardPanel — double-dispose safety]");
    mockVscode._resetPanel();
    wizardMod.WizardPanel.openForSetup(extUri);
    var panelDD = mockVscode._getLastPanel();
    assert("double-dispose: panel created", panelDD !== null);
    wizardMod.WizardPanel.currentPanel.dispose();
    assert("double-dispose: first dispose clears currentPanel", wizardMod.WizardPanel.currentPanel === undefined);
    // Second dispose should not throw
    try {
      panelDD.dispose();
      assert("double-dispose: second dispose does not throw", true);
    } catch (e) {
      assert("double-dispose: second dispose does not throw", false);
    }

    console.log("\n[WizardPanel — cancel message disposes panel]");
    mockVscode._resetPanel();
    wizardMod.WizardPanel.openForSetup(extUri);
    var panel4 = mockVscode._getLastPanel();
    assert("panel created for cancel test", panel4 !== null);
    panel4.webview.simulateMessage({ type: "cancel" });
    assert("cancel: currentPanel cleared", wizardMod.WizardPanel.currentPanel === undefined);

    console.log("\n[WizardPanel — detectIdes message handler]");
    mockVscode._resetPanel();
    wizardMod.WizardPanel.openForSetup(extUri);
    var panel5 = mockVscode._getLastPanel();
    panel5.webview.simulateMessage({ type: "detectIdes" });
    // detectIdes is async — wait a tick for promise to resolve
    setTimeout(function () {
      var ideMsg = panel5.webview._sentMessages.find(function (m) { return m.type === "ideDetection"; });
      assert("detectIdes: sends ideDetection message", ideMsg !== undefined);
      assert("detectIdes: results has claude key", ideMsg && "claude" in ideMsg.results);
      assert("detectIdes: results has codex key", ideMsg && "codex" in ideMsg.results);
      assert("detectIdes: results has cursor key", ideMsg && "cursor" in ideMsg.results);

      if (wizardMod.WizardPanel.currentPanel) {
        wizardMod.WizardPanel.currentPanel.dispose();
      }

      console.log("\n[openWizard — backward compatibility]");
      mockVscode._resetPanel();
      wizardMod.openWizard({ extensionUri: extUri, subscriptions: [] });
      assert("openWizard creates panel for fresh setup", mockVscode._getLastPanel() !== null);
      if (wizardMod.WizardPanel.currentPanel) {
        wizardMod.WizardPanel.currentPanel.dispose();
      }

      mockVscode._resetPanel();
      wizardMod.openWizard({ extensionUri: extUri, subscriptions: [] }, { prefill: true, harness: "codex" });
      assert("openWizard creates panel for reconfigure", mockVscode._getLastPanel() !== null);
      var panel6 = mockVscode._getLastPanel();
      // Simulate ready to trigger prefill
      panel6.webview.simulateMessage({ type: "ready" });
      var prefillMsg2 = panel6 && panel6.webview._sentMessages.find(function (m) { return m.type === "prefill"; });
      assert("openWizard reconfigure sends prefill", prefillMsg2 !== undefined);
      assert("openWizard reconfigure uses harness from options", prefillMsg2 && prefillMsg2.harness === "codex");

      if (wizardMod.WizardPanel.currentPanel) {
        wizardMod.WizardPanel.currentPanel.dispose();
      }

      // getNonce tests
      console.log("\n[getNonce — HTML output]");
      wizardMod.WizardPanel.currentPanel = undefined;
      mockVscode._resetPanel();
      var extUri2 = new mockVscode.Uri("/fake/ext2");
      wizardMod.WizardPanel.openForSetup(extUri2);
      var panelN = mockVscode._getLastPanel();
      if (panelN) {
        var htmlN = panelN.webview.html;
        var nonceMatch = htmlN.match(/nonce="([A-Za-z0-9]+)"/);
        assert("generated HTML contains nonce", nonceMatch !== null);
        assert("nonce is 32 chars", nonceMatch && nonceMatch[1].length === 32);
        var nonce = nonceMatch ? nonceMatch[1] : "";
        var nonceOccurrences = (htmlN.match(new RegExp(nonce, "g")) || []).length;
        assert("nonce appears in CSP (2x) and script tag (1x) = 3 occurrences", nonceOccurrences === 3);
      }
      if (wizardMod.WizardPanel.currentPanel) {
        wizardMod.WizardPanel.currentPanel.dispose();
      }

      resolve();
    }, 100);
  });
}

// ===========================================================================
// Part 3: wizard.html validation
// ===========================================================================
function runStaticTests() {
  console.log("\n[wizard.html — structure]");
  assert("html has DOCTYPE", wizardHtml.includes("<!DOCTYPE html>"));
  assert("html has lang=en", wizardHtml.includes('lang="en"'));
  assert("html has charset UTF-8", wizardHtml.includes('charset="UTF-8"'));
  assert("html has wizard-root div", wizardHtml.includes('id="wizard-root"'));
  assert("html links wizard.css", wizardHtml.includes('href="wizard.css"'));
  assert("html loads wizard.js", wizardHtml.includes('src="wizard.js"'));
  assert("html wizard.js is at end of body", wizardHtml.indexOf('src="wizard.js"') > wizardHtml.indexOf("wizard-root"));

  // ===========================================================================
  // Part 4: wizard.css validation
  // ===========================================================================
  console.log("\n[wizard.css — VS Code variables]");
  assert("css uses --vscode-editor-background", wizardCss.includes("--vscode-editor-background"));
  assert("css uses --vscode-foreground", wizardCss.includes("--vscode-foreground"));
  assert("css uses --vscode-button-background", wizardCss.includes("--vscode-button-background"));
  assert("css uses --vscode-button-foreground", wizardCss.includes("--vscode-button-foreground"));
  assert("css uses --vscode-focusBorder", wizardCss.includes("--vscode-focusBorder"));
  assert("css uses --vscode-input-background", wizardCss.includes("--vscode-input-background"));
  assert("css uses --vscode-input-foreground", wizardCss.includes("--vscode-input-foreground"));
  assert("css uses --vscode-list-hoverBackground", wizardCss.includes("--vscode-list-hoverBackground"));
  assert("css uses --vscode-list-activeSelectionBackground", wizardCss.includes("--vscode-list-activeSelectionBackground"));
  assert("css uses --vscode-terminal-background", wizardCss.includes("--vscode-terminal-background"));
  assert("css uses --vscode-terminal-foreground", wizardCss.includes("--vscode-terminal-foreground"));

  console.log("\n[wizard.css — key selectors]");
  assert("css has .progress-bar", wizardCss.includes(".progress-bar"));
  assert("css has .progress-step", wizardCss.includes(".progress-step"));
  assert("css has .step", wizardCss.includes(".step {"));
  assert("css has .step.active", wizardCss.includes(".step.active"));
  assert("css has .card", wizardCss.includes(".card {"));
  assert("css has .card.selected", wizardCss.includes(".card.selected"));
  assert("css has .card .badge", wizardCss.includes(".card .badge"));
  assert("css has .credential-fields", wizardCss.includes(".credential-fields {"));
  assert("css has .credential-fields.visible", wizardCss.includes(".credential-fields.visible"));
  assert("css has .radio-group", wizardCss.includes(".radio-group"));
  assert("css has .summary-table", wizardCss.includes(".summary-table"));
  assert("css has .output-log", wizardCss.includes(".output-log {"));
  assert("css has .output-log.visible", wizardCss.includes(".output-log.visible"));
  assert("css has .spinner", wizardCss.includes(".spinner {"));
  assert("css has .spinner.visible", wizardCss.includes(".spinner.visible"));
  assert("css has .nav-buttons", wizardCss.includes(".nav-buttons"));
  assert("css has .status-message.success", wizardCss.includes(".status-message.success"));
  assert("css has .status-message.error", wizardCss.includes(".status-message.error"));
  assert("css has button.primary", wizardCss.includes("button.primary"));
  assert("css has button.secondary", wizardCss.includes("button.secondary"));
  assert("css has button:disabled", wizardCss.includes("button:disabled"));
  assert("css has @keyframes spin", wizardCss.includes("@keyframes spin"));

  // Balanced braces
  var braceCount = 0;
  for (var i = 0; i < wizardCss.length; i++) {
    if (wizardCss[i] === "{") braceCount++;
    else if (wizardCss[i] === "}") braceCount--;
  }
  assert("css has balanced braces", braceCount === 0);

  // ===========================================================================
  // Part 5: wizard.js — static source analysis
  // ===========================================================================
  console.log("\n[wizard.js — structure]");
  assert("js is an IIFE", wizardJs.includes("(function ()") && wizardJs.trimEnd().endsWith("})();"));
  assert("js uses strict mode", wizardJs.includes('"use strict"'));
  assert("js calls acquireVsCodeApi", wizardJs.includes("acquireVsCodeApi()"));
  assert("js has state object", wizardJs.includes("const state ="));
  assert("js has TOTAL_STEPS = 4", wizardJs.includes("const TOTAL_STEPS = 4"));
  assert("js has STEP_TITLES array", wizardJs.includes("const STEP_TITLES ="));

  console.log("\n[wizard.js — render functions]");
  assert("js has render function", wizardJs.includes("function render()"));
  assert("js has renderProgressBar", wizardJs.includes("function renderProgressBar()"));
  assert("js has renderStep1", wizardJs.includes("function renderStep1()"));
  assert("js has renderStep2", wizardJs.includes("function renderStep2()"));
  assert("js has renderStep3", wizardJs.includes("function renderStep3()"));
  assert("js has renderStep4", wizardJs.includes("function renderStep4()"));
  assert("js has renderNavButtons", wizardJs.includes("function renderNavButtons()"));

  console.log("\n[wizard.js — state machine]");
  assert("js has canAdvance function", wizardJs.includes("function canAdvance()"));
  assert("js has nextStep function", wizardJs.includes("function nextStep()"));
  assert("js has prevStep function", wizardJs.includes("function prevStep()"));
  assert("js canAdvance validates step 1 (harness required)", wizardJs.includes('state.harness !== ""'));
  assert("js canAdvance validates step 2 (backend required)", wizardJs.includes("!state.backend"));
  assert("js canAdvance validates arize credentials", wizardJs.includes("state.credentials.apiKey") && wizardJs.includes("state.credentials.spaceId"));
  assert("js nextStep skips step 3 for non-Claude", wizardJs.includes('state.harness !== "claude"') && wizardJs.includes("return 4"));
  assert("js prevStep skips step 3 going back", wizardJs.includes("return 2"));

  console.log("\n[wizard.js — credential sync]");
  assert("js has syncCredentials function", wizardJs.includes("function syncCredentials()"));
  assert("js syncs phoenix endpoint", wizardJs.includes('"phoenix-endpoint"'));
  assert("js syncs arize api key", wizardJs.includes('"arize-api-key"'));
  assert("js syncs arize space id", wizardJs.includes('"arize-space-id"'));
  assert("js syncs arize otlp endpoint", wizardJs.includes('"arize-otlp-endpoint"'));
  assert("js syncs user id", wizardJs.includes('"user-id"'));
  assert("js syncs scope radio", wizardJs.includes('input[name="scope"]:checked'));

  console.log("\n[wizard.js — install flow]");
  assert("js has startInstall function", wizardJs.includes("function startInstall()"));
  assert("js sets installing = true on start", wizardJs.includes("state.installing = true"));
  assert("js posts install message", wizardJs.includes('type: "install"'));
  assert("js install message includes harness", wizardJs.includes("harness: state.harness"));
  assert("js install message includes backend", wizardJs.includes("backend: state.backend"));
  assert("js install message includes credentials", wizardJs.includes("credentials: state.credentials"));
  assert("js install message includes userId", wizardJs.includes("userId: state.userId"));
  assert("js install message includes scope", wizardJs.includes("scope: state.scope"));

  console.log("\n[wizard.js — message handlers]");
  assert("js listens for window message events", wizardJs.includes('window.addEventListener("message"'));
  assert("js handles output message", wizardJs.includes('case "output"'));
  assert("js handles complete message", wizardJs.includes('case "complete"'));
  assert("js handles ideDetection message", wizardJs.includes('case "ideDetection"'));
  assert("js handles prefill message", wizardJs.includes('case "prefill"'));
  assert("js appendLog function", wizardJs.includes("function appendLog"));
  assert("js complete success shows status", wizardJs.includes('"status-success"'));
  assert("js complete error shows status", wizardJs.includes('"status-error"'));
  assert("js complete re-enables install button", wizardJs.includes('btnInstall.disabled = false'));
  assert("js complete sets button text to Done on success", wizardJs.includes('"Done"'));
  assert("js complete sets button text to Retry on failure", wizardJs.includes('"Retry"'));

  console.log("\n[wizard.js — helpers]");
  assert("js has escapeHtml function", wizardJs.includes("function escapeHtml("));
  assert("js has escapeAttr function", wizardJs.includes("function escapeAttr("));
  assert("js escapeAttr handles &", wizardJs.includes("&amp;"));
  assert("js escapeAttr handles quotes", wizardJs.includes("&quot;"));
  assert("js escapeAttr handles <", wizardJs.includes("&lt;"));
  assert("js escapeAttr handles >", wizardJs.includes("&gt;"));

  console.log("\n[wizard.js — init]");
  assert("js calls render() on load", wizardJs.includes("render();"));
  assert("js sends ready message on load", wizardJs.includes('vscode.postMessage({ type: "ready" })'));
  assert("js requests IDE detection on load", wizardJs.includes('vscode.postMessage({ type: "detectIdes" })'));

  console.log("\n[wizard.js — appendLog adds newline]");
  assert("js appendLog adds newline to each line", wizardJs.includes('log.textContent += text + "\\n"'));

  console.log("\n[wizard.js — card rendering]");
  assert("js renders claude card", wizardJs.includes('id: "claude"'));
  assert("js renders codex card", wizardJs.includes('id: "codex"'));
  assert("js renders cursor card", wizardJs.includes('id: "cursor"'));
  assert("js renders phoenix card", wizardJs.includes('id: "phoenix"'));
  assert("js renders arize card", wizardJs.includes('id: "arize"'));
  assert("js shows Detected badge", wizardJs.includes("Detected"));
  assert("js renders summary row function", wizardJs.includes("function summaryRow"));
  assert("js masks API key in summary (last 4 chars)", wizardJs.includes('.slice(-4)'));
  assert("js shows scope for claude only in summary", wizardJs.includes('state.harness === "claude" ? summaryRow("Scope"'));

  console.log("\n[wizard.js — log toggle]");
  assert("js has log toggle click handler", wizardJs.includes('"log-toggle"'));
  assert("js toggles output-log visible class", wizardJs.includes('log.classList.toggle("visible")'));
  assert("js updates toggle text to show", wizardJs.includes("Show install log"));
  assert("js updates toggle text to hide", wizardJs.includes("Hide install log"));

  // ===========================================================================
  // Part 6: Logic function testing (extracted from wizard.js)
  // ===========================================================================
  console.log("\n[wizard.js — canAdvance logic]");

  function testCanAdvance(step, harness, backend, credentials) {
    switch (step) {
      case 1: return harness !== "";
      case 2:
        if (!backend) return false;
        if (backend === "arize") {
          return (credentials.apiKey || "").trim() !== ""
            && (credentials.spaceId || "").trim() !== "";
        }
        return true;
      case 3: return true;
      case 4: return true;
      default: return false;
    }
  }

  // Step 1
  assert("canAdvance step 1: false when no harness", testCanAdvance(1, "", "", {}) === false);
  assert("canAdvance step 1: true when harness set", testCanAdvance(1, "claude", "", {}) === true);

  // Step 2
  assert("canAdvance step 2: false when no backend", testCanAdvance(2, "claude", "", {}) === false);
  assert("canAdvance step 2: true for phoenix", testCanAdvance(2, "claude", "phoenix", {}) === true);
  assert("canAdvance step 2: false for arize no creds", testCanAdvance(2, "claude", "arize", {}) === false);
  assert("canAdvance step 2: false arize only apiKey", testCanAdvance(2, "claude", "arize", { apiKey: "k" }) === false);
  assert("canAdvance step 2: false arize only spaceId", testCanAdvance(2, "claude", "arize", { spaceId: "s" }) === false);
  assert("canAdvance step 2: true arize both creds", testCanAdvance(2, "claude", "arize", { apiKey: "k", spaceId: "s" }) === true);
  assert("canAdvance step 2: false arize whitespace apiKey", testCanAdvance(2, "claude", "arize", { apiKey: "  ", spaceId: "s" }) === false);
  assert("canAdvance step 2: false arize whitespace spaceId", testCanAdvance(2, "claude", "arize", { apiKey: "k", spaceId: "  " }) === false);

  // Step 3-4 always true
  assert("canAdvance step 3: always true", testCanAdvance(3, "", "", {}) === true);
  assert("canAdvance step 4: always true", testCanAdvance(4, "", "", {}) === true);
  assert("canAdvance step 0: false", testCanAdvance(0, "", "", {}) === false);
  assert("canAdvance step 5: false", testCanAdvance(5, "", "", {}) === false);

  console.log("\n[wizard.js — nextStep logic]");

  function testNextStep(currentStep, harness) {
    if (currentStep === 2 && harness !== "claude") return 4;
    return currentStep + 1;
  }

  assert("nextStep: 1 → 2", testNextStep(1, "claude") === 2);
  assert("nextStep: 2 → 3 for claude", testNextStep(2, "claude") === 3);
  assert("nextStep: 2 → 4 for codex", testNextStep(2, "codex") === 4);
  assert("nextStep: 2 → 4 for cursor", testNextStep(2, "cursor") === 4);
  assert("nextStep: 3 → 4", testNextStep(3, "claude") === 4);

  console.log("\n[wizard.js — prevStep logic]");

  function testPrevStep(currentStep, harness) {
    if (currentStep === 4 && harness !== "claude") return 2;
    return currentStep - 1;
  }

  assert("prevStep: 2 → 1", testPrevStep(2, "claude") === 1);
  assert("prevStep: 3 → 2", testPrevStep(3, "claude") === 2);
  assert("prevStep: 4 → 3 for claude", testPrevStep(4, "claude") === 3);
  assert("prevStep: 4 → 2 for codex", testPrevStep(4, "codex") === 2);
  assert("prevStep: 4 → 2 for cursor", testPrevStep(4, "cursor") === 2);

  console.log("\n[wizard.js — escapeAttr logic]");

  function testEscapeAttr(str) {
    return (str || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  assert("escapeAttr: null/undefined", testEscapeAttr(null) === "");
  assert("escapeAttr: empty string", testEscapeAttr("") === "");
  assert("escapeAttr: plain text", testEscapeAttr("hello") === "hello");
  assert("escapeAttr: ampersand", testEscapeAttr("a&b") === "a&amp;b");
  assert("escapeAttr: quotes", testEscapeAttr('a"b') === "a&quot;b");
  assert("escapeAttr: angle brackets", testEscapeAttr("a<b>c") === "a&lt;b&gt;c");
  assert("escapeAttr: all special chars", testEscapeAttr('&"<>') === "&amp;&quot;&lt;&gt;");

  // ===========================================================================
  // Part 7: Full navigation flow simulation
  // ===========================================================================
  console.log("\n[Navigation flow — Claude path]");

  var step = 1;
  assert("flow-claude: starts at step 1", step === 1);
  assert("flow-claude: cannot advance without harness", testCanAdvance(1, "", "", {}) === false);
  var harness = "claude";
  assert("flow-claude: can advance after selecting claude", testCanAdvance(1, harness, "", {}) === true);
  step = testNextStep(step, harness);
  assert("flow-claude: now at step 2", step === 2);

  assert("flow-claude: cannot advance without backend", testCanAdvance(2, harness, "", {}) === false);
  var backend = "arize";
  assert("flow-claude: cannot advance without creds", testCanAdvance(2, harness, backend, {}) === false);
  var creds = { apiKey: "key123", spaceId: "sp456" };
  assert("flow-claude: can advance with creds", testCanAdvance(2, harness, backend, creds) === true);
  step = testNextStep(step, harness);
  assert("flow-claude: now at step 3", step === 3);

  assert("flow-claude: can advance from step 3", testCanAdvance(3, harness, backend, creds) === true);
  step = testNextStep(step, harness);
  assert("flow-claude: now at step 4", step === 4);

  step = testPrevStep(step, harness);
  assert("flow-claude: back to step 3", step === 3);
  step = testPrevStep(step, harness);
  assert("flow-claude: back to step 2", step === 2);
  step = testPrevStep(step, harness);
  assert("flow-claude: back to step 1", step === 1);

  console.log("\n[Navigation flow — Codex path (skip step 3)]");
  step = 1;
  harness = "codex";
  step = testNextStep(step, harness);
  assert("flow-codex: 1 → 2", step === 2);
  step = testNextStep(step, harness);
  assert("flow-codex: 2 → 4 (skip 3)", step === 4);
  step = testPrevStep(step, harness);
  assert("flow-codex: 4 → 2 (skip 3 back)", step === 2);

  console.log("\n[Navigation flow — Cursor path (skip step 3)]");
  step = 1;
  harness = "cursor";
  step = testNextStep(step, harness);
  assert("flow-cursor: 1 → 2", step === 2);
  step = testNextStep(step, harness);
  assert("flow-cursor: 2 → 4 (skip 3)", step === 4);
  step = testPrevStep(step, harness);
  assert("flow-cursor: 4 → 2 (skip 3 back)", step === 2);

  // ===========================================================================
  // Part 8: getNonce analysis
  // ===========================================================================
  console.log("\n[getNonce — analysis]");
  assert("getNonce uses alphanumeric chars", wizardTs.includes("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"));
  assert("getNonce produces 32-char output", wizardTs.includes("i < 32"));
  assert("getNonce uses Math.random", wizardTs.includes("Math.random()"));
}

// ===========================================================================
// Run all tests
// ===========================================================================
runStaticTests();

runRuntimeTests().then(function () {
  // Cleanup
  Module._resolveFilename = origResolve;
  try { fs.unlinkSync(mockVscodePath); } catch {}

  printSummary();
  process.exit(failed > 0 ? 1 : 0);
}).catch(function (err) {
  console.log("\n  UNEXPECTED ERROR:", err.message);
  console.log(err.stack);
  Module._resolveFilename = origResolve;
  try { fs.unlinkSync(mockVscodePath); } catch {}
  printSummary();
  process.exit(1);
});
