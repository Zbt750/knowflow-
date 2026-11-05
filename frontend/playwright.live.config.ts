import { defineConfig } from "@playwright/test";

if (process.env.E2E_LIVE_CHAT !== "1") throw new Error("Live model calls require explicit E2E_LIVE_CHAT=1, authorized test data, and permission to send that data to the configured model endpoint.");
export default defineConfig({
  testDir: "./live", workers: 1, timeout: 420_000,
  reporter: [["list"], ["json", { outputFile: "../eval/reports/live-chat-latest.json" }]],
  outputDir: `../eval/reports/live-chat-artifacts/${new Date().toISOString().replace(/[:.]/g, "-")}`,
  use: { baseURL: process.env.LIVE_CHAT_BASE_URL ?? "http://127.0.0.1:5176", channel: "chrome", viewport: { width: 1366, height: 768 }, screenshot: "only-on-failure" },
});
