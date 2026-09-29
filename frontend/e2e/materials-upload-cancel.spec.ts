import { expect, test } from "@playwright/test";

test("资料上传过程中可以取消浏览器请求", async ({ page }) => {
  test.setTimeout(30_000);
  let releaseUpload!: () => void;
  let requestObserved = false;
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve; });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    // Vite 的源码模块路径也含 `/api/` 目录（例如 `/src/api/materials.ts`），
    // 只 mock 真正以 `/api/` 开头的服务端路由，其他资源照常交给 Vite。
    if (!path.startsWith("/api/")) return route.continue();
    if (path === "/api/health") {
      return route.fulfill({ json: { status: "ok", database: "connected", environment: "test", retrieval: "ready", worker: "running" } });
    }
    if (path === "/api/materials" && request.method() === "GET") {
      return route.fulfill({ json: { items: [], total: 0, stats: { total: 0, ready: 0 } } });
    }
    if (path === "/api/materials" && request.method() === "POST") {
      requestObserved = true;
      await uploadGate;
      try {
        await route.fulfill({ status: 201, json: { material: {}, job_id: "cancelled", message: "uploaded" } });
      } catch {
        // 浏览器已 abort 请求时，Playwright 不再有待完成的 response 可 fulfill。
      }
      return;
    }
    return route.fulfill({ json: {} });
  });

  try {
    await page.goto("/materials");
    await expect(page.getByTestId("materials-page")).toBeVisible();
    await page.getByTestId("upload-file").setInputFiles({
      name: "temporary.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# 临时资料\n"),
    });
    await page.getByTestId("upload-title").fill("取消上传测试");
    await expect(page.getByTestId("upload-submit")).toBeEnabled();
    await page.getByTestId("upload-submit").click();
    await expect.poll(() => requestObserved).toBe(true);
    const cancel = page.getByTestId("upload-cancel");
    await expect(cancel).toHaveText("取消上传");
    await cancel.click();
    await expect(page.getByTestId("upload-notice")).toContainText("已取消上传请求");
    await expect(page.getByTestId("upload-form")).toHaveCount(0);
  } finally {
    releaseUpload();
  }
});
