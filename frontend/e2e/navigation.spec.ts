import { expect, expectSystemStatus, revealLeaf, test } from "./fixtures";

async function selectOnlyKnowledgePoint(page: import("@playwright/test").Page, code: string): Promise<void> {
  await page.getByTestId("tree-kp-picker-open").click();
  const picker = page.getByTestId("tree-kp-picker");
  // 搜索学科编码会展开匹配的祖先路径；节点数随知识库扩充而变化，不能写死数量。
  await page.getByTestId("scope-picker-search").fill("math");
  const target = picker.getByTestId("pick-node-" + code);
  await expect(target).toBeVisible();

  // 通过已选列表移除其它知识点（包括当前搜索结果之外的），只留下目标叶子。
  // 反向遍历，删除行不会让尚未处理的索引发生偏移。
  const selectedRows = picker.locator(".scope-selected-list li");
  const targetId = (await target.getAttribute("id"))?.replace("scope-leaf-", "");
  if (!targetId) throw new Error(`目标知识点没有稳定标识：${code}`);
  for (let index = (await selectedRows.count()) - 1; index >= 0; index -= 1) {
    const row = selectedRows.nth(index);
    if ((await row.getAttribute("data-testid")) === `scope-selected-${targetId}`) continue;
    await row.getByRole("button", { name: /从范围移出/ }).click();
  }
  if ((await target.getAttribute("aria-pressed")) !== "true") await target.click();
  await expect(page.getByTestId("selected-kp-count")).toContainText("本次包含 1 个知识点");
  await page.getByTestId("close-tree-kp-picker").click();
}

/**
 * 阶段 B 前端冒烟测试。
 *
 * 设计要点：
 * - 全部打真实后端与真实 PostgreSQL，不使用任何 mock 成功。
 * - 系统状态区域用 data-status 断言真实健康检查结果。
 * - 每个用例由夹具重置「今日练习卷」，因此互相独立、可重复运行。
 */

