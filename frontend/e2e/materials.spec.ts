import { fileURLToPath } from "node:url";

import { E2E_PREFIX, expect, test, userMaterials } from "./fixtures";

/**
 * 资料页端到端测试：走真实浏览器 + 真实后端 + 真实模型。
 *
 * 覆盖「上传 → 后台索引 → 可检索 → 检索命中原文 → 删除」整条链路。
 * 用真实文件（仓库自带的讲义），不使用任何前端假数据。
 *
 * **前提约定：这些用例不得依赖「资料库为空」。**
 * 用户自己的资料可能就在库里，测试必须能在有资料的库上正常通过，
 * 也必须在自己结束后把库恢复原样（见 fixtures.ts 的两条铁律）。
 */

const PROJECT_ROOT = fileURLToPath(new URL("../..", import.meta.url));
const LECTURE_PATH = `${PROJECT_ROOT}/seed/materials/gaoshu-lecture-01.md`;
/**
 * 每次上传用带随机后缀的标题。
 * 固定标题会与「上一次失败留下的同名资料」混淆，也让 `detail-title` 断言
 * 有机会匹配到旧的那一条。加上后缀后，标题就唯一标识本次上传的资料。
 */
function uniqueTestTitle(): string {
  return `${E2E_PREFIX}高等数学核心考点讲义-${Math.random().toString(36).slice(2, 8)}`;
}
/** 与 playwright.config.ts / fixtures.ts 保持一致的后端地址。 */
const API_BASE = process.env.E2E_API_BASE ?? "http://127.0.0.1:8001";

/**
 * 上传一份讲义并等待处理完成（后台任务 + 页面轮询），返回测试资料的 id。
 *
 * id 来自**上传接口的响应**，而不是之后再去列表里找：
 * 列表查询存在时序竞争（刚上传的资料可能还没出现在结果里），
 * 一旦拿到空 id，后面的检索断言就会以 422 失败，看起来像接口坏了。
 */
async function uploadLecture(page: import("@playwright/test").Page): Promise<string> {
  const testTitle = uniqueTestTitle();
  const uploaded = page.waitForResponse(
    (response) =>
      response.url().includes("/api/materials") &&
      response.request().method() === "POST" &&
      response.status() === 201,
  );

  await page.goto("/materials");
  // 首次进入会加载懒加载页面模块；允许冷启动/编译波动，但仍会在 30 秒后明确失败。
  await expect(page.getByTestId("materials-page")).toBeVisible({ timeout: 30_000 });

  const fileChooser = page.waitForEvent("filechooser");
  await page.getByTestId("upload-toggle").click();
  await (await fileChooser).setFiles(LECTURE_PATH);
  await expect(page.getByTestId("upload-title")).toHaveValue("gaoshu-lecture-01");
  await page.getByTestId("upload-title").fill(testTitle);
  await page.getByTestId("upload-submit").click();

  const created = (await (await uploaded).json()) as { material: { id: string } };
  const materialId = created.material.id;
  expect(materialId).toBeTruthy();

  const row = page.locator(".material-item").filter({ hasText: testTitle });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row.locator(".material-status")).toHaveText("可检索", { timeout: 180_000 });
  await row.locator(".material-view").click();

  await expect(page.getByTestId("detail-title")).toHaveText(testTitle);
  await expect(page.getByTestId("material-reader")).toContainText("极限");
  await expect(page.getByTestId("material-reader").getByRole("heading", { name: "高等数学核心考点讲义" })).toBeVisible();
  await expect(page.getByTestId("detail-toggle")).toHaveAttribute("aria-expanded", "false");
  await page.getByTestId("detail-toggle").click();
  await expect(page.getByTestId("chunk-list")).toBeVisible({ timeout: 60_000 });
  return materialId;
}

/**
 * 限定资料范围的混合检索。
 *
 * 为什么要限定范围：用户的资料库可能已经有别的（甚至很大的）资料，
 * 那会改变检索排序 —— 之前就出现过「开发文档把讲义挤出前两名」的情况。
 * 这里用公开的 `material_ids` 过滤参数把范围收窄到测试资料，
 * 断言才能只反映「这份资料是否可被检索」，而不是整个库的排序偶然性。
 *
 * 注意 id 字段：`MaterialRecord` 只声明了 id 与 title，
 * 这里用一次独立的 API 调用取回完整结果。
 */
