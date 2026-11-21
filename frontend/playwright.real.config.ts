import { defineConfig } from "@playwright/test";
import config from "./playwright.config";
// Opt-in: requires the prepared local PostgreSQL + real API. No API mocks.
export default defineConfig({
  ...config,
  testDir: "./tests/real",
  workers: 1,
  fullyParallel: false,
});
