import { expect, test } from './fixtures';

test('R37: 408库存不足时报告缺口并保留当前正式卷', async ({ page }) => {
  const paper = () => page.evaluate(async () => (await fetch('/api/plans/today')).json());
  await page.goto('/study');
  await page.getByTestId('confirm-home-paper').click();
  await expect.poll(async () => (await paper()).total_count ?? 0, { timeout: 30000 }).toBeGreaterThan(0);
  const before = await paper();
  const panel = page.getByTestId('learning-task-panel');
  if ((await panel.getAttribute('open')) === null) await page.getByTestId('study-frog-launcher').click();
  await page.getByTestId('task-goal').fill(
    '把当前数学题全部换成408，根据我没有做过的知识点安排6个知识点，预算60分钟左右。',
  );
  await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('task-goal')).toBeEnabled({ timeout: 30000 });
  await expect(page.getByTestId('task-goal')).toHaveValue('');
  const response = page.getByTestId('frog-message-assistant').last();
  await expect(response).toHaveAttribute('data-status', 'completed', { timeout: 30000 });
  await expect(response).toContainText('未创建方案，原卷保留');
  const message = await response.innerText();
  const after = await paper();
  expect(after.plan_id).toBe(before.plan_id);
  expect(after.total_count).toBe(before.total_count);
  expect(after.items.map((item: { question_id: string }) => item.question_id))
    .toEqual(before.items.map((item: { question_id: string }) => item.question_id));
  await test.info().attach('r37-cross-subject-shortage.json', {
    body: JSON.stringify({
      status: 'BLOCKED_BY_REAL_INVENTORY_SHORTAGE',
      evidence_kind: 'REAL_BROWSER_AND_HTTP_WITH_ISOLATED_POSTGRES',
      database_is_test_fixture: true,
      request: '把当前数学题全部换成408，根据我没有做过的知识点安排6个知识点，预算60分钟左右。',
      response: message,
      plan_id_before: before.plan_id,
      plan_id_after: after.plan_id,
      active_question_ids_before: before.items.map((item: { question_id: string }) => item.question_id),
      active_question_ids_after: after.items.map((item: { question_id: string }) => item.question_id),
    }, null, 2),
    contentType: 'application/json',
  });
  await page.screenshot({ path: test.info().outputPath('408-shortage-original-paper-preserved.png'), fullPage: true });
});
