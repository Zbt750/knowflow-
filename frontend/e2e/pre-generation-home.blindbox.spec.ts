import { expect, test } from "./fixtures";

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 430, height: 932 },
  { width: 390, height: 844 },
  { width: 360, height: 800 },
];

for (const viewport of VIEWPORTS) {
  test(`PRE_GENERATION：首页只显示方案摘要与真实准入题量 @${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/study");
    await expect(page.getByTestId("home-recommendation-assistant")).toBeVisible();
    const systemCard = page.getByTestId("workbench-system-recommendation");
    await expect(systemCard).toBeVisible({ timeout: 30_000 });

    const result = await page.evaluate(async () => {
      const response = await fetch("/api/plans/today/home-recommendation");
      const paperResponse = await fetch("/api/plans/today");
      return { status: response.status, body: await response.json(),
        paperStatus: paperResponse.status, paper: await paperResponse.json() };
    });
    expect(result.status).toBe(200);
    expect(result.body.inventory).toBeTruthy();
    expect(result.body.inventory.practice_eligible_count).toBeGreaterThanOrEqual(0);
    expect(result.body.inventory.recommendation_nodes).toEqual(
      expect.arrayContaining(result.body.recommendations.map((node: { kp_id: string }) =>
        expect.objectContaining({ kp_id: node.kp_id, practice_eligible_count: expect.any(Number) }),
      )),
    );
    expect(result.body.initial_paper?.questions ?? []).toEqual([]);
    expect(result.paperStatus).toBe(200);
    expect(result.paper).not.toHaveProperty("plan_id");
    expect(result.paper).not.toHaveProperty("items");
    expect(JSON.stringify(result.body)).not.toMatch(
      /"(?:question_id|question_version_id|stem|options|correct_answer|explanation)"/,
    );

    const shown = await systemCard.innerText();
    if (result.body.recommendations.length) {
      expect(shown).toMatch(/\d+道可用题/);
      expect(shown).toContain("今日安排");
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      viewport.width + 1,
    );
    await expect(page.getByTestId("confirm-home-paper")).toBeEnabled();
    await expect(page.getByTestId("confirm-home-paper")).toContainText("确定生成试卷");
    await expect(page.getByText("尚未生成正式试卷")).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`homepage-${viewport.width}.png`), fullPage: true });
    if (viewport.width === 1440) {
      const measurement = await page.evaluate(async () => {
        const milliseconds: number[] = []; const signatures: string[] = [];
        const profiles: Array<Record<string, unknown>> = [];
        for (let i = 0; i < 10; i++) {
          const start = performance.now();
          const response = await fetch('/api/plans/today/home-recommendation');
          if (!response.ok) throw new Error(`Homepage timing HTTP ${response.status}`);
          const body = await response.json(); milliseconds.push(performance.now() - start);
          signatures.push(JSON.stringify(body.recommendations.map((node: { kp_id: string }) => node.kp_id)));
          profiles.push({
            sql_count: Number(response.headers.get('x-sql-count') ?? 0),
            sql_seconds: Number(response.headers.get('x-sql-seconds') ?? 0),
            service_seconds: Number(response.headers.get('x-service-seconds') ?? 0),
            service_non_sql_seconds: Number(response.headers.get('x-service-non-sql-seconds') ?? 0),
            top_sql: response.headers.get('x-sql-top') ?? '',
            top_stacks: JSON.parse(response.headers.get('x-sql-stack') ?? '[]'),
          });
        }
        const sorted = [...milliseconds].sort((a, b) => a - b);
        return { milliseconds, p50_ms: (sorted[4] + sorted[5]) / 2, stable_recommendation_ids: new Set(signatures).size === 1,
          signatures, profiles,
          scope: '10 warm live HTTP reads with per-request SQL and service non-SQL timing; no before-after optimization claim' };
      });
      expect(measurement.stable_recommendation_ids).toBe(true);
      await test.info().attach('homepage-http-timings.json', { body: JSON.stringify(measurement, null, 2), contentType: 'application/json' });
    }
    const confirm = page.getByTestId("confirm-home-paper");
    await confirm.scrollIntoViewIfNeeded();
    // The primary action must be reachable above the fixed mobile navigation,
    // not merely enabled behind it. Trial checks hit testing without writing.
    await confirm.click({ trial: true });
    await confirm.click();
    const paper = () => page.evaluate(async () => (await fetch('/api/plans/today')).json());
    await expect.poll(async () => (await paper()).total_count ?? 0, { timeout: 30_000 }).toBeGreaterThan(0);
    const generated = await paper();
    const bindings = generated.items.map((item: { id: string; question_id: string; question_version_id: string }) =>
      [item.id, item.question_id, item.question_version_id]);
    expect(bindings.every((row: string[]) => row.every(Boolean))).toBe(true);
    expect(new Set(bindings.map((row: string[]) => row[1])).size).toBe(bindings.length);
    await page.reload();
    await expect.poll(async () => (await paper()).items.map(
      (item: { id: string; question_id: string; question_version_id: string }) =>
        [item.id, item.question_id, item.question_version_id]), { timeout: 30_000 }).toEqual(bindings);
    await page.screenshot({ path: test.info().outputPath(`generated-paper-${viewport.width}.png`), fullPage: true });
  });
}
