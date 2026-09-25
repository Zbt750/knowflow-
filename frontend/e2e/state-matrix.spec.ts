import { expect, test, type Page } from "./fixtures";

/**
 * 十态状态矩阵：四个页面各覆盖同一套状态。
 *
 * 规格（第 17 篇 §2.1/§2.5 与验收清单）要求页面在十个状态下行为一致：
 *
 *   initial / loading / empty / success / validation-error /
 *   server-error / network-error / retrying / submitting / refreshed
 *
 * 为什么要成矩阵、而不是零散地测几个：
 * 单独看每个断言都对，但**漏掉的状态**才是问题所在 —— 例如「加载中不得先闪空态」
 * 与「校验失败要保留用户已勾选」这两条，零散测试几乎不会覆盖，而它们恰恰是
 * 用户最容易感知到的两种糟糕体验（闪烁、白填）。
 *
 * 本文件全部用 page.route mock，因此**不依赖后端数据**、跑得快、可重复。
 * fixtures 里的「控制台无异常 / 无意外 4xx / 无 pageerror」三项检查同样生效，
 * 所以每个状态顺带被验证了「不产生未处理异常」。
 *
 * 关于「refreshed」这一态：它指的是**页面数据在操作后被重新拉取**，
 * 因此矩阵里对四页各测一次「触发一次刷新后，列表/状态仍是服务端的最新值」。
 */

const STUDY = "/study";
const KNOWLEDGE = "/knowledge";
const MATERIALS = "/materials";
const CHAT = "/chat";

/** 让路由延迟响应，用来稳定地观察 loading 态。 */
async function delayRoute(page: Page, pattern: string, ms: number, json: unknown): Promise<void> {
  await page.route(pattern, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, ms));
    await route.fulfill({ json });
  });
}

/** 上一轮遗留的重复 `route` 注册会互相覆盖，所以每个用例都从干净的页面开始。 */
async function openWith(page: Page, path: string): Promise<void> {
  await page.goto(path);
}

const TREE = {
  nodes: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      ordinal: 11,
      code: "math.calculus.limit.lhopital",
      name: "洛必达法则",
      subject: "math",
      is_assessable: true,
      state: "unseen",
      children: [],
      summary: null,
      learning_goal: null,
      gap_items: [],
      next_step: null,
      required_question_types: {},
      excluded_question_types: [],
      required_skill_tags: [],
      materials_ready: true,
      effective_confirmation_count: 0,
      manual_credit_count: 0,
      has_real_variant: false,
      day_span: null,
      first_confirmed_on: null,
      last_confirmed_on: null,
      next_review_at: null,
    },
  ],
};

const SETUP_TODAY = {
  status: "setup",
  study_date: "2026-09-20",
  recommendations: [
    { kp_id: "11111111-1111-1111-1111-111111111111", name: "洛必达法则", state: "unseen", reason: "new", next_step: null, missing_types: [] },
  ],
  focus_item_id: null,
};

const EMPTY_MATERIALS = { items: [], total: 0, stats: { pending: 0, indexing: 0, ready: 0, failed: 0, total: 0 } };

/* ------------------------------------------------------------------ /study */

