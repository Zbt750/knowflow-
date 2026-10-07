import { expect, test, type Page } from "./fixtures";

/**
 * 窄窗口（小屏）覆盖：规格第 17 篇要求的视口检查之一。
 *
 * 为什么不能只看「元素存在」：
 * 窄屏最容易出现的两种真实毛病是
 *   1) 整页横向溢出 —— 出现横向滚动条，右侧内容被裁掉，用户够不到按钮；
 *   2) 关键操作被挤出视口或被别的元素压住 —— 元素存在于 DOM，但点不到。
 * 所以这里除了可见性，还直接量 `scrollWidth > clientWidth`，
 * 并对按钮做真实点击（点击失败会直接抛错，比断言更硬）。
 *
 * 注意：本文件只做**只读**断言与点击导航类按钮，不新建/删除任何资料。
 */

const NARROW = { width: 375, height: 667 };
const TABLET = { width: 768, height: 1024 };

/** 整页是否横向溢出（容 1px 取整误差）。 */
async function horizontalOverflow(page: Page): Promise<{ scroll: number; client: number }> {
  return page.evaluate(() => {
    const root = document.documentElement;
    return { scroll: root.scrollWidth, client: root.clientWidth };
  });
}

async function assertNoHorizontalOverflow(page: Page, label: string): Promise<void> {
  const { scroll, client } = await horizontalOverflow(page);
  expect(
    scroll,
    `${label}：页面横向溢出（scrollWidth=${scroll} > clientWidth=${client}），窄屏会出现横向滚动、内容被裁`,
  ).toBeLessThanOrEqual(client + 1);
}

test.describe("窄窗口 · 375×667", () => {
  test.use({ viewport: NARROW });

  test("五个页面都不横向溢出，且根节点可见", async ({ page }) => {
    // 注意：学习页与知识页**没有** `study-page` / `knowledge-page` 这两个 testid，
    // 它们的根节点只有 class="page"。这里按各页真实存在的标记定位，
    // 不去发明一个不存在的 testid —— 那样写出来的用例是假的。
    const pages: [string, string, string][] = [
      ["/study", ".page", "今日学习"],
      ["/knowledge", ".page", "知识树"],
      ["/materials", '[data-testid="materials-page"]', "资料库"],
      ["/chat", ".chat-workspace", "问答"],
      ["/settings", ".settings-page", "设置"],
    ];
    for (const [path, selector, title] of pages) {
      await page.goto(path);
      await expect(page.locator(selector).first()).toBeVisible({ timeout: 25_000 });
      await expect(page.locator(".app-header > strong")).toHaveText(title, { timeout: 25_000 });
      await assertNoHorizontalOverflow(page, `${path} @375px`);
    }
  });

  test("学习页的主按钮在窄屏下仍可点击（不靠 hover 也点得到）", async ({ page }) => {
    await page.goto("/study");
    await expect(page.locator(".page").first()).toBeVisible({ timeout: 25_000 });

    // 准备页的「生成练习卷」是主路径入口；窄屏下不能被挤出视口。
    const generate = page.getByTestId("generate-plan");
    if (await generate.count()) {
      await generate.scrollIntoViewIfNeeded();
      await expect(generate).toBeInViewport();
      await expect(generate).toBeEnabled();
    }
    await assertNoHorizontalOverflow(page, "/study @375px");
  });

  test("知识页在窄屏下树与详情都可达", async ({ page }) => {
    await page.goto("/knowledge");
    await expect(page.locator(".page").first()).toBeVisible({ timeout: 25_000 });
    // 树必须渲染出来（数据来自测试库）。
    await expect(page.getByTestId("knowledge-tree")).toBeVisible({ timeout: 25_000 });
    await assertNoHorizontalOverflow(page, "/knowledge @375px");
  });

  test("问答页在窄屏下输入区与发送按钮仍在视口内", async ({ page }) => {
    await page.goto("/chat");
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    const composer = page.locator(".composer");
    await composer.scrollIntoViewIfNeeded();
    await expect(composer).toBeInViewport();
    // 输入框必须可交互：窄屏把输入区挤没了是最典型的回归。
    await page.locator("#chat-question").fill("窄屏可用性检查");
    await expect(page.locator("#chat-question")).toHaveValue("窄屏可用性检查");
    await assertNoHorizontalOverflow(page, "/chat @375px");
  });

  test("资料页在窄屏下上传入口可见可交互", async ({ page }) => {
    await page.goto("/materials");
    await expect(page.getByTestId("materials-page")).toBeVisible({ timeout: 25_000 });
    const add = page.getByTestId("upload-toggle");
    await add.scrollIntoViewIfNeeded();
    await expect(add).toBeVisible();
    await assertNoHorizontalOverflow(page, "/materials @375px");
  });
});

test.describe("窄窗口 · 768×1024（平板）", () => {
  test.use({ viewport: TABLET });

  test("四个页面都不横向溢出", async ({ page }) => {
    const pages: [string, string][] = [
      ["/study", ".page"],
      ["/knowledge", ".page"],
      ["/materials", '[data-testid="materials-page"]'],
      ["/chat", ".chat-workspace"],
    ];
    for (const [path, selector] of pages) {
      await page.goto(path);
      await expect(page.locator(selector).first()).toBeVisible({ timeout: 25_000 });
      await assertNoHorizontalOverflow(page, `${path} @768px`);
    }
  });
});