test.describe("阶段 A：外壳与连通性", () => {
  test("五个真实 Vue 路由都可打开，且系统状态真实反映后端连接", async ({ page }) => {
    await page.goto("/study");
    await expect(page.locator(".app-header > strong")).toHaveText("今日学习");
    await expect(page.locator(".workspace-main h1")).toHaveText("今日学习");
    await expect(page).toHaveTitle("今日学习 · 考研知识库");
    await expect(page.locator(".primary-nav a span").first()).toBeHidden();
    await expect(page.locator(".brand-mark")).toHaveCount(0);

    const sidebar = page.locator(".app-sidebar");
    const sidebarWidth = () => sidebar.evaluate((element) => Math.round(element.getBoundingClientRect().width));
    const iconLeft = await page.locator(".primary-nav a").first().evaluate((element) => element.getBoundingClientRect().left);
    const initialWidth = await sidebarWidth();
    const resizeHandle = page.getByRole("separator", { name: /调整侧栏宽度/ });
    await expect(resizeHandle).toBeVisible();
    const handleBox = await resizeHandle.boundingBox();
    if (!handleBox) throw new Error("侧栏宽度调整手柄不可用");
    const dragY = Math.min(220, Math.max(80, handleBox.y + 120));
    await page.mouse.move(handleBox.x + 4, dragY);
    await page.mouse.down();
    await page.mouse.move(handleBox.x + 44, dragY, { steps: 5 });
    await page.mouse.up();
    await expect.poll(sidebarWidth).toBeGreaterThan(initialWidth + 24);
    const resizedWidth = await sidebarWidth();
    const resizedIconLeft = await page.locator(".primary-nav a").first().evaluate((element) => element.getBoundingClientRect().left);
    expect(resizedIconLeft).toBe(iconLeft);

    await page.getByRole("button", { name: "收起导航栏" }).click();
    await expect.poll(sidebarWidth).toBeLessThan(100);
    const collapsedIconLeft = await page.locator(".primary-nav a").first().evaluate((element) => element.getBoundingClientRect().left);
    expect(collapsedIconLeft).toBe(iconLeft);
    await page.getByRole("button", { name: "展开导航栏" }).click();
    await expect.poll(sidebarWidth).toBe(resizedWidth);

    const status = await expectSystemStatus(page, "ready");
    await expect(status).toContainText("后端可用");

    await page.getByRole("link", { name: "知识树" }).click();
    await expect(page).toHaveURL(/\/knowledge$/);
    await expect(page.locator(".app-header > strong")).toHaveText("知识树");
    await expect(page.locator(".workspace-main h1")).toHaveText("知识树");
    await expect(page).toHaveTitle("知识树 · 考研知识库");

    await page.getByRole("link", { name: "资料" }).click();
    // 资料页进入时会**自动选中第一份资料**并把 material_id 同步进 URL
    // （这样刷新、深链接、浏览器前进后退都能恢复选择）。所以这里只断言
    // 路径是 /materials，允许带查询参数 —— 写死 `$` 会在资料页一旦有资料时误报。
    await expect(page).toHaveURL(/\/materials(\?.*)?$/);
    // 用 testid 而不是标题文本：标题会随文案调整，testid 是页面身份的稳定标识。
    await expect(page.getByTestId("materials-page")).toBeVisible();
    await expect(page.locator(".workspace-main h1")).toHaveText("资料库");
    await expect(page).toHaveTitle("资料库 · 考研知识库");

    await page.getByRole("link", { name: "问答" }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.locator(".app-header > strong")).toHaveText("问答");
    await expect(page.locator(".workspace-main h1")).toHaveText("问答");
    await expect(page).toHaveTitle("问答 · 考研知识库");
    await expect.poll(sidebarWidth).toBe(resizedWidth);
    await expect(page.getByTestId("scope-switch")).toBeVisible();
    await expect(page.getByRole("button", { name: "重新检查" })).toBeVisible();

    await page.getByRole("link", { name: "设置" }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.locator(".app-header > strong")).toHaveText("设置");
    await expect(page.locator(".workspace-main h1")).toHaveText("设置");
    await expect(page).toHaveTitle("设置 · 考研知识库");
    await expect(page.getByRole("heading", { name: "问答模型" })).toBeVisible();
  });

  test("健康检查返回 503 时显示明确错误与重试按钮", async ({ page }) => {
    // 本用例**故意**让 /api/health 返回 503：那是被测行为，不是事故。
    // 夹具的「无意外 4xx/5xx」与「控制台无 error」因此按 URL 豁免这一条 ——
    // 其余任何 4xx/5xx 仍然会被抓出来。
    // 拦截只发生在浏览器侧；后端仍是真实服务。
    await page.route("**/api/health", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "database_unavailable", message: "database unavailable" },
        }),
      });
    });

    await page.goto("/study");
    const status = await expectSystemStatus(page, "error");
    await expect(status).toContainText("database unavailable");
    await expect(status).toContainText("database_unavailable");

    const retry = page.getByRole("button", { name: "重新检查" });
    await expect(retry).toBeEnabled();
    await page.unroute("**/api/health");
    await retry.click();
    const recovered = await expectSystemStatus(page, "ready");
    await expect(recovered).toContainText("后端可用");
  });

  test("设置页区分数据库不可用与后端未启动，并可刷新恢复", async ({ page }) => {
    await page.route("**/api/health", (route) =>
      route.fulfill({ status: 503, json: { error: { code: "database_unavailable", message: "database unavailable" } } }),
    );
    await page.goto("/settings");
    await expect(page.locator(".settings-page [role='alert']")).toContainText("后端已启动，但数据库不可用");
    await page.unroute("**/api/health");
    await page.locator(".settings-page").getByRole("button", { name: "刷新状态" }).click();
    await expect(page.locator(".settings-page")).toContainText("已连接");
  });
});