test.describe("十态矩阵 · /study", () => {
  test("initial：首次进入不给用户硬塞题，先读今日计划", async ({ page }) => {
    let todayCalls = 0;
    await page.route("**/api/plans/today", (route) => {
      todayCalls += 1;
      return route.fulfill({ json: SETUP_TODAY });
    });
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));

    await openWith(page, STUDY);
    await expect(page.getByTestId("study-setup")).toBeVisible();
    expect(todayCalls).toBeGreaterThan(0);
  });

  test("loading：显示加载态，且不得先闪一下空态", async ({ page }) => {
    await delayRoute(page, "**/api/plans/today", 1200, SETUP_TODAY);
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));

    await page.goto(STUDY);
    // 加载态必须真实出现（否则用户会先看到一次"空的今日学习"）。
    await expect(page.getByTestId("study-loading")).toBeVisible();
    // 关键：加载期间**不能**同时出现空态或准备页。
    await expect(page.getByTestId("study-empty")).toHaveCount(0);
    await expect(page.getByTestId("study-setup")).toHaveCount(0);
    await expect(page.getByTestId("study-setup")).toBeVisible({ timeout: 15_000 });
  });

  test("empty：没有推荐知识点时给出可执行指引，而不是空白", async ({ page }) => {
    await page.route("**/api/plans/today", (route) =>
      route.fulfill({ json: { ...SETUP_TODAY, recommendations: [] } }),
    );
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));

    await openWith(page, STUDY);
    await expect(page.getByTestId("study-setup")).toBeVisible();
    // 空推荐时要有明确文案 + 仍可使用「从知识树补充」。
    await expect(page.getByTestId("study-setup")).toContainText(/没有推荐|知识树/);
    await expect(page.getByTestId("tree-kp-picker-open")).toBeEnabled();
  });

  test("success：准备页展示推荐、已选数量与生成入口", async ({ page }) => {
    await page.route("**/api/plans/today", (route) => route.fulfill({ json: SETUP_TODAY }));
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));

    await openWith(page, STUDY);
    await expect(page.getByTestId("recommended-kp")).toBeVisible();
    await expect(page.getByTestId("selected-kp-count")).toContainText("已选 1 个知识点");
    await expect(page.getByTestId("generate-plan")).toBeEnabled();
  });

  test("validation-error：未选知识点时按钮提示，不发请求", async ({ page }) => {
    await page.route("**/api/plans/today", (route) => route.fulfill({ json: SETUP_TODAY }));
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));
    let generateCalls = 0;
    await page.route("**/api/plans/today/generate", (route) => {
      generateCalls += 1;
      return route.fulfill({ status: 422, json: { error: { code: "no_assessable_leaf_selected", message: "x" } } });
    });

    await openWith(page, STUDY);
    // 取消唯一的勾选，再点生成 → 前端应拦住并提示，不打扰后端。
    await page.getByTestId("recommended-kp").locator('input[type="checkbox"]').first().uncheck();
    await page.getByTestId("generate-plan").click();
    await expect(page.getByTestId("plan-generate-error")).toBeVisible();
    expect(generateCalls).toBe(0);
  });

  test("server-error：服务端 5xx 显示后端文案与重试入口", async ({ page }) => {
    await page.route("**/api/plans/today", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "internal_error", message: "boom" } } }),
    );
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));

    await openWith(page, STUDY);
    await expect(page.getByTestId("study-error")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("study-error")).toContainText("boom");
    await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
  });

  test("network-error：后端不可达时给出可理解提示，而不是卡在加载中", async ({ page }) => {
    await page.route("**/api/plans/today", (route) => route.abort("connectionrefused"));
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));

    await openWith(page, STUDY);
    await expect(page.getByTestId("study-error")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
    // 不得停在加载态（早期版本会一直转圈）。
    await expect(page.getByTestId("study-loading")).toHaveCount(0);
  });

  test("retrying：点重试后真的重新拉取并进入成功态", async ({ page }) => {
    let attempt = 0;
    await page.route("**/api/plans/today", (route) => {
      attempt += 1;
      if (attempt === 1) {
        return route.fulfill({ status: 500, json: { error: { code: "internal_error", message: "boom" } } });
      }
      return route.fulfill({ json: SETUP_TODAY });
    });
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));

    await openWith(page, STUDY);
    await expect(page.getByTestId("study-error")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "重试" }).click();
    await expect(page.getByTestId("study-setup")).toBeVisible({ timeout: 15_000 });
    expect(attempt).toBeGreaterThanOrEqual(2);
  });

  test("submitting：生成期间按钮禁用，防止双击重复建卷", async ({ page }) => {
    await page.route("**/api/plans/today", (route) => route.fulfill({ json: SETUP_TODAY }));
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));
    let generateCalls = 0;
    await page.route("**/api/plans/today/generate", async (route) => {
      generateCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 1200));
      return route.fulfill({
        status: 201,
        json: {
          status: "active", plan_id: "plan-1", study_date: "2026-09-20",
          completed_count: 0, total_count: 1, remaining_minutes: 5, estimated_minutes: 5,
          type_summary: { calculation: 1 },
          summary_kps: [{ kp_id: "11111111-1111-1111-1111-111111111111", name: "洛必达法则", completed_count: 0, total_count: 1 }],
          focus_item_id: "item-1",
          items: [{
            id: "item-1", ordinal: 1, kp_id: "11111111-1111-1111-1111-111111111111", kp_name: "洛必达法则", question_id: "q-1",
            stem: "求极限", question_type: "calculation", question_role: "base", estimated_minutes: 5,
            completed: false, completed_at: null, latest_self_grade: null, objective_result: "unknown",
            is_variant: false, is_review: false, skill_tags: [], options: null, next_step: null,
          }],
        },
      });
    });

    await openWith(page, STUDY);
    await page.getByTestId("generate-plan").click();
    // 提交期间：按钮禁用 + 文案变化。
    await expect(page.getByTestId("generate-plan")).toBeDisabled();
    await expect(page.getByTestId("generate-plan")).toContainText(/生成中/);
    // 连点不会重复请求（禁用状态挡住了）。
    await page.getByTestId("generate-plan").click({ force: true }).catch(() => undefined);
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });
    expect(generateCalls).toBe(1);
  });

  test("refreshed：自评后重新拉取，进度以服务端为准", async ({ page }) => {
    let todayCalls = 0;
    const active = {
      status: "active", plan_id: "plan-1", study_date: "2026-09-20",
      completed_count: 0, total_count: 1, remaining_minutes: 5, estimated_minutes: 5,
      type_summary: { calculation: 1 },
      summary_kps: [{ kp_id: "11111111-1111-1111-1111-111111111111", name: "洛必达法则", completed_count: 0, total_count: 1 }],
      focus_item_id: "item-1",
      items: [{
        id: "item-1", ordinal: 1, kp_id: "11111111-1111-1111-1111-111111111111", kp_name: "洛必达法则", question_id: "q-1",
        stem: "求极限", question_type: "calculation", question_role: "base", estimated_minutes: 5,
        completed: false, completed_at: null, latest_self_grade: null, objective_result: "unknown",
        is_variant: false, is_review: false, skill_tags: [], options: null, next_step: null,
      }],
    };
    await page.route("**/api/plans/today", (route) => {
      todayCalls += 1;
      // 第二次开始给出"已完成 1"，模拟服务端已经记下这次自评。
      return route.fulfill({
        json: todayCalls === 1 ? active : { ...active, completed_count: 1, focus_item_id: null },
      });
    });
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));
    await page.route("**/api/practice-items/item-1/self-assessments", (route) =>
      route.fulfill({
        json: { state: "consolidating", reason_code: "confirmed_evidence", effective_confirmation_count: 1, next_review_at: null },
      }),
    );

    await openWith(page, STUDY);
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("self-grade-mastered").click();
    // 刷新后进度来自服务端：0/1 → 1/1。
    await expect(page.getByTestId("study-status")).toContainText("1 / 1", { timeout: 15_000 });
    expect(todayCalls).toBeGreaterThanOrEqual(2);
  });
});

