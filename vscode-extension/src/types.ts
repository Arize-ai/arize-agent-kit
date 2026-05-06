/**
 * TypeScript interfaces mirroring core/vscode_bridge/models.py.
 */

/** Supported harness identifiers. */
export type HarnessKey = "claude-code" | "codex" | "cursor" | "copilot" | "gemini";

/** All supported harness keys, in canonical order. */
export const HARNESS_KEYS: readonly HarnessKey[] = [
  "claude-code",
  "codex",
  "cursor",
  "copilot",
  "gemini",
] as const;

/** Tracing backend configuration. */
export interface Backend {
  type: "arize" | "phoenix" | "custom";
  api_key?: string;
  endpoint?: string;
  space_id?: string;
}

/** Status of a single configured harness. */
export interface HarnessStatusItem {
  harness: HarnessKey;
  configured: boolean;
  project_name?: string;
  backend?: Backend;
}

/** Full status payload returned by the bridge. */
export interface StatusPayload {
  harnesses: HarnessStatusItem[];
}

/** Request to install/configure a harness. */
export interface InstallRequest {
  harness: HarnessKey;
  project_name: string;
  backend: Backend;
}

/** Result of an install, reconfigure, or uninstall operation. */
export interface OperationResult {
  success: boolean;
  message: string;
  harness: HarnessKey;
}

/** Codex buffer state payload. */
export interface CodexBufferPayload {
  running: boolean;
  pid?: number;
  log_path?: string;
}
