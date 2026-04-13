/**
 * Tests for the VS Code extension scaffold.
 * Validates package.json, tsconfig.json, build output, and file structure.
 *
 * Run: node test/scaffold.test.js
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
let passed = 0;
let failed = 0;

function assert(name, condition) {
  if (condition) {
    passed++;
    console.log(`  PASS: ${name}`);
  } else {
    failed++;
    console.log(`  FAIL: ${name}`);
  }
}

function fileExists(rel) {
  return fs.existsSync(path.join(ROOT, rel));
}

// --- File structure ---
console.log("\n[File structure]");
assert("package.json exists", fileExists("package.json"));
assert("tsconfig.json exists", fileExists("tsconfig.json"));
assert("esbuild.js exists", fileExists("esbuild.js"));
assert(".vscodeignore exists", fileExists(".vscodeignore"));
assert(".gitignore exists", fileExists(".gitignore"));
assert("media/icon.svg exists", fileExists("media/icon.svg"));
assert("src/extension.ts exists", fileExists("src/extension.ts"));

// --- package.json validation ---
console.log("\n[package.json]");
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

assert("name is arize-agent-kit", pkg.name === "arize-agent-kit");
assert("displayName is Arize Agent Kit", pkg.displayName === "Arize Agent Kit");
assert("version is 0.1.0", pkg.version === "0.1.0");
assert("publisher is arize", pkg.publisher === "arize");
assert("engine vscode ^1.85.0", pkg.engines && pkg.engines.vscode === "^1.85.0");
assert("main is ./dist/extension.js", pkg.main === "./dist/extension.js");
assert("categories includes Other", Array.isArray(pkg.categories) && pkg.categories.includes("Other"));

// Commands
const cmds = (pkg.contributes && pkg.contributes.commands || []).map(c => c.command);
assert("command arize.setup", cmds.includes("arize.setup"));
assert("command arize.reconfigure", cmds.includes("arize.reconfigure"));
assert("command arize.startCollector", cmds.includes("arize.startCollector"));
assert("command arize.stopCollector", cmds.includes("arize.stopCollector"));
assert("exactly 4 commands", cmds.length === 4);

// Activity bar
const activitybar = pkg.contributes && pkg.contributes.viewsContainers && pkg.contributes.viewsContainers.activitybar;
assert("activity bar container exists", Array.isArray(activitybar) && activitybar.length > 0);
assert("activity bar id is arize", activitybar && activitybar[0].id === "arize");
assert("activity bar icon is media/icon.svg", activitybar && activitybar[0].icon === "media/icon.svg");

// Sidebar view
const views = pkg.contributes && pkg.contributes.views && pkg.contributes.views.arize;
assert("sidebar view exists", Array.isArray(views) && views.length > 0);
assert("sidebar view id is arize-sidebar", views && views[0].id === "arize-sidebar");
assert("sidebar view type is webview", views && views[0].type === "webview");

// Activation events
assert("activation onView:arize-sidebar", Array.isArray(pkg.activationEvents) && pkg.activationEvents.includes("onView:arize-sidebar"));
assert("activation onCommand:arize.setup", pkg.activationEvents.includes("onCommand:arize.setup"));

// Dependencies
assert("yaml dependency", pkg.dependencies && !!pkg.dependencies.yaml);
assert("esbuild devDependency", pkg.devDependencies && !!pkg.devDependencies.esbuild);
assert("typescript devDependency", pkg.devDependencies && !!pkg.devDependencies.typescript);
assert("@types/vscode devDependency", pkg.devDependencies && !!pkg.devDependencies["@types/vscode"]);
assert("@types/node devDependency", pkg.devDependencies && !!pkg.devDependencies["@types/node"]);

// Scripts
assert("build script exists", pkg.scripts && !!pkg.scripts.build);
assert("watch script exists", pkg.scripts && !!pkg.scripts.watch);
assert("package script exists", pkg.scripts && !!pkg.scripts.package);
assert("build script uses esbuild", pkg.scripts.build.includes("esbuild"));
assert("build script externals vscode", pkg.scripts.build.includes("--external:vscode"));
assert("build script format cjs", pkg.scripts.build.includes("--format=cjs"));

// --- tsconfig.json validation ---
console.log("\n[tsconfig.json]");
const ts = JSON.parse(fs.readFileSync(path.join(ROOT, "tsconfig.json"), "utf8"));
const co = ts.compilerOptions;

assert("module commonjs", co.module === "commonjs");
assert("target ES2020", co.target === "ES2020");
assert("lib includes ES2020", Array.isArray(co.lib) && co.lib.includes("ES2020"));
assert("outDir dist", co.outDir === "dist");
assert("rootDir src", co.rootDir === "src");
assert("strict true", co.strict === true);
assert("esModuleInterop true", co.esModuleInterop === true);
assert("sourceMap true", co.sourceMap === true);
assert("resolveJsonModule true", co.resolveJsonModule === true);
assert("skipLibCheck true", co.skipLibCheck === true);
assert("include has src/**/*", Array.isArray(ts.include) && ts.include.includes("src/**/*"));
assert("exclude has node_modules", Array.isArray(ts.exclude) && ts.exclude.includes("node_modules"));
assert("exclude has dist", ts.exclude.includes("dist"));

