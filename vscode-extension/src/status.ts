import * as vscode from "vscode";

export enum StatusBarState {
  NotConfigured = "notConfigured",
  PythonRequired = "pythonRequired",
  Running = "running",
  Stopped = "stopped",
}

const STATUS_LABELS: Record<StatusBarState, string> = {
  [StatusBarState.NotConfigured]: "$(circle-slash) Arize: Not configured",
  [StatusBarState.PythonRequired]: "$(warning) Arize: Python required",
  [StatusBarState.Running]: "$(pulse) Arize: Collector running",
  [StatusBarState.Stopped]: "$(debug-stop) Arize: Collector stopped",
};

/**
 * Create the Arize status bar item. Clicking it opens the setup wizard.
 */
export function createStatusBarItem(): vscode.StatusBarItem {
  const item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    50
  );
  item.command = "arize.setup";
  updateStatusBar(item, StatusBarState.NotConfigured);
  item.show();
  return item;
}

/**
 * Update the status bar item text and tooltip based on state.
 */
export function updateStatusBar(
  item: vscode.StatusBarItem,
  state: StatusBarState
): void {
  item.text = STATUS_LABELS[state];
  item.tooltip = `Arize Agent Kit — ${state.replace(/([A-Z])/g, " $1").trim()}`;
}
