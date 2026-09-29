import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const dataset = readFileSync(new URL("../../eval/dataset/chat_ragas_v2.jsonl", import.meta.url), "utf-8").trim().split("\n").map(line => JSON.parse(line));
const rounds = Math.min(2, Math.max(1, Number(process.env.LIVE_CHAT_ROUNDS ?? 1)));
test.beforeAll(async ({ request }) => {
  const health = await request.get("/api/health");
  expect((await health.json()).environment).toBe("test");
  const materials = await request.get("/api/materials?limit=100");
  const data = await materials.json();
  expect(data.total).toBe(2);
  expect(data.items.map((item: { title: string }) => item.title).sort()).toEqual(["阶段A验收笔记", "高等数学核心考点讲义"].sort());
});

for (let round = 1; round <= rounds; round++) {
  for (const entry of [...dataset.slice(0, 6), { id: "builtin-full-lesson-detail", mode: "builtin", question: "请把《高等数学核心考点讲义》的每一部分都细讲一遍：说明概念、适用条件、使用步骤、例子和常见误区，不要只给目录或概述。" }]) {
    test(`${round} ${entry.id}: real frontend + current model`, async ({ page }, info) => {
      const pageErrors: string[] = [];
      page.on("pageerror", error => pageErrors.push(error.message));
      await page.goto("/chat");
      await expect(page.locator(".empty-state").filter({ hasText: "正在读取" })).toHaveCount(0);
      const switcher = page.getByTestId("scope-switch");
      await expect(switcher).toBeEnabled();
      const current = await switcher.getAttribute("aria-label");
      if ((entry.mode === "builtin" && current?.startsWith("当前我的资料")) || (entry.mode === "user" && current?.startsWith("当前内置资料"))) await switcher.click();
      await expect(switcher).toHaveAttribute("aria-label", entry.mode === "builtin" ? "当前内置资料，切换到我的资料" : "当前我的资料，切换到内置资料");
      await page.locator('button[title="新建对话"]').click();
      await page.locator("#chat-question").fill(entry.question);
      await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
      const responsePromise = page.waitForResponse(response => response.url().includes("/answers") && response.request().method() === "POST");
      const started = Date.now();
      await page.getByRole("button", { name: "发送", exact: true }).click();
      const response = await responsePromise;
      const sentMode = await page.request.get(`/api/chat/sessions`);
      expect((await sentMode.json())[0].mode).toBe(entry.mode);
      await response.finished();
      const raw = await response.text();
      const frames = raw.split("\n\n").filter(Boolean).map(frame => ({ event: frame.match(/^event: (.+)$/m)?.[1], data: JSON.parse(frame.match(/^data: (.+)$/m)?.[1] ?? "{}") }));
      const done = frames.find(frame => frame.event === "done");
      const error = frames.find(frame => frame.event === "error");
      const resetCount = frames.filter(frame => frame.event === "delta" && frame.data.replace === true).length;
      const assistant = page.locator(".message-row--assistant").last();
      await expect(page.locator("#chat-question")).toBeEnabled();
      await info.attach("result.json", { contentType: "application/json", body: Buffer.from(JSON.stringify({ case: entry.id, round, question: entry.question, answer: done?.data.answer, source: done?.data.answer_source, retrieval_mode: frames.find(frame => frame.event === "meta")?.data.retrieval_mode, elapsed_ms: Date.now() - started, characters: done?.data.answer?.length ?? 0, error: error?.data ?? null, recovery_count: resetCount, browser_errors: pageErrors })) });
      console.log(JSON.stringify({ case: entry.id, round, elapsed_ms: Date.now() - started, characters: done?.data.answer?.length ?? 0, error: error?.data?.code ?? null, recovery_count: resetCount }));
      expect(error, "Actual upstream SSE must not finish in error").toBeUndefined();
      expect(done?.data.answer?.length).toBeGreaterThan(40);
      await expect(page.getByRole("alert")).toHaveCount(0);
      await expect(assistant).not.toContainText("回答生成失败");
      expect(pageErrors).toEqual([]);
      await page.reload();
      await expect(page.locator(".message-row--assistant").last().locator(".markdown-content")).not.toBeEmpty();
    });
  }
}
