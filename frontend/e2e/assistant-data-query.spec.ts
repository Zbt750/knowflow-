import { expect, test } from "@playwright/test";

// Uses the project's isolated E2E PostgreSQL and OfflineProvider. The page talks
// to the real FastAPI/SSE route; no model-quality claim is made by this test.
test("学习问答承接知识点上下文并查询真实可练库存，刷新后保留结果", async ({ page }) => {
  const pageErrors: string[] = [];
  const assistantRequests: Array<Record<string, unknown>> = [];
  let persistedSessionId: string | null = null;
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/assistant:stream")) {
      persistedSessionId = new URL(request.url()).pathname.split("/").at(-2) ?? null;
      try {
        assistantRequests.push(request.postDataJSON() as Record<string, unknown>);
      } catch {
        assistantRequests.push({ invalid_json: true });
      }
    }
  });

  await page.goto("/chat");
  const input = page.locator("#chat-question");
  await input.fill("请解释一下洛必达法则的适用条件。");
  await input.press("Enter");
  const replies = page.locator(".message-row--assistant .message-bubble");
  await expect(replies.last()).toContainText("洛必达法则");
  await expect.poll(() => assistantRequests.length).toBe(1);

  await input.fill("那我现在有多少道这种题可以练？");
  await input.press("Enter");
  await expect(replies.last()).toContainText(/\d+ 道符合当前可练资格/);
  await expect.poll(() => assistantRequests.length).toBe(2);
  expect(assistantRequests[1].question).toBe("那我现在有多少道这种题可以练？");

  expect(persistedSessionId).toMatch(/^[0-9a-f-]{36}$/i);
  await page.reload();
  await expect(replies).toHaveCount(2);
  await expect(replies.last()).toContainText(/\d+ 道符合当前可练资格/);
  expect(pageErrors).toEqual([]);
});

test("资料库入口明确区分系统题库数据与资料引用，并在刷新后恢复", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/materials");
  const input = page.getByTestId("material-search-question");
  await expect(input).toBeVisible();
  await input.fill("系统题库里有多少道可练题？");
  await page.getByTestId("material-search-send").click();

  const replies = page.getByTestId("material-search-assistant");
  await expect(replies.last()).toContainText("数据来源：系统题库（不是资料文档检索）。");
  await expect(replies.last()).toContainText(/\d+ 道符合当前可练资格/);
  await expect(replies.last()).not.toContainText(/\[C\d+\]/);

  await page.reload();
  await expect(page.getByTestId("material-search-assistant")).toHaveCount(1);
  await expect(page.getByTestId("material-search-assistant").last()).toContainText(
    "数据来源：系统题库（不是资料文档检索）。",
  );
  expect(pageErrors).toEqual([]);
});
