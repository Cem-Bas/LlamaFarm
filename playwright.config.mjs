import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "test_swarm_ui.mjs",
  timeout: 30000,
  use: {
    browserName: "chromium",
    headless: true,
  },
});
