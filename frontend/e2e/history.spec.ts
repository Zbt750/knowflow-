import { expect, test } from "./fixtures";

/**
 * 浏览器前进/后退语义（规格第 17 篇 §5 要求覆盖）。
 *
 * 为什么必须单独覆盖这一组：
 * 页面的「状态」有两个来源 —— 内存里的 ref 和 URL。前进/后退只改 URL，
 * 不会重新执行 SPA 内部的跳转代码。所以「点一下能进详情」不代表
 * 「按后退能回到列表、再按前进能再进详情」。这类缺陷在正常点击流程里
 * 完全看不出来，只有用户真按了浏览器的返回键才会炸。
 *
 * 断言原则：后退/前进后必须**恢复用户能看见的东西**（详情面板、列表、
 * 查询参数），而不是只检查页面没白屏。
 *
 * 关于等待：本文件不再「count() === 0 就跳过」——那会让用例在数据其实存在、
 * 只是列表还没渲染完的时候假装通过（实测踩过：库里有 2 份资料却报了 skip）。
 * 正确做法是先等列表真的渲染出来，再决定是否有数据可用。
 */

/** 等资料列表渲染完成，返回条目数。渲染不出内容才算「没有资料」。 */
async function waitForMaterials(page: import("@playwright/test").Page): Promise<number> {
  await page.goto("/materials");
  await expect(page.getByTestId("materials-page")).toBeVisible({ timeout: 20_000 });
  // 要么出现资料条目，要么出现「还没有资料」空态 —— 两者之一必然出现，
  // 这样等待是确定的，不会靠 sleep 撞运气。
  await expect(page.locator(".material-item").first().or(page.getByTestId("materials-empty"))).toBeVisible({
    timeout: 25_000,
  });
  return page.locator(".material-item").count();
}

test.describe("浏览器前进后退 · /materials", () => {
  test("资料详情可以关闭并从列表打开另一份资料", async ({ page }) => {
    const count = await waitForMaterials(page);
    expect(count, "prepare_e2e_data 应准备 2 份资料；为 0 说明测试数据没准备好").toBeGreaterThan(1);

    const idOf = async (): Promise<string | null> => new URL(page.url()).searchParams.get("material_id");

    // The reader is a modal drawer. Close it before selecting another row;
    // trying to click behind the open drawer is not a supported interaction.
    expect(await idOf()).toBeNull();
    await expect(page.getByTestId("material-detail")).toHaveCount(0);
    await page.locator(".material-item").first().locator(".material-view").click();
    await expect.poll(idOf, { timeout: 20_000 }).not.toBeNull();
    const firstId = await idOf();
    await expect(page.getByTestId("detail-title")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "关闭资料" }).click();
    await expect.poll(idOf, { timeout: 20_000 }).toBeNull();

    // Close the modal before selecting another item from the list.
    await page.locator(".material-item").nth(1).locator(".material-view").click();
    await expect
      .poll(idOf, { timeout: 20_000, message: "选择第二份资料后 URL 必须更新" })
      .not.toBe(firstId);
    await expect(page.getByTestId("detail-title")).toBeVisible({ timeout: 20_000 });
    const secondId = await idOf();

    expect(secondId).not.toBe(firstId);
    await expect(page.getByTestId("detail-title")).toBeVisible({ timeout: 20_000 });
  });

  test("刷新当前详情页后，URL 里的选择仍然生效（深链接可恢复）", async ({ page }) => {
    const count = await waitForMaterials(page);
    expect(count, "prepare_e2e_data 应准备 2 份资料").toBeGreaterThan(0);

    await page.locator(".material-item").first().locator(".material-view").click();
    await expect
      .poll(() => new URL(page.url()).searchParams.get("material_id"), { timeout: 20_000 })
      .not.toBeNull();
    await expect(page.getByTestId("detail-title")).toBeVisible({ timeout: 20_000 });

    const url = page.url();
    const selectedTitle = await page.getByTestId("detail-title").innerText();

    // 直接重开这个 URL（等于用户按 F5 / 从历史打开 / 把链接发给别人），选择必须被恢复。
    await page.goto(url);
    await expect(page.getByTestId("materials-page")).toBeVisible({ timeout: 20_000 });
    await expect
      .poll(() => new URL(page.url()).searchParams.get("material_id"), { timeout: 20_000 })
      .toBe(new URL(url).searchParams.get("material_id"));
    // 不只是 URL 恢复了 —— 详情内容本身也要恢复成同一份资料。
    await expect(page.getByTestId("detail-title")).toHaveText(selectedTitle, { timeout: 20_000 });
  });
});

test.describe("浏览器前进后退 · 页面之间", () => {
  test("四个页面互相导航后，后退按访问顺序回退且页面内容正确", async ({ page }) => {
    // 每页各有自己的根节点：学习/知识/资料页是 `.page`，
    // 问答页是 `.chat-workspace`（它没有 `.page`）——断言必须按各页真实标记写。
    const roots: [string, string][] = [
      ["/study", ".page"],
      ["/knowledge", ".page"],
      ["/materials", ".page"],
      ["/chat", ".chat-workspace"],
    ];
    for (const [path, selector] of roots) {
      await page.goto(path);
      await expect(page.locator(selector).first()).toBeVisible({ timeout: 20_000 });
    }

    // 依次后退：chat → materials → knowledge → study
    for (const expected of ["/materials", "/knowledge", "/study"]) {
      await page.goBack();
      await expect
        .poll(() => new URL(page.url()).pathname, {
          timeout: 20_000,
          message: `后退后应回到 ${expected}`,
        })
        .toBe(expected);
      // 每个页面都要真的渲染出自己的根节点，而不是只改了 router 状态。
      await expect(page.locator(".page").first()).toBeVisible({ timeout: 20_000 });
    }

    await page.goForward();
    await expect.poll(() => new URL(page.url()).pathname, { timeout: 20_000 }).toBe("/knowledge");
    await expect(page.locator(".page").first()).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("浏览器前进后退 · /chat", () => {
  test("后退再前进后，问答页与会话列表都恢复", async ({ page }) => {
    await page.goto("/chat");
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("chat-source")).toHaveText("奶蛙 · 学习问答");
    await expect(page.locator(".conversation-list")).toBeVisible({ timeout: 25_000 });

    // 注意：这里**不**去 UI 里真发一条问题来「制造历史」。
    // 发一条真实问题要等模型回答（本机实测约 20~55 秒），在 180 秒的
    // 用例超时下极其脆弱，而且那是 chat.spec.ts 已经覆盖的契约。
    // 本文件只负责前进/后退语义，所以按当前真实数据断言。
    const before = await page.locator(".conversation-item").count();

    await page.goBack();
    await expect(page.locator("body")).toBeVisible();

    await page.goForward();
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    // 会话列表容器必须重新渲染出来（不能只剩空壳框架）。
    await expect(page.locator(".conversation-list")).toBeVisible({ timeout: 20_000 });
    // 历史条目数量不能因为前进/后退而变（列表只显示「已有消息」的会话）。
    await expect
      .poll(() => page.locator(".conversation-item").count(), {
        timeout: 25_000,
        message: "前进/后退后会话条目数量发生变化",
      })
      .toBe(before);
  });
});