test.describe("阶段 B：知识树页面", () => {
  test("父节点只汇总、叶子可查看题库与练习记录，且父节点没有整体自评按钮", async ({ page }) => {
    await page.goto("/knowledge");
    await expectSystemStatus(page, "ready");

    const tree = page.getByTestId("knowledge-tree");
    await expect(tree).toBeVisible();
    await expect(tree.locator(".tree-edges path").first()).toBeVisible();
    const treeBox = await tree.boundingBox();
    const detailBox = await page.locator(".detail").boundingBox();
    expect(treeBox && detailBox && treeBox.y < detailBox.y).toBeTruthy();

    // 未选中叶子时明确提示父节点不可考核。
    await expect(page.getByTestId("knowledge-empty")).toBeVisible();

    // 父节点有章节导读，但不提供考核。
    await page.getByTestId("tree-node-math.calculus").click();
    await expect(page.getByTestId("knowledge-parent-summary")).toBeVisible();
    await expect(page.getByTestId("node-assessment")).toHaveCount(0);
    await expect(page.getByTestId("knowledge-lesson-link")).toContainText("章节导读");
    await expect(tree).toContainText("已毕业");

    await revealLeaf(page, [
      "math.calculus",
      "math.calculus.limit",
      "math.calculus.limit.lhopital",
    ]);

    await expect(page.getByTestId("detail-title")).toHaveText("洛必达法则");
    await page.getByTestId("knowledge-advanced").locator("summary").click();
    await expect(page.getByTestId("effective-count")).toBeVisible();
    await expect(page.getByTestId("manual-credit")).toBeVisible();

    // 概览 Tab 才有整体自评按钮。
    await expect(page.getByTestId("node-assessment")).toBeVisible();
    await expect(page.getByTestId("node-self-mastered")).toBeEnabled();

    // 题库 Tab：能看到题干，且不显示答案。
    await page.getByTestId("tab-questions").click();
    const questions = page.getByTestId("question-bank");
    await expect(questions).toBeVisible();
    // 题库题数由该叶子的策略决定，不再是固定的 3 道；
    // 这里只要求「有足够的题且能看到变式题标记」。
    expect(await questions.locator("li.pool-item").count()).toBeGreaterThanOrEqual(3);
    await expect(questions).toContainText("求极限");
    await expect(questions).toContainText("变式题");
    // 题库面板不得泄露答案或解析。
    await expect(questions).not.toContainText("参考答案");
    await expect(questions).not.toContainText("解析：");

    // 练习记录 Tab 可以打开（可能为空）。
    await page.getByTestId("tab-attempts").click();
    await expect(page.getByTestId("attempt-history")).toBeVisible();

    // 关联资料不把未匹配内容伪装成关联资料。
    await page.getByTestId("tab-materials").click();
    await expect(page.getByTestId("panel-materials")).toBeVisible();
    await expect(page.getByTestId("panel-materials")).toContainText("暂不自动匹配");
  });

  test("节点讲解可阅读公式，并能返回节点或进入今日练习", async ({ page }) => {
    await page.goto("/knowledge");
    await revealLeaf(page, [
      "math.calculus",
      "math.calculus.limit",
      "math.calculus.limit.lhopital",
    ]);
    await page.getByTestId("knowledge-lesson-link").click();
    await expect(page).toHaveURL(/\/knowledge\/math\.calculus\.limit\.lhopital\/lesson$/);
    await expect(page.getByTestId("lesson-article")).toContainText("洛必达法则");
    await expect(page.getByTestId("lesson-article").locator(".katex").first()).toBeVisible();
    await page.getByRole("link", { name: /查看相关题目/ }).click();
    await expect(page.getByTestId("question-bank")).toBeVisible();
    await page.getByTestId("tab-overview").click();
    await page.getByTestId("knowledge-lesson-link").click();
    await page.getByRole("link", { name: "去今日学习选题" }).click();
    await expect(page).toHaveURL(/\/study\?kp_id=/);
    await expect(page.getByTestId("selected-kp-count")).toContainText("本次包含 1 个知识点");
  });

  test("叶子整体自评显示透明基础确认 +2，且不伪装成做过两题", async ({ page }) => {
    await page.goto("/knowledge");
    await revealLeaf(page, [
      "math.calculus",
      "math.calculus.differential",
      "math.calculus.differential.implicit",
    ]);

    await page.getByTestId("node-self-mastered").click();
    // 自评反馈是瞬时提示：后端返回后立即读取。
    const notice = page.getByTestId("node-notice");
    await expect(notice).toBeVisible({ timeout: 15_000 });
    // 必须明确显示基础确认 +2，绝不伪装成用户做过两题。
    await expect(notice).toContainText("基础确认 +2");
    await page.getByTestId("knowledge-advanced").locator("summary").click();
    await expect(page.getByTestId("manual-credit")).toHaveText("2");

    // 练习记录里绝不能出现两条伪造的作答。
    await page.getByTestId("tab-attempts").click();
    await expect(page.getByTestId("attempt-history")).toContainText("还没有练习记录");

    // 再点「我部分掌握」：基础确认清零，练习记录仍然为空。
    await page.getByTestId("tab-overview").click();
    await page.getByTestId("node-self-partial").click();
    await expect(page.getByTestId("node-notice")).toContainText("基础确认为 0", { timeout: 15_000 });
    await page.getByTestId("knowledge-advanced").locator("summary").click();
    await expect(page.getByTestId("manual-credit")).toHaveText("0");
    await page.getByTestId("tab-attempts").click();
    await expect(page.getByTestId("attempt-history")).toContainText("还没有练习记录");
  });
});

