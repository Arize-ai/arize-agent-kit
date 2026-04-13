/**
 * Minimal VS Code API mock for unit testing.
 */

export enum StatusBarAlignment {
  Left = 1,
  Right = 2,
}

function createMockStatusBarItem(): any {
  return {
    text: "",
    tooltip: "",
    command: undefined as string | undefined,
    alignment: StatusBarAlignment.Right,
    priority: 0,
    show: jest.fn(),
    hide: jest.fn(),
    dispose: jest.fn(),
  };
}

export const window = {
  createStatusBarItem: jest.fn((_alignment?: StatusBarAlignment, _priority?: number) =>
    createMockStatusBarItem(),
  ),
  showQuickPick: jest.fn(),
  showInformationMessage: jest.fn(),
  showWarningMessage: jest.fn(),
  showErrorMessage: jest.fn(),
  registerWebviewViewProvider: jest.fn(),
};

export const commands = {
  registerCommand: jest.fn((_command: string, _callback: (...args: any[]) => any) => ({
    dispose: jest.fn(),
  })),
  executeCommand: jest.fn(),
};

export interface QuickPickItem {
  label: string;
  description?: string;
  detail?: string;
}

export type ExtensionContext = {
  subscriptions: { dispose: () => void }[];
  extensionUri: any;
};
