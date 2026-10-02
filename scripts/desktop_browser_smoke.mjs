// Read-only, no-LLM smoke of the actual built frontend served by the desktop host.
import { createRequire } from "node:module";
const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const base = new URL(process.argv[2] ?? "http://127.0.0.1:18751");
if (base.hostname !== "127.0.0.1" || base.protocol !== "http:" || Number(base.port) < 18000) {
  throw new Error("Only explicit local desktop smoke ports are allowed");
}
const health = await fetch(new URL("/api/health", base));
const body = await health.json();
if (!health.ok || body.database !== "connected" || body.llm_configured) {
  throw new Error("Smoke requires a connected database and an unconfigured model; caller must supply an isolated DB");
}
// Match the project's E2E channel; no browser installation or user profile reuse.
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
const routes = ["/study", "/knowledge", "/materials", "/chat", "/settings", "/knowledge/math.calculus.limit.lhopital/lesson"];
try {
  const page = await browser.newPage();
  await page.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== base.origin || !["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      errors.push(`blocked unexpected request: ${request.method()} ${url.pathname}`);
      await route.abort();
    } else await route.continue();
  });
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("response", response => {
    if (response.status() >= 400) errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });
  for (const path of routes) {
    await page.goto(new URL(path, base).href, { waitUntil: "networkidle" });
    await page.locator("#app > *").first().waitFor();
    await page.reload({ waitUntil: "networkidle" });
    if (await page.locator("#app").innerText() === "") throw new Error(`empty page: ${path}`);
    if (errors.length) throw new Error(`route failed: ${path}\n` + errors.join("\n"));
    process.stdout.write(`PASS built desktop ${path}\n`);
  }
  if (errors.length) throw new Error(errors.join("\n"));
  process.stdout.write("PASS read-only desktop browser smoke; zero page/console/request errors\n");
} finally {
  await browser.close();
}
