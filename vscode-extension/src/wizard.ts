import * as vscode from "vscode";

export interface WizardOptions {
  /** When true, pre-fill the form with values from existing config. */
  prefill?: boolean;
}

/**
 * Open the Arize setup wizard as a webview panel.
 */
export function openWizard(
  context: vscode.ExtensionContext,
  options?: WizardOptions
): void {
  const panel = vscode.window.createWebviewPanel(
    "arize-wizard",
    "Arize: Setup Wizard",
    vscode.ViewColumn.One,
    {
      enableScripts: true,
      localResourceRoots: [context.extensionUri],
    }
  );

  const prefillNote = options?.prefill
    ? "<p><em>Pre-filling from existing configuration…</em></p>"
    : "";

  panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Arize Setup Wizard</title>
  <style>
    body { font-family: var(--vscode-font-family); padding: 16px; color: var(--vscode-foreground); }
  </style>
</head>
<body>
  <h2>Arize Setup Wizard</h2>
  ${prefillNote}
  <p>Wizard implementation coming soon.</p>
</body>
</html>`;
}
