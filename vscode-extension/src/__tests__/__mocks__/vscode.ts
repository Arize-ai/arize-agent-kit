/**
 * Minimal manual mock for the `vscode` module.
 * Provides stubs sufficient to import and test extension.ts under Jest.
 */

export const commands = {
  registerCommand: jest.fn((_id: string, _cb: (...args: unknown[]) => unknown) => ({
    dispose: jest.fn(),
  })),
};

export const window = {
  showInformationMessage: jest.fn((_msg: string) => Promise.resolve(undefined)),
  createWebviewPanel: jest.fn(() => ({
    webview: { html: "", onDidReceiveMessage: jest.fn(), postMessage: jest.fn() },
    onDidDispose: jest.fn(),
    dispose: jest.fn(),
  })),
  registerWebviewViewProvider: jest.fn((_id: string, _provider: unknown) => ({
    dispose: jest.fn(),
  })),
};

export const Uri = {
  file: jest.fn((path: string) => ({ scheme: "file", path })),
};

export class EventEmitter {
  private _listeners: Array<(e: unknown) => void> = [];

  event = jest.fn((listener: (e: unknown) => void) => {
    this._listeners.push(listener);
    return { dispose: jest.fn(() => {
      this._listeners = this._listeners.filter((l) => l !== listener);
    }) };
  });

  fire = jest.fn((data: unknown) => {
    for (const listener of this._listeners) {
      listener(data);
    }
  });

  dispose = jest.fn(() => {
    this._listeners = [];
  });
}

export class Disposable {
  static from(..._disposables: Array<{ dispose: () => void }>): Disposable {
    return new Disposable();
  }
  dispose = jest.fn();
}
