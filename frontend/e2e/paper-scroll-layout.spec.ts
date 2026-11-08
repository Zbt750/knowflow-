import { expect, test, type Page, type TestInfo } from '@playwright/test';

const viewports = [1440, 430, 390, 360] as const;
const questionCount = 18;

const activePlan = {
  status: 'active',
  study_date: '2026-11-07',
  plan_id: '99999999-9999-4999-8999-999999999999',
  completed_count: 0,
  total_count: questionCount,
  retry_wrong_items: [],
  focus_item_id: 'layout-q1',
  summary_kps: [],
  type_summary: { single_choice: questionCount },
  estimated_minutes: questionCount * 3,
  remaining_minutes: questionCount * 3,
  items: Array.from({ length: questionCount }, (_, index) => {
    const ordinal = index + 1;
    const id = `layout-q${ordinal}`;
    return {
      id,
      ordinal,
      display_number: ordinal,
      kp_id: '22222222-2222-4222-8222-222222222222',
      kp_name: 'SYNTHETIC 全卷滚动布局',
      question_id: `layout-question-${ordinal}`,
      question_version_id: `layout-version-${ordinal}`,
      question_type: 'single_choice',
      question_role: 'basic',
      difficulty: 'basic',
      stem: `SYNTHETIC 第 ${ordinal} 题。${'用于验证题目滚动容器和页面滚动边界的内容。'.repeat(8)}`,
      options: { A: '选项 A', B: '选项 B' },
      skill_tags: [],
      is_variant: false,
      estimated_minutes: 3,
      is_review: false,
      completed: false,
      completed_at: null,
      latest_self_grade: null,
      is_external_reference: false,
      exam_reference: null,
      answer_grading_method: 'single_choice',
    };
  }),
};

async function installApi(page: Page) {
  await page.route(/^https?:\/\/[^/]+\/api(?:\/|$)/, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/health') return route.fulfill({ json: { status: 'ok', database: 'connected', environment: 'test' } });
    if (url.pathname === '/api/plans/today' && request.method() === 'GET') return route.fulfill({ json: structuredClone(activePlan) });
    if (url.pathname === '/api/knowledge/tree') return route.fulfill({ json: { nodes: [] } });
    if (url.pathname === '/api/materials') return route.fulfill({ json: { items: [], total: 0, stats: { total: 0, ready: 0 } } });
    if (url.pathname === '/api/practice-requests') return route.fulfill({ json: [] });
    if (url.pathname === '/api/chat/sessions') return route.fulfill({ json: [] });
    if (/^\/api\/practice-items\/[^/]+\/activity$/.test(url.pathname)) {
      return route.fulfill({ json: { event_id: 'layout-only-activity', kind: 'viewed' } });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'layout_test_unconfigured', message: `${request.method()} ${url.pathname}` } } });
  });
}

