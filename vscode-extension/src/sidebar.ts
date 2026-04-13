import * as vscode from "vscode";

/**
 * Webview provider for the Arize sidebar panel.
 *
 * Shows installed harnesses and their status by reading
 * `~/.arize/harness/config.yaml`.
 */
export class SidebarProvider implements vscode.WebviewViewProvider {
  constructor(private readonly extensionUri: vscode.Uri) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };

    webviewView.webview.html = this.getHtml();
  }

  private getHtml(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Arize Tracing</title>
  <style>
    body { font-family: var(--vscode-font-family); padding: 8px; color: var(--vscode-foreground); }
    p { margin: 4px 0; }
  </style>
</head>
<body>
  <p>Arize Tracing sidebar — not yet implemented.</p>
  <p>Run <strong>Arize: Set Up Tracing</strong> from the command palette to get started.</p>
</body>
</html>`;
  }
}
