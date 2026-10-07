import { expect, test } from "@playwright/test";

const makeNode = (code: string) => ({
  id: code, code, name: code === "topic.a" ? "反常积分" : "希尔排序", subject: "数学二",
  ordinal: 1, is_assessable: true, children: [], state: "unseen",
  is_reference_only: false,
  required_question_types: {}, required_skill_tags: [], excluded_question_types: [], gap_items: [],
});
const a = makeNode("topic.a"), b = makeNode("topic.b");
test.setTimeout(30_000);

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", r => r.fulfill({ json: { status: "ok", database: "connected" } }));
  await page.route("**/api/plans/today", r => r.fulfill({ json: { status: "setup", recommendations: [] } }));
  await page.route("**/api/knowledge/tree", r => r.fulfill({ json: { nodes: [
    { ...a, id: "root", code: "root", name: "测试章节", is_assessable: false, children: [a, b] },
  ] } }));
  for (const node of [a, b]) {
    await page.route(`**/api/knowledge/${node.id}`, r => r.fulfill({ json: {
      node, questions: [], attempts: [], exam_references: [], lesson_available: true, materials_ready: false,
    } }));
  }
});

test("选择节点展示简要概览，点击文件入口进入完整独立阅读页", async ({ page }) => {
  await page.route("**/api/knowledge/lessons/topic.a", r => r.fulfill({ json: {
    code: a.code, name: a.name, markdown: "# 反常积分\n\n## 概念\n无穷端点的极限定义。\n\n## 例题\n$p>1$ 时收敛。",
    question_count: 0, exam_reference_count: 0,
  } }));
  await page.goto("/knowledge?node=topic.a");
  await expect(page.getByTestId("inline-knowledge-lesson")).toHaveCount(0);
  const link = page.getByTestId("knowledge-lesson-link");
  await expect(link).toHaveAttribute("href", "/knowledge/topic.a/lesson");
  await link.click();
  const article = page.getByTestId("lesson-article");
  await expect(article).toContainText("无穷端点的极限定义");
  await expect(article.locator(".katex")).toBeVisible();
});

test("独立阅读页加载失败可重试，前往另一个节点不会保留旧正文", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/knowledge/lessons/topic.a", r => {
    calls++;
    return calls === 1
      ? r.fulfill({ status: 503, json: { error: { code: "unavailable", message: "讲解暂时不可用" } } })
      : r.fulfill({ json: { code: a.code, name: a.name, markdown: "# 反常积分\n第一节点正文", question_count: 0, exam_reference_count: 0 } });
  });
  await page.route("**/api/knowledge/lessons/topic.b", r => r.fulfill({ json: {
    code: b.code, name: b.name, markdown: "# 希尔排序\n第二节点正文", question_count: 0, exam_reference_count: 0,
  } }));
  await page.goto("/knowledge/topic.a/lesson");
  await page.getByTestId("lesson-error").getByRole("button", { name: "重试" }).click();
  const article = page.getByTestId("lesson-article");
  await expect(article).toContainText("第一节点正文");
  await page.goto("/knowledge/topic.b/lesson");
  await expect(page.getByTestId("lesson-article")).toContainText("第二节点正文");
  await expect(page.getByTestId("lesson-article")).not.toContainText("第一节点正文");
});
