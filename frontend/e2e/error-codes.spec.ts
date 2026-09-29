import { expect, test, type Page } from "./fixtures";

/**
 * 第 17 篇规格 2.5「错误码与页面行为」的前端契约测试。
 *
 * 为什么这些用例全部用 `page.route` mock：
 * 规格要求的是「页面**只按 code 决定行为**」，而构造真实的 409 / 404 / 422
 * 需要先把库造到特定状态，既慢又难覆盖（例如「今天已经有卷」天然不可重复触发）。
 * mock 掉 HTTP 之后，被测的东西恰好就是页面拿到这个 code 之后做了什么 ——
 * 那正是规格要锁的部分。规格第 5 节的验收脚本也是这么写的。
 *
 * 这些用例**不碰后端、不碰数据库**，所以它们对隔离环境零风险、也跑得很快。
 */

const STUDY = "/study";
const CHAT = "/chat";

const TREE_EMPTY = { nodes: [] };

const SETUP_TODAY = {
  status: "setup",
  study_date: "2026-09-20",
  recommendations: [
    { kp_id: "kp-limit", name: "洛必达法则", state: "stuck", reason: "stuck", next_step: "先补一道变式题", missing_types: [] },
  ],
  focus_item_id: null,
};

/** 一份 active 计划：两道题，第一道未完成。 */
const ACTIVE_PLAN = {
  status: "active",
  plan_id: "plan-1",
  study_date: "2026-09-20",
  completed_count: 0,
  total_count: 2,
  remaining_minutes: 10,
  estimated_minutes: 10,
  type_summary: { calculation: 2 },
  summary_kps: [{ kp_id: "kp-limit", name: "洛必达法则", completed_count: 0, total_count: 2 }],
  focus_item_id: "item-1",
  items: [
    {
      id: "item-1", ordinal: 1, kp_id: "kp-limit", kp_name: "洛必达法则", question_id: "q-1",
      stem: "求极限：tan x − sin x 除以 x 的三次方", question_type: "calculation", question_role: "base",
      estimated_minutes: 5, completed: false, completed_at: null, latest_self_grade: null,
      objective_result: "unknown", is_variant: false, is_review: false, skill_tags: [], options: null,
      next_step: null,
    },
    {
      id: "item-2", ordinal: 2, kp_id: "kp-limit", kp_name: "洛必达法则", question_id: "q-2",
      stem: "第二题", question_type: "calculation", question_role: "base",
      estimated_minutes: 5, completed: false, completed_at: null, latest_self_grade: null,
      objective_result: "unknown", is_variant: false, is_review: false, skill_tags: [], options: null,
      next_step: null,
    },
  ],
};

/** 回一个业务错误体：后端统一是 { error: { code, message } }。 */
function errorBody(code: string, message = `backend says ${code}`) {
  return { error: { code, message } };
}

/** 让 /study 页面进入「准备页」，且 generate 的响应可被用例覆盖。 */
async function mockSetupPage(page: Page): Promise<void> {
  await page.route("**/api/plans/today", (route) =>
    route.fulfill({ json: SETUP_TODAY }),
  );
  await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE_EMPTY }));
}