async function searchWithinMaterial(
  materialId: string,
  query: string,
): Promise<{ hits: Array<{ material_id: string; heading_path: string[] }> }> {
  const response = await fetch(`${API_BASE}/api/materials/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: 5, material_ids: [materialId] }),
  });
  if (!response.ok) throw new Error(`检索接口返回 ${response.status}`);
  return (await response.json()) as {
    hits: Array<{ material_id: string; heading_path: string[] }>;
  };
}

test.describe("资料库页面", () => {
  test("上传讲义后建立索引，并可被资料范围检索命中", async ({ page }) => {
    const materialId = await uploadLecture(page);

    // 索引版本必须符合后端契约 v1-<16 位十六进制>，前端只展示不推断。
    const version = await page.getByTestId("detail-index-version").innerText();
    expect(version).toMatch(/^v1-[0-9a-f]{16}$/);

    // 块数必须大于零，且块预览带标题路径。
    const chunkCount = Number(await page.getByTestId("detail-chunk-count").innerText());
    expect(chunkCount).toBeGreaterThan(0);
    await expect(page.getByTestId("chunk-list")).toBeVisible();
    await expect(page.getByTestId("chunk-kp").first()).toContainText("math.calculus");

    // 资料页**不再提供检索入口**：检索与问答属于 /chat。
    // 这里断言它确实不在，防止以后又被加回来造成职责重叠。
    await expect(page.getByTestId("search-panel")).toHaveCount(0);

    // 用限定资料范围的接口检索做确定性断言：
    // 不传过滤条件时排序会被库里其他资料影响，这里只看这份讲义本身。
    const scoped = await searchWithinMaterial(materialId, "加减法里能不能直接替换等价无穷小");
    expect(scoped.hits.length).toBeGreaterThan(0);
    for (const hit of scoped.hits) {
      expect(hit.material_id).toBe(materialId);
    }
    expect(scoped.hits[0].heading_path.join(" / ")).toContain("等价无穷小");

    // 搜索由后端过滤，列表只显示匹配标题，清空后恢复分页浏览。
    const title = await page.getByTestId("detail-title").innerText();
    await page.getByRole("button", { name: "关闭资料" }).click();
    const search = page.getByTestId("material-search");
    await search.fill(title);
    await expect(page.getByTestId("material-list").locator(".material-item")).toHaveCount(1);
    await expect(page.getByTestId("material-list")).toContainText(title);
    await search.fill("不存在的资料名称-端到端");
    await expect(page.getByTestId("materials-empty")).toContainText("没有找到匹配");
    await search.fill("");
    await expect(page.getByTestId("material-list")).toContainText(title);
  });

  test("重建索引后块数不变且版本号稳定", async ({ page }) => {
    await uploadLecture(page);
    const before = await page.getByTestId("detail-chunk-count").innerText();
    const versionBefore = await page.getByTestId("detail-index-version").innerText();

    await page.getByTestId("action-reindex").click();
    await expect(page.getByTestId("detail-status")).toHaveText("可检索", { timeout: 180_000 });
    await expect(page.getByTestId("detail-index-version")).toHaveText(versionBefore);
    await expect(page.getByTestId("detail-chunk-count")).toHaveText(before);
  });

  test("资料阅读器默认只显示正文，索引信息可主动展开", async ({ page }) => {
    await uploadLecture(page);
    await page.getByRole("button", { name: "关闭资料" }).click();
    await expect(page.getByTestId("material-detail")).toHaveCount(0);

    await page.locator(".material-item").first().locator(".material-view").click();
    await expect(page.getByTestId("material-reader")).toBeVisible();
    await expect(page.getByTestId("detail-index-version")).toHaveCount(0);
    const toggle = page.getByTestId("detail-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(page.getByTestId("detail-index-version")).toBeVisible();
    await expect(page.getByTestId("chunk-list")).toBeVisible();
    await toggle.click();
    await expect(page.getByTestId("detail-index-version")).toHaveCount(0);
  });
  test("删除资料后列表不再包含它，且检索不到它的内容", async ({ page }) => {
    const materialId = await uploadLecture(page);
    const testTitle = await page.getByTestId("detail-title").innerText();

    // 删除是不可逆动作，页面必须弹确认框；这里接受它。
    page.on("dialog", (dialog) => {
      void dialog.accept();
    });
    await page.getByTestId("action-delete").click();

    // 这条测试资料必须从列表里消失（不假设整库为空：用户可能有自己的资料）。
    await expect(page.getByTestId("material-list")).not.toContainText(testTitle, {
      timeout: 30_000,
    });

    // 确定性断言：限定在这份已删除资料的范围内检索，必须一条都没有。
    // （页面上不传过滤条件，返回空与否还取决于库里其他资料，不能作为判据。）
    const scoped = await searchWithinMaterial(materialId, "加减结构为什么不能直接替换等价无穷小");
    expect(scoped.hits).toEqual([]);
  });

  test("删除被问答引用过的资料也必须成功（此前会 500）", async ({ page }) => {
    // 为什么必须补这一条：原来的删除用例删的是**刚上传、从未被问答引用过**的资料，
    // 根本不经过 `fk_message_citations_chunk_id_document_chunks` 那条外键。
    // 于是 72 条 e2e 一条都没抓到这个用户可见缺陷（changelog D-47）。
    // 测试覆盖面看的不是数量，而是「每条真实路径有没有被走一遍」。
    const materialId = await uploadLecture(page);
    const testTitle = await page.getByTestId("detail-title").innerText();

    // 第一步：走真实问答，让这份资料**带上真实引用**。
    // 不造引用就等于没测 —— 这正是原有用例的失误。
    await page.goto("/chat");
    await expect(page.locator(".chat-workspace")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("scope-switch")).toBeVisible();

    // 切到「我的资料」范围：刚上传的资料属于 user 来源。
    const switcher = page.getByTestId("scope-switch");
    if (!(await switcher.innerText()).includes("当前：我的资料")) await switcher.click();
    await expect(switcher).toContainText("当前：我的资料");

    const setupNotice = page.locator(".chat-notice--setup");
    const send = page.locator(".send-button");
    if (await setupNotice.isVisible().catch(() => false)) {
      // 我的资料范围下没有可检索资料 —— 环境问题，不是产品缺陷。
      test.skip(true, "该范围没有可检索资料，无法制造引用");
    }

    // 先填问题再判断按钮可用性。
    // **这里踩过一次坑**：空输入框时发送按钮本来就该禁用（canSend 要求问题非空），
    // 据此跳过会让用例**永远**跳过、永远测不到目标路径 —— 与被测缺陷同样的毛病：
    // 看起来在测，其实没测到。所以判据必须是「填了真实问题之后是否仍禁用」。
    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await expect
      .poll(async () => await send.isEnabled(), {
        timeout: 20_000,
        message: "填了问题后发送按钮仍不可用（该范围没有可检索资料）",
      })
      .toBe(true)
      .catch(() => {
        test.skip(true, "填了问题后发送按钮仍不可用，无法制造引用");
      });

    await page.locator(".icon-button").click();
    await expect(page.getByTestId("chat-source")).toBeVisible();
    await page.locator("#chat-question").fill("洛必达法则的适用条件是什么？");
    await send.click();

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
      // 上游模型不可用时拿不到引用 —— 这条用例在语义上是「跳过」而不是失败，
      // 但要**如实说明跳过的原因**，不能静默通过。
      test.skip(
        true,
        `上游模型不可用，无法制造引用：${(await errorNotice.innerText()).slice(0, 60)}`,
      );
    }
    await expect(citation).toHaveCount(1);

    // 第二步：回到这份资料并删除它 —— 此刻它**真的被引用过**。
    await page.goto(`/materials?material_id=${materialId}`);
    await expect(page.getByTestId("detail-title")).toHaveText(testTitle, { timeout: 30_000 });
    await page.getByTestId("detail-toggle").click();

    page.on("dialog", (dialog) => {
      void dialog.accept();
    });
    await page.getByTestId("action-delete").click();

    // 核心断言：删除必须成功（此前这里是 500，且资料留在列表里）。
    await expect(page.getByTestId("material-list")).not.toContainText(testTitle, {
      timeout: 60_000,
    });
    // 删除失败时页面会给出错误提示；这里断言它没有出现。
    await expect(page.getByTestId("action-error")).toHaveCount(0);
  });

  test("拒绝不支持的格式并给出中文原因", async ({ page }) => {
    await page.goto("/materials");
    await expect(page.getByTestId("materials-page")).toBeVisible();

    // 直接构造一个 .exe 文件：前端先拦一次，错误必须可读。
    await page.getByTestId("upload-file").setInputFiles({
      name: "notes.exe",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("MZ"),
    });
    await page.getByTestId("upload-title").fill(`${E2E_PREFIX}错误格式`);
    await page.getByTestId("upload-submit").click();

    await expect(page.getByTestId("action-error")).toContainText("只支持");
  });

  test("超过上限的文件在上传阶段就被拒绝，并说明真实上限", async ({ page }) => {
    await page.goto("/materials");
    await expect(page.getByTestId("materials-page")).toBeVisible();

    // 构造一份明确超过解析上限的文件。
    // 这条用例锁定的是：**不允许出现「上传成功、随后异步失败」**这种先成功后失败的体验。
    const oversized = Buffer.alloc(11 * 1024 * 1024, "a");
    await page.getByTestId("upload-file").setInputFiles({
      name: "huge.md",
      mimeType: "text/markdown",
      buffer: oversized,
    });
    await page.getByTestId("upload-title").fill(`${E2E_PREFIX}超大文件`);
    await page.getByTestId("upload-submit").click();

    await expect(page.getByTestId("action-error")).toBeVisible({ timeout: 60_000 });
    // 提示里必须出现真实上限数值，不能是一句与事实不符的「超过 20 MB」。
    await expect(page.getByTestId("action-error")).toContainText("MB");
    // 也不该产生一条失败资料。
    await expect(page.getByTestId("material-list")).not.toContainText(`${E2E_PREFIX}超大文件`);
  });

  test("分页接口按偏移量返回不同资料", async ({ page }) => {
    const firstResponse = await page.request.get("/api/materials?limit=1&offset=0");
    const secondResponse = await page.request.get("/api/materials?limit=1&offset=1");
    expect(firstResponse.ok()).toBe(true);
    expect(secondResponse.ok()).toBe(true);
    const first = await firstResponse.json();
    const second = await secondResponse.json();
    expect(first.total).toBeGreaterThan(1);
    expect(first.items).toHaveLength(1);
    expect(second.items).toHaveLength(1);
    expect(first.items[0].id).not.toBe(second.items[0].id);
  });
  test("统计数字与列表条数一致，且不会因为库里有别的资料而错位", async ({ page }) => {
    await page.goto("/materials");
    await expect(page.getByTestId("materials-page")).toBeVisible();

    const listCount = await page.getByTestId("material-list").locator("li").count();
    const statsText = await page.getByTestId("materials-stats").innerText();
    const total = Number(/共\s*(\d+)\s*份/.exec(statsText)?.[1] ?? "-1");

    expect(listCount).toBe(Math.min(total, 8));
  });
});

test.describe("测试隔离（不碰用户数据）", () => {
  test("跑完资料页用例后，用户自己的资料一份都不能少", async ({ page }) => {
    // 先记录用户已有的资料（不含测试前缀的那些）。
    const before = await userMaterials();

    await page.goto("/materials");
    await expect(page.getByTestId("materials-page")).toBeVisible();
    await uploadLecture(page);

    // 用户资料的标题必须仍然出现在列表里。
    for (const item of before) {
      await expect(page.getByTestId("material-list")).toContainText(item.title);
    }
  });
});