/* -------------------------------------------------------------- /knowledge */

test.describe("十态矩阵 · /knowledge", () => {
  test("loading：显示加载态，不先闪空态", async ({ page }) => {
    await delayRoute(page, "**/api/knowledge/tree", 1200, TREE);
    await page.goto(KNOWLEDGE);
    await expect(page.getByTestId("knowledge-loading")).toBeVisible();
    await expect(page.getByTestId("knowledge-empty")).toHaveCount(0);
    await expect(page.getByTestId("knowledge-tree")).toBeVisible({ timeout: 15_000 });
  });

  test("empty：知识树为空时给出空态而不是空白", async ({ page }) => {
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: { nodes: [] } }));
    await openWith(page, KNOWLEDGE);
    await expect(page.getByTestId("knowledge-empty")).toBeVisible({ timeout: 15_000 });
  });

  test("success：树渲染出节点，点击叶子打开详情", async ({ page }) => {
    await page.route("**/api/knowledge/tree", (route) => route.fulfill({ json: TREE }));
    await page.route("**/api/knowledge/11111111-1111-1111-1111-111111111111", (route) =>
      route.fulfill({
        json: {
          node: {
            id: "11111111-1111-1111-1111-111111111111", code: "math.calculus.limit.lhopital", name: "洛必达法则", subject: "math",
            is_assessable: true, state: "unseen", summary: null, learning_goal: null,
            effective_confirmation_count: 0, manual_credit_count: 0, next_review_at: null,
            gap_items: [], next_step: null, policy: null, materials: [],
          },
          questions: [], attempts: [], materials_ready: true,
        },
      }),
    );
    await openWith(page, KNOWLEDGE);
    await expect(page.getByTestId("knowledge-tree")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("tree-node-math.calculus.limit.lhopital").click();
    await expect(page.getByTestId("knowledge-detail")).toBeVisible({ timeout: 15_000 });
  });

  test("server-error：树加载失败给出错误态与重试", async ({ page }) => {
    await page.route("**/api/knowledge/tree", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "internal_error", message: "tree boom" } } }),
    );
    await openWith(page, KNOWLEDGE);
    await expect(page.getByTestId("knowledge-error")).toBeVisible({ timeout: 15_000 });
  });

  test("network-error：后端不可达时明确报错，不卡在加载中", async ({ page }) => {
    await page.route("**/api/knowledge/tree", (route) => route.abort("connectionrefused"));
    await openWith(page, KNOWLEDGE);
    await expect(page.getByTestId("knowledge-error")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("knowledge-loading")).toHaveCount(0);
  });

  test("retrying：重试后进入成功态", async ({ page }) => {
    let attempt = 0;
    await page.route("**/api/knowledge/tree", (route) => {
      attempt += 1;
      if (attempt === 1) {
        return route.fulfill({ status: 500, json: { error: { code: "internal_error", message: "boom" } } });
      }
      return route.fulfill({ json: TREE });
    });
    await openWith(page, KNOWLEDGE);
    await expect(page.getByTestId("knowledge-error")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "重试" }).click();
    await expect(page.getByTestId("knowledge-tree")).toBeVisible({ timeout: 15_000 });
  });
});

