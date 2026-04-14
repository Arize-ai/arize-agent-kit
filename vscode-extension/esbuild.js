const esbuild = require("esbuild");

const watch = process.argv.includes("--watch");

/** @type {import("esbuild").BuildOptions} */
const sharedOptions = {
  bundle: true,
  format: "cjs",
  platform: "node",
  target: "ES2020",
  sourcemap: true,
};

/** @type {import("esbuild").BuildOptions} */
const buildOptions = {
  ...sharedOptions,
  entryPoints: ["./src/extension.ts"],
  outfile: "dist/extension.js",
  external: ["vscode"],
};

/** @type {import("esbuild").BuildOptions} */
const uninstallOptions = {
  ...sharedOptions,
  entryPoints: ["./src/uninstall.ts"],
  outfile: "dist/uninstall.js",
};

async function main() {
  if (watch) {
    const ctx = await esbuild.context(buildOptions);
    await ctx.watch();
    console.log("Watching for changes...");
  } else {
    await Promise.all([
      esbuild.build(buildOptions),
      esbuild.build(uninstallOptions),
    ]);
    console.log("Build complete.");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
