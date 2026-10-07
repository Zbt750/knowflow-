import { test, expect } from "@playwright/test";

test("今日卷编号独立于原卷编号，专注和整卷都隐藏原题号", async ({ page }) => {
  const item = {
    id: "local-item", ordinal: 1, kp_id: "local-kp", kp_name: "合成隔离知识点",
    question_id: "local-question", question_type: "single_choice", question_role: "typical",
    difficulty: "medium", stem: "合成隔离题：$1+1=$（ ）。", options: { A: "2", B: "3" },
    skill_tags: [], is_variant: false, estimated_minutes: 5, completed: false,
    completed_at: null, latest_self_grade: null, is_review: false, is_external_reference: false,
    exam_reference: null, answer_submission: null, answer_grading_method: null,
    question_source: { source_type: "exam", year: 2025, question_number: 19, subject: "数学二",
      paper_title: "合成隔离原卷", content_status: "source_transcribed" },
  };
  await page.route("**/api/health", route => route.fulfill({ json: { status: "ok", database: "connected" } }));
  await page.route("**/api/knowledge/tree", route => route.fulfill({ json: { nodes: [] } }));
  await page.route("**/api/plans/today", route => route.fulfill({ json: {
    status: "active", plan_id: "local-plan", study_date: "2026-10-03", completed_count: 0,
    total_count: 1, items: [item], focus_item_id: item.id, summary_kps: [],
    type_summary: { single_choice: 1 }, estimated_minutes: 5, remaining_minutes: 5,
  } }));
  await page.goto("/study");
  const focus = page.getByTestId("focus-question");
  await expect(focus.locator("header strong")).toHaveText("第 1 题");
  await expect(focus.getByTestId("question-source")).toContainText("2025 年 · 数学二真题");
  await expect(focus.getByTestId("question-source")).not.toContainText("第 19 题");
  await page.getByTestId("full-paper").click();
  const paper = page.getByTestId("paper-list");
  await expect(paper.locator("header strong")).toHaveText("第 1 题");
  await expect(paper.getByTestId("question-source")).not.toContainText("第 19 题");
});
