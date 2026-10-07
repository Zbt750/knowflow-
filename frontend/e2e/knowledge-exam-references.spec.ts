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

test("已有原卷引用的节点补入完整题后可以打开在线题库", async ({ page }) => {
  await page.route("**/api/health", route => route.fulfill({ json: { status: "ok", database: "connected" } }));
  await page.route("**/api/knowledge/tree", route => route.fulfill({ json: { nodes: [root] } }));
  await page.route("**/api/plans/today", route => route.fulfill({ json: { status: "setup", recommendations: [] } }));
  await page.route("**/api/knowledge/ref-topic-1", route => route.fulfill({ json: {
    node: topic, attempts: [], lesson_available: false, materials_ready: false, exam_references: [],
    questions: [{ id: "transcribed-1", question_type: "single_choice", stem: "合成界面样例：$x^2$，不是原卷题。",
      kp_id: topic.id, options: { A: "选项甲", B: "选项乙" },
      question_role: "typical", difficulty: "medium", skill_tags: ["隔离样例"], estimated_minutes: 5, is_variant: false,
      question_source: { source_type: "exam", year: 2026, question_number: 8, subject: "数学二",
        paper_title: "合成隔离样例", content_status: "source_transcribed", edition: "回忆版" } }],
  } }));
  await page.goto("/knowledge?node=cs408.ds.topic.example&tab=questions");
  await expect(page.getByTestId("tab-questions")).toBeVisible();
  await expect(page.getByTestId("tab-exam-references")).toHaveCount(0);
  await expect(page.getByTestId("question-source")).toContainText("原卷转录");
  await expect(page.getByTestId("question-source")).not.toContainText("答案待核验");
  await expect(page.locator(".katex").first()).toBeVisible();
  await expect(page.getByTestId("question-bank")).toContainText("选项甲");
  await expect(page.getByTestId("question-bank")).toContainText("选项乙");
  const plan = { status: "active", plan_id: "online-plan" };
  await page.route("**/api/plans/today/generate", async route => {
    expect(route.request().postDataJSON().selected_kp_ids).toEqual([topic.id]);
    expect(route.request().postDataJSON().budget).toBe("light");
    await route.fulfill({ json: plan });
  });
  await page.route("**/api/plans/online-plan/questions", async route => {
    expect(route.request().postDataJSON().question_ids).toEqual(["transcribed-1"]);
    await route.fulfill({ json: plan });
  });
  await page.getByTestId("question-bank").getByRole("button", { name: "加入今日学习", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("已加入今日学习");
});

test("知识树不再展示历史题号关联和专题汇总", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/health", (route) => route.fulfill({ json: { status: "ok", database: "connected" } }));
  await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: { nodes: [{ ...root, children: [...root.children, { ...topic, id: "summary", code: "cs408.family.stack", name: "专题汇总：栈", children: [] }] }] } }));
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
  await expect(page.getByText("专题汇总：栈", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("knowledge-lesson-link")).toHaveCount(0);
  await expect(page.getByTestId("tab-exam-references")).toHaveCount(0);
  await expect(page.getByTestId("exam-reference-panel")).toHaveCount(0);
  await expect(page.getByText(/条题号关联/)).toHaveCount(0);
  expect(errors).toEqual([]);
});
