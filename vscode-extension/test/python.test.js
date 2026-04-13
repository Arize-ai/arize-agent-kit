/**
 * Tests for vscode-extension/src/python.ts
 * Validates Python detection, OS-specific install instructions,
 * venv existence checks, and arize-install path resolution.
 *
 * Run: node test/python.test.js
 */

const fs = require("fs");
const path = require("path");
const { execSync, execFile } = require("child_process");
const Module = require("module");

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

// ---------------------------------------------------------------------------
// 0. Source file exists and is valid TypeScript
// ---------------------------------------------------------------------------
console.log("\n[Source validation]");

const srcPath = path.join(ROOT, "src", "python.ts");
assert("src/python.ts exists", fs.existsSync(srcPath));

const src = fs.readFileSync(srcPath, "utf8");
assert("exports findPython", src.includes("export async function findPython"));
assert("exports getPythonInstallInstructions", src.includes("export function getPythonInstallInstructions"));
assert("exports checkVenvExists", src.includes("export function checkVenvExists"));
assert("exports getArizeInstallPath", src.includes("export function getArizeInstallPath"));

// Verify TypeScript compiles without errors
console.log("\n[TypeScript compilation]");
let tscOk = false;
try {
  execSync("npx tsc --noEmit", { cwd: ROOT, stdio: "pipe" });
  tscOk = true;
} catch (e) {
  const stderr = e.stderr ? e.stderr.toString() : "";
  console.log("    tsc errors:", stderr.slice(0, 500));
}
assert("tsc --noEmit passes (python.ts compiles)", tscOk);

// ---------------------------------------------------------------------------
// 1. Build the module so we can load and test it
// ---------------------------------------------------------------------------
console.log("\n[Build for testing]");

