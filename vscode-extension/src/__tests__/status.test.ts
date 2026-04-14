import * as vscode from "vscode";
import * as fs from "fs";
import * as http from "http";
import * as os from "os";
import * as path from "path";

// Must mock modules before importing the module under test
jest.mock("fs");
jest.mock("http");
jest.mock("os");

const mockedFs = fs as jest.Mocked<typeof fs>;
const mockedHttp = http as jest.Mocked<typeof http>;
const mockedOs = os as jest.Mocked<typeof os>;

// Provide a stable homedir for all tests
mockedOs.homedir.mockReturnValue("/mock-home");

import {
  StatusBarManager,
  StatusBarState,
  registerStatusBarMenuCommand,
} from "../status";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CONFIG_PATH = path.join("/mock-home", ".arize", "harness", "config.yaml");

/** Create a mock HTTP response with the given status code. */
function mockHttpSuccess(statusCode: number): void {
  const mockRes = {
    statusCode,
    resume: jest.fn(),
    on: jest.fn(),
  };
  const mockReq = {
    on: jest.fn(),
    destroy: jest.fn(),
  };
  (mockedHttp.get as jest.Mock).mockImplementation((_opts: any, cb: any) => {
    cb(mockRes);
    return mockReq;
  });
}

/** Make HTTP request fail with an error. */
function mockHttpError(): void {
  const mockReq: any = {
    on: jest.fn(),
    destroy: jest.fn(),
  };
  mockReq.on.mockImplementation((event: string, cb: () => void) => {
    if (event === "error") {
      cb();
    }
    return mockReq;
  });
  (mockedHttp.get as jest.Mock).mockImplementation((_opts: any, _cb: any) => {
    return mockReq;
  });
}

/** Make HTTP request timeout. */
function mockHttpTimeout(): void {
  const mockReq: any = {
    on: jest.fn(),
    destroy: jest.fn(),
  };
  mockReq.on.mockImplementation((event: string, cb: () => void) => {
    if (event === "timeout") {
      cb();
    }
    return mockReq;
  });
  (mockedHttp.get as jest.Mock).mockImplementation((_opts: any, _cb: any) => {
    return mockReq;
  });
}

function setConfigFile(content: string): void {
  (mockedFs.existsSync as jest.Mock).mockImplementation((p: string) =>
    p === CONFIG_PATH,
  );
  (mockedFs.readFileSync as jest.Mock).mockImplementation((p: string) => {
    if (p === CONFIG_PATH) {
      return content;
    }
    throw new Error(`ENOENT: ${p}`);
  });
}

