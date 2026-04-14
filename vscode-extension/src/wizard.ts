import * as vscode from "vscode";
import { existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { InstallerBridge, InstallOptions } from "./installer";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WizardOptions {
  /** When true, pre-fill the form with values from existing config. */
  prefill?: boolean;
  /** Harness to pre-select (used by reconfigure). */
  harness?: string;
}

/** Messages sent from the webview to the extension. */
interface WebviewToExtension {
  type: "install" | "detectIdes" | "cancel" | "ready";
  harness?: string;
  backend?: string;
  credentials?: Record<string, string>;
  userId?: string;
  scope?: string;
}

// ---------------------------------------------------------------------------
// WizardPanel — singleton webview panel
// ---------------------------------------------------------------------------

export class WizardPanel {
  public static currentPanel: WizardPanel | undefined;

  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private readonly installer: InstallerBridge;
  private disposables: vscode.Disposable[] = [];
  private disposed = false;
  private pendingPrefill?: {
    harness: string;
    backend?: string;
    credentials?: Record<string, string>;
    userId?: string;
    scope?: string;
  };

  private constructor(
    panel: vscode.WebviewPanel,
    extensionUri: vscode.Uri,
  ) {
    this.panel = panel;
    this.extensionUri = extensionUri;
    this.installer = new InstallerBridge(extensionUri.fsPath);

    // Stream install output to the webview
    this.installer.onOutput.event((line) => {
      this.panel.webview.postMessage({ type: "output", line });
    });

    // Handle messages from the webview
    this.panel.webview.onDidReceiveMessage(
      (msg: WebviewToExtension) => this.handleMessage(msg),
      undefined,
      this.disposables,
    );

    // Clean up on panel close
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

    // Set the HTML content
    this.panel.webview.html = this.getHtmlContent();
  }

  /**
   * Open the wizard for a fresh setup.
   */
  static openForSetup(extensionUri: vscode.Uri): void {
    WizardPanel.createOrReveal(extensionUri);
  }

  /**
   * Open the wizard pre-filled with existing config for reconfiguration.
   */
  static openForReconfigure(
    extensionUri: vscode.Uri,
    harness: string,
    config: { backend?: string; credentials?: Record<string, string>; userId?: string; scope?: string },
  ): void {
    const panel = WizardPanel.createOrReveal(extensionUri);
    // Store prefill data — it will be sent when the webview sends "ready"
    panel.pendingPrefill = {
      harness,
      backend: config.backend,
      credentials: config.credentials,
      userId: config.userId,
      scope: config.scope,
    };
  }

  // -------------------------------------------------------------------------
  // Singleton management
  // -------------------------------------------------------------------------

  private static createOrReveal(extensionUri: vscode.Uri): WizardPanel {
    if (WizardPanel.currentPanel) {
      WizardPanel.currentPanel.panel.reveal(vscode.ViewColumn.One);
      return WizardPanel.currentPanel;
    }

    const panel = vscode.window.createWebviewPanel(
      "arize-wizard",
      "Arize: Setup Wizard",
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(extensionUri, "media"),
        ],
      },
    );

    WizardPanel.currentPanel = new WizardPanel(panel, extensionUri);
    return WizardPanel.currentPanel;
  }

  // -------------------------------------------------------------------------
  // Message handling
  // -------------------------------------------------------------------------

  private async handleMessage(msg: WebviewToExtension): Promise<void> {
    switch (msg.type) {
      case "ready":
        this.handleReady();
        break;
      case "install":
        await this.handleInstall(msg);
        break;
      case "detectIdes":
        await this.handleDetectIdes();
        break;
      case "cancel":
        this.panel.dispose();
        break;
    }
  }

  private handleReady(): void {
    if (this.pendingPrefill) {
      this.panel.webview.postMessage({
        type: "prefill",
        harness: this.pendingPrefill.harness,
        backend: this.pendingPrefill.backend,
        credentials: this.pendingPrefill.credentials,
        userId: this.pendingPrefill.userId,
        scope: this.pendingPrefill.scope,
      });
      this.pendingPrefill = undefined;
    }
  }

  private async handleInstall(msg: WebviewToExtension): Promise<void> {
    const options: InstallOptions = {
      harness: msg.harness ?? "",
      backend: msg.backend ?? "",
      credentials: msg.credentials ?? {},
      userId: msg.userId,
      scope: msg.scope,
    };

    try {
      const result = await this.installer.runInstall(options);
      this.panel.webview.postMessage({
        type: "complete",
        success: result.success,
        error: result.error,
      });
    } catch (err) {
      this.panel.webview.postMessage({
        type: "complete",
        success: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  private async handleDetectIdes(): Promise<void> {
    // Detection is best-effort — check for common IDE config locations
    const results: Record<string, boolean> = {
      claude: false,
      codex: false,
      cursor: false,
    };

    try {
      const home = homedir();

      // Claude Code: check for settings directory
      const claudePaths = [
        join(home, ".claude"),
      ];
      results.claude = claudePaths.some((p) => existsSync(p));

      // Codex: check for config directory
      const codexPaths = [
        join(home, ".codex"),
        join(home, ".config", "codex"),
      ];
      results.codex = codexPaths.some((p) => existsSync(p));

      // Cursor: check for config across platforms
      const cursorPaths = [
        join(home, ".cursor"),                                       // Linux / common
        join(home, "Library", "Application Support", "Cursor"),      // macOS
        join(home, ".config", "Cursor"),                             // Linux XDG
      ];
      if (process.env.APPDATA) {
        cursorPaths.push(join(process.env.APPDATA, "Cursor"));       // Windows
      }
      results.cursor = cursorPaths.some((p) => existsSync(p));
    } catch {
      // Silently fall through — all false
    }

    this.panel.webview.postMessage({
      type: "ideDetection",
      results,
    });
  }

  // -------------------------------------------------------------------------
  // HTML content
  // -------------------------------------------------------------------------

  private getHtmlContent(): string {
    const webview = this.panel.webview;
    const mediaUri = vscode.Uri.joinPath(this.extensionUri, "media");

    const cssUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaUri, "wizard.css"));
    const jsUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaUri, "wizard.js"));
    const nonce = getNonce();

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src ${webview.cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';" />
  <link rel="stylesheet" href="${cssUri}" />
  <title>Arize Setup Wizard</title>
</head>
<body>
  <div id="wizard-root"></div>
  <script nonce="${nonce}" src="${jsUri}"></script>
</body>
</html>`;
  }

  // -------------------------------------------------------------------------
  // Disposal
  // -------------------------------------------------------------------------

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    WizardPanel.currentPanel = undefined;
    this.installer.dispose();
    this.panel.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
    this.disposables = [];
  }
}

// ---------------------------------------------------------------------------
// Backward-compatible openWizard function used by extension.ts
// ---------------------------------------------------------------------------

export function openWizard(
  context: vscode.ExtensionContext,
  options?: WizardOptions,
): void {
  if (options?.prefill && options.harness) {
    // Reconfigure mode — would normally read config.yaml here
    WizardPanel.openForReconfigure(context.extensionUri, options.harness, {});
  } else {
    WizardPanel.openForSetup(context.extensionUri);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getNonce(): string {
  let text = "";
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}
