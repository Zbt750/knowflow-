import { test, expect, type Page } from "@playwright/test";
test.setTimeout(30_000);

// UI-only, isolated API mocks. Backend integration tests exercise real comparison/PG.
function item(id: string, type = "single_choice") {
  return { id, question_id: `q-${id}`, kp_id: "ready", kp_name: "有在线题目的知识点", ordinal: id === "first" ? 1 : 2,
    question_type: type, stem: id === "first" ? "第一道合成练习：请选择正确答案。" : "第二道合成练习题",
    options: type === "single_choice" ? { A: "答案甲", B: "答案乙", C: "答案丙", D: "答案丁" } : null,
    question_source: { source_type: "exam", content_status: "source_transcribed", subject: "数学二", year: 2025,
      question_number: 1, paper_title: "隔离合成试卷" },
    answer_grading_method: type === "single_choice" ? "reference_single_choice" : "reference_constant_final",
    completed: false, completed_at: null, latest_self_grade: null, skill_tags: [], is_variant: false,
    is_review: false, is_external_reference: false, exam_reference: null, estimated_minutes: 5, answer_submission: null as any };
}

async function setup(page: Page, type = "single_choice") {
  const first = item("first", type), second = item("second", type);
  const plan = { status: "active", plan_id: "plan", study_date: "2026-10-05", total_count: 2, completed_count: 0,
    items: [first, second], focus_item_id: "first", summary_kps: [], type_summary: {}, estimated_minutes: 10, remaining_minutes: 10 };
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health") return route.fulfill({ json: { status: "ok", database: "connected" } });
    if (path === "/api/plans/today") return route.fulfill({ json: plan });
    if (path === "/api/knowledge/tree") return route.fulfill({ json: { nodes: [{
      id: "root", code: "root", name: "数学", is_assessable: false, online_question_count: 0, children: [
        { id: "empty", code: "empty", name: "只有原卷索引", is_assessable: true, is_reference_only: true, online_question_count: 0, children: [] },
        { id: "ready", code: "ready", name: "有在线题目的知识点", is_assessable: true, online_question_count: 2, children: [] },
      ],
    }] } });
    if (path.endsWith("/answer-submissions")) {
      const body = route.request().postDataJSON();
      const right = type === "single_choice" ? body.selected_option === "A" : body.raw_answer === "sqrt(2)/2";
      const receipt = { attempt_id: "attempt-first", practice_item_id: "first", result: right ? "right" : "wrong",
        reason: "reference_comparison", method: "reference_single_choice_v1", assisted: false,
        raw_answer: body.raw_answer ?? null, selected_option: body.selected_option ?? null,
        effective_confirmation_count: 0, submitted_at: "2026-10-05T08:00:00Z", state: "unseen",
        mastery_reason: "answer_recorded", can_retry: !right, attempt_number: 1 };
      first.answer_submission = receipt;
      first.completed = true;
      plan.completed_count = 1;
      plan.focus_item_id = "second";
      return route.fulfill({ json: receipt });
    }
    if (path.endsWith("/answer-reveal") || path.endsWith("/answer")) return route.fulfill({ json: {
      practice_item_id: "first", question_id: "q-first", stem: first.stem, options: first.options,
      correct_answer: type === "single_choice" ? "A" : "sqrt(2)/2", explanation: "这是隔离合成解析，提交后可以阅读。",
    } });
    return route.fulfill({ json: { items: [], questions: [], exam_references: [] } });
  });
  return { errors };
}

test("原卷转录选择题提交即显示对错，错误后仍留在当前题看解析", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/study");
  await expect(page.getByTestId("answer-grading-boundary")).toHaveText("按题库答案核对最终结果。");
  await expect(page.locator("body")).not.toContainText("答案待核验");
  await page.getByTestId("option-B").check();
  await page.getByTestId("submit-answer").click();
  await expect(page.getByTestId("answer-submission-notice")).toHaveText("×");
  await expect(page.getByTestId("focus-stem")).toContainText("第一道合成练习");
  await page.getByTestId("answer-explanation").click();
  await expect(page.getByTestId("focus-answer")).toContainText("隔离合成解析");
  await page.getByTestId("full-paper").click();
  await expect(page.getByTestId("paper-submission-first")).toHaveText("×");
  expect(errors).toEqual([]);
});

test("追加树不显示无题节点；根式答案的输入和正确反馈可用", async ({ page }) => {
  const { errors } = await setup(page, "fill_blank");
  await page.goto("/study");
  await page.getByTestId("append-questions").click();
  await page.getByTestId("question-picker-node-root").click();
  await expect(page.getByTestId("question-picker-node-empty")).toHaveCount(0);
  await expect(page.getByTestId("question-picker-node-ready")).toBeVisible();
  await page.getByTestId("question-picker").getByRole("button", { name: "取消", exact: true }).click();
  await page.getByTestId("raw-answer").fill("sqrt(2)/2");
  await page.getByTestId("submit-answer").click();
  await expect(page.getByTestId("answer-submission-notice")).toHaveText("✓");
  expect(errors).toEqual([]);
});
