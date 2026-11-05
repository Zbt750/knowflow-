// UI-only synthetic API fixtures. No backend calls, resets, or learner writes.
import { test, expect } from "@playwright/test";

const id = "11111111-1111-4111-8111-111111111111";
const node = { id, code: "math.synthetic.progress", name: "合成学习知识点", subject: "考研数学", ordinal: 1,
  is_assessable: true, is_reference_only: false, state: "mastered", children: [],
  assessment_basis: "legacy_self_reported", next_step: "旧严格评价建议", gap_items: [],
  required_question_types: {}, required_question_origins: {}, required_skill_tags: [] };

const cases = [
  ["NOT_STARTED", "尚未练习", "当前知识点缺少可用练习题，可以先阅读讲解。"],
  ["PRACTICING", "正在练习", "参考答案比对不一致，建议换题验证。"],
  ["NEEDS_CONSOLIDATION", "待巩固", "可靠判题中存在错误，建议巩固方法。"],
  ["IMPROVING", "有进展", "不同题目中出现改善，继续验证。"],
  ["RETEST_RECOMMENDED", "建议复测", "在查看解析后完成，建议稍后独立复验。"],
  ["STABLE_PRACTICE", "基础练习表现稳定", "当前有效严格证据满足有限练习稳定规则。"],
] as const;

for (const [status, label, reason] of cases) {
  test(`${label}是主反馈，历史严格状态折叠保留`, async ({ page }, testInfo) => {
    const pageErrors: string[] = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      // Vite imports /src/api/*.ts too; never return fixture JSON for JS modules.
      if (!path.startsWith("/api/")) return route.continue();
      const data = path.endsWith("/knowledge/tree") ? { nodes: [node] }
        : path.endsWith(`/knowledge/${id}`) ? { node, questions: [], attempts: [], exam_references: [],
          lesson_available: false, materials_ready: false, capability_profile: {
            version: "capability-evidence-v1", dimensions: [], note: "合成UI夹具，不是实际核验。",
            learning_progress: { version: "learning_progress_v1", status, label, reason,
              reliability_note: "练习观察与严格毕业评价分开。", next_action: "validate_with_other_questions",
              next_step: "请在今日学习选择不同题目验证。", limitations: ["这是隔离的UI测试数据。"] } } }
        : { status: "ok", database: "connected", retrieval: "ready", worker: "running" };
      await route.fulfill({ json: data });
    });
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/knowledge?node=math.synthetic.progress");
    await expect(page.getByTestId("learning-progress")).toHaveAttribute("data-status", status);
    await expect(page.getByTestId("learning-progress-label")).toHaveText(label);
    expect(pageErrors).toEqual([]);
    if (status === "PRACTICING") await page.screenshot({ path: testInfo.outputPath("learning-progress.png"), fullPage: true });
    await expect(page.getByTestId("learning-progress")).toContainText(reason);
    await expect(page.getByTestId("detail-state")).not.toBeVisible();
    await expect(page.getByTestId("knowledge-detail")).not.toContainText("旧严格评价建议");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByTestId("knowledge-advanced").locator(":scope > summary").click();
    await expect(page.getByTestId("detail-state")).toContainText("已毕业");
    await expect(page.getByTestId("learning-progress-label")).toHaveText(label);
  });
}
