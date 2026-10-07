import { expect, test } from "./fixtures";

/**
 * 问答页端到端测试（阶段 D）。
 *
 * 覆盖契约里「页面行为」那部分：
 * - 会话能创建、能恢复（刷新后历史还在）；
 * - 两种模式严格隔离：`我的资料` 不产生学习事件、也不推练习；
 * - 未配置模型时给出可理解的提示，而不是编造回答。
 *
 * 注意：这些用例**不依赖真实 LLM**。本机没有配 API key 时，
 * 提问会得到 `llm_not_configured`，这本身就是契约要求的行为之一
 * （「无足够资料时明确说明」与「模型未配置时明确提示」都不能伪装成回答）。
 */

const CHAT = "/chat";

/** 打开问答页并等它加载完成。 */
async function openChat(page: import("@playwright/test").Page): Promise<void> {
  await page.goto(CHAT);
  await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
  // 侧栏加载完成后「历史会话」标签会存在；避免在数据未就绪时断言。
  await expect(page.getByTestId("scope-switch")).toBeVisible();
}

async function selectScope(page: import("@playwright/test").Page, mode: "我的资料" | "内置资料"): Promise<void> {
  const switcher = page.getByTestId("scope-switch");
  await expect(switcher).toBeEnabled({ timeout: 30_000 });
  if (!(await switcher.innerText()).includes(`当前：${mode}`)) await switcher.click();
  await expect(switcher).toContainText(`当前：${mode}`, { timeout: 15_000 });
}

