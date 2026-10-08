import { execFileSync } from "node:child_process";

import { readFileSync, writeFileSync } from "node:fs";

export default function globalSetup() {
  execFileSync("uv", ["run", "python", "scripts/demo_setup.py"], { stdio: "inherit" });
  // the React example reads the same demo project's keys
  const p = JSON.parse(readFileSync(".demo-project.json", "utf8"));
  writeFileSync("examples/react/.env.local",
    `VITE_ZERCH_PROJECT=${p.project_id}\nVITE_ZERCH_KEY=${p.search_key}\nVITE_ZERCH_URL=http://localhost:8000\n`);
}
