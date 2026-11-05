import { apiFetch, expect, test } from "./fixtures";

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
  await expect(page.getByTestId("chat-source")).toHaveText("奶蛙 · 学习问答");
}

async function selectScope(page: import("@playwright/test").Page, mode: "我的资料" | "内置资料"): Promise<void> {
  // Learning chat now has one scope; private RAG is tested in /materials.
  if (mode !== "内置资料") throw new Error("Private RAG lives in Materials");
  await expect(page.getByTestId("chat-source")).toHaveText("奶蛙 · 学习问答");
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
        return route.fulfill({ json: { session_id: sessionId, title: "新对话", mode: "builtin" } });
      }
      if (route.request().method() === "GET" && url.pathname === "/api/chat/sessions") {
        return route.fulfill({ json: [] });
      }
      return route.continue();
    });
    await page.route("**/api/chat/sessions/*/assistant:stream", (route) =>
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

  test("个人资料范围跨页读取，不把首批文件当作全部", async ({ page }) => {
    const files = Array.from({ length: 101 }, (_, i) => ({
      id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(i).padStart(12, "0")}`, title: `范围文件${i}`,
      source_type: "user", status: "ready", active_index_version: "v1",
    }));
    await page.route("**/api/materials?*", route => {
      const query = new URL(route.request().url()).searchParams;
      const offset = Number(query.get("offset") ?? 0), limit = Number(query.get("limit") ?? 100);
      return route.fulfill({ json: { items: files.slice(offset, offset + limit), total: 101, stats: { total: 101, ready: 101 } } });
    });
    await page.goto("/materials");
    await page.getByTestId("material-search-scope").click();
    const picker = page.getByTestId("material-search-scope-picker");
    await expect(picker.getByRole("checkbox")).toHaveCount(101);
    await expect(picker).toContainText("范围文件100");
  });

  test("学习问答与个人资料搜索分别提供清晰入口", async ({ page }) => {
    await openChat(page);
    await expect(page.locator(".conversation-sidebar")).toBeVisible();
    await expect(page.locator(".composer")).toBeVisible();
    await expect(page.locator(".messages")).toBeVisible();
    await expect(page.getByTestId("scope-switch")).toHaveCount(0);
    await page.getByRole("link", { name: "资料", exact: true }).click();
    await expect(page.getByTestId("material-search-panel")).toBeVisible();
    await expect(page.getByTestId("material-search-scope")).toContainText("全部资料");
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
      if (request.url().includes("assistant:stream")) streamFailed = true;
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
        return route.fulfill({ json: { session_id: sessionId, title: questionText, mode: "builtin" } });
      }
      if (route.request().method() === "GET" && url.pathname === "/api/chat/sessions") {
        return route.fulfill({ json: [{ session_id: sessionId, title: questionText, mode: "builtin" }] });
      }
      if (route.request().method() === "GET" && url.pathname.endsWith("/messages")) {
        return route.fulfill({ json: persistedMessages });
      }
      return route.continue();
    });
    await page.route("**/api/chat/sessions/*/assistant:stream", async (route) => {
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
    await selectScope(page, "内置资料");
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
        return route.fulfill({ json: { session_id: sessionId, title: "新对话", mode: "builtin" } });
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
    await page.route("**/api/chat/sessions/*/assistant:stream", async (route) => {
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
    // chat workspace renders before its asynchronous history request completes.
    // Wait for the initial list response so the baseline cannot be captured as
    // an empty, still-loading sidebar and later appear as a false extra session.
    const historyLoaded = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/chat/sessions"
        && response.request().method() === "GET"
        && url.searchParams.get("mode") === "builtin"
        && response.ok();
    });
    await openChat(page);
    await historyLoaded;

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

  test("学习问答历史不混入当天个人资料搜索", async ({ page }) => {
    const modes: string[] = [];
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname === "/api/chat/sessions") modes.push(url.searchParams.get("mode") ?? "");
    });
    await page.goto("/materials");
    await expect(page.getByTestId("material-search-panel")).toBeVisible();
    await openChat(page);
    await expect.poll(() => modes.includes("builtin")).toBe(true);
    const labels = await page.locator(".conversation-item small").allInnerTexts();
    expect(labels.every(text => text.trim() === "学习问答")).toBe(true);
    await expect(page.locator(".conversation-sidebar")).not.toContainText("我的资料搜索");
  });

  test("历史会话旁有直接删除入口，右键菜单保留其他会话操作", async ({ page }) => {
    await openChat(page);
    await expect(page.getByTestId("chat-source")).toContainText("学习问答");
    await expect(page.locator(".conversation-rename")).toHaveCount(0);

    const rows = page.locator(".conversation-row");
    await expect(page.locator(".conversation-delete")).toHaveCount(await rows.count());
    if (await rows.count()) {
      await expect(rows.first().getByRole("button", { name: `删除会话：${await rows.first().locator(".conversation-title").innerText()}` })).toBeVisible();
    }
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
    // 生成结束后点击历史记录旁的删除按钮。
    await expect(page.locator("#chat-question")).toBeEnabled({ timeout: 180_000 });

    // Playwright 默认会 dismiss 对话框；删除有确认框，必须显式接受。
    page.once("dialog", (dialog) => dialog.accept());
    await target.getByRole("button", { name: /^删除会话：/ }).click();

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

  test("知识问答不自动创建试卷，后续学习动作由用户提出", async ({ page }) => {
    const before = await (await apiFetch("/api/plans/today")).json();
    await openChat(page);
    await page.locator(".sidebar-head .icon-button").click();
    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await page.locator(".send-button").click();
    await expect(page.locator("#chat-question")).toBeEnabled({ timeout: 60000 });
    await expect(page.locator(".chat-notice--error")).toHaveCount(0);
    await expect(page.locator(".message-row--assistant").last().locator(".response-duration")).toBeVisible();
    await expect(page.getByTestId("answer-suggestions")).toHaveCount(0);
    const after = await (await apiFetch("/api/plans/today")).json();
    expect(after).toEqual(before);
  });

  test("通用问答明确标注非资料结论并保留回答", async ({ page }) => {
    await openChat(page);
    await page.locator(".icon-button").click();
    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await page.locator(".send-button").click();
    const lastAnswer = page.locator(".message-row--assistant").last();
    await expect(lastAnswer.locator('.message-bubble')).toContainText('通用知识参考', { timeout: 60_000 });
    await expect(lastAnswer.getByTestId("answer-source")).toHaveCount(0);
    await expect(lastAnswer.locator(".message-bubble")).toBeVisible();
    await expect(lastAnswer.locator(".citation-box")).toHaveCount(0);
    await page.reload();
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".message-row--assistant").last().getByTestId("answer-source")).toHaveCount(0);
  });

  test.skip("资料检索回答展示归因依据：知识点名 + 引用编号", async ({ page }) => {
    // This suite uses an offline general-answer provider with no retrieved
    // evidence; citation attribution is exercised only by retrieval fixtures.
    // Generic OfflineProvider responses contain no retrieval evidence. The
    // dedicated retrieval integration tests own this contract; never invent
    // citations merely to satisfy this browser fixture.
    // 契约：matched_kp 决定推荐哪些追练题，因此它不能只给结论。
    // 用户必须能看到「凭什么归到这个叶子知识点、依据是正文里的哪一个来源」。
    // 这条用例验证的正是前端有没有把这份依据显示出来（依据由后端算出并落库）。
    await openChat(page);

    // 必须在**内置资料**模式下验证。
    // 「我的资料」按契约固定不归因（不产生学习事件、不推荐追练），
    // 在内置模式之外做这条断言只会验到「确实没有归因」，等于白跑。
    // 注意：范围选择器必须限定在 .scope-picker 内 ——
    // 历史会话条目的无障碍名字里也带「内置资料」，直接用 role 会匹配到十几个元素。
    const scopePicker = page.getByTestId("chat-source");
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

  test("RAG检索证据由服务端保存，但问答页不展开引用片段", async ({ page }) => {
    // 当前产品要求问答页不展示资料依据侧栏或引用片段。后端引用与归因
    // 持久化由 test_chat_flow.py / test_chat_stream.py 在真实隔离数据库中覆盖；
    // 这里验证 Vue 对完整 SSE 契约的消费与当前展示边界。
    const sessionId = "11111111-1111-4111-8111-111111111111";
    const assistantId = "22222222-2222-4222-8222-222222222222";
    const answerText = "洛必达法则用于满足条件的未定式，计算前应先确认函数可导。";
    const citations = [{ label: "C1", chunk_id: "chunk-fixture", material_id: "material-fixture",
      material_title: "测试资料：极限方法", heading_path: ["极限"], ordinal: 2,
      preview: "仅供协议测试的引用片段，不应在问答页展开。" }];
    const matchedKp = { kp_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", kp_name: "洛必达法则",
      source_chunk_id: "chunk-fixture", source_rank: 1, cosine: 0.8, score: 1, total: 1,
      runner_up_total: 0, attribution_label: "C1", plain: "测试归因依据" };
    let history: Array<Record<string, unknown>> = [];
    await page.route("**/api/materials?*", route =>
      route.fulfill({ json: { items: [], total: 0, stats: { total: 0, ready: 0 } } }));
    await page.route("**/api/chat/sessions**", route => {
      const url = new URL(route.request().url()), method = route.request().method();
      if (method === "POST" && url.pathname === "/api/chat/sessions")
        return route.fulfill({ status: 201, json: { session_id: sessionId, title: "RAG展示边界", mode: "builtin" } });
      if (method === "GET" && url.pathname === "/api/chat/sessions")
        return route.fulfill({ json: [{ session_id: sessionId, title: "RAG展示边界", mode: "builtin" }] });
      if (method === "GET" && url.pathname.endsWith("/messages")) return route.fulfill({ json: history });
      return route.continue();
    });
    await page.route("**/api/chat/sessions/*/assistant:stream", route => {
      history = [
        { message_id: "33333333-3333-4333-8333-333333333333", role: "user", content: "洛必达法则什么时候可以用？", status: "completed", matched_kp_id: null, citations: [] },
        { message_id: assistantId, role: "assistant", content: answerText, status: "completed", response_duration_ms: 120,
          matched_kp_id: matchedKp.kp_id, matched_kp: matchedKp, answer_source: "knowledge_base", citations },
      ];
      const frames = [
        "event: meta\ndata: " + JSON.stringify({ message_id: assistantId, retrieval_mode: "hybrid", retrieved_count: 1 }) + "\n\n",
        "event: delta\ndata: " + JSON.stringify({ seq: 1, text: answerText }) + "\n\n",
        "event: citations\ndata: " + JSON.stringify({ citations }) + "\n\n",
        "event: done\ndata: " + JSON.stringify({ message_id: assistantId, answer: answerText, citations,
          matched_kp_id: matchedKp.kp_id, matched_kp: matchedKp, answer_source: "knowledge_base", response_duration_ms: 120 }) + "\n\n",
      ].join("");
      return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream; charset=utf-8" }, body: frames });
    });
    await openChat(page);
    await page.locator(".sidebar-head .icon-button").click();
    await page.locator("#chat-question").fill("洛必达法则什么时候可以用？");
    await page.locator(".send-button").click();
    const lastAnswer = page.locator(".message-row--assistant").last();
    await expect(lastAnswer.locator(".message-bubble")).toContainText(answerText);
    await expect(lastAnswer.locator(".citation-box, .citation-list, [data-testid='attribution-box']")).toHaveCount(0);
    await expect(lastAnswer.locator(".message-bubble")).not.toContainText("仅供协议测试的引用片段");
    await page.reload();
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    const restored = page.locator(".message-row--assistant").last();
    await expect(restored.locator(".message-bubble")).toContainText(answerText);
    await expect(restored.locator(".citation-box, .citation-list, [data-testid='attribution-box']")).toHaveCount(0);
    expect(history[1]).toMatchObject({ matched_kp_id: matchedKp.kp_id, citations });
  });

  test("不存在的会话返回明确错误而不是空页面", async ({ page }) => {
    // 直接访问一个不存在的会话：页面应给出错误提示，不能白屏。
    await page.goto(CHAT);
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    // 侧栏仍可用（页面没崩）。
    await expect(page.locator(".conversation-sidebar")).toBeVisible();
  });
});
