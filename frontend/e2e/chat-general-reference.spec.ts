import { expect, test } from "@playwright/test";

// Pure UI mocks: no shared fixture, database resets, or real model calls.
test("空资料库仍可提问，通用答案无伪引用且刷新后保留来源标识", async ({ page }) => {
  const sessionId = "11111111-1111-4111-8111-111111111111";
  const answerId = "22222222-2222-4222-8222-222222222222";
  const question = "什么是 TCP？";
  const answer = "## 通用知识参考\n\n知识库中没有足够依据。TCP 提供可靠的字节流传输。";
  let messages: Array<Record<string, unknown>> = [];
  let sent = false;
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/materials") {
      return route.fulfill({ json: { items: [], total: 0, stats: { total: 0, ready: 0 } } });
    }
    if (path === "/api/chat/sessions") {
      if (request.method() === "POST") {
        return route.fulfill({ json: { session_id: sessionId, title: question, mode: "user" } });
      }
      return route.fulfill({ json: sent ? [{ session_id: sessionId, title: question, mode: "user" }] : [] });
    }
    if (path.endsWith("/messages")) return route.fulfill({ json: messages });
    if (path.endsWith("/answers:stream")) {
      expect(request.postDataJSON().question).toBe(question);
      sent = true;
      messages = [
        { message_id: "33333333-3333-4333-8333-333333333333", role: "user", content: question, status: "completed", citations: [] },
        { message_id: answerId, role: "assistant", content: answer, status: "completed", answer_source: "general", response_duration_ms: 120, matched_kp_id: null, citations: [] },
      ];
      const frames = [
        ["meta", { message_id: answerId, retrieval_mode: "general", retrieved_count: 0 }],
        ["delta", { seq: 1, text: "第一轮未完成的残句" }],
        ["delta", { seq: 2, text: "", replace: true, recovering: true }],
        ["delta", { seq: 3, text: answer + " [C99]" }],
        ["citations", { citations: [] }],
        ["done", { message_id: answerId, answer, answer_source: "general", citations: [], matched_kp_id: null, response_duration_ms: 120 }],
      ].map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
      return route.fulfill({ headers: { "content-type": "text/event-stream; charset=utf-8" }, body: frames });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto("/chat");
  const scope = page.getByTestId("scope-switch");
  await expect(scope).toBeVisible();
  if (!(await scope.innerText()).includes("当前：我的资料")) await scope.click();
  await expect(page.locator(".chat-notice--setup")).toContainText("仍可提问");
  await page.locator("#chat-question").fill(question);
  await expect(page.locator(".send-button")).toBeEnabled();
  await page.locator(".send-button").click();
  await expect(page.getByTestId("answer-source")).toContainText("非资料结论");
  const bubble = page.locator(".message-row--assistant .message-bubble");
  await expect(bubble).toContainText("可靠的字节流传输");
  await expect(bubble).not.toContainText("[C99]");
  await expect(bubble).not.toContainText("第一轮未完成的残句");
  await page.reload();
  await expect(page.getByTestId("answer-source")).toContainText("非资料结论");
  await expect(bubble).toContainText("可靠的字节流传输");
  expect(pageErrors).toEqual([]);
});
