import { execFileSync } from "node:child_process";

import { readFileSync, writeFileSync } from "node:fs";

export default async function globalSetup() {
  execFileSync("uv", ["run", "python", "scripts/demo_setup.py"], { stdio: "inherit" });
  // the React example reads the same demo project's keys
  const p = JSON.parse(readFileSync(".demo-project.json", "utf8"));
  writeFileSync("examples/react/.env.local",
    `VITE_FINDARO_PROJECT=${p.project_id}\nVITE_FINDARO_KEY=${p.search_key}\nVITE_FINDARO_URL=http://localhost:8000\n`);
  // The first search builds the project's value dictionary and warms the model; on a slow CI runner that alone can
  // exceed an assertion timeout, so do it here, once, before any test measures anything.
  for (const llm of [true, false]) {
    const r = await fetch("http://localhost:8000/v1/search", {
      method: "POST",
      headers: { authorization: `Bearer ${p.search_key}`, "content-type": "application/json" },
      body: JSON.stringify({ query: "kaale joote 1000 ke andar", llm }),
    });
    if (!r.ok) throw new Error(`warm-up search failed: ${r.status} ${await r.text()}`);
  }
}