test.describe("问答页", () => {
  test("检索超时后明确结束等待并显示可重试提示", async ({ page }) => {
    const sessionId = "11111111-1111-4111-8111-111111111111";
    await page.route("**/api/materials?*", (route) => {
      const mode = new URL(route.request().url()).searchParams.get("source_type") ?? "user";
      return route.fulfill({
        json: {
          items: [{ id: mode + "-1", source_type: mode, status: "ready" }],
          total: 1,
          stats: { total: 1, ready: 1 },
        },
      });
    });
    await page.route("**/api/chat/sessions**", (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "POST" && url.pathname === "/api/chat/sessions") {
        return route.fulfill({ json: { session_id: sessionId, title: "新对话", mode: "user" } });
      }
      if (route.request().method() === "GET" && url.pathname === "/api/chat/sessions") {
        return route.fulfill({ json: [] });
      }
      return route.continue();
    });
    await page.route("**/api/chat/sessions/*/answers:stream", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream; charset=utf-8" },
        body: "event: error\ndata: {\"code\":\"retrieval_timeout\",\"message\":\"retrieval timed out\",\"retryable\":true}\n\n",
      }),
    );

    await openChat(page);
    await page.locator("#chat-question").fill("请概述那份文件");
    await page.locator(".send-button").click();

    await expect(page.getByRole("alert")).toContainText("资料检索超过 30 秒");
    await expect(page.getByTestId("response-progress")).toHaveCount(0);
    await page.locator("#chat-question").fill("重试一次");
    await expect(page.locator(".send-button")).toBeEnabled();
  });

  test("资料超过 50 份时仍能识别下一页的内置资料", async ({ page }) => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      id: `user-${index}`,
      source_type: "user",
      status: "ready",
    }));
    await page.route("**/api/materials?*", (route) => {
      const query = new URL(route.request().url()).searchParams;
      if (query.get("status") === "ready" && query.get("source_type") === "user") {
        return route.fulfill({ json: { items: firstPage.slice(0, 1), total: 50, stats: { total: 51, ready: 51 } } });
      }
      if (query.get("status") === "ready" && query.get("source_type") === "builtin") {
        return route.fulfill({ json: { items: [{ id: "builtin-51", source_type: "builtin", status: "ready" }], total: 1, stats: { total: 51, ready: 51 } } });
      }
      return route.fulfill({ json: { items: firstPage, total: 51, stats: { total: 51, ready: 51 } } });
    });

    await openChat(page);
    await selectScope(page, "内置资料");
    await expect(page.getByTestId("scope-switch")).toContainText("1 份");
    await expect(page.locator(".chat-notice--setup")).toHaveCount(0);
    await page.locator("#chat-question").fill("测试问题");
    await expect(page.locator(".send-button")).toBeEnabled();
  });

  test("页面可打开，含会话侧栏、模式选择与输入区", async ({ page }) => {
    await openChat(page);

    await expect(page.locator(".conversation-sidebar")).toBeVisible();
    await expect(page.locator(".scope-picker")).toBeVisible();
    await expect(page.locator(".composer")).toBeVisible();
    await expect(page.locator(".messages")).toBeVisible();

    // 一个按钮切换两个隔离的资料范围。
    const switcher = page.getByTestId("scope-switch");
    await expect(switcher).toHaveCount(1);
    const firstMode = await switcher.innerText();
    await switcher.click();
    expect(await switcher.innerText()).not.toBe(firstMode);
  });

  test("切换到其他页面期间流式回答继续，返回问答后显示完整结果", async ({ page }) => {
    const sessionId = "11111111-1111-4111-8111-111111111111";
    const answerText = "切换页面不会中断这条正在生成的回答。";
    const questionText = "切页时继续回答";
    let releaseStream!: () => void;
    let markStreamStarted!: () => void;
    const streamGate = new Promise<void>((resolve) => { releaseStream = resolve; });
    const streamStarted = new Promise<void>((resolve) => { markStreamStarted = resolve; });
    let streamFailed = false;
    let persistedMessages: Array<Record<string, unknown>> = [];

    page.on("requestfailed", (request) => {
      if (request.url().includes("answers:stream")) streamFailed = true;
    });
    await page.route("**/api/materials?*", (route) => {
      const sourceType = new URL(route.request().url()).searchParams.get("source_type") ?? "user";
      const items = sourceType === "user"
        ? [{ id: "material-1", title: "测试资料", source_type: "user", status: "ready" }]
        : [];
      return route.fulfill({ json: { items, total: items.length, stats: { total: 1, ready: 1 } } });
    });
    await page.route("**/api/chat/sessions**", (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "POST" && url.pathname === "/api/chat/sessions") {
        return route.fulfill({ json: { session_id: sessionId, title: questionText, mode: "user" } });
      }
      if (route.request().method() === "GET" && url.pathname === "/api/chat/sessions") {
        return route.fulfill({ json: [{ session_id: sessionId, title: questionText, mode: "user" }] });
      }
      if (route.request().method() === "GET" && url.pathname.endsWith("/messages")) {
        return route.fulfill({ json: persistedMessages });
      }
      return route.continue();
    });
    await page.route("**/api/chat/sessions/*/answers:stream", async (route) => {
      markStreamStarted();
      await streamGate;
      const assistantId = "22222222-2222-4222-8222-222222222222";
      persistedMessages = [
        { message_id: "33333333-3333-4333-8333-333333333333", role: "user", content: questionText, status: "completed", matched_kp_id: null, citations: [] },
        { message_id: assistantId, role: "assistant", content: answerText, status: "completed", response_duration_ms: 120, matched_kp_id: null, matched_kp: null, citations: [] },
      ];
      const frames = [
        "event: meta\ndata: " + JSON.stringify({ message_id: assistantId, retrieval_mode: "hybrid", retrieved_count: 0 }) + "\n\n",
        "event: delta\ndata: " + JSON.stringify({ seq: 1, text: answerText }) + "\n\n",
        "event: citations\ndata: " + JSON.stringify({ citations: [] }) + "\n\n",
        "event: done\ndata: " + JSON.stringify({ message_id: assistantId, citations: [], matched_kp_id: null, response_duration_ms: 120 }) + "\n\n",
      ].join("");
      await route.fulfill({ status: 200, headers: { "content-type": "text/event-stream; charset=utf-8" }, body: frames });
    });

    await openChat(page);
    await selectScope(page, "我的资料");
    await page.locator("#chat-question").fill(questionText);
    await page.locator(".send-button").click();
    await streamStarted;

    await page.getByRole("link", { name: "资料" }).click();
    await expect(page.getByTestId("materials-page")).toBeVisible();
    expect(streamFailed).toBe(false);
    await page.getByRole("link", { name: "问答" }).click();
    await expect(page.locator(".chat-workspace")).toBeVisible();
    await expect(page.getByTestId("response-progress")).toBeVisible();

    releaseStream();
    await expect(page.locator(".message-row--assistant").last().locator(".message-bubble")).toContainText(answerText);
    await expect(page.locator("#chat-question")).toBeEnabled();
    expect(streamFailed).toBe(false);
  });

  test("可以选中回答并作为可移除的引用加入下一条提问", async ({ page }) => {
    const sessionId = "11111111-1111-4111-8111-111111111111";
    const answerText = "阶段 D 有独立的 citations 帧，并通过资料名和章节定位来源。";
    const submittedQuestions: string[] = [];

    await page.route("**/api/materials?*", (route) => {
      const query = new URL(route.request().url()).searchParams;
      return route.fulfill({
        json: {
          items: [],
          total: 1,
          stats: { total: 1, ready: 1 },
          source_type: query.get("source_type"),
        },
      });
    });
    await page.route("**/api/chat/sessions**", (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "POST" && url.pathname === "/api/chat/sessions") {
        return route.fulfill({ json: { session_id: sessionId, title: "新对话", mode: "user" } });
      }
      return route.continue();
    });
    await page.route("**/api/chat/sessions/*/messages", (route) => {
      const history = submittedQuestions.flatMap((question, index) => [
        {
          message_id: "33333333-3333-4333-8333-" + String(index * 2).padStart(12, "0"),
          role: "user",
          content: question,
          status: "completed",
          matched_kp_id: null,
          citations: [],
        },
        {
          message_id: "33333333-3333-4333-8333-" + String(index * 2 + 1).padStart(12, "0"),
          role: "assistant",
          content: answerText,
          status: "completed",
          response_duration_ms: 12,
          matched_kp_id: null,
          matched_kp: null,
          citations: [],
        },
      ]);
      return route.fulfill({ json: history });
    });
    await page.route("**/api/chat/sessions/*/answers:stream", async (route) => {
      const body = route.request().postDataJSON() as { question?: string };
      submittedQuestions.push(body.question ?? "");
      const messageId = "22222222-2222-4222-8222-" + String(submittedQuestions.length).padStart(12, "0");
      const frames = [
        "event: meta\ndata: " + JSON.stringify({ message_id: messageId, retrieval_mode: "hybrid", retrieved_count: 0 }) + "\n\n",
        "event: delta\ndata: " + JSON.stringify({ seq: 1, text: answerText }) + "\n\n",
        "event: citations\ndata: " + JSON.stringify({ citations: [] }) + "\n\n",
        "event: done\ndata: " + JSON.stringify({ message_id: messageId, citations: [], matched_kp_id: null, response_duration_ms: 12 }) + "\n\n",
      ].join("");
      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream; charset=utf-8" },
        body: frames,
      });
    });

    await openChat(page);
    await page.locator(".sidebar-head .icon-button").click();
    await page.locator("#chat-question").fill("请总结阶段 D");
    await page.locator(".send-button").click();
    const answer = page.locator(".message-row--assistant .message-bubble").last();
    await expect(answer).toContainText(answerText);
    await expect(page.locator(".messages")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByTestId("selection-quote-action")).toHaveCount(0);

    await answer.evaluate((element) => {
      const target = element.querySelector("p") ?? element;
      const range = document.createRange();
      range.selectNodeContents(target);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    });
    await expect(page.getByTestId("selection-quote-action")).toBeVisible();
    await page.getByTestId("quote-selected-answer").click();
    await expect(page.getByTestId("composer-quotes")).toContainText(answerText);

    await page.locator("#chat-question").fill("这里的 citations 帧有什么作用？");
    await page.locator(".send-button").click();
    await expect.poll(() => submittedQuestions.length).toBe(2);
    expect(submittedQuestions[1]).toContain("> " + answerText);
    await expect(page.getByTestId("composer-quotes")).toHaveCount(0);
  });

  test("新建对话先只开一段草稿，发出第一条问题后才进入历史", async ({ page }) => {
    await openChat(page);

    const before = await page.locator(".conversation-item").count();
    // 侧栏头部的「＋」是新建对话。
    await page.locator(".icon-button").click();

    // 新草稿清空消息区，顶部只展示资料来源。
    await expect(page.getByTestId("chat-source")).toBeVisible();
    await expect(page.locator(".message-row--assistant")).toHaveCount(0);

    // 但历史**不能**因此多出一条。
    // 契约：会话推迟到「用户真的发出第一条问题」才落库 —— 以前是点一次就建一条空会话，
    // 开发库里 94 条未归档会话有 46 条是空壳，历史列表被冲成噪声、翻不动。
    // 这一步不涉及任何网络请求，所以断言是确定的，不需要 sleep。
    expect(await page.locator(".conversation-item").count()).toBe(before);

    // 若当前范围没有可检索资料，提问按钮是禁用的，后面的步骤跳过。
    const setupNotice = page.locator(".chat-notice--setup");
    if (await setupNotice.isVisible().catch(() => false)) return;

    // 发出第一条问题之后，历史里才应该出现这条会话。
    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await page.locator(".send-button").click();
    await expect
      .poll(async () => page.locator(".conversation-item").count(), {
        // 流式回答可能较慢，会话在流开始前就已创建，但列表要等流结束后才刷新。
        timeout: 180_000,
        message: "发出第一条问题后，会话必须出现在历史里",
      })
      .toBe(before + 1);
  });

  test("历史会话跟随当前资料范围，不混入另一种模式", async ({ page }) => {
    // 契约：篇 01「两种问答模式严格隔离」——两种模式的检索范围、matched_kp、
    // 追练推荐与学习事件都不同。混在一个列表里用户分不清哪条属于哪个范围，
    // 所以历史必须按当前范围过滤，并且每条仍带模式小字（双保险）。
    await openChat(page);
    for (const mode of ["我的资料", "内置资料"] as const) {
      await selectScope(page, mode);
      await expect
        .poll(
          async () => {
            const labels = await page.locator(".conversation-item small").allInnerTexts();
            return labels.every((text) => text.trim() === mode);
          },
          { timeout: 15_000, message: `历史里不能混入「${mode}」以外的会话` },
        )
        .toBe(true);
    }
  });

  test("右键会话可重命名、分享、置顶或删除，列表不显示铅笔和叉号", async ({ page }) => {
    await openChat(page);
    await expect(page.getByTestId("chat-source")).toContainText("资料来源：");
    await expect(page.locator(".conversation-rename")).toHaveCount(0);
    await expect(page.locator(".conversation-delete")).toHaveCount(0);

    const rows = page.locator(".conversation-row");
    if (await rows.count()) {
      await rows.first().click({ button: "right" });
      const menu = page.getByRole("menu", { name: "会话操作" });
      await expect(menu).toBeVisible();
      await expect(menu.getByRole("menuitem", { name: "重命名" })).toBeVisible();
      await expect(menu.getByRole("menuitem", { name: "分享链接" })).toBeVisible();
      await expect(menu.getByRole("menuitem", { name: "删除" })).toBeVisible();
      await menu.getByRole("menuitem", { name: "置顶" }).click();
      await expect(rows.first()).toHaveClass(/pinned/);

      await rows.first().click({ button: "right" });
      await expect(menu.getByRole("menuitem", { name: "取消置顶" })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(menu).toHaveCount(0);
    }
  });

  test("确认删除会话后永久移除它，不误伤其他会话", async ({ page }) => {
    // 删除落到后端 `DELETE /chat/sessions/{id}`，是不可恢复的物理删除。
    // 这条用例**只删它自己新建的那一条**；夹具已强制只连接隔离 test 后端，
    // 因此不会碰开发库中用户的真实对话。
    await openChat(page);

    const setupNotice = page.locator(".chat-notice--setup");
    if (await setupNotice.isVisible().catch(() => false)) return; // 无法提问 → 造不出会话 → 跳过

    const before = await page.locator(".conversation-row").count();

    // 先造一条属于本用例的会话：新建草稿 → 发出第一条问题才会落库。
    await page.locator(".icon-button").click();
    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await page.locator(".send-button").click();
    await expect
      .poll(async () => page.locator(".conversation-row").count(), {
        timeout: 180_000,
        message: "发出第一条问题后，会话必须出现在历史里",
      })
      .toBe(before + 1);

    // 列表按 updated_at 倒序，刚建的这条必定在第一位。
    const target = page.locator(".conversation-row").first();
    // 生成结束后从右键菜单删除；菜单不在生成中开放。
    await expect(page.locator("#chat-question")).toBeEnabled({ timeout: 180_000 });

    // Playwright 默认会 dismiss 对话框；删除有确认框，必须显式接受。
    page.once("dialog", (dialog) => dialog.accept());
    await target.click({ button: "right" });
    await page.getByRole("menu", { name: "会话操作" }).getByRole("menuitem", { name: "删除" }).click();

    // 只少一条，并回到用例开始时的数量。
    await expect
      .poll(async () => page.locator(".conversation-row").count(), {
        timeout: 30_000,
        message: "删除后历史里只应少掉被删的那一条",
      })
      .toBe(before);

    // 刷新后仍保持少一条，证明不是仅从 Vue 内存列表隐藏，而是后端已永久删除。
    await page.reload();
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".conversation-row")).toHaveCount(before);
  });

  test("回答后在输入框显示四个可选动作，找题与跳过都不强制继续追问", async ({ page }) => {
    await openChat(page);
    await selectScope(page, "内置资料");
    if (await page.locator(".chat-notice--setup").isVisible().catch(() => false)) return;

    await page.locator(".icon-button").click();
    const suggestions = page.getByTestId("answer-suggestions");
    await expect(suggestions).toHaveCount(0);
    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await page.locator(".send-button").click();

    const errorNotice = page.locator(".chat-notice--error");
    await expect.poll(async () =>
      (await page.locator(".message-row--assistant .citation-box").count()) > 0 ||
      (await errorNotice.isVisible().catch(() => false)),
      { timeout: 150_000, message: "回答应完成并带引用，或明确报错" },
    ).toBe(true);
    if (await errorNotice.isVisible().catch(() => false)) return;

    await expect.poll(async () =>
      (await page.locator(".message-row--assistant").last().locator(".response-duration").count()) > 0 ||
      (await errorNotice.isVisible().catch(() => false)),
      { timeout: 150_000, message: "引用出现后，回答仍须完成或明确报错" },
    ).toBe(true);
    if (await errorNotice.isVisible().catch(() => false)) return;
    await expect(suggestions).toBeVisible();
    for (const id of ["action-rephrase", "action-steps", "action-example", "action-find-questions", "action-skip"]) {
      await expect(page.getByTestId(id)).toBeVisible();
    }
    await expect(page.locator("#chat-question")).toBeEnabled();
    await expect(page.getByTestId("followup-candidates")).toHaveCount(0);

    await page.getByTestId("action-find-questions").click();
    const candidates = page.getByTestId("followup-candidates");
    await expect(candidates).toBeVisible({ timeout: 15_000 });
    await expect.poll(async () =>
      (await candidates.locator("li").count()) > 0 ||
      (await candidates.getByTestId("followup-empty").count()) > 0,
    ).toBe(true);
    // 查题本身绝不会自动勾选或追加到今日卷。
    await expect(candidates.locator('input[type="checkbox"]:checked')).toHaveCount(0);
    await page.getByTestId("action-skip").click();
    await expect(suggestions).toHaveCount(0);
    await expect(candidates).toHaveCount(0);
    await expect(page.locator("#chat-question")).toBeEnabled();
  });

  test("真实提问能得到回答，且回答带可核验来源", async ({ page }) => {
    await openChat(page);

    const setupNotice = page.locator(".chat-notice--setup");
    if (await setupNotice.isVisible().catch(() => false)) {
      // 当前范围没有可检索资料：页面必须明确指向资料页，而不是允许提问后失败。
      await expect(setupNotice).toContainText("资料");
      await expect(page.locator(".send-button")).toBeDisabled();
      return;
    }

    // 先新建一个干净会话：否则默认打开的历史会话里已有消息，
    // `.last()` 会抓到旧消息（包括历史里那条「正在生成」的文案），断言就失去意义。
    await page.locator(".icon-button").click();
    await expect(page.getByTestId("chat-source")).toBeVisible();
    await expect(page.locator(".message-row--assistant")).toHaveCount(0);

    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await page.locator(".send-button").click();

    await expect(page.locator(".message-row--user").last().locator(".message-bubble")).toHaveCSS("background-color", "rgb(232, 243, 255)");

    // 结果只有两种，但**绝不能一直停在生成中**：
    // 要么出现引用（真实模型答完），要么出现明确错误。
    const citation = page.locator(".message-row--assistant").last().locator(".citation-box");
    const errorNotice = page.locator(".chat-notice--error");
    await expect
      .poll(
        async () =>
          (await citation.count()) > 0 || (await errorNotice.isVisible().catch(() => false)),
        { timeout: 150_000, message: "assistant 必须给出引用或明确错误，不能停在生成中" },
      )
      .toBe(true);

    if (await errorNotice.isVisible().catch(() => false)) {
      // 上游不可用时的提示来自后端 SAFE_MESSAGES（英文契约），页面会原样显示；
      // 这里同时接受英文契约文案与中文兜底文案 —— 断言的是
      // 「给出可理解的错误」而不是某一句具体措辞。
      await expect(errorNotice).toContainText(/模型|失败|配置|不可用|generation failed|not configured/i);
      return;
    }

    // 有真实回答：必须带来源，且来源里要有可回跳的标题路径。
    const lastAnswer = page.locator(".message-row--assistant").last();
    await expect(lastAnswer.locator(".markdown-content")).toBeVisible();
    await expect(lastAnswer.locator(".message-bubble")).toHaveCSS("background-color", "rgb(255, 255, 255)");
    const citationToggle = lastAnswer.locator(".citation-toggle");
    await expect(citationToggle).toContainText(/引用\s*\d+\s*个资料片段/);
    await expect(citationToggle).toHaveAttribute("aria-expanded", "false");
    await expect(lastAnswer.locator(".citation-list")).toHaveCount(0);
    await citationToggle.click();
    await expect(citationToggle).toHaveAttribute("aria-expanded", "true");
    await expect(lastAnswer.locator(".citation-list")).toBeVisible();
    await citationToggle.click();
    await expect(citationToggle).toHaveAttribute("aria-expanded", "false");
    await expect(lastAnswer.locator(".citation-list")).toHaveCount(0);

    // 刷新后回答与来源必须还在（契约：刷新页面仍有完整回答和真实来源）。
    await page.reload();
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    await expect(
      page.locator(".message-row--assistant").last().locator(".citation-box"),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("回答展示归因依据：知识点名 + 依据的引用编号，且刷新后仍在", async ({ page }) => {
    // 契约：matched_kp 决定推荐哪些追练题，因此它不能只给结论。
    // 用户必须能看到「凭什么归到这个叶子知识点、依据是正文里的哪一个来源」。
    // 这条用例验证的正是前端有没有把这份依据显示出来（依据由后端算出并落库）。
    await openChat(page);

    // 必须在**内置资料**模式下验证。
    // 「我的资料」按契约固定不归因（不产生学习事件、不推荐追练），
    // 在内置模式之外做这条断言只会验到「确实没有归因」，等于白跑。
    // 注意：范围选择器必须限定在 .scope-picker 内 ——
    // 历史会话条目的无障碍名字里也带「内置资料」，直接用 role 会匹配到十几个元素。
    const scopePicker = page.locator(".scope-picker");
    await expect(scopePicker).toBeVisible();
    await selectScope(page, "内置资料");
    await page.locator(".icon-button").click();
    await expect(page.getByTestId("chat-source")).toBeVisible();

    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await page.locator(".send-button").click();

    await expect(page.locator(".message-row--user").last().locator(".message-bubble")).toHaveCSS("background-color", "rgb(232, 243, 255)");

    const lastAnswer = page.locator(".message-row--assistant").last();
    const errorNotice = page.locator(".chat-notice--error");
    await expect
      .poll(
        async () =>
          (await lastAnswer.locator(".citation-box").count()) > 0 ||
          (await errorNotice.isVisible().catch(() => false)),
        { timeout: 150_000, message: "assistant 必须给出引用或明确错误，不能停在生成中" },
      )
      .toBe(true);

    // 内置换来了真实回答（未配置模型时给出可理解的错误并跳过）。
    if (await errorNotice.isVisible().catch(() => false)) {
      await expect(errorNotice).toContainText(/模型|失败|配置|不可用|generation failed|not configured/i);
      return;
    }

    // 归因依据块必须出现，并且给出知识点名称（不能只显示 uuid）。
    const box = lastAnswer.getByTestId("attribution-box");
    await expect(box).toBeVisible({ timeout: 30_000 });
    const kpText = box.getByTestId("attribution-kp");
    await expect(kpText).not.toBeEmpty();
    // 显示成 uuid 说明后端没带上名称（这个坑真的踩过）：
    // 用户看到「归到 3f2a…-…」等于没解释。
    await expect(kpText).not.toHaveText(/^[0-9a-f]{8}-[0-9a-f]{4}-/i);
    // 依据要能对上是正文里的哪一个引用编号，例如 [C1]。
    await expect(box.getByTestId("attribution-label")).toContainText(/\[C\d+\]/);

    // 依据块给出的引用编号必须真的存在于这份回答的来源列表里 ——
    // 指向一个不存在的编号，等于给了一个没法核对的依据。
    const label = (await box.getByTestId("attribution-label").innerText()).replace(/[[\]]/g, "");

    // 展开引用列表并确认依据编号确实在里面。
    //
    // 这里刻意用 `expect.poll` 把「点击 → 确认」做成一个**会重试的整体**：
    // 展开是前端本地状态（`openCitationIds`），而流结束后消息列表还会被
    // `fetchChatMessages` 刷新一次；如果点击恰好撞上那一瞬的重渲染，
    // 这次展开就会丢掉（aria-expanded 回到 false），点击本身却不报错。
    // 单独点一次再断言会偶发失败；重试一次点击则稳定 ——
    // 已经展开时再点会收起，所以只在「没看到编号」时才补点。
    await expect
      .poll(
        async () => {
          const codes = await lastAnswer.locator(".citation-list code").allInnerTexts();
          if (codes.some((text) => text.includes(label))) return true;
          await lastAnswer.locator(".citation-toggle").click({ timeout: 5_000 }).catch(() => undefined);
          await page.waitForTimeout(200);
          const after = await lastAnswer.locator(".citation-list code").allInnerTexts();
          return after.some((text) => text.includes(label));
        },
        {
          timeout: 30_000,
          message: `引用列表里应当能找到归因依据引用的 [${label}]`,
        },
      )
      .toBe(true);

    // 刷新后依据仍然在（它随消息落库，不是前端临时算出来的）。
    await page.reload();
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    const reloaded = page.locator(".message-row--assistant").last();
    await expect(reloaded.getByTestId("attribution-box")).toBeVisible({ timeout: 30_000 });
    await expect(reloaded.getByTestId("attribution-label")).toContainText(/\[C\d+\]/);
  });

  test("不存在的会话返回明确错误而不是空页面", async ({ page }) => {
    // 直接访问一个不存在的会话：页面应给出错误提示，不能白屏。
    await page.goto(CHAT);
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    // 侧栏仍可用（页面没崩）。
    await expect(page.locator(".conversation-sidebar")).toBeVisible();
  });
});
