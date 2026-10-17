import { defineConfig, devices } from "@playwright/test";

// Needs the stack running (docker compose up -d) and the widget built (npm run build).
// Run with `npm run e2e`: e2e/prepare.mjs creates/refreshes the demo project and writes the example pages' keys first.
export default defineConfig({
  testDir: "e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },  // shared CI runners are slow; local runs finish far below this
  retries: 0,
  use: { baseURL: "http://localhost:8080", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", testMatch: /widget\.spec/, use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", testMatch: /widget\.spec/, use: { ...devices["Pixel 7"] } },
    { name: "ai-mode", testMatch: /ai\.spec/, use: { ...devices["Desktop Chrome"] } },
    { name: "react", testMatch: /react\.spec/, use: { ...devices["Desktop Chrome"], baseURL: "http://localhost:4173" } },
  ],
  // the React example (headless SDK) is built and served by vite preview
  webServer: {
    command: "npm run build -w findaro-react-example && npm run preview -w findaro-react-example",
    url: "http://localhost:4173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
