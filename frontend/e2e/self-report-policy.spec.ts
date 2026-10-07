import { test, expect } from "./fixtures";

for (const mode of ["focus", "paper"]) {
  for (const type of ["single_choice", "fill_blank", "calculation"]) {
    test(`${mode}：待核验${type}直接提交，不用自评代替判题`, async ({ page }) => {
      let completed = false;
      const receipt = { attempt_id: "policy-attempt", practice_item_id: "policy-item", result: "unknown",
        reason: "answer_not_verified", method: "unsupported_v1", assisted: false, submitted_at: "2026-10-04T00:00:00Z" };
      await page.route("**/api/plans/today", route => route.fulfill({ json: {
        status: "active", plan_id: "policy-plan", study_date: "2026-10-04", total_count: 1, completed_count: completed ? 1 : 0,
        remaining_minutes: 5, estimated_minutes: 5, type_summary: {}, summary_kps: [], items: [{
          id: "policy-item", question_id: "policy-q", kp_id: "policy-kp", kp_name: "隔离知识点", ordinal: 1,
          question_type: type, question_role: "basic", estimated_minutes: 5, stem: "隔离待核验题目",
          options: type === "single_choice" ? { A: "甲", B: "乙" } : null, skill_tags: [], is_variant: false,
          is_review: false, completed, answer_grading_method: null, answer_submission: completed ? receipt : null,
          question_source: { source_type: "unknown", content_status: "source_transcribed" },
        }],
      } }));
      await page.route("**/api/practice-items/policy-item/answer-submissions", route => {
        expect(route.request().method()).toBe("POST");
        completed = true;
        return route.fulfill({ json: receipt });
      });
      await page.goto("/study");
      if (mode === "paper") await page.getByTestId("full-paper").click();
      await expect(page.getByTestId("self-report")).toHaveCount(0);
      const boundary = page.getByTestId(mode === "focus" ? "answer-grading-boundary" : "paper-grading-boundary-policy-item");
      await expect(boundary).toContainText("答案格式暂不支持自动比较");
      await expect(boundary).toContainText("不计入毕业确认");
      if (type === "single_choice") await page.getByTestId(mode === "focus" ? "option-A" : "paper-option-policy-item-A").check();
      else {
        const input = page.getByTestId(mode === "focus" ? "raw-answer" : "paper-raw-answer-policy-item");
        await expect(input).toHaveAttribute("placeholder", "在纸上计算，在这里填写最终答案");
        await input.fill("1");
      }
      const submit = page.getByTestId(mode === "focus" ? "submit-answer" : "paper-submit-answer-policy-item");
      await expect(submit).toHaveText("提交答案");
      await submit.click();
      await expect(page.getByTestId(mode === "focus" ? "answer-submission-notice" : "paper-submission-policy-item")).toHaveText("未判定");
      await expect(page.getByTestId("self-report")).toHaveCount(0);
    });
  }
  test(`${mode}：机器判题无自评替代入口，开放题表现默认收起且不称为掌握`, async ({ page }) => {
    let automatic = true;
    let openType = "proof";
    const item = () => ({ id: "policy-item", question_id: "policy-q", kp_id: "policy-kp", kp_name: "合成知识点", ordinal: 1,
      question_type: automatic ? "fill_blank" : openType, question_role: "basic", estimated_minutes: 5,
      stem: "合成题目", options: null, skill_tags: [], is_variant: false, is_review: false,
      completed: false, completed_at: null, latest_self_grade: null, objective_result: "unknown",
      answer_grading_method: automatic ? "numeric_final" : null });
    await page.route("**/api/plans/today", route => route.fulfill({ json: { status: "active", plan_id: "policy-plan", study_date: "2026-09-30",
      focus_item_id: "policy-item", items: [item()], total_count: 1, completed_count: 0, remaining_minutes: 5, estimated_minutes: 5,
      type_summary: {}, summary_kps: [] } }));
    await page.goto("/study");
    if (mode === "paper") await page.getByTestId("full-paper").click();
    await expect(page.getByTestId("self-report")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "跳过", exact: true })).toHaveCount(0);
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
    openType = "subjective";
    await page.reload();
    if (mode === "paper") await page.getByTestId("full-paper").click();
    await expect(page.getByTestId("self-report")).toBeVisible();
    await expect(page.getByTestId("self-report")).not.toHaveAttribute("open", "");
  });
}
