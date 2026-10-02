import { test, expect, apiFetch } from "./fixtures";

async function numericItem() {
  const tree = await (await apiFetch("/api/knowledge/tree")).json();
  const walk = (nodes: any[]): any[] => nodes.flatMap(n => [n, ...walk(n.children ?? [])]);
  const node = walk(tree.nodes).find(n => n.code === "math.calculus.limit.lhopital");
  const detail = await (await apiFetch(`/api/knowledge/${node.id}`)).json();
  const q = detail.questions.find((q: any) => q.stem === "求极限 lim(x->0) (e^x - 1) / x 的值。");
  let plan = await (await apiFetch("/api/plans/today/generate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selected_kp_ids: [node.id] }),
  })).json();
  if (!plan.items.some((item: any) => item.question_id === q.id)) {
    plan = await (await apiFetch(`/api/plans/${plan.plan_id}/questions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question_ids: [q.id] }),
    })).json();
  }
  return { node, item: plan.items.find((item: any) => item.question_id === q.id) };
}

test("可靠最终答案形成独立证据，证明能力不被连带确认，详情默认收起", async ({ page }) => {
  const { node, item } = await numericItem();
  const response = await apiFetch(`/api/practice-items/${item.id}/answer-submissions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: `cap-e2e-correct-${item.id}`, raw_answer: "1" }),
  });
  expect(response.ok).toBeTruthy();
  await page.goto(`/knowledge?node=${encodeURIComponent(node.code)}`);
  const result = page.getByTestId("capability-final_result");
  await expect(result).toContainText("已有独立证据");
  await expect(result).not.toHaveAttribute("open", "");
  await result.locator("summary").click();
  await expect(result).toContainText("独立证据 1");
  await expect(result).toContainText("不代表全面掌握");
  await result.locator("summary").click();
  await expect(result).not.toHaveAttribute("open", "");
  await expect(page.getByTestId("capability-reasoning_process")).toContainText("尚未验证");
  await page.reload();
  await expect(page.getByTestId("capability-final_result")).toContainText("已有独立证据");
});

test("答错自行改正仍显示待复测，不把重复记录变成多份证据", async ({ page }) => {
  const { node, item } = await numericItem();
  const first = await (await apiFetch(`/api/practice-items/${item.id}/answer-submissions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: `cap-e2e-wrong-${item.id}`, raw_answer: "3" }),
  })).json();
  const second = await apiFetch(`/api/practice-items/${item.id}/answer-submissions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: `cap-e2e-retry-${item.id}`, raw_answer: "1", expected_previous_attempt_id: first.attempt_id }),
  });
  expect(second.ok).toBeTruthy();
  await page.goto(`/knowledge?node=${encodeURIComponent(node.code)}`);
  const result = page.getByTestId("capability-final_result");
  await expect(result).toContainText("待复测");
  await result.locator("summary").click();
  await expect(result).toContainText("独立证据 0");
  await expect(result).toContainText("立即改正或看解析后完成不替代复测");
});

test("浅窄屏保持简洁可展开，父节点不显示能力确认面板", async ({ page }) => {
  const { node } = await numericItem();
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto(`/knowledge?node=${encodeURIComponent(node.code)}`);
  await expect(page.getByTestId("knowledge-capabilities")).toBeVisible();
  await page.getByTestId("capability-reasoning_process").locator("summary").click();
  await expect(page.getByTestId("capability-reasoning_process")).toContainText("尚无可靠的过程核验");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.goto("/knowledge?node=math.calculus");
  await expect(page.getByTestId("knowledge-parent-summary")).toBeVisible();
  await expect(page.getByTestId("knowledge-capabilities")).toHaveCount(0);
});