test.describe("阶段 B：今日学习主流程", () => {
  test("准备页、生成练习卷、专注模式、查看答案后自评、全卷回看", async ({ page }) => {
    await page.goto("/study");
    await expectSystemStatus(page, "ready");

    // 准备页：没有用户确认就不创建计划。
    const setup = page.getByTestId("study-setup");
    await expect(setup).toBeVisible();
    await expect(setup).toContainText("今天的练习");
    // 推荐范围默认已准备好，无须逐项勾选。
    await expect(setup.locator('input[type="checkbox"]')).toHaveCount(0);
    await expect(page.getByTestId("tree-kp-picker")).toHaveCount(0);
    const generate = page.getByTestId("generate-plan");
    await expect(generate).toBeEnabled();
    await generate.click();

    // 生成后进入答题态。
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("study-status")).toBeVisible();

    const generated = await (await page.request.get("/api/plans/today")).json();
    const ranks: Record<string, number> = { single_choice: 0, fill_blank: 1, calculation: 2, proof: 3, subjective: 4 };
    const order = generated.items.map((item: { question_type: string }) => ranks[item.question_type] ?? 99);
    expect(order).toEqual([...order].sort((a, b) => a - b));

    // 专注模式：一次一道未完成题。
    await page.getByTestId("mode-focus").click();
    const card = page.getByTestId("focus-question");
    const empty = page.getByTestId("focus-empty");
    if (await empty.isVisible().catch(() => false)) {
      // 今天的题已全部完成，属于合法终态。
      await expect(empty).toBeVisible();
      return;
    }

    await expect(card).toBeVisible();
    await expect(page.getByTestId("focus-question")).not.toBeEmpty();
    // 专注模式不得显示答案。
    await expect(page.getByTestId("focus-answer")).toHaveCount(0);

    // 做题前可以查看答案，且查看答案后自评仍可用。
    await page.getByTestId("answer-explanation").click();
    const answer = page.getByTestId("focus-answer");
    await expect(answer).toBeVisible();
    await expect(answer).toContainText("参考答案");
    await expect(answer).toContainText("解析");
    await expect(page.getByTestId("answer-explanation")).toHaveAttribute("aria-expanded", "true");
    await page.getByTestId("answer-explanation").click();
    await expect(answer).toHaveCount(0);
    await expect(page.getByTestId("answer-explanation")).toHaveText("查看答案详解");
    await page.getByTestId("answer-explanation").click();
    await expect(answer).toBeVisible();
    const focusStemBox = await page.getByTestId("focus-stem").boundingBox();
    const focusAnswerBox = await answer.boundingBox();
    expect(focusStemBox && focusAnswerBox && focusAnswerBox.x > focusStemBox.x + 100).toBeTruthy();
    await page.setViewportSize({ width: 375, height: 667 });
    const narrowFocusStemBox = await page.getByTestId("focus-stem").boundingBox();
    const narrowFocusAnswerBox = await answer.boundingBox();
    expect(narrowFocusStemBox && narrowFocusAnswerBox && narrowFocusAnswerBox.y > narrowFocusStemBox.y).toBeTruthy();
    await page.setViewportSize({ width: 1366, height: 768 });

    // 四种自评按钮都存在。
    for (const id of ["self-grade-mastered", "self-grade-partial", "self-grade-not-mastered", "self-grade-skip"]) {
      await expect(page.getByTestId(id)).toBeEnabled();
    }

    // 提交「已掌握」。提交成功后页面按设计跳到下一道未完成题，
    // 因此自评反馈要在全卷模式里回看（该题保留在卷内）。
    await page.getByTestId("self-grade-mastered").click();

    // 等自评**确实提交完成**再切视图。
    //
    // 为什么必须显式等：提交成功后前端会重新拉取今日学习（`load()`），
    // 而刷新期间页面**保留旧视图**（这正是为了避免整页闪回 loading 摘掉卷子）。
    // 于是「卷子可见」并不等于「卷子已刷新」——`paper-list` 会立刻可见，
    // 但里面的「已完成」标记要等新数据回来才出现。只断言可见就切视图，
    // 后续的文本断言就只能在默认 5 秒内赌刷新完成，机器一忙就偶发失败。
    // 这里用真实后端作为同步点：自评确实落库了，再往下走。
    await expect
      .poll(
        async () => {
          const plan = await (await page.request.get("/api/plans/today")).json();
          return plan.items.filter((item: { completed: boolean }) => item.completed).length;
        },
        { timeout: 30_000, message: "自评应当被后端真实记录" },
      )
      .toBeGreaterThan(0);

    await page.getByTestId("full-paper").click();
    const paper = page.getByTestId("paper-list");
    await expect(paper).toBeVisible({ timeout: 15_000 });
    await expect(paper).toContainText("已完成", { timeout: 15_000 });
    const firstPaperQuestion = paper.locator(".paper-item").first();
    const paperAnswerButton = firstPaperQuestion.getByRole("button", { name: "收起答案详解" });
    await expect(paperAnswerButton).toHaveAttribute("aria-expanded", "true");
    await paperAnswerButton.click();
    await expect(firstPaperQuestion.locator(".answer-box")).toHaveCount(0);
    await firstPaperQuestion.getByRole("button", { name: "查看答案详解" }).click();
    await expect(firstPaperQuestion.locator(".answer-box")).toBeVisible();
    const paperStemBox = await firstPaperQuestion.locator(".stem").boundingBox();
    const paperAnswerBox = await firstPaperQuestion.locator(".answer-box").boundingBox();
    expect(paperStemBox && paperAnswerBox && paperAnswerBox.x > paperStemBox.x + 100).toBeTruthy();
    await page.setViewportSize({ width: 375, height: 667 });
    const narrowStemBox = await firstPaperQuestion.locator(".stem").boundingBox();
    const narrowAnswerBox = await firstPaperQuestion.locator(".answer-box").boundingBox();
    expect(narrowStemBox && narrowAnswerBox && narrowAnswerBox.y > narrowStemBox.y).toBeTruthy();
    await page.setViewportSize({ width: 1366, height: 768 });
    await expect(paper).toContainText("已完成", { timeout: 15_000 });
    // 全卷里能看到变式题标签（毕业证据来源对用户透明）。
    await expect(paper).toContainText("变式题");
    // 自评反馈来自后端 reason_code 与有效确认数。
    const paperNotice = page.getByTestId("paper-notice").first();
    await expect(paperNotice).toBeVisible({ timeout: 15_000 });
    await expect(paperNotice).toContainText("已记录");

    // 今日知识点摘要显示实际涉及的知识点与完成数量。
    await expect(page.getByTestId("today-kp-summary")).toBeVisible();
    await expect(page.getByTestId("today-kp-summary")).toContainText("/");

    // 回到专注模式后，已完成的题不会再出现。
    await page.getByTestId("mode-focus").click();
    await expect(page.getByTestId("focus-question")).toBeVisible();
    await expect(page.getByTestId("focus-question").locator("header")).toContainText("未完成");
  });

  test("跳过切换到下一道未完成题，但不记录掌握度", async ({ page }) => {
    await page.goto("/study");
    await page.getByTestId("generate-plan").click();
    await expect(page.getByTestId("focus-question")).toBeVisible();
    const beforeStem = await page.getByTestId("focus-stem").innerText();
    await expect(page.getByTestId("self-grade-skip")).toHaveText("跳过");
    await page.getByTestId("self-grade-skip").click();
    await expect(page.getByTestId("focus-stem")).not.toHaveText(beforeStem);
    const plan = await (await page.request.get("/api/plans/today")).json();
    expect(plan.completed_count).toBe(0);
    await page.getByTestId("full-paper").click();
    await expect(page.getByTestId("paper-list").getByRole("button", { name: "跳过" }).first()).toBeVisible();
  });

  test("做完全部题后仍可追加练习，计划回到进行中", async ({ page }) => {
    await page.goto("/study");
    await expectSystemStatus(page, "ready");
    await expect(page.getByTestId("study-setup")).toBeVisible();

    // 只留一个知识点，让卷内题数可控。
    await selectOnlyKnowledgePoint(page, "math.calculus.limit.lhopital");
    await page.getByTestId("generate-plan").click();
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });

    // 做完卷内全部题目（题数由该叶子的毕业缺口决定）。
    await page.getByTestId("full-paper").click();
    const paperCount = await page.getByTestId("paper-list").locator("li.paper-item").count();
    await page.getByTestId("mode-focus").click();
    for (let index = 0; index < paperCount; index += 1) {
      await expect(page.getByTestId("focus-question")).toBeVisible({ timeout: 15_000 });
      // 先挂上等待，再点击：自评成功后前端一定会重新拉取今日学习（load()）。
      // 等这次刷新真的回来，而不是 sleep 一个猜出来的 400ms ——
      // 固定延时要么不够（机器慢时 flakes），要么白等（机器快时拖时间）。
      const refreshed = page.waitForResponse(
        (response) =>
          response.url().includes("/api/plans/today") && response.request().method() === "GET",
        { timeout: 15_000 },
      );
      await page.getByTestId("self-grade-mastered").click();
      await refreshed;
    }

    // 此时计划应为 completed，专注模式显示空态。
    await expect(page.getByTestId("study-status")).toContainText("今日已完成", { timeout: 15_000 });
    await expect(page.getByTestId("focus-empty")).toBeVisible();
    // 记下完成后的总数，追加后应恰好 +1。
    const beforeAppend = await page.getByTestId("paper-summary").innerText();
    const totalBefore = Number(beforeAppend.match(/共 (\d+) 道/)?.[1] ?? 0);
    expect(totalBefore).toBeGreaterThan(0);

    // 关键：这里以前会返回 409 plan_not_active，用户无法继续练习。
    await page.getByTestId("append-questions").click();
    const picker = page.getByTestId("question-picker");
    await expect(picker).toBeVisible();
    await picker.getByRole("searchbox", { name: "搜索知识点" }).fill("等比级数");
    await picker.getByRole("button", { name: "等比级数的敛散性与求和" }).click();
    const candidates = picker.locator('input[type="checkbox"]');
    await expect(candidates.first()).toBeVisible({ timeout: 15_000 });
    await candidates.first().check();
    await page.getByTestId("confirm-append").click();

    await expect(picker).toBeHidden({ timeout: 15_000 });
    // 计划回到进行中：新题加在卷尾，所以完成数不变、总数 +1。
    await expect(page.getByTestId("study-status")).toContainText("进行中", { timeout: 15_000 });
    await expect(page.getByTestId("paper-summary")).toContainText(`共 ${totalBefore + 1} 道`);
    await expect(page.getByTestId("focus-question")).toBeVisible();
  });

  test("追加练习题只能从已有题库选题并按题型展示", async ({ page }) => {
    await page.goto("/study");
    await expectSystemStatus(page, "ready");

    // 只保留一个知识点入卷，这样其他叶子的题库才有可追加的题。
    await expect(page.getByTestId("study-setup")).toBeVisible();
    await selectOnlyKnowledgePoint(page, "math.calculus.limit.lhopital");
    await page.getByTestId("generate-plan").click();
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });
    // 题数由该叶子的毕业缺口决定，先读出来再判断追加结果。
    await page.getByTestId("full-paper").click();
    const baseCount = await page.getByTestId("paper-list").locator("li.paper-item").count();
    expect(baseCount).toBeGreaterThan(0);
    await expect(page.getByTestId("study-status")).toContainText(`/ ${baseCount}`);

    await page.getByTestId("append-questions").click();
    const picker = page.getByTestId("question-picker");
    await expect(picker).toBeVisible();

    // 先用搜索定位，再从树中展开知识点，避免题目多时面对平铺长列表。
    const search = picker.getByRole("searchbox", { name: "搜索知识点" });
    await search.fill("不存在的知识点");
    await expect(picker.getByTestId("question-picker-empty")).toBeVisible();
    await search.fill("等比级数");
    await expect(picker.getByTestId("question-picker-tree")).toBeVisible();

    // 搜索会自动展开匹配路径，但父级仍必须可以手动收起和重新展开。
    const mathBranch = picker.getByRole("button", { name: "高等数学" });
    await expect(mathBranch).toHaveAttribute("aria-expanded", "true");
    await mathBranch.click();
    await expect(mathBranch).toHaveAttribute("aria-expanded", "false");
    await expect(picker.getByRole("button", { name: "等比级数的敛散性与求和" })).toHaveCount(0);
    await mathBranch.click();
    await expect(mathBranch).toHaveAttribute("aria-expanded", "true");

    // 选择另一个知识点，加载它的题库。
    const nodeToggle = picker.getByRole("button", { name: "等比级数的敛散性与求和" });
    const candidates = picker.locator('input[type="checkbox"]');
    await expect(nodeToggle).toBeVisible();

    // 请求失败时给出提示；再次展开重试成功后，旧错误应消失。
    await page.route("**/api/knowledge/*", (route) => route.abort());
    await nodeToggle.click();
    await expect(picker.locator(".form-error")).toContainText("无法连接后端服务");
    await page.unroute("**/api/knowledge/*");
    await nodeToggle.click();
    await expect(nodeToggle).toHaveAttribute("aria-expanded", "false");
    await nodeToggle.click();
    await expect(candidates.first()).toBeVisible({ timeout: 15_000 });
    await expect(picker.locator(".form-error")).toHaveCount(0);

    // 重新建立 locator；候选区域尚未出现时不要用首元素直接断言。
    await expect(candidates.first()).toBeVisible({ timeout: 15_000 });
    await expect(nodeToggle).toHaveAttribute("aria-expanded", "true");
    await nodeToggle.click();
    await expect(nodeToggle).toHaveAttribute("aria-expanded", "false");
    await expect(candidates).toHaveCount(0);
    await nodeToggle.click();
    await expect(candidates.first()).toBeVisible();
    expect(await candidates.count()).toBeGreaterThan(0);

    // 只追加一道，并且确认追加后的候选缓存已剔除它。
    const candidatesBeforeAppend = await candidates.count();
    // 标签同时包含题干和「变式题」标记；卷面题干本身不包含该标记。
    const appendedQuestionText = await candidates.first().locator("xpath=..").locator("span").first().innerText();
    await candidates.first().check();
    const confirm = page.getByTestId("confirm-append");
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect(picker).toBeHidden({ timeout: 15_000 });
    // 题数增加一道：追加只加一道，且不重洗已有顺序。
    await expect(page.getByTestId("study-status")).toContainText(`/ ${baseCount + 1}`);

    await page.getByTestId("append-questions").click();
    const pickerAfterAppend = page.getByTestId("question-picker");
    await pickerAfterAppend.getByRole("searchbox", { name: "搜索知识点" }).fill("等比级数");
    await pickerAfterAppend.getByRole("button", { name: "等比级数的敛散性与求和" }).click();
    const cachedCandidates = pickerAfterAppend.locator('input[type="checkbox"]');
    await expect(cachedCandidates).toHaveCount(candidatesBeforeAppend - 1);
    await expect(
      pickerAfterAppend.locator("label.question-picker-tree__question").filter({ hasText: appendedQuestionText.trim() }),
    ).toHaveCount(0);
    await pickerAfterAppend.getByRole("button", { name: "取消" }).click();

    // 全卷模式：追加题参与题型排序，而不是强制显示在卷尾。
    await page.getByTestId("full-paper").click();
    const paper = page.getByTestId("paper-list");
    await expect(paper).toBeVisible();
    await expect(paper.locator("li.paper-item")).toHaveCount(baseCount + 1);
    // 追加的是另一个知识点的题，附加信息默认收起但仍可展开查看。
    const appended = paper.locator("li.paper-item").filter({ hasText: appendedQuestionText.trim() });
    await expect(appended).toHaveCount(1);
    await expect(appended.locator("details.question-meta")).not.toHaveAttribute("open");
    await appended.locator("summary").click();
    await expect(appended.locator("details.question-meta")).toHaveAttribute("open", "");
  });
});

