import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Explicit consent: acceptance upload plus synthetic fixtures; no external judge.
const dataset = JSON.parse(readFileSync(new URL("../../eval/dataset/multifile_benchmark.json", import.meta.url), "utf8"));
const results: Array<Record<string, unknown>> = [];
const groups = new Map<string, string>();
const owned = new Set<string>();
const selectedIds = new Set((process.env.LIVE_MULTIFILE_CASE_IDS ?? "").split(",").filter(Boolean));
const cases = selectedIds.size ? dataset.cases.filter((entry: { id: string }) => selectedIds.has(entry.id)) : dataset.cases.filter((entry: { probe?: boolean }) => !entry.probe);
const reportTag = (process.env.LIVE_MULTIFILE_REPORT_TAG ?? "probes").replace(/[^a-z0-9-]/gi, "");
const outputName = selectedIds.size || process.env.LIVE_MULTIFILE_REPORT_TAG ? `multifile-depth-${reportTag}.json` : "multifile-depth-actual.json";
test.setTimeout(1_800_000);

test("多文件真实回答：原文对照、跨文件、冲突版本与多轮", async ({ page, request }) => {
  const health = await (await request.get("/api/health")).json();
  expect(health.environment).toBe("test");
  const materials = await (await request.get("/api/materials?limit=100")).json();
  expect(materials.total).toBe(8);
  expect(materials.items.every((m: { status: string }) => m.status === "ready")).toBe(true);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const started = Date.now();
  try {
    for (const entry of cases) {
      const mode = entry.mode ?? "user";
      let sessionId = entry.group ? groups.get(entry.group) : undefined;
      if (!sessionId) {
        await page.goto("/chat");
        const switcher = page.getByTestId("scope-switch");
        await expect(switcher).toBeEnabled();
        const current = await switcher.getAttribute("aria-label");
        if ((mode === "user" && current?.startsWith("当前内置资料")) || (mode === "builtin" && current?.startsWith("当前我的资料"))) await switcher.click();
        await page.locator('button[title="新建对话"]').click();
      } else {
        await page.goto(`/chat?session_id=${sessionId}`);
      }
      await expect(page.getByTestId("scope-switch")).toBeEnabled();
      await expect(page.getByTestId("scope-switch")).toHaveAttribute("aria-label", mode === "user" ? "当前我的资料，切换到内置资料" : "当前内置资料，切换到我的资料");
      await page.locator("#chat-question").fill(entry.question);
      await expect(page.locator(".send-button")).toBeEnabled();
      const callStart = Date.now();
      const createdPromise = !sessionId ? page.waitForResponse(r => new URL(r.url()).pathname === "/api/chat/sessions" && r.request().method() === "POST", { timeout: 10000 }) : null;
      const pending = page.waitForResponse(r => r.url().includes("/answers:stream") && r.request().method() === "POST", { timeout: 200_000 });
      await page.locator(".send-button").click();
      if (createdPromise) {
        sessionId = (await (await createdPromise).json()).session_id;
        owned.add(sessionId!);
        if (entry.group) groups.set(entry.group, sessionId!);
      }
      const response = await pending;
      await response.finished();
      const raw = await response.text();
      const frames = raw.split("\n\n").filter(Boolean).map(f => ({ event: f.match(/^event: (.+)$/m)?.[1], data: JSON.parse(f.match(/^data: (.+)$/m)?.[1] ?? "{}") }));
      const done = frames.find(f => f.event === "done");
      const answer = String(done?.data.answer ?? "");
      const streamError = frames.find(f => f.event === "error")?.data ?? null;
      const missing = entry.checks.filter((pattern: string) => !new RegExp(pattern, "i").test(answer));
      const forbidden = (entry.forbidden ?? []).filter((pattern: string) => new RegExp(pattern, "i").test(answer));
      const cards = frames.find(f => f.event === "citations")?.data?.citations ?? [];
      const citedFiles = [...new Set(cards.map((card: { material_title: string }) => card.material_title))];
      const missingFiles = (entry.expectedFiles ?? []).filter((title: string) => !citedFiles.includes(title));
      const assistant = page.locator(".message-row--assistant").last();
      let visible = "";
      try { visible = await assistant.innerText({ timeout: 3000 }); } catch { /* retain transport result */ }
      const messages = await request.get(`/api/chat/sessions/${sessionId}/messages`);
      const saved = messages.ok() ? await messages.json() : null;
      const result = { id: entry.id, mode, group: entry.group ?? null, question: entry.question, expected_checks: entry.checks, answer, visible_answer: visible, elapsed_ms: Date.now() - callStart, characters: answer.length, missing_checks: missing, forbidden_matches: forbidden, cited_files: citedFiles, missing_files: missingFiles, stream_error: streamError, http_status: response.status(), meta: frames.find(f => f.event === "meta")?.data, citations: frames.find(f => f.event === "citations")?.data, done, saved, recovery_count: frames.filter(f => f.event === "delta" && f.data.replace).length };
      results.push(result);
      writeFileSync(new URL(`../../eval/reports/${outputName}`, import.meta.url), JSON.stringify({ started_at: new Date(started).toISOString(), model: "configured-current-model", judge: "no external judge; source facts plus manual audit required", cases: results, browser_errors: errors }, null, 2));
      console.log(JSON.stringify({ id: entry.id, chars: answer.length, seconds: Math.round(result.elapsed_ms / 100) / 10, missing, missingFiles, forbidden, error: streamError?.code ?? null }));
      await expect(page.locator("#chat-question")).toBeEnabled({ timeout: 5000 });
    }
  } finally {
    for (const id of owned) await request.delete(`/api/chat/sessions/${id}`);
  }
  expect(results).toHaveLength(cases.length);
  expect(errors).toEqual([]);
  // Semantic issues are reported, not allowed to stop later diagnostic cases.
  expect(results.filter(r => r.stream_error || Number(r.http_status) !== 200), "Real upstream/transport failures").toEqual([]);
});
