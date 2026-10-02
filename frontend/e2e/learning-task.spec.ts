import { test, expect } from "./fixtures";

const id = "11111111-1111-4111-8111-111111111111";
const view = (status = "created") => ({ task_id: id, session_id: null, goal: "洛必达比较弱", budget_minutes: 90,
  status, trace: [], draft: null, message: "", error_code: null, metrics: {} });
const ready = () => ({ ...view("ready"), message: "没有近期作答，先做基础题。", trace: [{ tool: "find_questions", status: "completed" }],
  draft_version: "a".repeat(64),
  draft: { total_minutes: 3, budget_minutes: 90, can_commit: true, review_minutes: 0, review_nodes: [],
    questions: [{ question_id: "q1", stem: "检验洛必达适用条件", minutes: 3 }], rationale: "先检查适用条件", warnings: [] } });

async function builtin(page: any, navigate = true) {
  if (navigate) await page.goto("/chat");
  await expect(page.getByTestId("scope-switch")).toBeEnabled();
  if ((await page.getByTestId("chat-source").textContent())?.includes("我的资料")) {
    await page.getByTestId("scope-switch").click();
  }
  await expect(page.getByTestId("learning-task-panel")).toBeVisible();
}

test("确认草案后显示已加入，编辑目标时禁止确认旧草案", async ({ page }) => {
  let current: any = view();
  let confirms = 0;
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}/run`, route => { current = ready(); return route.fulfill({ json: current }); });
  await page.route(`**/api/learning-tasks/${id}/confirm`, route => {
    expect(route.request().postDataJSON().draft_version).toBe("a".repeat(64));
    confirms++;
    current = { ...current, metrics: { commit: { plan_id: id, added_count: 1 } }, message: "已将 1 道题加入今日学习" };
    return route.fulfill({ json: current });
  });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-confirm")).toBeEnabled();
  await page.getByTestId("task-goal").fill("只做填空题");
  await expect(page.getByTestId("task-confirm")).toBeDisabled();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-confirm").click();
  await expect(page.getByTestId("task-result")).toContainText("题目已加入今日学习");
  await expect(page.getByTestId("task-confirm")).toHaveCount(0);
  await expect(page.getByTestId("task-cancel")).toHaveCount(0);
  expect(confirms).toBe(1);
  await page.getByRole("button", { name: "去做题", exact: true }).click();
  await expect(page).toHaveURL(/\/study$/);
});

test("学习安排仅在内置模式出现，默认收起", async ({ page }) => {
  await builtin(page);
  await expect(page.getByTestId("task-goal")).not.toBeVisible();
  await page.getByTestId("scope-switch").click();
  await expect(page.getByTestId("learning-task-panel")).toHaveCount(0);
});

test("草案显示步骤与时长，刷新后切回内置范围可恢复且不写今日卷", async ({ page }) => {
  let planWrites = 0;
  let current = view();
  await page.route("**/api/plans/**", async route => {
    if (route.request().method() === "POST") planWrites++;
    await route.continue();
  });
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}/run`, route => { current = ready() as any; return route.fulfill({ json: current }); });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-result")).toContainText("预计 3 / 90 分钟");
  await expect(page.getByTestId("task-result")).toContainText("查找真实题目 · 完成");
  await expect(page.getByTestId("task-result")).toContainText("尚未加入今日学习");
  await page.reload();
  await builtin(page, false);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await expect(page.getByTestId("task-result")).toContainText("检验洛必达适用条件");
  expect(planWrites).toBe(0);
});

test("运行失败保留目标，可修改预算后重试", async ({ page }) => {
  let current = view();
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => {
    if (route.request().method() === "PATCH") current = { ...view(), ...route.request().postDataJSON() };
    return route.fulfill({ json: current });
  });
  await page.route(`**/api/learning-tasks/${id}/run`, route => {
    current = { ...current, status: "failed", message: "安排未完成，可重试。" };
    return route.fulfill({ json: current });
  });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-result")).toContainText("本次未完成");
  await expect(page.getByTestId("task-goal")).toHaveValue("洛必达比较弱");
  await page.getByTestId("task-budget").fill("20");
  await page.getByTestId("task-arrange").click();
  expect(current.budget_minutes).toBe(20);
});

