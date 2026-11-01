import { apiFetch, expect, test } from "./fixtures";

test("普通问答首条消息、连续提问、刷新和切换会话走真实 assistant SSE 链路", async ({ page }) => {
  const firstQuestion = "矩阵的秩怎么理解？请用一个小例子说明。";
  const followupQuestion = "再用另一个小例子解释一次。";
  const secondQuestion = "行列式按行展开是什么意思？";

  await page.goto("/chat");
  await expect(page.locator(".chat-workspace")).toBeVisible();
  await expect(page.getByTestId("chat-source")).toHaveText("奶蛙 · 学习问答");
  await page.locator('button[title="新建对话"]').click();

  async function sendAndAssert(question: string): Promise<{ sessionId: string; body: Record<string, unknown> }> {
    await page.locator("#chat-question").fill(question);
    const responsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "POST" && url.pathname.endsWith("/assistant:stream");
    });
    await page.locator(".send-button").click();
    const response = await responsePromise;
    const raw = await response.text();
    expect(response.status(), raw).toBe(200);
    expect(raw).toContain("event: done");
    const match = new URL(response.url()).pathname.match(/\/sessions\/([^/]+)\/assistant:stream$/);
    expect(match).not.toBeNull();
    const body = response.request().postDataJSON() as Record<string, unknown>;
    const context = body.study_context as Record<string, unknown>;
    expect(context.conversation_id).toBe(match![1]);
    expect(context.material_id).toBeUndefined();
    await expect(page.locator("#chat-question")).toBeEnabled();
    await expect(page.locator(".message-row--assistant").last()).toContainText("离线回答");
    return { sessionId: match![1], body };
  }

  const first = await sendAndAssert(firstQuestion);
  const firstHistory = await apiFetch(`/api/chat/sessions/${first.sessionId}/messages`);
  expect(firstHistory.status).toBe(200);
  expect((await firstHistory.json() as Array<{ content: string }>).map((item) => item.content)).toContain(firstQuestion);

  await page.reload();
  await expect(page.locator(".message-row--user").filter({ hasText: firstQuestion })).toBeVisible();
  const continued = await sendAndAssert(followupQuestion);
  expect(continued.sessionId).toBe(first.sessionId);

  await page.locator('button[title="新建对话"]').click();
  const second = await sendAndAssert(secondQuestion);
  expect(second.sessionId).not.toBe(first.sessionId);

  const firstSessionButton = page.locator(".conversation-item").filter({ hasText: firstQuestion.slice(0, 16) });
  await expect(firstSessionButton).toBeVisible();
  await firstSessionButton.click();
  await expect(page.locator(".message-row--user").filter({ hasText: firstQuestion })).toBeVisible();
  await expect(page.locator(".message-row--user").filter({ hasText: followupQuestion })).toBeVisible();
});
