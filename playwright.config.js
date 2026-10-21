const { defineConfig } = require("@playwright/test");
const path = require("node:path");

const isWindows = process.platform === "win32";
const python = process.env.E2E_PYTHON || (isWindows ? ".venv\\Scripts\\python.exe" : "python");
const databasePath = path.join(__dirname, "tmp", "playwright-e2e.db");
const port = process.env.E2E_PORT || "8877";
const baseURL = `http://127.0.0.1:${port}`;
const reuseExistingServer = process.env.E2E_REUSE_SERVER === "true";

module.exports = defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    channel: process.env.E2E_BROWSER_CHANNEL || (isWindows ? "msedge" : undefined),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "zh-CN",
  },
  webServer: {
    command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${port}`,
    url: `${baseURL}/api/health`,
    timeout: 120_000,
    reuseExistingServer,
    env: {
      ...process.env,
      APP_ENV: "e2e",
      DEMO_MODE: "false",
      ADMIN_API_TOKEN: "e2e-admin-token-32-characters-long",
      DATABASE_PATH: databasePath,
      AI_MODE: "deterministic",
      OCR_ENABLED: "true",
    },
  },
});