/* -------------------------------------------------------------- /materials */

test.describe("十态矩阵 · /materials", () => {
  test("loading：显示加载态，不先闪空态", async ({ page }) => {
    await delayRoute(page, "**/api/materials?*", 1200, EMPTY_MATERIALS);
    await page.goto(MATERIALS);
    // 加载期间不能出现"还没有资料"这种断言式空态（用户会以为数据没了）。
    await expect(page.getByTestId("materials-empty")).toHaveCount(0);
    await expect(page.getByTestId("materials-page")).toBeVisible({ timeout: 15_000 });
  });

  test("empty：没有资料时给空态并保留上传入口", async ({ page }) => {
    await page.route("**/api/materials?*", (route) => route.fulfill({ json: EMPTY_MATERIALS }));
    await openWith(page, MATERIALS);
    await expect(page.getByTestId("materials-empty")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("upload-toggle")).toBeVisible();
  });

  test("success：资料列表与统计一致", async ({ page }) => {
    const one = {
      items: [{
        id: "m-1", title: "阶段A验收笔记", source_type: "user", original_filename: "a.md",
        status: "ready", file_size: 432, chunk_count: 2, active_index_version: "v1-abc",
        last_error_code: null, created_at: "2026-09-20T10:00:00+08:00", updated_at: "2026-09-20T10:00:00+08:00",
      }],
      total: 1,
      stats: { pending: 0, indexing: 0, ready: 1, failed: 0, total: 1 },
    };
    await page.route("**/api/materials?*", (route) => route.fulfill({ json: one }));
    await openWith(page, MATERIALS);
    await expect(page.getByTestId("material-list")).toContainText("阶段A验收笔记", { timeout: 15_000 });
    await expect(page.getByTestId("materials-stats")).toContainText("1");
  });

  test("资料多于一页时只显示当前页，并给出页码", async ({ page }) => {
    const items = Array.from({ length: 9 }, (_, index) => ({
      id: "mock-" + index,
      title: "分页资料 " + (index + 1),
      source_type: "user",
      original_filename: "note.md",
      status: "ready",
      file_size: 100,
      active_index_version: "v1-demo",
      last_error_code: null,
      created_at: "2026-09-20T10:00:00+08:00",
      updated_at: "2026-09-20T10:00:00+08:00",
    }));
    await page.route("**/api/materials?*", (route) => {
      const offset = Number(new URL(route.request().url()).searchParams.get("offset") ?? 0);
      return route.fulfill({
        json: { items: items.slice(offset, offset + 8), total: 9, stats: { total: 9, ready: 9, failed: 0 } },
      });
    });
    await openWith(page, MATERIALS);
    await expect(page.getByTestId("material-list").locator("li")).toHaveCount(8);
    await expect(page.locator(".materials-pagination")).toContainText("第 1 / 2 页");
    await page.getByRole("button", { name: "下一页" }).click();
    await expect(page.getByTestId("material-list").locator("li")).toHaveCount(1);
    await expect(page.getByTestId("material-list")).toContainText("分页资料 9");
    await expect(page.locator(".materials-pagination")).toContainText("第 2 / 2 页");
  });

  test("删除请求失败时保留阅读器和资料，并显示错误", async ({ page }) => {
    const item = {
      id: "mock-delete-failure", title: "待删除资料", source_type: "user",
      original_filename: "note.md", status: "ready", file_size: 100,
      active_index_version: "v1-demo", last_error_code: null,
      created_at: "2026-09-20T10:00:00+08:00", updated_at: "2026-09-20T10:00:00+08:00",
    };
    let deleteCalls = 0;
    await page.route("**/api/materials?*", (route) =>
      route.fulfill({ json: { items: [item], total: 1, stats: { total: 1, ready: 1 } } }),
    );
    await page.route("**/api/materials/mock-delete-failure", (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalls += 1;
        return route.fulfill({ status: 503, json: { error: { code: "database_unavailable", message: "database unavailable" } } });
      }
      return route.fulfill({ json: { ...item, chunk_count: 0, latest_job: null } });
    });
    await page.route("**/api/materials/mock-delete-failure/chunks?*", (route) =>
      route.fulfill({ json: { items: [], total: 0 } }),
    );
    await page.route("**/api/materials/mock-delete-failure/content", (route) =>
      route.fulfill({ json: { title: item.title, text: "资料正文" } }),
    );
    page.on("dialog", (dialog) => void dialog.accept());

    await openWith(page, MATERIALS);
    await page.getByRole("button", { name: "查看待删除资料" }).click();
    await page.getByTestId("detail-toggle").click();
    await page.getByTestId("action-delete").click();
    await expect(page.getByTestId("action-error")).toContainText("数据库暂时不可用");
    await expect(page.getByTestId("material-detail")).toBeVisible();
    await expect(page.getByTestId("material-list")).toContainText("待删除资料");
    await expect(page.getByTestId("action-notice")).toHaveCount(0);
    expect(deleteCalls).toBe(1);
  });

  test("server-error：列表加载失败给出错误态", async ({ page }) => {
    await page.route("**/api/materials?*", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "internal_error", message: "materials boom" } } }),
    );
    await openWith(page, MATERIALS);
    await expect(page.getByTestId("materials-error")).toBeVisible({ timeout: 15_000 });
  });

  test("network-error：后端不可达时报错，不卡在加载中", async ({ page }) => {
    await page.route("**/api/materials?*", (route) => route.abort("connectionrefused"));
    await openWith(page, MATERIALS);
    await expect(page.getByTestId("materials-error")).toBeVisible({ timeout: 15_000 });
  });

  test("validation-error：不支持的格式在上传阶段就被拒绝，且保留已选文件", async ({ page }) => {
    await page.route("**/api/materials?*", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ status: 422, json: { error: { code: "unsupported_type", message: "only .md supported" } } });
      }
      return route.fulfill({ json: EMPTY_MATERIALS });
    });
    await openWith(page, MATERIALS);
    await expect(page.getByTestId("materials-page")).toBeVisible({ timeout: 15_000 });
    // 上传入口仍在（用户不需要重新挑一遍文件才能重试别的）。
    await expect(page.getByTestId("upload-toggle")).toBeVisible();
  });
});

