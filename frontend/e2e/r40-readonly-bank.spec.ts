import { expect, test } from './fixtures';

for (const width of [1440, 430, 390, 360]) {
  test(`R40只读选题不创建方案或今日卷 @${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    // Read the real SSE bytes as the app receives them. Chromium's devtools
    // response cache may evict a streaming body during the session URL change.
    await page.addInitScript(() => {
      const fetch = window.fetch.bind(window);
      window.fetch = async (...args) => {
        const response = await fetch(...args);
        if (response.url.includes('/assistant:stream')) {
          void response.clone().text().then(text => sessionStorage.setItem('r40-real-sse', text));
        }
        return response;
      };
    });
    await page.goto('/chat');
    const input = page.locator('#chat-question');
    await expect(input).toBeEnabled({ timeout: 30000 });
    const before = await page.evaluate(async () => (await fetch('/api/plans/today')).json());
    expect(before).not.toHaveProperty('plan_id');
    await input.fill('先选一道洛必达法则题，让我看看。');
    await page.locator('.send-button').click();
    await page.waitForFunction(() => sessionStorage.getItem('r40-real-sse')?.includes('event: done'), undefined, { timeout: 30000 });
    const stream = (await page.evaluate(() => sessionStorage.getItem('r40-real-sse')))!;
    await test.info().attach('real-assistant-stream', { body: stream, contentType: 'text/event-stream' });
    expect(stream).toMatch(/"capability":\s*"data_query"/);
    expect(stream).toMatch(/"intent":\s*"find"/);
    expect(stream).not.toMatch(/event: (?:planner|practice_request|personal_generation)\n/);
    await expect(input).toBeEnabled({ timeout: 30000 });
    const answer = page.locator('.message-row--assistant').last();
    await expect(answer).toContainText('洛必达');
    await expect(page.getByTestId('practice-request-card')).toHaveCount(0);
    const after = await page.evaluate(async () => (await fetch('/api/plans/today')).json());
    expect(after).not.toHaveProperty('plan_id');
    const shown = await answer.innerText();
    await page.reload();
    await expect(page.locator('.message-row--assistant').last()).toContainText('洛必达');
    expect(await page.locator('.message-row--assistant').last().innerText()).toBe(shown);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await expect(page.locator('.katex-error')).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath(`readonly-selection-${width}.png`), fullPage: true });
  });
}
