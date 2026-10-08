import { build } from "esbuild";

const common = { entryPoints: ["src/index.ts"], bundle: true, minify: true, target: "es2020", sourcemap: true };
await build({ ...common, format: "esm", outfile: "dist/zerch-sdk.mjs" });
// UMD-style: an IIFE that sets window.ZerchSDK, and module.exports under CommonJS
await build({
  ...common, format: "iife", globalName: "ZerchSDK", outfile: "dist/zerch-sdk.umd.js",
  footer: { js: 'if(typeof module==="object"&&module.exports)module.exports=ZerchSDK;' },
});
