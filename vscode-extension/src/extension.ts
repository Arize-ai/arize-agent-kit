import * as vscode from "vscode";
import { findPython, getArizeInstallPath } from "./python";
import { SidebarProvider } from "./sidebar";
import { openWizard } from "./wizard";
import { runInstallerCommand, InstallerBridge } from "./installer";
import { createStatusBarItem, updateStatusBar, StatusBarState } from "./status";

let statusBarItem: vscode.StatusBarItem | undefined;
let pollingInterval: ReturnType<typeof setInterval> | undefined;
let pythonPath: string | null = null;

// ---------------------------------------------------------------------------
// Command handlers
// ---------------------------------------------------------------------------

async function handleSetup(context: vscode.ExtensionContext): Promise<void> {
  if (!pythonPath) {
    pythonPath = await findPython();
  }
  if (!pythonPath) {
    vscode.window.showErrorMessage(
      "Arize: Python 3.9+ is required. Please install Python and try again."
    );
    return;
  }
  openWizard(context);
}

async function handleReconfigure(context: vscode.ExtensionContext): Promise<void> {
  if (!pythonPath) {
    pythonPath = await findPython();
  }
  if (!pythonPath) {
    vscode.window.showErrorMessage(
      "Arize: Python 3.9+ is required. Please install Python and try again."
    );
    return;
  }
  openWizard(context, { prefill: true });
}

async function handleStartCollector(): Promise<void> {
  const installPath = getArizeInstallPath();
  if (!installPath) {
    vscode.window.showErrorMessage(
      "Arize: arize-install not found. Run the setup wizard first."
    );
    return;
  }
  try {
    await runInstallerCommand(installPath, ["collector", "start"]);
    vscode.window.showInformationMessage("Arize: Collector started.");
    refreshStatusBar();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Arize: Failed to start collector — ${msg}`);
  }
}

async function handleStopCollector(): Promise<void> {
  const installPath = getArizeInstallPath();
  if (!installPath) {
    vscode.window.showErrorMessage(
      "Arize: arize-install not found. Run the setup wizard first."
    );
    return;
  }
  try {
    await runInstallerCommand(installPath, ["collector", "stop"]);
    vscode.window.showInformationMessage("Arize: Collector stopped.");
    refreshStatusBar();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Arize: Failed to stop collector — ${msg}`);
  }
}

// ---------------------------------------------------------------------------
// Status bar polling
// ---------------------------------------------------------------------------

function refreshStatusBar(): void {
  if (!statusBarItem) {
    return;
  }
  const installPath = getArizeInstallPath();
  if (!installPath) {
    updateStatusBar(statusBarItem, StatusBarState.NotConfigured);
    return;
  }
  runInstallerCommand(installPath, ["collector", "status"])
    .then((output) => {
      if (output.includes("running")) {
        updateStatusBar(statusBarItem!, StatusBarState.Running);
      } else {
        updateStatusBar(statusBarItem!, StatusBarState.Stopped);
      }
    })
    .catch(() => {
      updateStatusBar(statusBarItem!, StatusBarState.NotConfigured);
    });
}

function startPolling(): void {
  refreshStatusBar();
  pollingInterval = setInterval(refreshStatusBar, 30_000);
}

function stopPolling(): void {
  if (pollingInterval !== undefined) {
    clearInterval(pollingInterval);
    pollingInterval = undefined;
  }
}

// ---------------------------------------------------------------------------
// Activation / deactivation
// ---------------------------------------------------------------------------

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand("arize.setup", () => handleSetup(context)),
    vscode.commands.registerCommand("arize.reconfigure", () => handleReconfigure(context)),
    vscode.commands.registerCommand("arize.startCollector", handleStartCollector),
    vscode.commands.registerCommand("arize.stopCollector", handleStopCollector)
  );

  // Register sidebar webview provider with installer bridge
  const sidebarProvider = new SidebarProvider(context.extensionUri);
  const installerBridge = new InstallerBridge(context.extensionPath);
  sidebarProvider.setInstaller(installerBridge);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("arize-sidebar", sidebarProvider),
    sidebarProvider,
    { dispose: () => installerBridge.dispose() }
  );

  // Create status bar item
  statusBarItem = createStatusBarItem();
  context.subscriptions.push(statusBarItem);

  // Run initial Python detection
  pythonPath = await findPython();
  if (!pythonPath) {
    updateStatusBar(statusBarItem, StatusBarState.PythonRequired);
    vscode.window.showWarningMessage(
      "Arize: Python 3.9+ not found. Some features require Python."
    );
  }

  // Start status bar polling
  startPolling();
}

export function deactivate(): void {
  stopPolling();
  if (statusBarItem) {
    statusBarItem.dispose();
    statusBarItem = undefined;
  }
}
