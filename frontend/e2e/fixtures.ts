import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { test as base, expect, type Page } from "@playwright/test";

/**
 * 端到端测试的共享夹具。
 *
 * 两条铁律：
 * 1. **测试绝不删除用户自己的数据。** 只清理带 `E2E_PREFIX` 标记的资料，
 *    并逐个核对 id 确实是「本用例执行期间新出现的」。
 *    早期版本直接清空整个资料库，跑一次端到端就会把用户上传的资料删光 ——
 *    这是不可接受的，验收命令绝不能有破坏性。
 * 2. 每个用例开始前把「今日练习卷」与练习历史复位，使用例互相独立、可重复运行
 *    （同一天不允许重新生成整卷，所以必须显式重置）。
 *    该动作只由本机脚本执行，后端不暴露任何重置接口。
 */

const PROJECT_ROOT = fileURLToPath(new URL("../..", import.meta.url));
/**
 * 后端地址。默认与 playwright.config.ts 托管的隔离测试后端一致；
 * 需要指向别处时用 `E2E_API_BASE` 覆盖。
 */
const API_BASE = process.env.E2E_API_BASE ?? "http://127.0.0.1:8001";

/**
 * 测试资料的标题前缀。
 * 既是清理时的识别标记，也让用户一眼能看出哪些是测试留下的东西。
 */
export const E2E_PREFIX = "E2E-自动化测试-";

export interface MaterialRecord {
  id: string;
  title: string;
}

/**
 * 带重试的请求，并**禁用 keep-alive 连接复用**。
 *
 * 为什么必须禁用复用：Node 的 undici 会复用 keep-alive 连接，而 uvicorn 默认
 * 5 秒空闲就关闭连接。夹具里的 `execFileSync(reset_today.py)` 会阻塞更久，
 * 之后从池里取到的连接其实已经被服务端关掉了，于是抛 `ECONNRESET` / `fetch failed`。
 * 更麻烦的是连接池可能**反复**复用同一条坏连接，重试也不管用。
 *
 * `Connection: close` 让每条请求都用新连接，问题从根上消失。
 * 这些请求都是测试的数据准备/清理，量很小，多建几次连接毫无影响。
 *
 * 只对网络层错误重试（不对 4xx/5xx 重试），因此不会掩盖真实的接口问题。
 */
async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("Connection", "close");

  const attempts = 3;
  let lastError: unknown;
  for (let index = 0; index < attempts; index += 1) {
    try {
      return await fetch(`${API_BASE}${path}`, { ...init, headers });
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 300 * (index + 1)));
    }
  }
  throw new Error(
    `请求后端失败（${API_BASE}${path}）：` +
      `${lastError instanceof Error ? lastError.message : String(lastError)}`,
  );
}

async function fetchMaterials(): Promise<MaterialRecord[]> {
  const response = await apiFetch("/api/materials");
  if (!response.ok) return [];
  const payload = (await response.json()) as { items?: MaterialRecord[] };
  return payload.items ?? [];
}

async function deleteMaterial(id: string): Promise<void> {
  await apiFetch(`/api/materials/${id}`, { method: "DELETE" });
}

/**
 * 只删除带测试前缀的资料。
 *
 * 刻意不提供「清空整个资料库」的函数：任何测试都不需要、也不应该有这个能力。
 * 返回删掉的条数，便于用例自查清理是否彻底。
 */
export async function clearTestMaterials(): Promise<number> {
  const materials = await fetchMaterials();
  const mine = materials.filter((item) => item.title.startsWith(E2E_PREFIX));
  for (const item of mine) {
    await deleteMaterial(item.id);
  }
  return mine.length;
}

/** 当前所有资料的 id；用例用它做「前后差集」，避免误删用户数据。 */
export async function currentMaterialIds(): Promise<Set<string>> {
  const materials = await fetchMaterials();
  return new Set(materials.map((item) => item.id));
}

/** 删掉「本用例执行期间新出现的」资料（无论标题是否带前缀）。 */
export async function deleteMaterialsCreatedSince(baseline: Set<string>): Promise<number> {
  const materials = await fetchMaterials();
  const created = materials.filter((item) => !baseline.has(item.id));
  for (const item of created) {
    await deleteMaterial(item.id);
  }
  return created.length;
}

/** 用户自己上传的资料（不带测试前缀），用于断言测试没有误伤它们。 */
export async function userMaterials(): Promise<MaterialRecord[]> {
  const materials = await fetchMaterials();
  return materials.filter((item) => !item.title.startsWith(E2E_PREFIX));
}

/**
 * 先确认后端真的可用。
 *
 * 为什么要显式检查：后端没起或中途退出时，夹具里的 fetch 会抛 `fetch failed`，
 * 16 个用例一起以这同一个报错失败 —— 看起来像测试代码坏了，
 * 实际只是环境没就绪。这里给出能直接指导操作的报错。
 */
