import { defineConfig } from "@playwright/test";

/**
 * Playwright 配置。
 *
 * 关于后端：
 * 后端**不由 Playwright 托管**，而是要求先独立启动：
 *
 *     APP_ENV=test ... uvicorn backend.app:create_app --port 8001
 *
 * 为什么不做成 webServer 自动托管：本环境下由 Playwright 通过管道托管的 Python
 * 进程会被杀掉（单个用例能过，后续用例全部 `fetch failed`），
 * 而 Playwright 的 url 健康检查是「只在没有实时读取输出时才发现」，
 * 因此启动看起来是成功的 —— 这类问题极难排查，不如明确要求独立启动。
 *
 * 后端没起时，`e2e/fixtures.ts` 会给出明确的起步指引，而不是一堆 fetch failed。
 *
 * 环境变量：
 * - `E2E_API_BASE`：测试访问的后端地址（默认 http://127.0.0.1:8001）
 * - `E2E_WEB_BASE`：前端地址（默认 http://127.0.0.1:5174）
 */

const API_BASE = process.env.E2E_API_BASE ?? "http://127.0.0.1:8001";
const WEB_BASE = process.env.E2E_WEB_BASE ?? "http://127.0.0.1:5174";

export default defineConfig({
  testDir: "./e2e",
  reporter: [["list"]],
  // 用例共享同一份数据库状态；串行执行避免互相干扰。
  workers: 1,
  // 单个用例 3 分钟。
  // 默认只有 30 秒，而「上传 → 后台加载 embedding 模型 → 建索引 → 状态变可检索」
  // 在冷启动时可能接近 1 分钟；默认值会让用例在断言等待期间就被整体砍掉，
  // 报错看起来像断言失败，实际是超时。断言自己的 timeout 不得超过这个值。
  timeout: 180_000,
  use: {
    baseURL: WEB_BASE,
    // 验收要求覆盖 **1366×768**（常见笔记本分辨率）与窄窗口。
    // 固定成 1366×768 当基准：Playwright 默认是 1280×720，
    // 不固定的话「某尺寸下按钮被挤出视口」这类问题永远测不到，
    // 而且不同机器上跑出来的布局断言也无法复现。
    viewport: { width: 1366, height: 768 },
    // 失败时留下截图：前端渲染类问题光看断言报错看不出页面到底长什么样。
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    // 保留失败产物。
    //
    // 默认值是 "on-first-retry"，而本配置没有开 retries ——
    // 结果是**一次偶发失败跑完之后 test-results 里空空如也**，
    // 只剩终端上一行断言信息，根本无法复盘（learning-flow 的
    // paper-list 未出现就是这么丢掉证据的）。
    // 这里改成 always，代价是每次跑完都要清理 test-results
    // （该目录已被 vite server.watch.ignored 忽略，不会触发前端热更新）。
    preserveOutput: "always",
    // 使用本机已安装的 Chrome，而不是下载 Playwright 自带 chromium：
    // 本机 cdn.playwright.dev 不可达（下载 0 字节），系统 Chrome 可用且行为一致。
    channel: "chrome",
  },
  webServer: {
    command: "npm run dev -- --port 5174",
    url: WEB_BASE,
    // 让浏览器页面、fixture 和测试后端始终落在同一套隔离服务上。
    env: { ...process.env, VITE_API_PROXY_TARGET: API_BASE },
    // 开发服务器若已在运行则直接复用，避免端口冲突。
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
