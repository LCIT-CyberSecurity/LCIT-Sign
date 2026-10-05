import { defineConfig } from "@playwright/test";

// End-to-end tests drive a real browser against a running stack (the
// Integrations VM), through the real nginx and the mock SSO provider.
//   LCIT_SIGN_E2E_BASE_URL=http://localhost:4180 npx playwright test
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.LCIT_SIGN_E2E_BASE_URL ?? "http://localhost:4180",
    // The test stack presents a self-signed certificate.
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
  },
});
