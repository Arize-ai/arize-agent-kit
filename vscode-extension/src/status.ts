import * as vscode from "vscode";
import { readFileSync, existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { parse as parseYaml } from "yaml";
import * as http from "http";

/** Base harness directory — mirrors core.constants.BASE_DIR. */
const HARNESS_DIR = join(homedir(), ".arize", "harness");

/** Config file path — mirrors core.constants.CONFIG_FILE. */
const CONFIG_PATH = join(HARNESS_DIR, "config.yaml");

/** Default collector health port. */
const DEFAULT_COLLECTOR_PORT = 4318;

/** Default polling interval in milliseconds. */
const DEFAULT_POLL_INTERVAL_MS = 30_000;

/** HTTP health check timeout in milliseconds. */
const HEALTH_CHECK_TIMEOUT_MS = 2_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export enum StatusBarState {
  NotConfigured = "notConfigured",
  PythonRequired = "pythonRequired",
  Running = "running",
  Stopped = "stopped",
}

interface HarnessConfig {
  name?: string;
  project?: string;
}

interface ArizeConfig {
  harnesses?: HarnessConfig[];
  collector?: {
    port?: number;
  };
}

// ---------------------------------------------------------------------------
// StatusBarManager
// ---------------------------------------------------------------------------

export class StatusBarManager {
  private readonly item: vscode.StatusBarItem;
  private pollingHandle: ReturnType<typeof setInterval> | undefined;

  constructor() {
    this.item = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      50,
    );
    this.item.command = "arize.statusBarMenu";
    this.setState(StatusBarState.NotConfigured);
    this.item.show();
  }

  /** Update status bar by reading config.yaml and checking collector health. */
  async update(): Promise<void> {
    const config = readConfig();

    if (!config) {
      this.setState(StatusBarState.NotConfigured);
      return;
    }

    const port = config.collector?.port ?? DEFAULT_COLLECTOR_PORT;
    const harnessCount = config.harnesses?.length ?? 0;
    const healthy = await checkCollectorHealth(port);

    if (healthy) {
      const suffix = harnessCount === 1 ? "1 harness" : `${harnessCount} harnesses`;
      this.item.text = `$(pulse) Arize: ${suffix} · Running`;
      this.item.tooltip = `Arize Agent Kit — ${suffix}, collector running on port ${port}`;
    } else {
      this.setState(StatusBarState.Stopped);
    }
  }

  /** Start periodic polling at the given interval. */
  startPolling(intervalMs: number = DEFAULT_POLL_INTERVAL_MS): void {
    this.update();
    this.pollingHandle = setInterval(() => this.update(), intervalMs);
  }

  /** Stop periodic polling. */
  stopPolling(): void {
    if (this.pollingHandle !== undefined) {
      clearInterval(this.pollingHandle);
      this.pollingHandle = undefined;
    }
  }

  /** Get the underlying StatusBarItem (for pushing to subscriptions). */
  getItem(): vscode.StatusBarItem {
    return this.item;
  }

  /** Set a named state (for states that don't need dynamic text). */
  setState(state: StatusBarState): void {
    const labels: Record<StatusBarState, string> = {
      [StatusBarState.NotConfigured]: "$(warning) Arize: Not configured",
      [StatusBarState.PythonRequired]: "$(warning) Arize: Python required",
      [StatusBarState.Running]: "$(pulse) Arize: Running",
      [StatusBarState.Stopped]: "$(error) Arize: Collector stopped",
    };

    const tooltips: Record<StatusBarState, string> = {
      [StatusBarState.NotConfigured]: "Arize Agent Kit — not configured. Click to set up.",
      [StatusBarState.PythonRequired]: "Arize Agent Kit — Python 3.9+ required",
      [StatusBarState.Running]: "Arize Agent Kit — collector running",
      [StatusBarState.Stopped]: "Arize Agent Kit — collector stopped. Click to manage.",
    };

    this.item.text = labels[state];
    this.item.tooltip = tooltips[state];
  }

  /** Clean up the status bar item and stop polling. */
  dispose(): void {
    this.stopPolling();
    this.item.dispose();
  }
}

// ---------------------------------------------------------------------------
// Quick-pick menu command
// ---------------------------------------------------------------------------

/**
 * Register the `arize.statusBarMenu` command that opens a quick-pick with
 * relevant actions when the status bar item is clicked.
 */
export function registerStatusBarMenuCommand(
  context: vscode.ExtensionContext,
): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("arize.statusBarMenu", async () => {
      const config = readConfig();
      const collectorRunning = config
        ? await checkCollectorHealth(config.collector?.port ?? DEFAULT_COLLECTOR_PORT)
        : false;

      const items: vscode.QuickPickItem[] = [];

      if (collectorRunning) {
        items.push({ label: "$(debug-stop) Stop Collector", description: "Stop the OTLP collector" });
      } else {
        items.push({ label: "$(play) Start Collector", description: "Start the OTLP collector" });
      }

      items.push(
        { label: "$(list-tree) Open Sidebar", description: "Show the Arize Tracing sidebar" },
        { label: "$(add) Set Up New Harness", description: "Run the setup wizard" },
      );

      const pick = await vscode.window.showQuickPick(items, {
        placeHolder: "Arize Agent Kit",
      });

      if (!pick) {
        return;
      }

      if (pick.label.includes("Start Collector")) {
        vscode.commands.executeCommand("arize.startCollector");
      } else if (pick.label.includes("Stop Collector")) {
        vscode.commands.executeCommand("arize.stopCollector");
      } else if (pick.label.includes("Open Sidebar")) {
        vscode.commands.executeCommand("arize-sidebar.focus");
      } else if (pick.label.includes("Set Up New Harness")) {
        vscode.commands.executeCommand("arize.setup");
      }
    }),
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Read and parse ~/.arize/harness/config.yaml.
 * Returns null if the file doesn't exist or can't be parsed.
 */
function readConfig(): ArizeConfig | null {
  if (!existsSync(CONFIG_PATH)) {
    return null;
  }
  try {
    const raw = readFileSync(CONFIG_PATH, "utf-8");
    const parsed = parseYaml(raw);
    if (parsed && typeof parsed === "object") {
      return parsed as ArizeConfig;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Check collector health via HTTP GET to 127.0.0.1:<port>/health.
 * Returns true if the collector responds within the timeout.
 */
function checkCollectorHealth(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(
      {
        hostname: "127.0.0.1",
        port,
        path: "/health",
        timeout: HEALTH_CHECK_TIMEOUT_MS,
      },
      (res) => {
        resolve(res.statusCode !== undefined && res.statusCode >= 200 && res.statusCode < 400);
        res.resume(); // Drain the response
      },
    );

    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}
