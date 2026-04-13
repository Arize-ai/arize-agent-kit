import * as vscode from "vscode";

export function activate(context: vscode.ExtensionContext): void {
  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand("arize.setup", () => {
      vscode.window.showInformationMessage("Arize: Setup wizard not yet implemented.");
    }),
    vscode.commands.registerCommand("arize.reconfigure", () => {
      vscode.window.showInformationMessage("Arize: Reconfigure not yet implemented.");
    }),
    vscode.commands.registerCommand("arize.startCollector", () => {
      vscode.window.showInformationMessage("Arize: Start collector not yet implemented.");
    }),
    vscode.commands.registerCommand("arize.stopCollector", () => {
      vscode.window.showInformationMessage("Arize: Stop collector not yet implemented.");
    })
  );
}

export function deactivate(): void {
  // Nothing to clean up yet.
}
