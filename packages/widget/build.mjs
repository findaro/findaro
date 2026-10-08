import { build } from "esbuild";

const common = {
  entryPoints: ["src/index.ts"], bundle: true, minify: true, target: "es2022", sourcemap: true,
  alias: { "@zerch/sdk": "../sdk/src/index.ts" },
};
// script-tag build (SDK bundled in): <script src="zerch-widget.js" data-project data-key defer>
await build({ ...common, format: "iife", outfile: "dist/zerch-widget.js" });
// ESM for bundlers
await build({ ...common, format: "esm", outfile: "dist/zerch-widget.mjs" });
