import * as vscode from "vscode";
import * as os from "os";
import * as path from "path";
import { parse as parseYaml } from "yaml";
import * as fs from "fs";
import { InstallerBridge } from "./installer";

/**
 * State sent to the sidebar webview for rendering.
 */
interface SidebarState {
  collector: { running: boolean; port: number };
  backend: string;
  harnesses: Array<{ name: string; project: string }>;
}

/**
 * Webview provider for the Arize sidebar panel.
 *
 * Shows installed harnesses and collector status by reading
 * `~/.arize/harness/config.yaml`. Auto-refreshes when the
 * config file changes on disk.
 */
export class SidebarProvider implements vscode.WebviewViewProvider {
  private view: vscode.WebviewView | undefined;
  private configWatcher: vscode.FileSystemWatcher | undefined;
  private installer: InstallerBridge | undefined;

  constructor(private readonly extensionUri: vscode.Uri) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this.view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };

    webviewView.webview.html = this.getHtml(webviewView.webview);

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage((msg) =>
      this.handleMessage(msg),
    );

    // Watch config.yaml for changes
    this.watchConfigFile();

    // Send initial state
    this.refresh();
  }

  /**
   * Re-read config and push updated state to the webview.
   */
  refresh(): void {
    if (!this.view) {
      return;
    }
    const state = this.readConfig();
    this.view.webview.postMessage({ type: "state", ...state });
  }

  /**
   * Provide the InstallerBridge so the sidebar can trigger
   * uninstall and collector control operations.
   */
  setInstaller(installer: InstallerBridge): void {
    this.installer = installer;
  }

  dispose(): void {
    this.configWatcher?.dispose();
  }

  // ---------------------------------------------------------------------------
  // Config reading
  // ---------------------------------------------------------------------------

  private getConfigPath(): string {
    return path.join(os.homedir(), ".arize", "harness", "config.yaml");
  }

  /**
   * Read `~/.arize/harness/config.yaml` and extract sidebar state.
   */
  private readConfig(): SidebarState {
    const configPath = this.getConfigPath();
    const empty: SidebarState = {
      collector: { running: false, port: 4318 },
      backend: "none",
      harnesses: [],
    };

    try {
      if (!fs.existsSync(configPath)) {
        return empty;
      }
      const raw = fs.readFileSync(configPath, "utf-8");
      const doc = parseYaml(raw) as Record<string, unknown> | null;
      if (!doc || typeof doc !== "object") {
        return empty;
      }

      // Collector info
      const collectorSection = doc.collector as
        | Record<string, unknown>
        | undefined;
      const collector = {
        running: collectorSection?.running === true,
        port:
          typeof collectorSection?.port === "number"
            ? collectorSection.port
            : 4318,
      };

      // Backend
      const backend =
        typeof doc.backend === "string" ? doc.backend : "none";

      // Harnesses
      const harnessesSection = doc.harnesses as
        | Record<string, Record<string, unknown>>
        | undefined;
      const harnesses: SidebarState["harnesses"] = [];
      if (harnessesSection && typeof harnessesSection === "object") {
        for (const [name, cfg] of Object.entries(harnessesSection)) {
          harnesses.push({
            name,
            project:
              typeof cfg?.project === "string"
                ? cfg.project
                : "(default)",
          });
        }
      }

      return { collector, backend, harnesses };
    } catch {
      return empty;
    }
  }

  // ---------------------------------------------------------------------------
  // File watching
  // ---------------------------------------------------------------------------

  private watchConfigFile(): void {
    const configDir = path.join(os.homedir(), ".arize", "harness");
    const pattern = new vscode.RelativePattern(
      vscode.Uri.file(configDir),
      "config.yaml",
    );
    this.configWatcher = vscode.workspace.createFileSystemWatcher(pattern);

    const onFileChange = () => this.refresh();
    this.configWatcher.onDidChange(onFileChange);
    this.configWatcher.onDidCreate(onFileChange);
    this.configWatcher.onDidDelete(onFileChange);
  }

  // ---------------------------------------------------------------------------
  // Message handling
  // ---------------------------------------------------------------------------

  private async handleMessage(msg: {
    type: string;
    harness?: string;
  }): Promise<void> {
    switch (msg.type) {
      case "addHarness":
        vscode.commands.executeCommand("arize.setup");
        break;

      case "reconfigure":
        if (msg.harness) {
          vscode.commands.executeCommand("arize.reconfigure", msg.harness);
        }
        break;

      case "remove":
        if (msg.harness) {
          await this.handleRemove(msg.harness);
        }
        break;

      case "startCollector":
        await this.handleCollectorControl("start");
        break;

      case "stopCollector":
        await this.handleCollectorControl("stop");
        break;
    }
  }

  private async handleRemove(harness: string): Promise<void> {
    const answer = await vscode.window.showWarningMessage(
      `Remove ${harness} harness? This will unregister Arize tracing hooks for ${harness}.`,
      { modal: true },
      "Remove",
    );
    if (answer !== "Remove") {
      return;
    }

    if (!this.installer) {
      vscode.window.showErrorMessage(
        "Arize: Installer not available. Run the setup wizard first.",
      );
      return;
    }

    const result = await this.installer.runUninstall(harness);
    if (result.success) {
      vscode.window.showInformationMessage(
        `Arize: ${harness} harness removed.`,
      );
    } else {
      vscode.window.showErrorMessage(
        `Arize: Failed to remove ${harness} — ${result.error ?? "unknown error"}`,
      );
    }
    this.refresh();
  }

  private async handleCollectorControl(
    action: "start" | "stop",
  ): Promise<void> {
    if (!this.installer) {
      vscode.window.showErrorMessage(
        "Arize: Installer not available. Run the setup wizard first.",
      );
      return;
    }

    const ok = await this.installer.controlCollector(action);
    if (ok) {
      vscode.window.showInformationMessage(
        `Arize: Collector ${action === "start" ? "started" : "stopped"}.`,
      );
    } else {
      vscode.window.showErrorMessage(
        `Arize: Failed to ${action} collector.`,
      );
    }
    this.refresh();
  }

  // ---------------------------------------------------------------------------
  // HTML generation
  // ---------------------------------------------------------------------------

  private getHtml(webview: vscode.Webview): string {
    // Use a nonce for Content Security Policy
    const nonce = getNonce();

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';" />
  <title>Arize Tracing</title>
  <style>
    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      padding: 0;
      margin: 0;
    }
    .header {
      padding: 8px 12px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--vscode-sideBarSectionHeader-foreground);
    }
    .status-row {
      display: flex;
      align-items: center;
      padding: 4px 12px;
      cursor: pointer;
      gap: 6px;
    }
    .status-row:hover {
      background: var(--vscode-list-hoverBackground);
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .dot.running { background: #3fb950; }
    .dot.stopped { background: #f85149; }
    .backend-row {
      padding: 4px 12px;
      font-size: 12px;
      color: var(--vscode-descriptionForeground);
    }
    .divider {
      padding: 8px 12px 4px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--vscode-sideBarSectionHeader-foreground);
      border-top: 1px solid var(--vscode-sideBarSectionHeader-border);
      margin-top: 4px;
    }
    .harness-card {
      padding: 6px 12px;
      border-bottom: 1px solid var(--vscode-widget-border, transparent);
    }
    .harness-card:hover {
      background: var(--vscode-list-hoverBackground);
    }
    .harness-name {
      font-weight: 600;
      font-size: 13px;
      margin-bottom: 2px;
    }
    .harness-project {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      margin-bottom: 4px;
    }
    .harness-actions {
      display: flex;
      gap: 8px;
    }
    .action-btn {
      background: none;
      border: none;
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      font-size: 11px;
      padding: 0;
    }
    .action-btn:hover {
      color: var(--vscode-textLink-activeForeground);
      text-decoration: underline;
    }
    .add-btn {
      display: block;
      width: calc(100% - 24px);
      margin: 8px 12px;
      padding: 6px 0;
      text-align: center;
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      border-radius: 2px;
      cursor: pointer;
      font-size: 12px;
    }
    .add-btn:hover {
      background: var(--vscode-button-hoverBackground);
    }
    .empty-state {
      padding: 16px 12px;
      text-align: center;
      color: var(--vscode-descriptionForeground);
      font-size: 12px;
      line-height: 1.4;
    }
    #harness-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }
  </style>
</head>
<body>
  <div class="header">ARIZE TRACING</div>

  <div id="collector-status" class="status-row" title="Click to toggle collector">
    <span class="dot stopped" id="collector-dot"></span>
    <span id="collector-label">Stopped</span>
  </div>

  <div class="backend-row" id="backend-row">Backend: —</div>

  <div class="divider">Installed</div>

  <div id="harness-list"></div>

  <div id="empty-state" class="empty-state" style="display: none;">
    No harnesses configured.<br />Click + Add Harness to get started.
  </div>

  <button class="add-btn" id="add-btn">+ Add Harness</button>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();

    const collectorStatus = document.getElementById('collector-status');
    const collectorDot = document.getElementById('collector-dot');
    const collectorLabel = document.getElementById('collector-label');
    const backendRow = document.getElementById('backend-row');
    const harnessList = document.getElementById('harness-list');
    const emptyState = document.getElementById('empty-state');
    const addBtn = document.getElementById('add-btn');

    // Render state from extension
    function renderState(state) {
      // Collector
      const running = state.collector && state.collector.running;
      collectorDot.className = 'dot ' + (running ? 'running' : 'stopped');
      collectorLabel.textContent = running ? 'Running' : 'Stopped';
      collectorStatus.title = running ? 'Click to stop collector' : 'Click to start collector';

      // Backend
      const backend = state.backend || 'none';
      backendRow.textContent = 'Backend: ' + (backend === 'none' ? '—' : backend);

      // Harnesses
      harnessList.innerHTML = '';
      const harnesses = state.harnesses || [];

      if (harnesses.length === 0) {
        emptyState.style.display = 'block';
      } else {
        emptyState.style.display = 'none';
        harnesses.forEach(function(h) {
          const card = document.createElement('div');
          card.className = 'harness-card';

          const name = document.createElement('div');
          name.className = 'harness-name';
          name.textContent = h.name;
          card.appendChild(name);

          const project = document.createElement('div');
          project.className = 'harness-project';
          project.textContent = 'Project: ' + h.project;
          card.appendChild(project);

          const actions = document.createElement('div');
          actions.className = 'harness-actions';

          const reconfigureBtn = document.createElement('button');
          reconfigureBtn.className = 'action-btn';
          reconfigureBtn.textContent = 'Reconfigure';
          reconfigureBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            vscode.postMessage({ type: 'reconfigure', harness: h.name });
          });
          actions.appendChild(reconfigureBtn);

          const removeBtn = document.createElement('button');
          removeBtn.className = 'action-btn';
          removeBtn.textContent = 'Remove';
          removeBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            vscode.postMessage({ type: 'remove', harness: h.name });
          });
          actions.appendChild(removeBtn);

          card.appendChild(actions);
          harnessList.appendChild(card);
        });
      }
    }

    // Collector toggle
    collectorStatus.addEventListener('click', function() {
      const isRunning = collectorDot.classList.contains('running');
      vscode.postMessage({ type: isRunning ? 'stopCollector' : 'startCollector' });
    });

    // Add harness
    addBtn.addEventListener('click', function() {
      vscode.postMessage({ type: 'addHarness' });
    });

    // Listen for state updates from extension
    window.addEventListener('message', function(event) {
      const msg = event.data;
      if (msg.type === 'state') {
        renderState(msg);
      }
    });
  </script>
</body>
</html>`;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getNonce(): string {
  let text = "";
  const possible =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}