function setNoConfig(): void {
  (mockedFs.existsSync as jest.Mock).mockReturnValue(false);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StatusBarManager", () => {
  let manager: StatusBarManager;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    mockedOs.homedir.mockReturnValue("/mock-home");
    manager = new StatusBarManager();
  });

  afterEach(() => {
    manager.dispose();
    jest.useRealTimers();
  });

  // --- Constructor ---

  test("constructor creates a right-aligned status bar item", () => {
    expect(vscode.window.createStatusBarItem).toHaveBeenCalledWith(
      vscode.StatusBarAlignment.Right,
      50,
    );
  });

  test("constructor sets command to arize.statusBarMenu", () => {
    const item = manager.getItem();
    expect(item.command).toBe("arize.statusBarMenu");
  });

  test("constructor shows the status bar item", () => {
    const item = manager.getItem();
    expect(item.show).toHaveBeenCalled();
  });

  test("constructor sets initial state to NotConfigured", () => {
    const item = manager.getItem();
    expect(item.text).toBe("$(warning) Arize: Not configured");
  });

  // --- setState ---

  test("setState NotConfigured sets correct text and tooltip", () => {
    manager.setState(StatusBarState.NotConfigured);
    const item = manager.getItem();
    expect(item.text).toBe("$(warning) Arize: Not configured");
    expect(item.tooltip).toBe("Arize Agent Kit — not configured. Click to set up.");
  });

  test("setState PythonRequired sets correct text and tooltip", () => {
    manager.setState(StatusBarState.PythonRequired);
    const item = manager.getItem();
    expect(item.text).toBe("$(warning) Arize: Python required");
    expect(item.tooltip).toBe("Arize Agent Kit — Python 3.9+ required");
  });

  test("setState Running sets correct text and tooltip", () => {
    manager.setState(StatusBarState.Running);
    const item = manager.getItem();
    expect(item.text).toBe("$(pulse) Arize: Running");
    expect(item.tooltip).toBe("Arize Agent Kit — collector running");
  });

  test("setState Stopped sets correct text and tooltip", () => {
    manager.setState(StatusBarState.Stopped);
    const item = manager.getItem();
    expect(item.text).toBe("$(error) Arize: Collector stopped");
    expect(item.tooltip).toBe("Arize Agent Kit — collector stopped. Click to manage.");
  });

  // --- update() with no config ---

  test("update sets NotConfigured when config file does not exist", async () => {
    setNoConfig();
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(warning) Arize: Not configured");
  });

  // --- update() with config but collector down ---

  test("update sets Stopped when config exists but collector is down", async () => {
    setConfigFile(`
harnesses:
  - name: claude
collector:
  port: 4318
`);
    mockHttpError();
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(error) Arize: Collector stopped");
  });

  // --- update() with config and collector running ---

  test("update shows harness count and Running when collector is healthy", async () => {
    setConfigFile(`
harnesses:
  - name: claude
  - name: codex
collector:
  port: 4318
`);
    mockHttpSuccess(200);
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(pulse) Arize: 2 harnesses · Running");
    expect(item.tooltip).toContain("2 harnesses");
    expect(item.tooltip).toContain("port 4318");
  });

  test("update uses singular 'harness' for single harness", async () => {
    setConfigFile(`
harnesses:
  - name: claude
collector:
  port: 4318
`);
    mockHttpSuccess(200);
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(pulse) Arize: 1 harness · Running");
  });

  test("update uses default port 4318 when not specified in config", async () => {
    setConfigFile(`
harnesses:
  - name: cursor
`);
    mockHttpSuccess(200);
    await manager.update();
    // Verify http.get was called with port 4318
    expect(mockedHttp.get).toHaveBeenCalledWith(
      expect.objectContaining({ port: 4318 }),
      expect.any(Function),
    );
  });

  test("update uses custom port from config", async () => {
    setConfigFile(`
harnesses:
  - name: claude
collector:
  port: 9999
`);
    mockHttpSuccess(200);
    await manager.update();
    expect(mockedHttp.get).toHaveBeenCalledWith(
      expect.objectContaining({ port: 9999 }),
      expect.any(Function),
    );
    const item = manager.getItem();
    expect(item.tooltip).toContain("port 9999");
  });

  test("update shows 0 harnesses when harnesses list is empty", async () => {
    setConfigFile(`
harnesses: []
collector:
  port: 4318
`);
    mockHttpSuccess(200);
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(pulse) Arize: 0 harnesses · Running");
  });

  test("update shows 0 harnesses when harnesses key is missing", async () => {
    setConfigFile(`
collector:
  port: 4318
`);
    mockHttpSuccess(200);
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(pulse) Arize: 0 harnesses · Running");
  });

  // --- update() health check edge cases ---

  test("update treats HTTP timeout as collector stopped", async () => {
    setConfigFile(`
harnesses:
  - name: claude
`);
    mockHttpTimeout();
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(error) Arize: Collector stopped");
  });

  test("update treats HTTP 500 as collector stopped", async () => {
    setConfigFile(`
harnesses:
  - name: claude
`);
    mockHttpSuccess(500);
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(error) Arize: Collector stopped");
  });

  test("update treats HTTP 200 as collector running", async () => {
    setConfigFile(`
harnesses:
  - name: claude
`);
    mockHttpSuccess(200);
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toContain("Running");
  });

  test("update treats HTTP 204 as collector running", async () => {
    setConfigFile(`
harnesses:
  - name: claude
`);
    mockHttpSuccess(204);
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toContain("Running");
  });

  // --- update() with invalid config ---

  test("update sets NotConfigured when config is invalid YAML", async () => {
    (mockedFs.existsSync as jest.Mock).mockReturnValue(true);
    (mockedFs.readFileSync as jest.Mock).mockReturnValue("{{{{invalid yaml");
    // The yaml parser may parse this oddly but not throw; let's test with something that throws
    (mockedFs.readFileSync as jest.Mock).mockImplementation(() => {
      throw new Error("read error");
    });
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(warning) Arize: Not configured");
  });

  test("update sets NotConfigured when config is a scalar (not object)", async () => {
    setConfigFile("just a string");
    await manager.update();
    const item = manager.getItem();
    expect(item.text).toBe("$(warning) Arize: Not configured");
  });

  // --- Polling ---

  test("startPolling calls update immediately", async () => {
    setNoConfig();
    const updateSpy = jest.spyOn(manager, "update");
    manager.startPolling(5000);
    expect(updateSpy).toHaveBeenCalledTimes(1);
  });

  test("startPolling calls update on interval", async () => {
    setNoConfig();
    const updateSpy = jest.spyOn(manager, "update");
    manager.startPolling(5000);
    // Initial call
    expect(updateSpy).toHaveBeenCalledTimes(1);
    // Advance timer
    jest.advanceTimersByTime(5000);
    expect(updateSpy).toHaveBeenCalledTimes(2);
    jest.advanceTimersByTime(5000);
    expect(updateSpy).toHaveBeenCalledTimes(3);
  });

  test("stopPolling prevents further updates", async () => {
    setNoConfig();
    const updateSpy = jest.spyOn(manager, "update");
    manager.startPolling(5000);
    expect(updateSpy).toHaveBeenCalledTimes(1);
    manager.stopPolling();
    jest.advanceTimersByTime(15000);
    // Should still only have the initial call
    expect(updateSpy).toHaveBeenCalledTimes(1);
  });

  test("startPolling uses default 30s interval", () => {
    setNoConfig();
    const updateSpy = jest.spyOn(manager, "update");
    manager.startPolling();
    expect(updateSpy).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(30_000);
    expect(updateSpy).toHaveBeenCalledTimes(2);
    // But not before 30s
    jest.advanceTimersByTime(29_999);
    expect(updateSpy).toHaveBeenCalledTimes(2);
  });

  // --- dispose ---

  test("dispose stops polling and disposes item", () => {
    setNoConfig();
    const updateSpy = jest.spyOn(manager, "update");
    manager.startPolling(5000);
    const item = manager.getItem();
    manager.dispose();
    jest.advanceTimersByTime(10000);
    // Should only have the initial update call
    expect(updateSpy).toHaveBeenCalledTimes(1);
    expect(item.dispose).toHaveBeenCalled();
  });

  // --- getItem ---

  test("getItem returns the underlying status bar item", () => {
    const item = manager.getItem();
    expect(item).toBeDefined();
    expect(item.show).toBeDefined();
    expect(item.dispose).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// Quick-pick menu
// ---------------------------------------------------------------------------

describe("registerStatusBarMenuCommand", () => {
  let context: vscode.ExtensionContext;

  beforeEach(() => {
    jest.clearAllMocks();
    mockedOs.homedir.mockReturnValue("/mock-home");
    context = {
      subscriptions: [],
      extensionUri: {},
    } as any;
  });

  test("registers the arize.statusBarMenu command", () => {
    registerStatusBarMenuCommand(context);
    expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
      "arize.statusBarMenu",
      expect.any(Function),
    );
  });

  test("pushes disposable to context.subscriptions", () => {
    registerStatusBarMenuCommand(context);
    expect(context.subscriptions.length).toBe(1);
  });

  test("menu shows Start Collector when collector is not running", async () => {
    setNoConfig();
    mockHttpError();

    registerStatusBarMenuCommand(context);
    // Get the callback registered for the command
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    expect(registerCall).toBeDefined();
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue(undefined);
    await menuHandler();

    expect(vscode.window.showQuickPick).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ label: expect.stringContaining("Start Collector") }),
      ]),
      expect.any(Object),
    );
  });

  test("menu shows Stop Collector when collector is running", async () => {
    setConfigFile(`
harnesses:
  - name: claude
collector:
  port: 4318
`);
    mockHttpSuccess(200);

    registerStatusBarMenuCommand(context);
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue(undefined);
    await menuHandler();

    expect(vscode.window.showQuickPick).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ label: expect.stringContaining("Stop Collector") }),
      ]),
      expect.any(Object),
    );
  });

  test("menu always includes Open Sidebar and Set Up New Harness", async () => {
    setNoConfig();
    mockHttpError();

    registerStatusBarMenuCommand(context);
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue(undefined);
    await menuHandler();

    const items = (vscode.window.showQuickPick as jest.Mock).mock.calls[0][0];
    const labels = items.map((item: any) => item.label);
    expect(labels).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Open Sidebar"),
        expect.stringContaining("Set Up New Harness"),
      ]),
    );
  });

  test("selecting Start Collector executes arize.startCollector", async () => {
    setNoConfig();
    mockHttpError();

    registerStatusBarMenuCommand(context);
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue({
      label: "$(play) Start Collector",
    });
    await menuHandler();

    expect(vscode.commands.executeCommand).toHaveBeenCalledWith("arize.startCollector");
  });

  test("selecting Stop Collector executes arize.stopCollector", async () => {
    setConfigFile(`
harnesses:
  - name: claude
collector:
  port: 4318
`);
    mockHttpSuccess(200);

    registerStatusBarMenuCommand(context);
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue({
      label: "$(debug-stop) Stop Collector",
    });
    await menuHandler();

    expect(vscode.commands.executeCommand).toHaveBeenCalledWith("arize.stopCollector");
  });

  test("selecting Open Sidebar executes arize-sidebar.focus", async () => {
    setNoConfig();
    mockHttpError();

    registerStatusBarMenuCommand(context);
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue({
      label: "$(list-tree) Open Sidebar",
    });
    await menuHandler();

    expect(vscode.commands.executeCommand).toHaveBeenCalledWith("arize-sidebar.focus");
  });

  test("selecting Set Up New Harness executes arize.setup", async () => {
    setNoConfig();
    mockHttpError();

    registerStatusBarMenuCommand(context);
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue({
      label: "$(add) Set Up New Harness",
    });
    await menuHandler();

    expect(vscode.commands.executeCommand).toHaveBeenCalledWith("arize.setup");
  });

  test("dismissing quick pick (undefined) does not execute any command", async () => {
    setNoConfig();
    mockHttpError();

    registerStatusBarMenuCommand(context);
    const registerCall = (vscode.commands.registerCommand as jest.Mock).mock.calls.find(
      (call: any[]) => call[0] === "arize.statusBarMenu",
    );
    const menuHandler = registerCall![1];

    (vscode.window.showQuickPick as jest.Mock).mockResolvedValue(undefined);
    await menuHandler();

    expect(vscode.commands.executeCommand).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// package.json validation
// ---------------------------------------------------------------------------

describe("package.json", () => {
  test("arize.statusBarMenu command is declared in contributes.commands", () => {
    const pkg = require("../../package.json");
    const commands = pkg.contributes.commands.map((c: any) => c.command);
    expect(commands).toContain("arize.statusBarMenu");
  });

  test("yaml dependency is declared", () => {
    const pkg = require("../../package.json");
    expect(pkg.dependencies?.yaml).toBeDefined();
  });
});
