import { expect, test, type Page } from "@playwright/test";

// Pure browser mocks: these tests do not reset a database or contact a live API.
interface ScopeNode { id: string; code: string; name: string; is_assessable: boolean; children: ScopeNode[] }
function leaf(index: number): ScopeNode {
  return { id: `leaf-${index}`, code: `math.calculus.limit.${index}`, name: `极限知识点 ${index}`, is_assessable: true, children: [] };
}
const selected = leaf(0);
const target = leaf(119);
const tree: ScopeNode[] = [{
  id: "math", code: "math", name: "数学", is_assessable: false, children: [{
    id: "calculus", code: "math.calculus", name: "高等数学", is_assessable: false, children: [{
      id: "limits", code: "math.calculus.limit", name: "函数与极限", is_assessable: false,
      children: Array.from({ length: 120 }, (_, index) => leaf(index)),
    }],
  }],
}];

async function mockSetup(page: Page, treeFailures = 0): Promise<{ generated: string[][]; errors: string[] }> {
  const generated: string[][] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/plans/today") {
      return route.fulfill({ json: { status: "setup", study_date: "2026-09-26", recommendations: [{ kp_id: selected.id, name: selected.name, state: "unseen", reason: "preview", next_step: "", missing_types: [] }] } });
    }
    if (path === "/api/knowledge/tree") {
      if (treeFailures-- > 0) return route.fulfill({ status: 503, json: { error: { code: "temporary_failure", message: "知识树暂时不可用" } } });
      return route.fulfill({ json: { nodes: tree } });
    }
    if (path === "/api/plans/today/generate") {
      generated.push(route.request().postDataJSON().selected_kp_ids);
      return route.fulfill({ json: { status: "active", plan_id: "plan-1", study_date: "2026-09-26", completed_count: 0, total_count: 0, items: [], focus_item_id: null, summary_kps: [], type_summary: {}, estimated_minutes: 0, remaining_minutes: 0 } });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto("/study");
  await expect(page.getByTestId("study-setup")).toBeVisible();
  return { generated, errors };
}

test("练习范围按章节展开收起，搜索保留祖先路径且生成只提交所选叶子", async ({ page }) => {
  const { generated, errors } = await mockSetup(page);
  await expect(page.getByTestId("selected-kp-count")).toContainText("本次包含 1 个知识点");
  await page.getByTestId("tree-kp-picker-open").click();
  const chapter = page.getByTestId("scope-branch-math.calculus");
  await expect(chapter).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId(`pick-node-${selected.code}`)).toHaveCount(0);
  await chapter.click();
  const limits = page.getByTestId("scope-branch-math.calculus.limit");
  await limits.click();
  await expect(page.getByTestId(`pick-node-${selected.code}`)).toHaveAttribute("aria-pressed", "true");
  await limits.click();
  await expect(page.getByTestId(`pick-node-${selected.code}`)).toHaveCount(0);

  await page.getByTestId("scope-picker-search").fill(target.name);
  await expect(page.getByTestId("scope-branch-math")).toBeVisible();
  await expect(chapter).toBeVisible();
  await expect(limits).toBeVisible();
  await expect(page.getByTestId(`pick-node-${target.code}`)).toBeVisible();
  await expect(page.getByTestId(`pick-node-${selected.code}`)).toHaveCount(0);
  // Even an automatically expanded search path must be manually collapsible.
  await limits.click();
  await expect(page.getByTestId(`pick-node-${target.code}`)).toHaveCount(0);
  await limits.click();
  await page.getByTestId(`pick-node-${target.code}`).click();
  await expect(page.getByTestId("selected-kp-count")).toContainText("本次包含 2 个知识点");
  await page.getByTestId("scope-picker-search").fill("不存在的知识点");
  await expect(page.getByTestId("scope-picker-empty")).toBeVisible();
  await expect(page.getByTestId("selected-kp-count")).toContainText("本次包含 2 个知识点");
  await page.getByTestId("scope-picker-search").fill(selected.name);
  await page.getByTestId(`pick-node-${selected.code}`).click();
  await page.getByTestId("close-tree-kp-picker").click();
  await expect(page.getByTestId("recommended-kp")).toContainText(target.name);
  await page.getByTestId("generate-plan").click();
  await expect(page.getByTestId("study-active")).toBeVisible();
  expect(generated).toEqual([[target.id]]);
  expect(errors).toEqual([]);
});

test("大量知识点在窄屏内滚动且加载失败可重试", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { errors } = await mockSetup(page, 1);
  await page.getByTestId("tree-kp-picker-open").click();
  await expect(page.getByRole("alert")).toContainText("知识树暂时不可用");
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await expect(page.getByTestId("scope-branch-math.calculus")).toBeVisible();
  await page.getByTestId("scope-picker-search").fill("极限知识点");
  const viewport = page.getByTestId("scope-tree-window");
  await expect(viewport.locator(".study-range-row")).toHaveCount(120);
  expect(await viewport.evaluate((element) => element.scrollHeight > element.clientHeight && element.clientHeight <= 390)).toBe(true);
  await viewport.hover();
  await page.mouse.wheel(0, 650);
  await expect.poll(() => viewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByTestId("scope-picker-search").fill(target.name);
  await page.getByTestId(`pick-node-${target.code}`).click();
  await expect(page.getByTestId(`pick-node-${target.code}`)).toHaveAttribute("aria-pressed", "true");
  expect(errors).toEqual([]);
});

test("选中项显示根路径，搜索不丢祖先计数，并能定位或直接移出", async ({ page }) => {
  const { errors } = await mockSetup(page);
  await page.getByTestId("tree-kp-picker-open").click();
  const root = page.getByTestId("scope-branch-math");
  const summary = page.getByTestId(`scope-selected-${selected.id}`);
  await expect(summary).toContainText("数学 › 高等数学 › 函数与极限");
  await expect(root).toHaveClass(/scope-tree__branch--selected/);
  await expect(root).toContainText("已选 1");
  await page.getByTestId("scope-picker-search").fill(target.name);
  await page.getByTestId(`pick-node-${target.code}`).click();
  await expect(root).toContainText("已选 2");
  await expect(summary).toBeVisible();
  await page.getByRole("button", { name: `定位${selected.name}`, exact: true }).click();
  await expect(page.getByTestId("scope-picker-search")).toHaveValue("");
  await expect(page.getByTestId(`pick-node-${selected.code}`)).toBeFocused();
  await page.getByRole("button", { name: `从范围移出${selected.name}`, exact: true }).click();
  await expect(page.getByTestId(`pick-node-${selected.code}`)).toHaveAttribute("aria-pressed", "false");
  await expect(root).toContainText("已选 1");
  await page.getByRole("button", { name: `从范围移出${target.name}`, exact: true }).click();
  await expect(root).not.toHaveClass(/scope-tree__branch--selected/);
  await expect(page.getByTestId("generate-plan")).toBeDisabled();
  expect(errors).toEqual([]);
});
