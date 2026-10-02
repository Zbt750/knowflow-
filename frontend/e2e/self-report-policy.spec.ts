import { test, expect } from "./fixtures";

for (const mode of ["focus", "paper"]) {
  test(`${mode}：机器判题无自评替代入口，开放题表现默认收起且不称为掌握`, async ({ page }) => {
    let automatic = true;
    const item = () => ({ id: "policy-item", question_id: "policy-q", kp_id: "policy-kp", kp_name: "合成知识点", ordinal: 1,
      question_type: automatic ? "fill_blank" : "proof", question_role: "basic", estimated_minutes: 5,
      stem: "合成题目", options: null, skill_tags: [], is_variant: false, is_review: false,
      completed: false, completed_at: null, latest_self_grade: null, objective_result: "unknown",
      answer_grading_method: automatic ? "numeric_final" : null });
    await page.route("**/api/plans/today", route => route.fulfill({ json: { status: "active", plan_id: "policy-plan", study_date: "2026-09-30",
      focus_item_id: "policy-item", items: [item()], total_count: 1, completed_count: 0, remaining_minutes: 5, estimated_minutes: 5,
      type_summary: {}, summary_kps: [] } }));
    await page.goto("/study");
    if (mode === "paper") await page.getByTestId("full-paper").click();
    await expect(page.getByTestId("self-report")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "跳过", exact: true })).toBeVisible();
    automatic = false;
    await page.reload();
    if (mode === "paper") await page.getByTestId("full-paper").click();
    const report = page.getByTestId("self-report");
    await expect(report).toBeVisible();
    await expect(report.getByRole("button", { name: "独立完成" })).not.toBeVisible();
    await report.locator("summary").click();
    for (const name of ["独立完成", "部分完成", "未完成"]) await expect(report.getByRole("button", { name, exact: true })).toBeVisible();
    await expect(report).toContainText("不作为机器判题或毕业确认");
    await expect(page.getByRole("button", { name: "已掌握", exact: true })).toHaveCount(0);
  });
}
