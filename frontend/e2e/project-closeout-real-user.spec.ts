import { fileURLToPath } from "node:url";
import type { Page, TestInfo } from "@playwright/test";
import { apiFetch, E2E_PREFIX, expect, test } from "./fixtures";

// Genuine Vue + API + isolated PostgreSQL. The server's OfflineProvider means
// these tests verify application transport and evidence, not model answer quality.
async function screenshot(page: Page, info: TestInfo, name: string) {
  const path = info.outputPath(name + ".png");
  await page.screenshot({ path, fullPage: true });
  await info.attach(name, { path, contentType: "image/png" });
}

test("隔离真实用户：确认建卷、作答锁定、刷新恢复和统一知识节点题库", async ({ page }, info) => {
  await page.goto("/study");
  await expect(page.getByTestId("study-setup")).toBeVisible();
  const before = await (await apiFetch("/api/plans/today")).json();
  expect(before.status).toBe("setup");
  await screenshot(page, info, "01-study-before-confirmation");
  await page.getByTestId("generate-plan").click();
  await expect(page.getByTestId("focus-question")).toBeVisible();
  await screenshot(page, info, "02-study-focus");
  const plan = await (await apiFetch("/api/plans/today")).json();
  expect(plan.items.length).toBeGreaterThan(0);
  expect(plan.items.every((item: any) => Boolean(item.question_version_id))).toBe(true);
  await page.getByTestId("full-paper").click();
  await expect(page.getByTestId("paper-list")).toBeVisible();
  await screenshot(page, info, "03-study-full-paper");
  await page.getByTestId("mode-focus").click();
  await page.getByTestId("study-frog-launcher").click();
  await expect(page.getByTestId("task-goal")).toBeVisible();
  await screenshot(page, info, "04-study-agent-before-any-request");
  await page.getByRole("button", { name: "收起奶蛙对话" }).click();

  const tree = await (await apiFetch("/api/knowledge/tree")).json();
  const walk = (nodes: any[]): any[] => nodes.flatMap(node => [node, ...walk(node.children ?? [])]);
  const node = walk(tree.nodes).find(node => node.code === "math.calculus.limit.lhopital");
  expect(node).toBeTruthy();
  await page.goto("/knowledge");
  await expect(page.getByTestId("knowledge-tree")).toBeVisible();
  await screenshot(page, info, "05-knowledge-tree");
  await page.goto(`/knowledge?node=${node.code}&tab=questions`);
  await expect(page.getByTestId("question-bank")).toBeVisible();
  await expect(page.getByTestId("detail-title")).toHaveText("洛必达法则");
  await screenshot(page, info, "06-node-unified-question-bank");
  await page.getByTestId("tab-overview").click();
  await page.getByTestId("knowledge-lesson-link").click();
  await expect(page.getByTestId("lesson-article")).toContainText("洛必达法则");
  await expect(page.getByTestId("lesson-article").locator(".katex").first()).toBeVisible();
  await screenshot(page, info, "07-knowledge-lesson");

  await page.goto("/study");
  const restored = await (await apiFetch("/api/plans/today")).json();
  expect(restored.plan_id).toBe(plan.plan_id);
  expect(restored.items.map((item: any) => item.id)).toEqual(plan.items.map((item: any) => item.id));
  await info.attach("plan-version-bindings", { body: JSON.stringify({ plan_id: plan.plan_id,
    items: plan.items.map((item: any) => ({ id: item.id, question_id: item.question_id,
      question_version_id: item.question_version_id, kp_id: item.kp_id })) }, null, 2), contentType: "application/json" });
});

test("隔离真实用户：资料上传、解析索引、阅读、指定资料检索和删除", async ({ page }, info) => {
  const project = fileURLToPath(new URL("../..", import.meta.url));
  const title = E2E_PREFIX + "收尾资料-" + Date.now();
  await page.goto("/materials");
  await expect(page.getByTestId("materials-page")).toBeVisible();
  await screenshot(page, info, "08-materials-library");
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("upload-toggle").click();
  await (await chooser).setFiles(`${project}/seed/materials/gaoshu-lecture-01.md`);
  await page.getByTestId("upload-title").fill(title);
  const upload = page.waitForResponse(response => new URL(response.url()).pathname === "/api/materials"
    && response.request().method() === "POST" && response.status() === 201);
  await page.getByTestId("upload-submit").click();
  const id = (await (await upload).json()).material.id;
  const row = page.locator(".material-item").filter({ hasText: title });
  await expect(row.locator(".material-status")).toHaveText("可检索", { timeout: 180000 });
  await row.locator(".material-view").click();
  await expect(page.getByTestId("material-reader")).toContainText("极限");
  await screenshot(page, info, "09-material-reader");
  const search = await apiFetch("/api/materials/search", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "洛必达法则的适用条件", top_k: 5, material_ids: [id] }) });
  expect(search.status).toBe(200);
  const results = await search.json();
  expect(results.hits.length).toBeGreaterThan(0);
  expect(results.hits.every((hit: any) => hit.material_id === id)).toBe(true);
  await info.attach("material-search-evidence", { body: JSON.stringify(results, null, 2), contentType: "application/json" });
  const deleted = await apiFetch(`/api/materials/${id}`, { method: "DELETE" });
  expect(deleted.ok).toBeTruthy();
  const after = await (await apiFetch("/api/materials/search", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "洛必达法则的适用条件", top_k: 5, material_ids: [id] }) })).json();
  expect(after.hits ?? []).toEqual([]);
});

test("隔离真实用户：问答首问、SSE结束、多轮历史恢复和设置权限保护", async ({ page }, info) => {
  await page.goto("/chat");
  await page.locator('button[title="新建对话"]').click();
  await screenshot(page, info, "10-chat-before-first-message");
  for (const question of ["矩阵的秩怎么理解？", "接着上题，给一个例子。"]) {
    await page.locator("#chat-question").fill(question);
    const received = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/assistant:stream"));
    await page.locator(".send-button").click();
    const response = await received;
    expect(response.status()).toBe(200);
    const stream = await response.text();
    expect(stream).toContain("event: done");
    expect(stream).not.toContain("event: error");
    await expect(page.locator("#chat-question")).toHaveValue("");
    await expect(page.locator("#chat-question")).toBeEnabled();
  }
  await expect(page.locator(".message-row--user")).toHaveCount(2);
  await expect(page.locator(".message-row--assistant")).toHaveCount(2);
  await screenshot(page, info, "11-chat-offline-business-sse");
  await page.reload();
  await expect(page.locator(".message-row--user")).toHaveCount(2);
  await expect(page.locator(".message-row--assistant")).toHaveCount(2);
  await page.goto("/settings");
  await expect(page.locator(".settings-page")).toContainText("已连接");
  // Settings credentials may only be changed in localhost dev. The test-mode
  // application must keep that boundary; browser protocol tests cover the form.
  await expect(page.getByTestId("save-model-settings")).toHaveCount(0);
  const denied = await apiFetch("/api/settings/model");
  expect(denied.status).toBe(403);
  expect((await denied.json()).error.code).toBe("settings_local_only");
  await screenshot(page, info, "12-settings-isolated-protection");
});