for (const width of viewports) {
  test(`full-paper scroll layers remain stable at ${width}px`, async ({ page }, testInfo: TestInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await installApi(page);
    await page.goto('/study');
    await expect(page.getByTestId('study-active')).toBeVisible();
    await page.getByTestId('full-paper').click();

    const toolbar = page.locator('.paper-reader-sticky');
    const controls = page.getByTestId('paper-reading-controls');
    const numbers = page.getByTestId('paper-reader-numbers');
    const region = page.getByTestId('paper-scroll-region');
    await expect(page.getByTestId('paper-list').locator('.paper-item')).toHaveCount(questionCount);

    // Position the two sticky rows below the application's own fixed top bar,
    // then treat that page position as invariant while testing the reader.
    await page.evaluate(() => {
      const row = document.querySelector<HTMLElement>('.paper-reader-sticky');
      const header = document.querySelector<HTMLElement>('.app-header');
      if (!row || !header) throw new Error('Missing reader toolbar or app header');
      const target = window.scrollY + row.getBoundingClientRect().top - header.getBoundingClientRect().height;
      window.scrollTo(0, Math.max(0, target));
    });
    await page.waitForTimeout(60);
    const pinned = await page.evaluate(() => {
      const row = document.querySelector<HTMLElement>('.paper-reader-sticky')!;
      const controlsRow = document.querySelector<HTMLElement>('[data-testid="paper-reading-controls"]')!;
      const numberRow = document.querySelector<HTMLElement>('[data-testid="paper-reader-numbers"]')!;
      const header = document.querySelector<HTMLElement>('.app-header')!;
      const list = document.querySelector<HTMLElement>('[data-testid="paper-scroll-region"]')!;
      return {
        pageY: window.scrollY,
        headerBottom: header.getBoundingClientRect().bottom,
        toolbarTop: row.getBoundingClientRect().top,
        controlsBottom: controlsRow.getBoundingClientRect().bottom,
        numbersTop: numberRow.getBoundingClientRect().top,
        numbersBottom: numberRow.getBoundingClientRect().bottom,
        listTop: list.getBoundingClientRect().top,
        position: getComputedStyle(row).position,
      };
    });
    expect(pinned.position).toBe('sticky');
    expect(pinned.toolbarTop).toBeGreaterThanOrEqual(pinned.headerBottom - 1);
    expect(pinned.numbersTop).toBeGreaterThanOrEqual(pinned.controlsBottom - 1);
    expect(pinned.listTop).toBeGreaterThanOrEqual(pinned.numbersBottom - 1);

    const pageY = await page.evaluate(() => window.scrollY);
    const scrollBox = await region.boundingBox();
    expect(scrollBox).not.toBeNull();
    await page.mouse.move(scrollBox!.x + scrollBox!.width / 2, scrollBox!.y + Math.min(180, scrollBox!.height / 2));
    for (let step = 0; step < 50; step += 1) {
      await page.mouse.wheel(0, 500);
      const atEnd = await region.evaluate((element) => element.scrollTop + element.clientHeight >= element.scrollHeight - 1);
      if (atEnd) break;
      await page.waitForTimeout(30);
    }
    await expect.poll(() => region.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    expect(await page.evaluate(() => window.scrollY)).toBe(pageY);
    await expect.poll(() => region.evaluate((element) => element.scrollTop + element.clientHeight)).toBeGreaterThanOrEqual(
      await region.evaluate((element) => element.scrollHeight - 1),
    );
    await expect(page.locator('#paper-item-layout-q18')).toBeInViewport();

    for (const number of [7, 15, 2, 18]) {
      await page.getByRole('button', { name: `跳转第 ${number} 题` }).click();
      const target = page.locator(`#paper-item-layout-q${number}`);
      const targetGeometry = await target.evaluate((element) => {
        const regionElement = element.closest<HTMLElement>('[data-testid="paper-scroll-region"]')!;
        const itemBounds = element.getBoundingClientRect();
        const regionBounds = regionElement.getBoundingClientRect();
        return { top: itemBounds.top - regionBounds.top, bottom: itemBounds.bottom - regionBounds.top };
      });
      // The final item may be unable to align at the very top when the list
      // has no trailing blank space; its heading must still be fully visible.
      if (number !== questionCount) expect(Math.abs(targetGeometry.top - 8)).toBeLessThan(5);
      await expect(target.locator('header')).toBeInViewport();
      const regionBounds = await region.boundingBox();
      expect(targetGeometry.top).toBeGreaterThanOrEqual(7);
      expect(targetGeometry.top).toBeLessThan(regionBounds!.height);
      expect(targetGeometry.bottom).toBeGreaterThan(0);
      expect(await page.evaluate(() => window.scrollY)).toBe(pageY);
    }

    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.getByTestId('paper-ask-frog').click();
    await expect(page.getByTestId('learning-task-panel')).toHaveAttribute('open', '');
    await expect(page.getByTestId('paper-ask-frog')).toBeVisible();

    await page.getByTestId('mode-focus').click();
    await page.getByTestId('full-paper').click();
    await expect(page.getByTestId('paper-reader-numbers')).toBeVisible();
    await page.reload();
    await expect(page.getByTestId('study-active')).toBeVisible();
    await page.getByTestId('full-paper').click();
    await expect(page.getByTestId('paper-reader-numbers')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`full-paper-${width}px.png`), fullPage: false });
  });
}
