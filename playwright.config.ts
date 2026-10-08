import { defineConfig, devices } from "@playwright/test";

// Needs the stack running (docker compose up -d) and the widget built (npm run build).
// globalSetup creates/refreshes the demo project and writes examples/plain-html/demo.html.
export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 45_000,
  retries: 0,
  use: { baseURL: "http://localhost:8080", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", testMatch: /widget\.spec/, use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", testMatch: /widget\.spec/, use: { ...devices["Pixel 7"] } },
    { name: "react", testMatch: /react\.spec/, use: { ...devices["Desktop Chrome"], baseURL: "http://localhost:4173" } },
  ],
  // the React example (headless SDK) is built and served by vite preview
  webServer: {
    command: "npm run build -w zerch-react-example && npm run preview -w zerch-react-example",
    url: "http://localhost:4173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
