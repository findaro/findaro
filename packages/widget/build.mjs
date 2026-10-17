import { build } from "esbuild";

const common = {
  entryPoints: ["src/index.ts"], bundle: true, minify: true, target: "es2022", sourcemap: true,
  alias: { "@findaro/sdk": "../sdk/src/index.ts" },
};
// script-tag build (SDK bundled in): <script src="findaro-widget.js" data-project data-key defer>
await build({ ...common, format: "iife", outfile: "dist/findaro-widget.js" });
// ESM for bundlers
await build({ ...common, format: "esm", outfile: "dist/findaro-widget.mjs" });
