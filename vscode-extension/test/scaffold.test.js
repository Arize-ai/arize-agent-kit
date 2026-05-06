const path = require("path");
const fs = require("fs");
const { execSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

describe("extension scaffold", () => {
  const expectedCommands = [
    "arize.setup",
    "arize.reconfigure",
    "arize.uninstall",
    "arize.refreshStatus",
    "arize.startCodexBuffer",
    "arize.stopCodexBuffer",
    "arize.statusBarMenu",
  ];

  test("package.json declares all 7 commands and only those", () => {
    const declared = pkg.contributes.commands.map((c) => c.command);
    expect(declared.sort()).toEqual(expectedCommands.sort());
    // No collector commands
    expect(declared).not.toContain("arize.startCollector");
    expect(declared).not.toContain("arize.stopCollector");
  });

  test("package.json declares the arize view container", () => {
    const containers = pkg.contributes.viewsContainers.activitybar;
    expect(containers).toEqual(
      expect.arrayContaining([expect.objectContaining({ id: "arize" })])
    );
  });

  test("package.json declares the arize-sidebar webview view", () => {
    const views = pkg.contributes.views.arize;
    expect(views).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ type: "webview", id: "arize-sidebar" }),
      ])
    );
  });

  test("package.json scripts include build, watch, test, package, vscode:uninstall", () => {
    for (const script of ["build", "watch", "test", "package", "vscode:uninstall"]) {
      expect(pkg.scripts).toHaveProperty(script);
    }
  });

  test("npm run build produces dist/extension.js", () => {
    const distPath = path.join(ROOT, "dist", "extension.js");
    // Build should have already run; verify the output exists
    expect(fs.existsSync(distPath)).toBe(true);
  });

  test("dist/extension.js exports activate and deactivate", () => {
    const ext = require(path.join(ROOT, "dist", "extension.js"));
    expect(typeof ext.activate).toBe("function");
    expect(typeof ext.deactivate).toBe("function");
  });
});