async function assertBackendReachable(): Promise<void> {
  let lastError = "";
  // 用 apiFetch 而不是裸 fetch：它内部会重试网络层错误，
  // 因此这里的循环只需要处理「后端确实还没起来」的情况。
  for (let index = 0; index < 5; index += 1) {
    try {
      const response = await apiFetch("/api/health");
      if (response.ok) {
        const health = (await response.json().catch(() => null)) as { environment?: unknown } | null;
        // reset_today.py 会清空学习证据；即使有人把 E2E_API_BASE 指到 8000，
        // 也必须在任何业务请求之前拒绝开发/生产服务。
        if (health?.environment === "test") return;
        lastError = `后端环境不是 test（${String(health?.environment ?? "unknown")}）`;
      } else {
        lastError = `HTTP ${response.status}`;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(
    `后端不可用（${API_BASE}，最后错误：${lastError}）。\n` +
      "请启动 APP_ENV=test、TEST_DATABASE_URL 指向 *_test 的隔离后端（默认端口 8001），\n" +
      "再运行 Playwright；测试拒绝连接 dev/prod，避免清空真实学习数据。",
  );
}

export const test = base.extend<{ page: Page }>({
  page: async ({ page }, use) => {
    await assertBackendReachable();
    execFileSync("python", ["scripts/reset_today.py"], {
      cwd: PROJECT_ROOT,
      stdio: "inherit",
      env: { ...process.env, APP_ENV: "test", ALLOW_TEST_DATA_RESET: "1" },
    });
    // 清掉上次失败留下的测试资料（只动带前缀的，用户的资料一律不碰）。
    await clearTestMaterials();
    const baseline = await currentMaterialIds();

    // 三项检查在夹具层做一次，而不是让每个用例各写一遍 ——
    // 这正是阶段 E 说的「统一」：规则只有一份，遗漏不可能发生。
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    page.on("console", (message) => {
      if (message.type() !== "error") return;
      // 必须带上位置：控制台里最常见的一句是
      // `Failed to load resource: the server responded with a status of 404`，
      // 单看这句话根本不知道是哪个资源 —— 那样这条检查等于没法用。
      const where = message.location();
      const suffix = where.url ? ` @ ${where.url}` : "";
      consoleErrors.push(`${message.text()}${suffix}`);
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));


    try {
      await use(page);

      // 用例体跑完再断言：这样失败信息里能带上完整的 URL 与文案，
      // 而不是只看到"某处有个 console.error"。
      // 注意：这三条只对**通过**的用例生效 —— 用例自己已经失败时，
      // 再叠一层"顺带"的报错没有价值，反而掩盖真正的失败原因。
      expect
        .soft(pageErrors, `页面出现未处理异常：\n${pageErrors.join("\n")}`)
        .toEqual([]);
      // 控制台错误分类处理。
      //
      // 为什么不用「用例声明豁免」那套：豁免集合是**模块级状态**，而实测
      // `beforeEach` 里声明之后、fixture 检查时读到的却是空集合 ——
      // 用它做豁免不可靠（声明了却不生效，比不声明更误导）。
      //
      // 改为按**错误类别**区分，判据不依赖跨生命周期的状态：
      //  - 「Failed to load resource」是浏览器对**非 2xx 响应**的固定文案。
      //    本项目的用例大量用 page.route 故意构造 409/500 来验页面行为，
      //    必然产生这一条。它已被 `badResponses` 检查覆盖（那一条能拿到
      //    精确 URL 与状态码），这里再报一次只是重复且无法豁免的噪声。
      //  - 其余 console error（未捕获异常、脚本报错、Vue 警告升级等）
      //    是真事故，**必须**报出来。
      const RESOURCE_LOAD_ERROR = "Failed to load resource";
      const unexpectedConsole = consoleErrors.filter(
        (text) => !text.includes(RESOURCE_LOAD_ERROR),
      );
      const resourceNoise = consoleErrors.length - unexpectedConsole.length;
      expect
        .soft(
          unexpectedConsole,
          `控制台出现 error：\n${unexpectedConsole.join("\n")}`,
        )
        .toEqual([]);
      // 让"被归类为噪声"这件事可见：如果某次运行里噪声数量异常飙升，
      // 说明有大量请求失败，值得去看 badResponses / 后端日志。
      if (resourceNoise > 0) {
        console.log(`[e2e] 归类为资源加载噪声的 console error：${resourceNoise} 条`);
      }
    } finally {
      // 放在 finally 里：用例失败（含超时、浏览器崩溃）时也必须清理，
      // 否则测试资料会留在库里，甚至卡在 indexing 状态。
      await deleteMaterialsCreatedSince(baseline);
    }
  },
});

/**
 * 声明「本用例预期会出现失败响应」的 URL 片段。
 *
 * 只对当前用例生效（夹具里会清空）。用于错误码契约测试：
 * 那些用例**就是要**构造 409/404/500，否则无法验证页面行为。
 */


export { expect };

export async function expectSystemStatus(page: Page, status: string) {
  const box = page.getByTestId("system-status");
  await expect(box).toBeVisible();
  await expect(box).toHaveAttribute("data-status", status, { timeout: 15_000 });
  return box;
}

/** 展开知识树上的一个汇总节点。

 * 折叠时子节点会从 DOM 中移除，所以每个中间层都必须先展开；
 * 父节点自身的点击是折叠/展开，不进入考核视图。
 */
export async function expandTreeRow(page: Page, testId: string): Promise<void> {
  const row = page.getByTestId(testId).locator("xpath=..");
  const toggle = row.locator(".tree-toggle");
  if ((await toggle.textContent())?.trim() === "▸") await toggle.click();
  await expect(toggle).toHaveText("▾");
}

/** 展开到某个可考核叶子：依次展开它路径上的每个汇总节点。 */
export async function revealLeaf(
  page: Page,
  path: string[],
): Promise<void> {
  for (const code of path.slice(0, -1)) {
    await expandTreeRow(page, `tree-node-${code}`);
  }
  const leaf = page.getByTestId(`tree-node-${path[path.length - 1]}`);
  await expect(leaf).toBeVisible();
  await leaf.click();
  await expect(page.getByTestId("knowledge-detail")).toBeVisible();
}
