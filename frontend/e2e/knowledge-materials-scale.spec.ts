import { expect, test, type Page } from "@playwright/test";

const leaves = Array.from({ length: 120 }, (_, i) => ({ id: `leaf-${i}`, code: `math.limits.${i}`, name: `极限知识点 ${i}`, is_assessable: true, state: "unseen", children: [] }));
const chapter = { id: "limits", code: "math.limits", name: "函数与极限", is_assessable: false, state: null, children: leaves };
const root = { id: "math", code: "math", name: "数学", is_assessable: false, state: null, children: [chapter] };

async function mockApi(page: Page, materialCount = 41) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const materials = Array.from({ length: materialCount }, (_, i) => ({ id: `material-${i}`, title: `数学讲义 ${String(i).padStart(2, "0")}`, original_filename: `notes-${i}.md`, source_type: "user", status: "ready", created_at: "2026-09-26T01:00:00Z", updated_at: "2026-09-26T01:00:00Z", file_size: 100, active_index_version: "v1", last_error_code: null }));
  const offsets: number[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/knowledge/tree") return route.fulfill({ json: { nodes: [root] } });
    if (url.pathname.startsWith("/api/knowledge/nodes/")) {
      const id = url.pathname.split("/").pop();
      return route.fulfill({ json: { node: [root, chapter, ...leaves].find((node) => node.id === id), questions: [], attempts: [] } });
    }
    if (url.pathname === "/api/materials") {
      const q = url.searchParams.get("q") ?? "";
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 8);
      offsets.push(offset);
      const matches = materials.filter((material) => material.title.includes(q));
      return route.fulfill({ json: { items: matches.slice(offset, offset + limit), total: matches.length, stats: { total: materials.length, ready: materials.length } } });
    }
    if (url.pathname.endsWith("/chunks")) return route.fulfill({ json: { items: [], total: 0 } });
    if (url.pathname.endsWith("/content")) return route.fulfill({ json: { title: "数学讲义", text: "# 讲义正文\n\n可以直接阅读。\n\n$$x^2+y^2=1$$" } });
    if (url.pathname.startsWith("/api/materials/")) {
      const id = url.pathname.split("/").pop();
      return route.fulfill({ json: { ...materials.find((material) => material.id === id), chunk_count: 1, latest_job: null } });
    }
    return route.fulfill({ json: {} });
  });
  return { errors, offsets };
}

test("120个知识点默认折叠，分批展示，搜索保留祖先并可收起", async ({ page }) => {
  const { errors } = await mockApi(page);
  await page.goto("/knowledge");
  await expect(page.getByTestId("tree-node-math.limits")).toBeVisible();
  await expect(page.getByTestId("tree-node-math.limits.0")).toHaveCount(0);
  await page.getByRole("button", { name: "展开函数与极限", exact: true }).click();
  await expect(page.locator('[data-testid^="tree-node-math.limits."]')).toHaveCount(20);
  await page.getByRole("button", { name: "显示更多函数与极限下的节点", exact: true }).click();
  await expect(page.locator('[data-testid^="tree-node-math.limits."]')).toHaveCount(40);
  await page.getByTestId("knowledge-search").fill("math.limits.119");
  await expect(page.getByTestId("tree-node-math")).toBeVisible();
  await expect(page.getByTestId("tree-node-math.limits.119")).toBeVisible();
  await page.getByRole("button", { name: "收起函数与极限", exact: true }).click();
  await expect(page.getByTestId("tree-node-math.limits.119")).toHaveCount(0);
  await page.getByRole("button", { name: "展开函数与极限", exact: true }).click();
  await page.getByTestId("tree-node-math.limits.119").click();
  await expect(page.getByTestId("knowledge-breadcrumb")).toContainText("数学 / 函数与极限 / 极限知识点 119");
  await expect(page.getByTestId("knowledge-lesson-link")).toBeVisible();
  await page.getByTestId("knowledge-search").fill("不存在的节点");
  await expect(page.getByTestId("knowledge-search-empty")).toBeVisible();
  expect(errors).toEqual([]);
});

test("资料页页码跳转、末页与搜索重置页码，正文仍可阅读", async ({ page }) => {
  const { errors, offsets } = await mockApi(page);
  await page.goto("/materials");
  const pagination = page.getByTestId("materials-pagination");
  await expect(pagination).toContainText("第 1 / 6 页");
  await pagination.getByRole("button", { name: "第 6 页", exact: true }).click();
  await expect(pagination).toContainText("第 6 / 6 页");
  await expect(page.locator(".material-list > li")).toHaveCount(1);
  expect(offsets).toContain(40);
  await expect(pagination.getByRole("button", { name: "下一页" })).toBeDisabled();
  await page.getByTestId("material-search").fill("数学讲义 10");
  await expect(pagination).toContainText("第 1 / 1 页");
  await expect(page.locator(".material-list > li")).toHaveCount(1);
  await page.getByRole("button", { name: "查看数学讲义 10" }).click();
  await expect(page.getByRole("dialog", { name: "资料阅读器" })).toContainText("可以直接阅读");
  await expect(page.getByRole("dialog", { name: "资料阅读器" }).locator(".katex")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("单页也显示页数，两页在375px仍可翻页且没有横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { errors } = await mockApi(page, 9);
  await page.goto("/materials");
  const pagination = page.getByTestId("materials-pagination");
  await expect(pagination).toContainText("第 1 / 2 页");
  await pagination.getByRole("button", { name: "下一页" }).click();
  await expect(pagination).toContainText("第 2 / 2 页");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto("/knowledge");
  await page.getByTestId("knowledge-search").fill("math.limits.119");
  await expect(page.getByTestId("tree-node-math.limits.119")).toBeAttached();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
