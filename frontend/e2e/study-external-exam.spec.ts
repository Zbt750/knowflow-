import { expect, test } from "@playwright/test";

const reference = {
  id: "exam-reference-1",
  subject: "408",
  year: 2010,
  question_number: 1,
  topic_label: "栈的应用",
  source_topic_label: "栈的应用",
  question_source_url: "https://www.codebrick.tech/exam-408/q/ds/2010/01",
  topic_source_url: "https://www.codebrick.tech/exam-408/",
  local_folder: "408/2010",
  source_note: "第三方复习标签，非官方命题标注；请按原题核对。",
};

function activePlan(completed = false) {
  return {
    status: completed ? "completed" : "active",
    plan_id: "external-plan-1",
    study_date: "2026-09-28",
    completed_count: completed ? 1 : 0,
    total_count: 1,
    items: [{
      id: "external-item-1",
      ordinal: 1,
      kp_id: "kp-stack-applications",
      kp_name: "栈的应用",
      question_id: null,
      question_type: "external_exam",
      question_role: null,
      difficulty: null,
      stem: null,
      options: null,
      skill_tags: [],
      is_variant: false,
      estimated_minutes: 15,
      completed,
      completed_at: completed ? "2026-09-28T02:00:00+00:00" : null,
      latest_self_grade: completed ? "mastered" : null,
      is_review: false,
      is_external_reference: true,
      exam_reference: reference,
    }],
    focus_item_id: completed ? null : "external-item-1",
    summary_kps: [{ kp_id: "kp-stack-applications", name: "栈的应用", completed_count: completed ? 1 : 0, total_count: 1 }],
    type_summary: { external_exam: 1 },
    estimated_minutes: 15,
    remaining_minutes: completed ? 0 : 15,
  };
}

test("历年原卷任务在专注和全卷模式都清楚显示来源，并将自评提交为毕业证据", async ({ page }) => {
  let completed = false;
  let submitted: Record<string, unknown> | null = null;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/health", (route) => route.fulfill({
    json: { status: "ok", database: "connected" },
  }));
  await page.route("**/api/plans/today", (route) => route.fulfill({ json: activePlan(completed) }));
  await page.route("**/api/practice-items/external-item-1/self-assessments", async (route) => {
    submitted = route.request().postDataJSON();
    completed = true;
    await route.fulfill({
      json: {
        practice_item_id: "external-item-1",
        kp_id: "kp-stack-applications",
        state: "mastered",
        reason_code: "graduated",
        effective_confirmation_count: 1,
        manual_credit_count: 0,
        next_review_at: null,
      },
    });
  });

  await page.goto("/study");
  await expect(page.getByTestId("focus-external-exam-task")).toContainText("2010 年第 1 题");
  await expect(page.getByTestId("focus-external-exam-task")).toContainText("作为 栈的应用 的毕业证据");
  await page.getByTestId("full-paper").click();
  await expect(page.getByTestId("external-exam-external-item-1")).toContainText("本地原卷：桌面 / 考研知识点 / 408/2010");
  await expect(page.getByRole("button", { name: "查看答案详解" })).toHaveCount(0);
  await page.getByTestId("mode-focus").click();
  await page.getByTestId("focus-external-exam-task").getByRole("button", { name: "已掌握" }).click();
  await expect.poll(() => submitted).toMatchObject({ self_grade: "mastered" });
  await expect(page.getByTestId("study-status")).toContainText("已完成");
  expect(errors).toEqual([]);
});
