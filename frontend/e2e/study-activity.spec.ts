// Real browser interactions with a fully intercepted API surface. These cases
// verify UI activity events only; they do not claim PostgreSQL persistence.
import { expect, test, type Page } from '@playwright/test';

const active = {
  status: 'active', study_date: '2026-11-03', plan_id: '99999999-9999-4999-8999-999999999999',
  completed_count: 0, total_count: 2, retry_wrong_items: [], focus_item_id: 'q1', summary_kps: [],
  type_summary: { single_choice: 2 }, estimated_minutes: 6, remaining_minutes: 6,
  items: ['q1', 'q2'].map((id, index) => ({
    id, ordinal: index + 1, display_number: index + 1, kp_id: '22222222-2222-4222-8222-222222222222',
    kp_name: 'SYNTHETIC 洛必达法则', question_id: `question-${id}`, question_version_id: `version-${id}`,
    question_type: 'single_choice', question_role: 'basic', difficulty: 'basic',
    stem: `SYNTHETIC 测试题 ${index + 1}：\u0078 的极限为？`, options: { A: '0', B: '1' },
    skill_tags: [], is_variant: false, estimated_minutes: 3, is_review: false, completed: false,
    completed_at: null, latest_self_grade: null, is_external_reference: false, exam_reference: null,
    answer_grading_method: 'single_choice',
  })),
};

async function installApi(page: Page, options: { failSkipOnce?: boolean } = {}) {
  const activityRequests: Array<{ itemId: string; kind: string; key: string }> = [];
  const answerRequests: string[] = [];
  let skippedFailures = 0;
  await page.route(/^https?:\/\/[^/]+\/api(?:\/|$)/, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/health') return route.fulfill({ json: { status: 'ok', database: 'connected', environment: 'test', llm_configured: false } });
    if (url.pathname === '/api/plans/today' && request.method() === 'GET') return route.fulfill({ json: structuredClone(active) });
    if (url.pathname === '/api/materials') return route.fulfill({ json: { items: [], total: 0, stats: { total: 0, ready: 0 } } });
    if (url.pathname === '/api/practice-requests') return route.fulfill({ json: [] });
    if (url.pathname === '/api/knowledge/tree') return route.fulfill({ json: { nodes: [] } });
    if (url.pathname === '/api/chat/sessions' && request.method() === 'GET') return route.fulfill({ json: [] });
    if (url.pathname.match(/^\/api\/practice-items\/[^/]+\/answer-submissions$/)) {
      answerRequests.push(url.pathname);
      return route.fulfill({ json: { result: 'right', submitted_at: '2026-11-03T12:00:00Z' } });
    }
    const activity = url.pathname.match(/^\/api\/practice-items\/([^/]+)\/activity$/);
    if (activity && request.method() === 'POST') {
      const body = request.postDataJSON() as { kind: string; idempotency_key: string };
      activityRequests.push({ itemId: activity[1], kind: body.kind, key: body.idempotency_key });
      if (options.failSkipOnce && body.kind === 'skipped' && skippedFailures === 0) {
        skippedFailures += 1;
        return route.fulfill({ status: 503, json: { error: { code: 'test_offline', message: '临时离线' } } });
      }
      return route.fulfill({ json: { event_id: `activity-${body.kind}-${activity[1]}`, kind: body.kind } });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'mock_api_unconfigured', message: `无 Mock API 夹具：${request.method()} ${url.pathname}` } } });
  });
  return { activityRequests, answerRequests };
}

test('study focus: skip persists before navigation and never submits an answer', async ({ page }) => {
  const state = await installApi(page);
  await page.goto('/study');
  await expect(page.getByTestId('focus-question')).toHaveAttribute('data-item-id', 'q1');
  await page.getByTestId('skip-question').click();
  await expect(page.getByTestId('focus-question')).toHaveAttribute('data-item-id', 'q2');
  await expect.poll(() => state.activityRequests.some((row) => row.itemId === 'q1' && row.kind === 'skipped')).toBe(true);
  expect(state.answerRequests).toEqual([]);
});

test('study focus: failed skip stays on the question and retries with the same idempotency key', async ({ page }) => {
  const state = await installApi(page, { failSkipOnce: true });
  await page.goto('/study');
  await expect(page.getByTestId('focus-question')).toHaveAttribute('data-item-id', 'q1');
  await page.getByTestId('skip-question').click();
  await expect(page.getByTestId('focus-question')).toHaveAttribute('data-item-id', 'q1');
  await expect(page.getByRole('alert')).toContainText('学习行为保存失败');
  await page.getByTestId('skip-question').click();
  await expect(page.getByTestId('focus-question')).toHaveAttribute('data-item-id', 'q2');
  const skipped = state.activityRequests.filter((row) => row.itemId === 'q1' && row.kind === 'skipped');
  expect(skipped).toHaveLength(2);
  expect(skipped[0].key).toBe(skipped[1].key);
  expect(state.answerRequests).toEqual([]);
});

test('study paper preview: only questions actually entering the viewport are recorded as viewed', async ({ page }) => {
  const state = await installApi(page);
  await page.goto('/study');
  await page.getByTestId('full-paper').click();
  const first = page.locator('[data-testid="paper-list"] [data-item-id="q1"]');
  const second = page.locator('[data-testid="paper-list"] [data-item-id="q2"]');
  await first.scrollIntoViewIfNeeded();
  await expect.poll(() => state.activityRequests.some((row) => row.itemId === 'q1' && row.kind === 'viewed')).toBe(true);
  await second.scrollIntoViewIfNeeded();
  await expect.poll(() => state.activityRequests.some((row) => row.itemId === 'q2' && row.kind === 'viewed')).toBe(true);
  expect(state.answerRequests).toEqual([]);
});
