// Synthetic UI fixtures only. Real comparison/receipt protection is tested in PG.
import { test, expect } from "@playwright/test";

for (const origin of ["real_exam", "legacy_unknown", "ai_generated_practice"]) {
  test(`教学参考反馈不打错号，来源标签不越界：${origin}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const item: any = { id: "test-item", ordinal: 1, kp_id: "test-kp", kp_name: "合成知识点", question_id: "test-q",
      question_type: "single_choice", question_role: "basic", difficulty: "basic", stem: "合成测试：请选择一项。",
      options: { A: "参考甲", B: "参考乙" }, skill_tags: [], is_variant: false, estimated_minutes: 5,
      completed: false, is_review: false, is_external_reference: false, answer_grading_method: null,
      question_source: { source_type: "exam", year: 2020, question_number: 1, subject: "数学二", paper_title: "合成测试", content_status: "source_transcribed" },
      question_trust: { question_provenance: origin, source_status: "traceable", source_attestation_current: true,
        teaching_use: "REFERENCE_ONLY", objective_feedback_eligible: false, evidence_capability: "reference_learning_only" } };
    const plan = { status: "active", plan_id: "test-plan", study_date: "2026-10-08", total_count: 1, completed_count: 0,
      focus_item_id: item.id, items: [item], summary_kps: [], type_summary: {}, estimated_minutes: 5, remaining_minutes: 5 };
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/plans/today") return route.fulfill({ json: plan });
      if (path === "/api/knowledge/tree") return route.fulfill({ json: { nodes: [] } });
      if (path === "/api/practice-requests") return route.fulfill({ json: [] });
      if (path.endsWith("/answer-submissions")) {
        const receipt = { attempt_id: "test-attempt", practice_item_id: item.id, result: "unknown", reference_result: "wrong",
          reason: "reference_answer_not_reliably_verified", method: "teaching_reference_v2", assisted: false,
          selected_option: "B", submitted_at: "2026-10-08T08:00:00Z", effective_confirmation_count: 0,
          feedback_notice: "仅供对照参考，暂不支持可靠自动判题。", can_retry: true };
        item.completed = true; item.answer_submission = receipt;
        return route.fulfill({ json: receipt });
      }
      if (path.endsWith("/answer-reveal") || path.endsWith("/answer")) return route.fulfill({ json: {
        practice_item_id: item.id, question_id: item.question_id, correct_answer: "A", explanation: "合成参考解析，未独立核验。" } });
      return route.fulfill({ json: { status: "ok", database: "connected", items: [] } });
    });
    await page.goto("/study");
    const label = origin === "real_exam" ? "真题整理" : origin === "legacy_unknown" ? "来源待核练习" : "AI练习题";
    await expect(page.getByTestId("focus-question").getByTestId("question-source")).toContainText(label);
    await expect(page.getByTestId("answer-grading-boundary")).toContainText("暂不支持可靠自动判题");
    await page.getByTestId("option-B").check();
    await page.getByTestId("submit-answer").click();
    await expect(page.getByTestId("answer-submission-notice")).toHaveText("未判定");
    await expect(page.getByTestId("answer-submission-notice")).toHaveAttribute("data-result", "unknown");
    await page.getByTestId("answer-explanation").click();
    await expect(page.getByTestId("focus-answer")).toContainText("参考解析：");
    await page.getByTestId("full-paper").click();
    await expect(page.getByTestId("paper-list").getByTestId("question-source")).toContainText(label);
    await expect(page.getByTestId("paper-submission-test-item")).toHaveText("未判定");
    expect(errors).toEqual([]);
  });
}
