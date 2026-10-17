// Fails (exit 1) if a built bundle exceeds its gzipped size budget.
import { readFileSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";

const BUDGETS = [
  ["packages/sdk/dist/findaro-sdk.mjs", 10 * 1024],
  ["packages/sdk/dist/findaro-sdk.umd.js", 10 * 1024],
  ["packages/widget/dist/findaro-widget.js", 40 * 1024], // includes the SDK
  ["packages/widget/dist/findaro-widget.mjs", 40 * 1024],
];
let failed = false;
for (const [file, budget] of BUDGETS) {
  if (!existsSync(file)) {
    console.error(`✗ ${file} missing (run npm run build)`);
    failed = true;
    continue;
  }
  const gz = gzipSync(readFileSync(file), { level: 9 }).length;
  const ok = gz <= budget;
  failed ||= !ok;
  console.log(`${ok ? "✓" : "✗"} ${file}  ${(gz / 1024).toFixed(1)} KB gz / ${(budget / 1024).toFixed(0)} KB budget`);
}
process.exit(failed ? 1 : 0);
