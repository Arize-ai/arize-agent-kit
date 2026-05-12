/**
 * Tests for wizard.ts → _sendPrefill mapping.
 *
 * Specifically: verify that kiro_options on a HarnessStatusItem is forwarded
 * into the prefill message posted to the webview during reconfigure.
 */

import * as vscode from "vscode";
import { WizardPanel } from "../wizard";
import type { InstallerBridge } from "../installer";
import type {
  HarnessKey,
  HarnessStatusItem,
  StatusPayload,
} from "../types";
import { HARNESS_KEYS } from "../types";

// ── Helpers ──────────────────────────────────────────────────────────

function makeHarness(
  name: HarnessKey,
  overrides: Partial<HarnessStatusItem> = {},
): HarnessStatusItem {
  return {
    name,
    configured: false,
    project_name: null,
    backend: null,
    scope: null,
    kiro_options: null,
    ...overrides,
  };
}

function makeStatus(overrides: Partial<StatusPayload> = {}): StatusPayload {
  return {
    success: true,
    error: null,
    user_id: "u1",
    harnesses: HARNESS_KEYS.map((k) => makeHarness(k)),
    logging: null,
    codex_buffer: null,
    ...overrides,
  };
}

function makeInstaller(status: StatusPayload): InstallerBridge {
  return {
    install: jest.fn(),
    uninstall: jest.fn(),
    loadStatus: jest.fn().mockResolvedValue(status),
  };
}

function getCreatedPanel(): {
  webview: {
    postMessage: jest.Mock;
    _simulateMessage: (msg: unknown) => void;
  };
  dispose: () => void;
} {
  const mockFn = vscode.window.createWebviewPanel as jest.Mock;
  const result = mockFn.mock.results[mockFn.mock.results.length - 1];
  return result.value;
}

// ── Tests ────────────────────────────────────────────────────────────

describe("WizardPanel._sendPrefill", () => {
  const extensionUri = vscode.Uri.file("/ext");

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset the singleton between tests.
    WizardPanel.currentPanel?.dispose();
  });

  afterEach(() => {
    WizardPanel.currentPanel?.dispose();
  });

  it("prefill for kiro forwards kiro_options.agent_name", async () => {
    const kiroItem = makeHarness("kiro", {
      configured: true,
      project_name: "my-kiro",
      backend: {
        target: "arize",
        endpoint: "https://otlp.arize.com/v1",
        api_key: "ak-1",
        space_id: "sp-1",
      },
      kiro_options: { agent_name: "x", set_default: false },
    });
    const status = makeStatus({
      harnesses: HARNESS_KEYS.map((k) =>
        k === "kiro" ? kiroItem : makeHarness(k),
      ),
    });

    const installer = makeInstaller(status);
    WizardPanel.open(extensionUri, installer, { prefillHarness: "kiro" });

    const panel = getCreatedPanel();
    panel.webview._simulateMessage({ type: "ready" });

    // Wait for _sendPrefill's async loadStatus() + postMessage to resolve.
    await new Promise((r) => setImmediate(r));

    expect(panel.webview.postMessage).toHaveBeenCalledTimes(1);
    const msg = panel.webview.postMessage.mock.calls[0][0];
    expect(msg.type).toBe("prefill");
    expect(msg.harness).toBe("kiro");
    expect(msg.request.kiro_options).toEqual({
      agent_name: "x",
      set_default: false,
    });
    expect(msg.request.kiro_options.agent_name).toBe("x");
  });
});