// Build just python.ts into a testable CommonJS module
const buildOutDir = path.join(ROOT, "test", "_build");
try {
  execSync(
    `npx esbuild src/python.ts --bundle --outfile=test/_build/python.js --format=cjs --platform=node`,
    { cwd: ROOT, stdio: "pipe" }
  );
  assert("esbuild compiles python.ts", true);
} catch (e) {
  assert("esbuild compiles python.ts", false);
  console.log("Build failed:", e.stderr ? e.stderr.toString().slice(0, 500) : e.message);
  printSummary();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// 2. Static source analysis — verify implementation details
// ---------------------------------------------------------------------------
console.log("\n[Static source analysis]");

// Version constants
assert("MIN_MAJOR is 3", src.includes("const MIN_MAJOR = 3"));
assert("MIN_MINOR is 9", src.includes("const MIN_MINOR = 9"));

// Candidate list
assert("tries python3 first", src.includes('"python3"'));
assert("tries python second", src.includes('"python"'));

// macOS paths
assert("macOS: /opt/homebrew/bin/python3", src.includes("/opt/homebrew/bin/python3"));
assert("macOS: /usr/local/bin/python3", src.includes("/usr/local/bin/python3"));
assert("macOS: Framework path", src.includes("/Library/Frameworks/Python.framework"));

// Windows paths
assert("Windows: py launcher", src.includes('"py"'));
assert("Windows: LOCALAPPDATA env", src.includes("process.env.LOCALAPPDATA"));
assert("Windows: WindowsApps path", src.includes("WindowsApps"));

// Linux paths
assert("Linux: /usr/bin/python3", src.includes("/usr/bin/python3"));

// Version parsing
assert("parses Python version from stdout or stderr", src.includes("stdout || stderr"));
assert("regex matches Python version", src.includes("Python\\s+(\\d+)\\.(\\d+)"));

// Venv paths
assert("venv: win32 Scripts/python.exe", src.includes("Scripts") && src.includes("python.exe"));
assert("venv: unix bin/python3", src.includes("bin") && src.includes("python3"));

// arize-install paths
assert("arize-install: win32 arize-install.exe", src.includes("arize-install.exe"));
assert("arize-install: unix arize-install", src.includes('"arize-install"'));

// ---------------------------------------------------------------------------
// 3. Load the built module and test exported functions
// ---------------------------------------------------------------------------
console.log("\n[Module loading]");

let pyMod;
try {
  // Clear cache so re-runs work
  delete require.cache[path.join(buildOutDir, "python.js")];
  pyMod = require(path.join(buildOutDir, "python.js"));
  assert("built module loads", true);
} catch (e) {
  assert("built module loads", false);
  console.log("Load error:", e.message);
  printSummary();
  process.exit(1);
}

assert("findPython is exported function", typeof pyMod.findPython === "function");
assert("getPythonInstallInstructions is exported function", typeof pyMod.getPythonInstallInstructions === "function");
assert("checkVenvExists is exported function", typeof pyMod.checkVenvExists === "function");
assert("getArizeInstallPath is exported function", typeof pyMod.getArizeInstallPath === "function");

// ---------------------------------------------------------------------------
// 4. getPythonInstallInstructions — test current platform
// ---------------------------------------------------------------------------
console.log("\n[getPythonInstallInstructions]");

const instructions = pyMod.getPythonInstallInstructions();
assert("returns non-empty string", typeof instructions === "string" && instructions.length > 0);
assert("returns valid HTML", instructions.includes("<") && instructions.includes(">"));
assert("mentions python.org", instructions.includes("python.org"));

if (process.platform === "darwin") {
  assert("macOS: mentions Homebrew", instructions.includes("Homebrew") || instructions.includes("brew"));
  assert("macOS: mentions brew install", instructions.includes("brew install python"));
  assert("macOS: title says macOS", instructions.includes("macOS"));
} else if (process.platform === "win32") {
  assert("Windows: mentions Microsoft Store", instructions.includes("Microsoft Store"));
  assert("Windows: mentions Add Python to PATH", instructions.includes("Add Python to PATH"));
  assert("Windows: title says Windows", instructions.includes("Windows"));
} else {
  assert("Linux: mentions apt", instructions.includes("apt"));
  assert("Linux: mentions dnf", instructions.includes("dnf"));
  assert("Linux: mentions pacman", instructions.includes("pacman"));
  assert("Linux: title says Linux", instructions.includes("Linux"));
}

// ---------------------------------------------------------------------------
// 5. checkVenvExists — should return false (no venv in test env)
// ---------------------------------------------------------------------------
console.log("\n[checkVenvExists]");

const venvExists = pyMod.checkVenvExists();
assert("returns boolean", typeof venvExists === "boolean");
// In a test environment, the venv likely doesn't exist
// but we just verify it returns boolean and doesn't throw

// ---------------------------------------------------------------------------
// 6. getArizeInstallPath — should return null (no venv in test env)
// ---------------------------------------------------------------------------
console.log("\n[getArizeInstallPath]");

const installPath = pyMod.getArizeInstallPath();
assert("returns string or null", installPath === null || typeof installPath === "string");
// Without a real venv, this should be null
assert("returns null when venv doesn't exist", installPath === null);

// ---------------------------------------------------------------------------
// 7. findPython — integration test (runs on real system)
// ---------------------------------------------------------------------------
console.log("\n[findPython - integration]");

async function testFindPython() {
  const result = await pyMod.findPython();

  // On most dev machines, Python 3.9+ should be available
  // But we can't guarantee it, so just check the contract
  assert("findPython returns string or null", result === null || typeof result === "string");

  if (result !== null) {
    assert("returned path is non-empty", result.length > 0);

    // Verify the returned candidate actually works
    let versionOk = false;
    try {
      const { execFileSync } = require("child_process");
      const output = execFileSync(result, ["--version"], { timeout: 10000 }).toString().trim();
      const match = output.match(/Python\s+(\d+)\.(\d+)/);
      if (match) {
        const major = parseInt(match[1], 10);
        const minor = parseInt(match[2], 10);
        versionOk = major === 3 && minor >= 9;
      }
    } catch (e) {
      // candidate not runnable
    }
    assert("returned Python is >= 3.9", versionOk);
  } else {
    console.log("    (Python 3.9+ not found on this system — skipping validation)");
  }
}

// ---------------------------------------------------------------------------
// 8. Version parsing logic — test via probeCandidate behavior
// ---------------------------------------------------------------------------
console.log("\n[Version parsing edge cases - source analysis]");

// The probeCandidate function checks: major === MIN_MAJOR && minor >= MIN_MINOR
// This means it ONLY accepts Python 3.x where x >= 9, NOT Python 4+
assert("version check uses exact major match (===)", src.includes("major === MIN_MAJOR"));
assert("version check uses >= for minor", src.includes("minor >= MIN_MINOR"));

// This is actually a design choice — Python 4.0 would be rejected.
// Document this behavior:
assert("rejects Python 2.x (major !== 3)", src.includes("major === MIN_MAJOR"));
assert("rejects Python 3.8 (minor < 9)", src.includes("minor >= MIN_MINOR"));

// ---------------------------------------------------------------------------
// 9. Verify the module handles execFile errors gracefully
// ---------------------------------------------------------------------------
console.log("\n[Error handling - source analysis]");

assert("probeCandidate resolves null on error", src.includes("resolve(null)"));
assert("handles missing stdout/stderr", src.includes("stdout || stderr"));
assert("has timeout on execFile", src.includes("timeout: 10_000") || src.includes("timeout: 10000"));
assert("handles non-matching version output", src.includes('resolve(null)'));

// ---------------------------------------------------------------------------
// 10. Path construction correctness
// ---------------------------------------------------------------------------
console.log("\n[Path construction]");

const os = require("os");
const expectedHarnessDir = path.join(os.homedir(), ".arize", "harness");
const expectedVenvDir = path.join(expectedHarnessDir, "venv");

// The module uses homedir() at load time — verify the paths are correct
assert("HARNESS_DIR uses homedir/.arize/harness", src.includes('join(homedir(), ".arize", "harness")'));
assert("VENV_DIR uses HARNESS_DIR/venv", src.includes('join(HARNESS_DIR, "venv")'));

// Platform-conditional binary paths
if (process.platform === "win32") {
  assert("checkVenvExists uses Scripts/python.exe on win32",
    src.includes('join(VENV_DIR, "Scripts", "python.exe")'));
  assert("getArizeInstallPath uses Scripts on win32",
    src.includes('"Scripts"'));
} else {
  assert("checkVenvExists uses bin/python3 on unix",
    src.includes('join(VENV_DIR, "bin", "python3")'));
  assert("getArizeInstallPath uses bin on unix",
    src.includes('"bin"'));
}

// ---------------------------------------------------------------------------
// 11. Candidate ordering verification
// ---------------------------------------------------------------------------
console.log("\n[Candidate ordering]");

// Extract candidate order from source
const candidateSection = src.substring(
  src.indexOf("const candidates: string[]"),
  src.indexOf("for (const candidate of candidates)")
);

const python3Idx = candidateSection.indexOf('"python3"');
const pythonIdx = candidateSection.indexOf('"python"');
assert("python3 comes before python in candidate list", python3Idx < pythonIdx && python3Idx !== -1);

if (process.platform === "darwin") {
  // Verify homebrew path is in the darwin section
  const darwinSection = src.substring(
    src.indexOf('process.platform === "darwin"'),
    src.indexOf('process.platform === "win32"')
  );
  assert("darwin adds /opt/homebrew/bin/python3", darwinSection.includes("/opt/homebrew/bin/python3"));
  assert("darwin adds /usr/local/bin/python3", darwinSection.includes("/usr/local/bin/python3"));
}

// ---------------------------------------------------------------------------
// 12. Verify instructions HTML structure
// ---------------------------------------------------------------------------
console.log("\n[Instructions HTML quality]");

assert("instructions contain <p> tag", instructions.includes("<p>"));
assert("instructions contain <ul> list", instructions.includes("<ul>"));
assert("instructions contain <li> items", instructions.includes("<li>"));
assert("instructions contain <code> for commands", instructions.includes("<code>"));
assert("instructions have closing tags", instructions.includes("</ul>") && instructions.includes("</p>"));

// Verify link formatting
if (instructions.includes("<a ")) {
  assert("links have href attribute", instructions.includes('href="'));
  assert("links point to python.org", instructions.includes("python.org/downloads"));
}

// ---------------------------------------------------------------------------
// Run async tests and print summary
// ---------------------------------------------------------------------------
function printSummary() {
  console.log(`\n========================================`);
  console.log(`Total: ${passed + failed} | Passed: ${passed} | Failed: ${failed}`);
  console.log(`========================================\n`);
}

testFindPython()
  .then(() => {
    printSummary();
    process.exit(failed > 0 ? 1 : 0);
  })
  .catch((e) => {
    console.log("  FAIL: findPython threw unexpected error:", e.message);
    failed++;
    printSummary();
    process.exit(1);
  });