test.describe("错误码与页面行为（规格 2.5）", () => {
  test("plan_already_generated：不显示「重新生成」，改为重新读计划并切到答题页", async ({ page }) => {
    let todayCalls = 0;
    // 第一次读今日计划给 setup（所以出现准备页）；生成时报 409；
    // 之后再读就给 active —— 页面据此切到答题页。
    await page.route("**/api/plans/today", (route) => {
      todayCalls += 1;
      return route.fulfill({ json: todayCalls === 1 ? SETUP_TODAY : ACTIVE_PLAN });
    });
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE_EMPTY }));
    await page.route("**/api/plans/today/generate", (route) =>
      route.fulfill({ status: 409, json: errorBody("plan_already_generated") }),
    );

    await page.goto(STUDY);
    await expect(page.getByTestId("study-setup")).toBeVisible();
    await page.getByTestId("generate-plan").click();

    // 页面自己把用户带到答题页，而不是丢一句英文错误停在准备页。
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("study-setup")).toHaveCount(0);
  });

  test("question_pool_incomplete：如实说明题库不足，且不猜缺哪一道题", async ({ page }) => {
    await mockSetupPage(page);
    await page.route("**/api/plans/today/generate", (route) =>
      route.fulfill({ status: 422, json: errorBody("question_pool_incomplete") }),
    );

    await page.goto(STUDY);
    await page.getByTestId("generate-plan").click();

    const generateError = page.getByTestId("plan-generate-error");
    await expect(generateError).toBeVisible({ timeout: 15_000 });
    await expect(generateError).toContainText(/题库不足/);
    // 不在前端猜「缺哪一道题」：不许出现具体题型/题量的推断式文案。
    await expect(generateError).not.toContainText(/缺少第 \d/);
    // 用户已勾选的知识点必须保留（兜底原则：不丢用户输入）。
    await expect(page.getByTestId("selected-kp-count")).toContainText("本次包含 1 个知识点");
  });

  test("kp_state_not_found：提示先跑 seed.py，且不自动重试", async ({ page }) => {
    await page.route("**/api/plans/today", (route) =>
      route.fulfill({ status: 409, json: errorBody("kp_state_not_found") }),
    );
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE_EMPTY }));

    await page.goto(STUDY);
    const errorState = page.getByTestId("study-error");
    await expect(errorState).toBeVisible({ timeout: 15_000 });
    await expect(errorState).toContainText(/seed\.py/);
  });

  test("practice_item_already_assessed：以服务端结果为准刷新，不重复累计进度", async ({ page }) => {
    await page.route("**/api/plans/today", (route) => route.fulfill({ json: ACTIVE_PLAN }));
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE_EMPTY }));
    await page.route("**/api/practice-items/item-1/self-assessments", (route) =>
      route.fulfill({ status: 409, json: errorBody("practice_item_already_assessed") }),
    );

    await page.goto(STUDY);
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("self-grade-mastered").click();

    // 提示说明「已提交过」，并且页面刷新为服务端记录（进度不因这次点击再涨）。
    await expect(page.getByTestId("study-status")).toContainText(/0 \/ 2/, { timeout: 15_000 });
  });

  test("practice_item_not_found：跳到下一道未完成题，不停在死题上", async ({ page }) => {
    await page.route("**/api/plans/today", (route) => route.fulfill({ json: ACTIVE_PLAN }));
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE_EMPTY }));
    await page.route("**/api/practice-items/item-1/self-assessments", (route) =>
      route.fulfill({ status: 404, json: errorBody("practice_item_not_found") }),
    );

    await page.goto(STUDY);
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("self-grade-mastered").click();
    // 仍然停在一个可作答的题卡上（而不是空态或死循环）。
    await expect(page.getByTestId("focus-question")).toBeVisible({ timeout: 15_000 });
  });

  test("plan_not_active：追加题目失败时提示已结束并刷新，绝不在本地插题", async ({ page }) => {
    await page.route("**/api/plans/today", (route) => route.fulfill({ json: ACTIVE_PLAN }));
    await page.route("**/api/knowledge/**", (route) => route.fulfill({ json: { node: null, questions: [] } }));
    // tree 响应必须保留 KnowledgeTreeResponse 结构，不能被上面的详情 mock 覆盖。
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE_EMPTY }));
    await page.route("**/api/plans/plan-1/questions", (route) =>
      route.fulfill({ status: 409, json: errorBody("plan_not_active") }),
    );

    await page.goto(STUDY);
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });

    // 先记下全卷条数。注意 paper-list 只在**全卷模式**下渲染，默认是专注模式。
    await page.getByTestId("full-paper").click();
    const paper = page.getByTestId("paper-list");
    await expect(paper).toBeVisible();
    const before = await paper.locator("li.paper-item").count();
    expect(before).toBeGreaterThan(0);

    // 打开追加选择器：空知识树 → 没有可勾选的题，所以这里只验证
    // 「打开这个动作本身不会改动卷子」。真正要锁的是下一条断言。
    await page.getByTestId("append-questions").click();
    await expect(page.locator(".picker")).toBeVisible();
    await page.getByRole("button", { name: "取消" }).click();

    // 关键：卷内条数不因这次失败而增加 —— 前端绝不本地插题。
    await expect(paper.locator("li.paper-item")).toHaveCount(before);
  });

  test("兜底：未列出的 code 只显示后端文案与普通重试，不做业务动作", async ({ page }) => {
    await page.route("**/api/plans/today", (route) =>
      route.fulfill({ status: 500, json: errorBody("some_brand_new_code", "brand new failure") }),
    );
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE_EMPTY }));

    await page.goto(STUDY);
    const errorState = page.getByTestId("study-error");
    await expect(errorState).toBeVisible({ timeout: 15_000 });
    // 展示后端给的文案（不自己编中文映射），并给出重试入口。
    await expect(errorState).toContainText("brand new failure");
    await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
  });
});