test.describe("阶段 B：从知识树补充与选择题选项", () => {
  test("准备页可以从知识树补充今天想学的叶子节点", async ({ page }) => {
    await page.goto("/study");
    await expectSystemStatus(page, "ready");
    await expect(page.getByTestId("study-setup")).toBeVisible();

    // 选择器打开前，叶子在页面上不存在。
    await expect(page.getByTestId("pick-node-math.calculus.limit.lhopital")).toHaveCount(0);

    await page.getByTestId("tree-kp-picker-open").click();
    const picker = page.getByTestId("tree-kp-picker");
    await expect(picker).toBeVisible();

    // 章节提供折叠导航，只有可考核叶子显示加入/移出按钮。
    await page.getByTestId("scope-picker-search").fill("math");
    await expect(picker.getByRole("button", { name: /^高等数学/ })).toBeVisible();

    const beforeText = await page.getByTestId("selected-kp-count").innerText();

    // 推荐范围默认包含全部叶子；手动移出再加入，计数须真实变化。
    const series = page.getByTestId("pick-node-math.calculus.series.geometric");
    await expect(series).toBeVisible();
    await expect(series).toHaveAttribute("aria-pressed", "true");
    await series.click();
    await expect(series).toHaveAttribute("aria-pressed", "false");
    expect(await page.getByTestId("selected-kp-count").innerText()).not.toBe(beforeText);

    await series.click();
    await expect(series).toHaveAttribute("aria-pressed", "true");
    expect(await page.getByTestId("selected-kp-count").innerText()).toBe(beforeText);

    await page.getByTestId("close-tree-kp-picker").click();
    await expect(picker).toBeHidden();
  });

  test("选择题选项可以点选，且客观结果不覆盖自评", async ({ page }) => {
    await page.goto("/study");
    await expectSystemStatus(page, "ready");
    await expect(page.getByTestId("study-setup")).toBeVisible();

    // 只留「洛必达法则」一个知识点。
    await selectOnlyKnowledgePoint(page, "math.calculus.limit.lhopital");
    await page.getByTestId("generate-plan").click();
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });

    // 展示层按选择、填空、大题排序；直接定位选择题并作答。
    await page.getByTestId("full-paper").click();
    const paper = page.getByTestId("paper-list");
    await expect(paper).toBeVisible();
    const items = paper.locator("li.paper-item");
    const total = await items.count();
    const types = await items.locator("header .tag:first-of-type").allInnerTexts();
    const rank = (type: string) => type.includes("选择") ? 0 : type.includes("填空") ? 1 : 2;
    expect(types.map(rank)).toEqual([...types.map(rank)].sort());
    await expect(items.first().locator("details.question-meta")).not.toHaveAttribute("open");
    let choice = null;
    for (let index = 0; index < total; index += 1) {
      const candidate = items.nth(index);
      if ((await candidate.innerText()).includes("选择题")) {
        choice = candidate;
        break;
      }
    }
    expect(choice, "卷内应当有一道选择题").not.toBeNull();
    if (!choice) return;

    // 全卷模式现在也提供可点选的选项（此前只是静态文本，无法作答）。
    const choiceId = (await choice.getAttribute("data-item-id")) ?? "";
    const optionA = choice.locator('input[type="radio"]').first();
    await expect(optionA).toBeVisible();
    await optionA.check();
    await expect(optionA).toBeChecked();

    // 故意选一个错选项（正确答案是 C），仍然自评「已掌握」。
    // 自评与客观结果互不覆盖：状态由自评决定。
    // 这里用接口完成自评：列表在提交后会重渲染，页面元素引用会失效，
    // 而本用例要验证的是「选项可点选 + 客观结果落库」这两件事。
    const planBefore = await (await page.request.get("/api/plans/today")).json();
    const target = planBefore.items.find(
      (item: { question_type: string; id: string; question_id: string }) =>
        item.question_type === "single_choice",
    );
    expect(target, "卷内应当有一道选择题").toBeTruthy();
    const choiceKey = await optionA.getAttribute("value");
    expect(choiceKey).toBeTruthy();

    const assess = await page.request.post(
      `/api/practice-items/${target.id}/self-assessments`,
      {
        data: {
          self_grade: "mastered",
          idempotency_key: `e2e-choice-${Date.now()}`,
          selected_option: choiceKey,
        },
      },
    );
    expect(assess.status()).toBe(200);
    const payload = await assess.json();
    // 客观结果只是复盘参考；自评才是毕业依据。
    expect(payload.effective_confirmation_count).toBeGreaterThan(0);
  });

  test("自评刷新期间整卷始终在场，且不会把用户从全卷弹回专注", async ({ page }) => {
    // 这条用例锁住一个真实缺陷（曾在自动化里表现为偶发失败）：
    // 自评提交成功后前端要重新拉取今日学习，而旧实现一进 load() 就把整页
    // 切成 loading 态 —— `study-active`（含全卷 paper-list）被从 DOM 摘掉，
    // 用户此时点「全卷模式」就会看到卷子消失；同时 grade() 无条件
    // `mode.value = "focus"`，会把正在全卷里逐题自评的用户弹回专注。
    //
    // 这里用接口延迟把那个刷新窗口放大到必然可见：只要修复还在，
    // 卷子在整个窗口里都不会消失，用户停留的视图也不会被夺走。
    await page.goto("/study");
    await expectSystemStatus(page, "ready");
    await expect(page.getByTestId("study-setup")).toBeVisible();

    await selectOnlyKnowledgePoint(page, "math.calculus.limit.lhopital");
    await page.getByTestId("generate-plan").click();
    await expect(page.getByTestId("study-active")).toBeVisible({ timeout: 15_000 });

    // 让后续每一次今日学习刷新（GET）都慢 1.5 秒，把刷新窗口显式放大。
    await page.route("**/api/plans/today", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    });

    await page.getByTestId("full-paper").click();
    await expect(page.getByTestId("paper-list")).toBeVisible();

    // 全卷模式下自评第一道未完成题。
    // 注意：全卷里的自评按钮没有 testid（只有专注模式有），按可见文本定位。
    const pendingItem = page
      .getByTestId("paper-list")
      .locator("li.paper-item")
      .filter({ has: page.getByRole("button", { name: "已掌握" }) })
      .first();
    await expect(pendingItem).toBeVisible();
    await pendingItem.getByRole("button", { name: "已掌握" }).click();

    // 刷新窗口内：卷子必须始终在场，绝不能出现「整页 loading」把它摘掉。
    await expect(page.getByTestId("paper-list")).toBeVisible();
    await expect(page.getByTestId("study-loading")).toHaveCount(0);

    // 用真实后端做同步点：自评确实落库后，再检查用户有没有被弹走。
    await expect
      .poll(
        async () => {
          const plan = await (await page.request.get("/api/plans/today")).json();
          return plan.items.filter((item: { completed: boolean }) => item.completed).length;
        },
        { timeout: 30_000, message: "自评应当被后端真实记录" },
      )
      .toBeGreaterThan(0);

    // 刷新完成后仍在全卷模式：用户没被弹回专注。
    await expect(page.getByTestId("paper-list")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("focus-question")).toHaveCount(0);
    // 卷内确实显示了这道题的自评反馈（依据来自后端 reason_code）。
    await expect(page.getByTestId("paper-notice").first()).toBeVisible({
      timeout: 15_000,
    });
  });
});
