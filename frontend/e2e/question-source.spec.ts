import { test, expect, apiFetch } from "./fixtures";

test("题目来源：专注、整卷显示年份但不显示原卷题号，不把模拟卷标成真题", async ({ page }) => {
  const tree = await (await apiFetch("/api/knowledge/tree")).json();
  const walk = (nodes: any[]): any[] => nodes.flatMap(node => [node, ...walk(node.children ?? [])]);
  const node = walk(tree.nodes).find(node => node.code === "math.calculus.limit.lhopital");
  const response = await apiFetch("/api/plans/today/generate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selected_kp_ids: [node.id] }),
  });
  expect(response.ok).toBeTruthy();
  const plan = await response.json();
  // Only a browser response fixture; no pretend real papers inserted into DB.
  for (const item of plan.items) {
    // This scenario replaces the source of a synthetic UI response; keep no
    // incompatible real-fixture trust label that would override that source.
    item.question_trust = null;
    item.question_source = { source_type: "mock", year: 2025, question_number: 3,
      paper_title: "合成隔离模拟卷", subject: "数学二", content_status: "source_transcribed", edition: "隔离样例" };
    item.stem = "仅用于界面测试的合成题：$x^2+1$。";
  }
  await page.route("**/api/plans/today", route => route.fulfill({ json: plan }));
  await page.goto("/study");
  await expect(page.getByTestId("focus-question").getByTestId("question-source")).toHaveText("2025 年 · 合成隔离模拟卷 · 模拟题 · 隔离样例 · 原卷转录");
  await expect(page.getByTestId("focus-question").locator(".katex").first()).toBeVisible();
  await page.getByTestId("full-paper").click();
  await expect(page.getByTestId("paper-list").getByTestId("question-source").first()).toHaveText("2025 年 · 合成隔离模拟卷 · 模拟题 · 隔离样例 · 原卷转录");
  await expect(page.getByTestId("paper-list").locator(".katex").first()).toBeVisible();
});
