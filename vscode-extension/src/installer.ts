import { execFile } from "child_process";

/**
 * Run an `arize-install` subcommand and return its stdout.
 *
 * @param installPath - Absolute path to the `arize-install` binary in the venv.
 * @param args - Arguments to pass (e.g. `["collector", "start"]`).
 * @returns Resolved stdout on success.
 * @throws On non-zero exit code or exec error.
 */
export function runInstallerCommand(
  installPath: string,
  args: string[]
): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(installPath, args, { timeout: 30_000 }, (err, stdout, stderr) => {
      if (err) {
        reject(new Error(stderr?.trim() || err.message));
        return;
      }
      resolve(stdout);
    });
  });
}