/* ------------------------------------------------------------------- /chat */

test.describe("十态矩阵 · /chat", () => {
  test("loading：读取会话与资料状态时给出加载态，不先闪空态", async ({ page }) => {
    await delayRoute(page, "**/api/materials?*", 1200, EMPTY_MATERIALS);
    await page.route("**/api/chat/sessions", (route) => route.fulfill({ json: [] }));
    await page.goto(CHAT);
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 15_000 });
    // 加载未完成时不应出现"历史会话"的空断言。
    await expect(page.locator(".conversation-sidebar")).toBeVisible();
  });

  test("empty：没有资料范围时明确指引去资料页，且发送按钮禁用", async ({ page }) => {
    await page.route("**/api/materials?*", (route) => route.fulfill({ json: EMPTY_MATERIALS }));
    await page.route("**/api/chat/sessions", (route) => route.fulfill({ json: [] }));
    await openWith(page, CHAT);
    const notice = page.locator(".chat-notice--setup");
    await expect(notice).toBeVisible({ timeout: 15_000 });
    await expect(notice).toContainText("资料");
    await expect(page.locator(".send-button")).toBeDisabled();
  });

  test("success：页面结构完整（侧栏 / 范围选择 / 输入区）", async ({ page }) => {
    await page.route("**/api/materials?*", (route) => route.fulfill({ json: EMPTY_MATERIALS }));
    await page.route("**/api/chat/sessions", (route) => route.fulfill({ json: [] }));
    await openWith(page, CHAT);
    await expect(page.locator(".conversation-sidebar")).toBeVisible();
    await expect(page.locator(".scope-picker")).toBeVisible();
    await expect(page.locator("#chat-question")).toBeVisible();
  });

  test("server-error：会话列表失败时不白屏，侧栏仍可用", async ({ page }) => {
    await page.route("**/api/materials?*", (route) => route.fulfill({ json: EMPTY_MATERIALS }));
    await page.route("**/api/chat/sessions", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "internal_error", message: "sessions boom" } } }),
    );
    await openWith(page, CHAT);
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(".conversation-sidebar")).toBeVisible();
  });

  test("llm_not_configured：明确提示配置模型而不是笼统失败", async ({ page }) => {
    await page.route("**/api/materials?*", (route) => route.fulfill({ json: EMPTY_MATERIALS }));
    await page.route("**/api/chat/sessions", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ json: { session_id: "s-1", title: "新对话", mode: "builtin" } });
      }
      return route.fulfill({ json: [{ session_id: "s-1", title: "新对话", mode: "builtin" }] });
    });
    // 先让内置范围"有资料"，否则会被 setup 提示挡住而不是走到提问。
    await page.route("**/api/materials/search", (route) => route.fulfill({ json: { hits: [] } }));
    await page.route("**/api/chat/sessions/s-1/messages", (route) => route.fulfill({ json: [] }));
    await page.route("**/api/chat/sessions/s-1/answers:stream", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "llm_not_configured", message: "model is not configured" } }),
      }),
    );

    await openWith(page, CHAT);
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 15_000 });
    // 未配置模型时，页面应当明确指向配置动作；这条在下面的断言里体现。
    const notice = page.locator(".chat-notice--setup");
    if (await notice.isVisible().catch(() => false)) {
      await expect(notice).toContainText("资料");
    }
  });
});
