import { expect, test } from "@playwright/test";

const topic = {
  id: "ref-topic-1",
  code: "cs408.ds.topic.example",
  name: "栈的应用",
  subject: "408",
  ordinal: 1,
  is_assessable: true,
  is_reference_only: true,
  summary: null,
  learning_goal: null,
  state: "unseen",
  next_review_at: null,
  mastered_at: null,
  node_self_grade: null,
  manual_credit_count: 0,
  effective_confirmation_count: 0,
  has_real_variant: false,
  first_confirmed_on: null,
  last_confirmed_on: null,
  day_span: null,
  gap_items: [],
  next_step: null,
  excluded_question_types: [],
  required_skill_tags: [],
  required_question_types: { external_exam: 1 },
  children: [],
};
const root = {
  ...topic,
  id: "ref-root",
  code: "cs408",
  name: "408 计算机学科专业基础",
  is_assessable: false,
  is_reference_only: false,
  children: [{ ...topic, id: "ref-ds", code: "cs408.ds", name: "数据结构", is_assessable: false, is_reference_only: false, children: [topic] }],
};

test("知识树历年题号可追溯来源、加入今日练习并标记毕业证据", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/health", (route) => route.fulfill({ json: { status: "ok", database: "connected" } }));
  await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: { nodes: [root] } }));
  await page.route("**/api/plans/today", (route) => route.fulfill({
    json: { status: "setup", study_date: "2026-09-28", recommendations: [] },
  }));
  await page.route("**/api/plans/today/exam-references", (route) => route.fulfill({
    json: {
      status: "active",
      plan_id: "today-plan",
      study_date: "2026-09-28",
      completed_count: 0,
      total_count: 1,
      items: [{
        id: "practice-ref-1", ordinal: 1, kp_id: topic.id, kp_name: topic.name,
        question_id: null, question_type: "external_exam", question_role: null,
        difficulty: null, stem: null, options: null, skill_tags: [], is_variant: false,
        estimated_minutes: 15, completed: false, completed_at: null, latest_self_grade: null,
        is_review: false, is_external_reference: true,
        exam_reference: {
          id: "reference-1", subject: "408", year: 2010, question_number: 1,
          topic_label: "栈的应用", source_topic_label: "栈的应用",
          question_source_url: "https://www.codebrick.tech/exam-408/q/ds/2010/01",
          topic_source_url: "https://www.codebrick.tech/exam-408/",
          local_folder: "408/2010", source_note: "第三方题目/考点索引，分类不是官方命题标注。",
        },
      }],
      focus_item_id: "practice-ref-1", summary_kps: [], type_summary: { external_exam: 1 },
      estimated_minutes: 15, remaining_minutes: 15,
    },
  }));
  await page.route("**/api/knowledge/ref-topic-1", (route) => route.fulfill({
    json: {
      node: { ...topic, required_question_types: { external_exam: 1 } },
      questions: [],
      attempts: [],
      lesson_available: false,
      materials_ready: false,
      exam_references: [{
        id: "reference-1",
        subject: "408",
        year: 2010,
        question_number: 1,
        topic_label: "栈的应用",
        source_topic_label: "栈的应用",
        question_source_url: "https://www.codebrick.tech/exam-408/q/ds/2010/01",
        topic_source_url: "https://www.codebrick.tech/exam-408/",
        local_folder: "408/2010",
        source_note: "第三方题目/考点索引，分类不是官方命题标注。",
      }],
    },
  }));

  await page.goto("/knowledge");
  await page.getByRole("button", { name: "展开数据结构", exact: true }).click();
  await expect(page.getByText("未学习 · 历年真题")).toBeVisible();
  await page.getByTestId("tree-node-cs408.ds.topic.example").click();
  await expect(page.getByTestId("exam-reference-only-note")).toContainText("毕业证据");
  await expect(page.getByTestId("knowledge-lesson-link")).toHaveCount(0);
  await page.getByTestId("tab-exam-references").click();
  await expect(page.getByTestId("exam-reference-panel")).toContainText("2010 年");
  await expect(page.getByRole("link", { name: "打开题目来源 ↗" })).toHaveAttribute(
    "href",
    "https://www.codebrick.tech/exam-408/q/ds/2010/01",
  );
  await page.getByRole("button", { name: "加入今日学习" }).click();
  await expect(page.getByTestId("exam-reference-notice")).toContainText("计入本知识点毕业证据");
  await expect(page.getByRole("button", { name: "已在今日学习" })).toBeDisabled();
  expect(errors).toEqual([]);
});
