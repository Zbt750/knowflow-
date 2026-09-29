import { expect, test } from "@playwright/test";

test("设置页保存即生效、留空保留密钥、成功后清空输入、刷新不回显", async ({ page }) => {
  let config = { base_url: "https://example.com/v1", model: "old-model", key_configured: true, max_output_tokens: 4000, timeout_seconds: 60, csrf_token: "test-csrf", storage_warning: false };
  const bodies: Record<string, unknown>[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/health") return route.fulfill({ json: { status: "ok", database: "connected", retrieval: "ready", worker: "running", environment: "dev", llm_configured: config.key_configured, llm_model: config.model } });
    if (path === "/api/settings/model") {
      if (request.method() === "PUT") {
        expect(request.headers()["x-settings-token"]).toBe("test-csrf");
        const body = request.postDataJSON();
        bodies.push(body);
        config = { ...config, base_url: body.base_url, model: body.model, max_output_tokens: body.max_output_tokens, timeout_seconds: body.timeout_seconds, key_configured: body.clear_key ? false : Boolean(body.api_key) || config.key_configured };
      }
      return route.fulfill({ json: config });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto("/settings");
  await expect(page.locator(".workspace-main h1")).toHaveText("设置");
  await expect(page.getByTestId("model-api-key")).toHaveValue("");
  await page.getByTestId("model-name").fill("new-model");
  await page.getByTestId("model-api-key").fill("unsaved-refresh-check");
  await page.getByRole("button", { name: "刷新状态" }).click();
  await expect(page.getByTestId("model-api-key")).toHaveValue("unsaved-refresh-check");
  await page.getByTestId("model-api-key").fill("");
  await page.getByTestId("save-model-settings").click();
  await expect(page.getByRole("status")).toContainText("下一次问答立即使用新配置");
  expect(bodies[0]).not.toHaveProperty("api_key");
  await page.getByTestId("model-api-key").fill("fake-test-key-only");
  await page.getByTestId("save-model-settings").click();
  await expect(page.getByTestId("model-api-key")).toHaveValue("");
  expect(bodies[1].api_key).toBe("fake-test-key-only");
  expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage))).not.toContain("fake-test-key-only");
  await page.reload();
  await expect(page.getByTestId("model-name")).toHaveValue("new-model");
  await expect(page.getByTestId("model-api-key")).toHaveValue("");
  await page.getByLabel("移除已保存的密钥", { exact: false }).check();
  await page.getByTestId("save-model-settings").click();
  await expect(page.getByText("尚未配置完整")).toBeVisible();
  expect(bodies[2].clear_key).toBe(true);
});

test("保存失败保留输入，显示具体字段错误，不误报成功", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route(/^https?:\/\/[^/]+\/api\//, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health") return route.fulfill({ json: { status: "ok", database: "connected", environment: "dev" } });
    if (route.request().method() === "PUT") return route.fulfill({ status: 422, json: { error: { code: "validation_failed", message: "validation failed", details: [{ field: "body.model", code: "value_error", message: "格式或取值不符合要求" }] } } });
    return route.fulfill({ json: { base_url: "https://example.com/v1", model: "old", key_configured: false, max_output_tokens: 4000, timeout_seconds: 60, csrf_token: "test", storage_warning: false } });
  });
  await page.goto("/settings");
  await page.getByTestId("model-name").fill("new");
  await page.getByTestId("save-model-settings").click();
  await expect(page.getByRole("alert")).toContainText("model：格式或取值不符合要求");
  await expect(page.getByTestId("model-name")).toHaveValue("new");
  await expect(page.getByRole("status")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("远程或生产访问不展示可写表单", async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health") return route.fulfill({ json: { status: "ok", database: "connected", environment: "prod" } });
    return route.fulfill({ status: 403, json: { error: { code: "settings_local_only", message: "local only" } } });
  });
  await page.goto("/settings");
  await expect(page.getByRole("alert")).toContainText("Web 部署暂不开放密钥修改");
  await expect(page.getByTestId("save-model-settings")).toHaveCount(0);
});
