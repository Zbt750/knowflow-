import { test, expect, apiFetch } from "./fixtures";

test("过程审阅在整卷保存反馈并跨视图保留草稿，失败重试复用键", async ({ page }) => {
  const tree = await (await apiFetch("/api/knowledge/tree")).json();
  const walk = (nodes: any[]): any[] => nodes.flatMap(n => [n, ...walk(n.children ?? [])]);
  const node = walk(tree.nodes).find(n => n.code === "math.calculus.limit.lhopital");
  const response = await apiFetch("/api/plans/today/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selected_kp_ids: [node.id] }) });
  expect(response.ok).toBeTruthy();
  const plan = await response.json();
  const item = plan.items.find((i: any) => i.question_type === "calculation");
  expect(item).toBeTruthy();
  let saved: any = null;
  const keys: string[] = [];
  await page.route(`**/api/practice-items/${item.id}/process-reviews/latest`, route => route.fulfill({ json: saved }));
  await page.route(`**/api/practice-items/${item.id}/process-reviews`, async route => {
    keys.push(route.request().postDataJSON().idempotency_key);
    if (keys.length === 1) { await route.abort(); return; }
    if (keys.length === 2) {
      saved = { review_id: "other-window-review", practice_item_id: item.id, review_kind: "calculation", feedback: "另一窗口建议：先核对前提。", reviewed_at: "2026-09-30T00:00:00+00:00", changes_mastery: false, is_final_grade: false };
      await route.fulfill({ status: 503, json: { error: { code: "process_review_busy", message: "过程审阅正在进行，请稍后查看结果或重试" } } });
      return;
    }
    saved = { review_id: "synthetic-review", practice_item_id: item.id, review_kind: "calculation", feedback: "请核对**使用条件**。", reviewed_at: "2026-09-30T00:00:00+00:00", changes_mastery: false, is_final_grade: false };
    await route.fulfill({ json: saved });
  });
  await page.goto("/study");
  await page.getByTestId("full-paper").click();
  const row = page.locator("li.paper-item").filter({ has: page.getByTestId(`paper-raw-answer-${item.id}`) });
  await row.getByText("检查我的过程", { exact: true }).click();
  const input = row.getByRole("textbox", { name: "解题过程或伪代码" });
  await expect(input).toBeEnabled();
  await input.fill("我先检查极限条件，然后对分子分母分别求导。");
  await row.getByRole("button", { name: "获取辅助建议" }).click();
  await expect(row.getByRole("alert")).toBeVisible();
  await page.getByTestId("mode-focus").click();
  await page.getByTestId("full-paper").click();
  await row.getByText("检查我的过程", { exact: true }).click();
  await expect(input).toHaveValue("我先检查极限条件，然后对分子分母分别求导。");
  await row.getByRole("button", { name: "获取辅助建议" }).click();
  await expect(row.getByRole("alert")).toContainText("过程审阅正在进行");
  await row.getByRole("button", { name: "读取最新建议" }).click();
  await expect(row.getByText("另一窗口建议：先核对前提。")).toBeVisible();
  expect(keys).toHaveLength(2);
  await row.getByRole("button", { name: "获取辅助建议" }).click();
  await expect(row.locator("strong").filter({ hasText: "使用条件" })).toBeVisible();
  expect(keys[1]).toBe(keys[0]);
  expect(keys[2]).toBe(keys[0]);
  await page.getByTestId("mode-focus").click();
  await page.getByTestId("full-paper").click();
  await row.getByText("检查我的过程", { exact: true }).click();
  await expect(input).toHaveValue("我先检查极限条件，然后对分子分母分别求导。");
  await page.reload();
  await page.getByTestId("full-paper").click();
  await row.getByText("检查我的过程", { exact: true }).click();
  await expect(row.locator("strong").filter({ hasText: "使用条件" })).toBeVisible();
});
