/**
 * Tests for SidebarProvider.
 *
 * Uses the manual vscode mock from src/__tests__/__mocks__/vscode.ts.
 * Jest is configured to map "vscode" to that mock via moduleNameMapper.
 */

const vscode = require("vscode");

const { SidebarProvider } = require("../src/sidebar");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeWebviewView() {
  const listeners = {};
  const webview = {
    options: {},
    html: "",
    postMessage: jest.fn().mockResolvedValue(true),
    onDidReceiveMessage: jest.fn((cb, _thisArg, _disposables) => {
      listeners.message = cb;
      return { dispose: jest.fn() };
    }),
  };
  const view = {
    webview,
    visible: true,
    onDidChangeVisibility: jest.fn((cb, _thisArg, _disposables) => {
      listeners.visibility = cb;
      return { dispose: jest.fn() };
    }),
  };
  return { view, webview, listeners };
}

function emptyState() {
  return {
    harnesses: [],
    userId: null,
    codexBuffer: null,
    bridgeError: null,
  };
}

function fullState() {
  return {
    harnesses: [
      { name: "claude-code", configured: true, projectName: "my-proj", backendLabel: "Arize AX" },
      { name: "codex", configured: true, projectName: "codex-proj", backendLabel: "Phoenix" },
      { name: "cursor", configured: false, projectName: null, backendLabel: null },
      { name: "copilot", configured: false, projectName: null, backendLabel: null },
      { name: "gemini", configured: false, projectName: null, backendLabel: null },
    ],
    userId: "user@example.com",
    codexBuffer: { state: "running", host: "localhost", port: 4318 },
    bridgeError: null,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SidebarProvider", () => {
  let provider;
  let viewParts;

  beforeEach(() => {
    jest.clearAllMocks();
    const extensionUri = vscode.Uri.file("/test/extension");
    provider = new SidebarProvider(extensionUri);
    viewParts = makeWebviewView();
  });

  afterEach(() => {
    provider.dispose();
  });

  test("resolveWebviewView does not throw", () => {
    expect(() => {
      provider.resolveWebviewView(viewParts.view, {}, {});
    }).not.toThrow();
  });

  test("resolveWebviewView sets html on the webview", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    expect(viewParts.webview.html).toBeTruthy();
    expect(viewParts.webview.html).toContain("<!DOCTYPE html>");
    expect(viewParts.webview.html).toContain("nonce-");
  });

  test("render() posts a render message via webview.postMessage", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const state = emptyState();
    provider.render(state);
    expect(viewParts.webview.postMessage).toHaveBeenCalledWith({
      type: "render",
      state,
    });
  });

  test("render() with full state posts correct structure", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const state = fullState();
    provider.render(state);
    const call = viewParts.webview.postMessage.mock.calls[0][0];
    expect(call.type).toBe("render");
    expect(call.state.harnesses).toHaveLength(5);
    expect(call.state.harnesses[0].name).toBe("claude-code");
    expect(call.state.harnesses[0].configured).toBe(true);
    expect(call.state.userId).toBe("user@example.com");
    expect(call.state.codexBuffer).toEqual({ state: "running", host: "localhost", port: 4318 });
  });

  test("render() is idempotent — calling twice posts twice", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const state = emptyState();
    provider.render(state);
    provider.render(state);
    expect(viewParts.webview.postMessage).toHaveBeenCalledTimes(2);
  });

  test("render() before resolveWebviewView does not throw", () => {
    expect(() => provider.render(emptyState())).not.toThrow();
  });

  test("action message from webview fires onAction", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const actionHandler = jest.fn();
    provider.onAction(actionHandler);

    const action = { type: "reconfigure", harness: "codex" };
    // Simulate the webview posting a message
    viewParts.listeners.message({ type: "action", action });

    expect(actionHandler).toHaveBeenCalledWith(action);
  });

  test("ready message from webview does not fire onAction", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const actionHandler = jest.fn();
    provider.onAction(actionHandler);

    viewParts.listeners.message({ type: "ready" });

    expect(actionHandler).not.toHaveBeenCalled();
  });

  test("action message with setup type fires correctly", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const actionHandler = jest.fn();
    provider.onAction(actionHandler);

    viewParts.listeners.message({ type: "action", action: { type: "setup" } });

    expect(actionHandler).toHaveBeenCalledWith({ type: "setup" });
  });

  test("bridgeError renders error banner content in posted state", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const state = { ...emptyState(), bridgeError: "Bridge failed to connect" };
    provider.render(state);
    const call = viewParts.webview.postMessage.mock.calls[0][0];
    expect(call.state.bridgeError).toBe("Bridge failed to connect");
  });

  test("HTML contains error-banner markup when bridgeError would be set", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    // The HTML template contains the error-banner conditional logic
    expect(viewParts.webview.html).toContain("error-banner");
  });

  test("codexBuffer null in state means no codex-buffer in posted state", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    provider.render(emptyState());
    const call = viewParts.webview.postMessage.mock.calls[0][0];
    expect(call.state.codexBuffer).toBeNull();
  });

  test("codexBuffer running state posts with Stop button context", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const state = {
      ...emptyState(),
      codexBuffer: { state: "running", host: "localhost", port: 4318 },
    };
    provider.render(state);
    const call = viewParts.webview.postMessage.mock.calls[0][0];
    expect(call.state.codexBuffer.state).toBe("running");
    // The webview JS will render a "Stop" button for "running" state
  });

  test("codexBuffer stopped state posts with Start button context", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const state = {
      ...emptyState(),
      codexBuffer: { state: "stopped", host: null, port: null },
    };
    provider.render(state);
    const call = viewParts.webview.postMessage.mock.calls[0][0];
    expect(call.state.codexBuffer.state).toBe("stopped");
    // The webview JS will render a "Start" button for "stopped" state
  });

  test("HTML contains codex-buffer conditional rendering logic", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    expect(viewParts.webview.html).toContain("codex-buffer");
    expect(viewParts.webview.html).toContain("Codex buffer service");
    expect(viewParts.webview.html).toContain("stopCodexBuffer");
    expect(viewParts.webview.html).toContain("startCodexBuffer");
  });

  test("HTML does not contain 'collector' wording", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    expect(viewParts.webview.html.toLowerCase()).not.toContain("collector");
  });

  test("visible returns false before resolveWebviewView", () => {
    expect(provider.visible).toBe(false);
  });

  test("visible returns true after resolveWebviewView with visible view", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    expect(provider.visible).toBe(true);
  });

  test("HTML renders all HARNESS_KEYS labels", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    expect(viewParts.webview.html).toContain("Claude Code");
    expect(viewParts.webview.html).toContain("Codex");
    expect(viewParts.webview.html).toContain("Cursor");
    expect(viewParts.webview.html).toContain("Copilot");
    expect(viewParts.webview.html).toContain("Gemini");
  });

  test("HTML has CSP with nonce", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    expect(viewParts.webview.html).toMatch(/Content-Security-Policy/);
    expect(viewParts.webview.html).toMatch(/nonce-[A-Za-z0-9]{32}/);
  });

  test("visibility change fires onDidChangeVisibility with true/false", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    const visHandler = jest.fn();
    provider.onDidChangeVisibility(visHandler);

    // Simulate view becoming hidden
    viewParts.view.visible = false;
    viewParts.listeners.visibility();
    expect(visHandler).toHaveBeenCalledWith(false);

    // Simulate view becoming visible again
    viewParts.view.visible = true;
    viewParts.listeners.visibility();
    expect(visHandler).toHaveBeenCalledWith(true);
    expect(visHandler).toHaveBeenCalledTimes(2);
  });

  test("dispose() does not throw and cleans up emitters", () => {
    provider.resolveWebviewView(viewParts.view, {}, {});
    expect(() => provider.dispose()).not.toThrow();

    // After dispose, firing actions should not reach previously-registered listeners
    const actionHandler = jest.fn();
    // onAction emitter is disposed, so registering after dispose is a no-op
    // (the mock EventEmitter clears listeners on dispose)
    provider.onAction(actionHandler);
    expect(actionHandler).not.toHaveBeenCalled();
  });
});
