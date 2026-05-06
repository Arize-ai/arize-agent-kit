import * as vscode from "vscode";

export function activate(ctx: vscode.ExtensionContext): void {
  const commands: Array<[string, () => void]> = [
    ["arize.setup", () => vscode.window.showInformationMessage("not yet implemented")],
    ["arize.reconfigure", () => vscode.window.showInformationMessage("not yet implemented")],
    ["arize.uninstall", () => vscode.window.showInformationMessage("not yet implemented")],
    ["arize.refreshStatus", () => vscode.window.showInformationMessage("not yet implemented")],
    ["arize.startCodexBuffer", () => vscode.window.showInformationMessage("not yet implemented")],
    ["arize.stopCodexBuffer", () => vscode.window.showInformationMessage("not yet implemented")],
    ["arize.statusBarMenu", () => vscode.window.showInformationMessage("not yet implemented")],
  ];

  for (const [id, handler] of commands) {
    ctx.subscriptions.push(vscode.commands.registerCommand(id, handler));
  }
}

export function deactivate(): void {
  // Nothing to clean up yet.
}
