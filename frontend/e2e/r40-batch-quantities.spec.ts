import { readFileSync } from 'node:fs';
import { expect, test } from './fixtures';

for (const width of [1440, 430, 390, 360]) {
  test(`正式卷混合题量、刷新与追加后首次作答 @${width}px`, async ({ page }) => {
    const fixturePath = process.env.R40_BATCH_FIXTURE;
    expect(fixturePath, 'Run the owned R40 browser station with marked synthetic inventory').toBeTruthy();
    const fixture = JSON.parse(readFileSync(fixturePath!, 'utf8'));
    expect(fixture.synthetic_inventory).toBe(true);
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/study');
    // Arrange the initial paper through actual APIs, then perform all batch
    // dialogue, confirmation and submission through the real visible UI.
    const prepared = await page.evaluate(async fixture => {
      const created = await fetch('/api/plans/today/generate', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_kp_ids: [fixture.base_kp_id], budget: 'light' }) });
      if (created.status !== 201) throw new Error(await created.text());
      const plan = await created.json();
      const added = await fetch(`/api/plans/${plan.plan_id}/questions`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question_ids: fixture.topics.flatMap((t: { initial_question_ids: string[] }) => t.initial_question_ids) }) });
      if (!added.ok) throw new Error(await added.text());
      return added.json();
    }, fixture);
    const paper = () => page.evaluate(async () => (await fetch('/api/plans/today')).json());
    await page.reload();
    await expect(page.getByTestId('focus-question')).toBeVisible({ timeout: 30000 });
    const panel = page.getByTestId('learning-task-panel');
    async function say(message: string) {
      if ((await panel.getAttribute('open')) === null) await page.getByTestId('study-frog-launcher').click();
      await page.getByTestId('task-goal').fill(message);
      await page.getByTestId('task-arrange').click();
      await expect(page.getByTestId('task-goal')).toBeEnabled({ timeout: 30000 });
      await expect(page.getByTestId('task-goal')).toHaveValue('');
      const answer = page.getByTestId('frog-message-assistant').last();
      await expect(answer).toHaveAttribute('data-status', 'completed', { timeout: 30000 });
      return answer;
    }
    const initial = await paper();
    expect(initial.total_count).toBe(prepared.total_count);
    for (const topic of fixture.topics) expect(initial.items.filter((i: { kp_id: string }) => i.kp_id === topic.kp_id)).toHaveLength(2);
    await expect(await say('能不能减少一道批量甲节点的题，增加两道批量乙节点的题？')).toContainText('未修改');
    expect((await paper()).total_count).toBe(initial.total_count);
    const preview = await say('减少一道批量甲节点的题目，增加两道批量乙节点的题目。');
    await expect(preview).toContainText('批量甲节点：2→1道');
    await expect(preview).toContainText('批量乙节点：2→4道');
    expect((await paper()).total_count).toBe(initial.total_count);
    await expect(await say('确认调整')).toContainText('新增2道');
    await expect.poll(async () => (await paper()).total_count).toBe(initial.total_count + 1);
    const changed = await paper();
    expect(changed.items.filter((i: { kp_id: string }) => i.kp_id === fixture.topics[0].kp_id)).toHaveLength(1);
    expect(changed.items.filter((i: { kp_id: string }) => i.kp_id === fixture.topics[1].kp_id)).toHaveLength(4);
    const oldIds = new Set(initial.items.map((i: { id: string }) => i.id));
    const additions = changed.items.filter((i: { id: string }) => !oldIds.has(i.id));
    expect(additions).toHaveLength(2);
    expect(additions.every((i: { kp_id: string; question_version_id: string; stem: string }) =>
      i.kp_id === fixture.topics[1].kp_id && i.question_version_id && i.stem)).toBe(true);
    await page.reload();
    expect((await paper()).items.map((i: { id: string; question_version_id: string }) => [i.id, i.question_version_id]))
      .toEqual(changed.items.map((i: { id: string; question_version_id: string }) => [i.id, i.question_version_id]));
    const target = additions[0];
    await page.goto(`/study?item_id=${target.id}`);
    await expect(page.getByTestId('focus-question')).toContainText(target.stem);
    await page.getByTestId('option-A').check();
    await page.getByTestId('submit-answer').click();
    await expect(page.getByTestId('answer-submission-notice')).toBeVisible();
    const answered = (await paper()).items.find((i: { id: string }) => i.id === target.id);
    expect(answered.completed).toBe(true);
    expect(answered.question_version_id).toBe(target.question_version_id);
    await expect(await say(`删除第${target.display_number}题`)).toContainText('系统保留了题目与历史记录');
    expect((await paper()).total_count).toBe(initial.total_count + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await test.info().attach('real-paper-after-batch', { body: JSON.stringify(await paper(), null, 2), contentType: 'application/json' });
    await page.screenshot({ path: test.info().outputPath(`mixed-batch-${width}.png`), fullPage: true });
  });
}