test("取消后迟到的运行响应不能覆盖取消状态", async ({ page }) => {
  let release: (() => void) | undefined;
  const blocked = new Promise<void>(resolve => { release = resolve; });
  let current = view();
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}/run`, async route => {
    current = view("running"); await blocked; await route.fulfill({ json: ready() });
  });
  await page.route(`**/api/learning-tasks/${id}/cancel`, route => {
    current = { ...view("cancelled"), message: "已取消，没有写入今日学习。" }; return route.fulfill({ json: current });
  });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-cancel")).toBeVisible();
  await page.getByTestId("task-cancel").click();
  await expect(page.getByTestId("task-result")).toContainText("已取消");
  release?.();
  await expect(page.getByTestId("task-arrange")).toBeEnabled();
  await expect(page.getByTestId("task-result")).not.toContainText("草案已校验");
});

test("运行响应丢失后读取已保存草案，不重复调用模型；刷新保留未保存目标", async ({ page }) => {
  let current: any = view();
  let runs = 0;
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}/run`, route => {
    runs++; current = ready(); return route.abort("failed");
  });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-confirm")).toBeEnabled();
  await page.getByTestId("task-goal").fill("只做填空题");
  await page.getByTestId("task-budget").fill("20");
  await page.getByTestId("task-refresh").click();
  await expect(page.getByTestId("task-refresh")).toBeEnabled();
  await expect(page.getByTestId("task-goal")).toHaveValue("只做填空题");
  await expect(page.getByTestId("task-budget")).toHaveValue("20");
  await expect(page.getByTestId("task-confirm")).toBeDisabled();
  expect(runs).toBe(1);
});

test("确认响应丢失后恢复提交回执，不重复加题", async ({ page }) => {
  let current: any = view();
  let confirms = 0;
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}/run`, route => { current = ready(); return route.fulfill({ json: current }); });
  await page.route(`**/api/learning-tasks/${id}/confirm`, route => {
    confirms++; current = { ...ready(), metrics: { commit: { plan_id: id, added_count: 1 } } };
    return route.abort("failed");
  });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-confirm")).toBeEnabled();
  await page.getByTestId("task-confirm").click();
  await expect(page.getByTestId("task-result")).toContainText("题目已加入今日学习");
  await expect(page.getByTestId("task-confirm")).toHaveCount(0);
  expect(confirms).toBe(1);
});

test("轮询连续失败后停止，用户可手动只读恢复", async ({ page }) => {
  let current: any = view();
  let failReads = true;
  let failures = 0;
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => {
    if (failReads) { failures++; return route.abort("failed"); }
    return route.fulfill({ json: current });
  });
  await page.route(`**/api/learning-tasks/${id}/run`, route => {
    current = view("running"); return route.abort("failed");
  });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByRole("alert")).toContainText("任务状态暂时无法读取");
  // Recovery GET itself failed: explicit refresh reconnects and resumes bounded polling.
  failReads = false;
  await page.getByTestId("task-refresh").click();
  await expect(page.getByTestId("task-result")).toContainText("正在安排");
  failReads = true;
  await expect(page.getByRole("alert")).toContainText("暂时无法读取进度", { timeout: 10000 });
  expect(failures).toBe(4);
  failReads = false; current = ready();
  await page.getByTestId("task-refresh").click();
  await expect(page.getByTestId("task-confirm")).toBeEnabled();
});

test("页面恢复任务首次读取失败，仍可刷新找到原草案", async ({ page }) => {
  let current: any = view();
  let fail = false;
  let runs = 0;
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, route => fail ? route.abort("failed") : route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}/run`, route => { runs++; current = ready(); return route.fulfill({ json: current }); });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-confirm")).toBeEnabled();
  fail = true;
  await page.reload(); await builtin(page, false);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await expect(page.getByRole("alert")).toContainText("上次学习任务暂时无法读取");
  fail = false;
  await page.getByTestId("task-refresh").click();
  await expect(page.getByTestId("task-confirm")).toBeEnabled();
  expect(runs).toBe(1);
});

test("慢进度请求串行读取，不重叠或覆盖最终草案", async ({ page }) => {
  let current: any = view();
  let reads = 0, inflight = 0, maximum = 0;
  await page.route("**/api/learning-tasks", route => route.fulfill({ json: current }));
  await page.route(`**/api/learning-tasks/${id}`, async route => {
    reads++; inflight++; maximum = Math.max(maximum, inflight);
    try {
      if (reads > 1) await new Promise(resolve => setTimeout(resolve, 2000));
      if (reads >= 3) current = ready();
      await route.fulfill({ json: current });
    } finally { inflight--; }
  });
  await page.route(`**/api/learning-tasks/${id}/run`, route => {
    current = view("running"); return route.abort("failed");
  });
  await builtin(page);
  await page.getByTestId("learning-task-panel").locator("summary").click();
  await page.getByTestId("task-goal").fill("洛必达比较弱");
  await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("task-confirm")).toBeEnabled({ timeout: 15000 });
  expect(maximum).toBe(1);
  expect(reads).toBe(3);
});