// --- Build output validation ---
console.log("\n[Build output]");
assert("dist/extension.js exists", fileExists("dist/extension.js"));

const bundle = fs.readFileSync(path.join(ROOT, "dist/extension.js"), "utf8");
assert("bundle is CommonJS (module.exports)", bundle.includes("module.exports"));
assert("bundle requires vscode externally", bundle.includes('require("vscode")'));
assert("bundle exports activate", bundle.includes("activate"));
assert("bundle exports deactivate", bundle.includes("deactivate"));
assert("bundle registers arize.setup command", bundle.includes("arize.setup"));
assert("bundle registers arize.reconfigure command", bundle.includes("arize.reconfigure"));
assert("bundle registers arize.startCollector command", bundle.includes("arize.startCollector"));
assert("bundle registers arize.stopCollector command", bundle.includes("arize.stopCollector"));

// Verify bundle loads with mocked vscode
const mockVscodePath = path.join(ROOT, "_test_mock_vscode.js");
fs.writeFileSync(mockVscodePath, `
module.exports = {
  window: { showInformationMessage: () => {} },
  commands: { registerCommand: (cmd, cb) => ({ dispose: () => {} }) }
};
`);
const Module = require("module");
const origResolve = Module._resolveFilename;
Module._resolveFilename = function(request, ...args) {
  if (request === "vscode") return mockVscodePath;
  return origResolve.call(this, request, ...args);
};

let ext;
try {
  // Clear require cache to reload with mock
  delete require.cache[path.join(ROOT, "dist/extension.js")];
  ext = require(path.join(ROOT, "dist/extension.js"));
} catch (e) {
  ext = null;
}
Module._resolveFilename = origResolve;
fs.unlinkSync(mockVscodePath);

assert("bundle loads successfully with mocked vscode", ext !== null);
assert("activate is a function", ext && typeof ext.activate === "function");
assert("deactivate is a function", ext && typeof ext.deactivate === "function");

// Test activate runs without error
if (ext && typeof ext.activate === "function") {
  let activateOk = false;
  try {
    const subs = [];
    ext.activate({ subscriptions: subs });
    activateOk = subs.length === 4; // 4 commands registered
  } catch (e) {
    activateOk = false;
  }
  assert("activate registers 4 commands", activateOk);
}

// --- .vscodeignore validation ---
console.log("\n[.vscodeignore]");
const vscodeignore = fs.readFileSync(path.join(ROOT, ".vscodeignore"), "utf8");
assert("ignores src/", vscodeignore.includes("src/"));
assert("ignores test/", vscodeignore.includes("test/"));
assert("ignores tsconfig.json", vscodeignore.includes("tsconfig.json"));
assert("ignores esbuild.js", vscodeignore.includes("esbuild.js"));

// --- .gitignore validation ---
console.log("\n[.gitignore]");
const gitignore = fs.readFileSync(path.join(ROOT, ".gitignore"), "utf8");
assert("ignores node_modules/", gitignore.includes("node_modules/"));
assert("ignores dist/", gitignore.includes("dist/"));
assert("ignores *.vsix", gitignore.includes("*.vsix"));

// --- icon.svg validation ---
console.log("\n[media/icon.svg]");
const icon = fs.readFileSync(path.join(ROOT, "media/icon.svg"), "utf8");
assert("icon is valid SVG (starts with <svg)", icon.trim().startsWith("<svg"));
assert("icon has xmlns", icon.includes('xmlns="http://www.w3.org/2000/svg"'));

// --- TypeScript type checking ---
console.log("\n[TypeScript type check]");
let tscOk = false;
try {
  execSync("npx tsc --noEmit", { cwd: ROOT, stdio: "pipe" });
  tscOk = true;
} catch (e) {
  tscOk = false;
}
assert("tsc --noEmit passes", tscOk);

// --- esbuild.js validation ---
console.log("\n[esbuild.js]");
const esbuildScript = fs.readFileSync(path.join(ROOT, "esbuild.js"), "utf8");
assert("esbuild.js requires esbuild", esbuildScript.includes('require("esbuild")'));
assert("esbuild.js has watch mode", esbuildScript.includes("--watch") || esbuildScript.includes("watch"));
assert("esbuild.js externals vscode", esbuildScript.includes('"vscode"'));
assert("esbuild.js targets ES2020", esbuildScript.includes("ES2020"));
assert("esbuild.js format cjs", esbuildScript.includes('"cjs"'));

// --- Summary ---
console.log(`\n========================================`);
console.log(`Total: ${passed + failed} | Passed: ${passed} | Failed: ${failed}`);
console.log(`========================================\n`);

process.exit(failed > 0 ? 1 : 0);
