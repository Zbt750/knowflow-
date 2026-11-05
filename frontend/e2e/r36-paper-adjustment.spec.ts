import { expect, test } from './fixtures';

test('正式卷聊天移除、浏览保护与刷新回读', async ({ page }) => {
  const paper = () => page.evaluate(async () => (await fetch('/api/plans/today')).json());
  await page.goto('/study');
  await page.getByTestId('confirm-home-paper').click();
  await expect.poll(async () => (await paper()).total_count ?? 0, { timeout: 30000 }).toBeGreaterThan(1);
  const before = await paper();
  const target = before.items.at(-1);
  const panel = page.getByTestId('learning-task-panel');
  async function say(message: string) {
    if ((await panel.getAttribute('open')) === null) await page.getByTestId('study-frog-launcher').click();
    await page.getByTestId('task-goal').fill(message);
    await page.getByTestId('task-arrange').click();
    await expect(page.getByTestId('task-goal')).toBeEnabled({ timeout: 30000 });
    await expect(page.getByTestId('task-goal')).toHaveValue('');
    await expect(page.getByTestId('frog-message-assistant').last()).toHaveAttribute('data-status', 'completed', { timeout: 30000 });
    return page.getByTestId('frog-message-assistant').last();
  }
  await expect(await say(`删除第${target.display_number}题`)).toContainText('待确认方案');
  expect((await paper()).total_count).toBe(before.total_count);
  await expect(await say('确认调整')).toContainText('调整已完成');
  await expect.poll(async () => (await paper()).total_count).toBe(before.total_count - 1);
  await page.reload();
  await expect.poll(async () => (await paper()).total_count).toBe(before.total_count - 1);
  await page.screenshot({ path: test.info().outputPath('paper-after-remove-and-refresh.png'), fullPage: true });
  const bank = await page.evaluate(async () => (await fetch('/api/plans/today/home-recommendation')).json());
  const historicalTopicCounts = new Map<string, number>();
  for (const item of before.items as Array<{ kp_id: string }>) {
    historicalTopicCounts.set(item.kp_id, (historicalTopicCounts.get(item.kp_id) ?? 0) + 1);
  }
  const addableTopic = (bank.inventory?.recommendation_nodes ?? []).find(
    (node: { kp_id: string; name: string; practice_eligible_count: number }) =>
      node.name && node.practice_eligible_count > (historicalTopicCounts.get(node.kp_id) ?? 0),
  );
  let countAfterAddAttempt = before.total_count - 1;
  const addReply = await say(addableTopic
    ? `给我增加一道${addableTopic.name}的题目`
    : '给我增加一道洛必达法则的题目');
  if ((await addReply.innerText()).includes('待确认方案')) {
    expect((await paper()).total_count).toBe(countAfterAddAttempt);
    await expect(await say('确认调整')).toContainText('新增1道');
    countAfterAddAttempt += 1;
  } else {
    await expect(addReply).toContainText('可追加题量不足');
    expect((await paper()).total_count).toBe(countAfterAddAttempt);
  }
  await expect.poll(async () => (await paper()).total_count).toBe(countAfterAddAttempt);
  await page.reload();
  await expect.poll(async () => (await paper()).total_count).toBe(countAfterAddAttempt);
  const first = (await paper()).items.find((item: { display_number: number }) => item.display_number === 1);
  expect(first).toBeTruthy();
  const beforeViewedRemoval = await paper();
  // The focused first question was displayed by the actual page, which records viewed activity.
  if ((await panel.getAttribute('open')) === null) await page.getByTestId('study-frog-launcher').click();
  await expect(await say('删除第1题')).toContainText('已浏览');
  await expect(await say('确认调整')).toContainText('二次确认');
  expect((await paper()).total_count).toBe(beforeViewedRemoval.total_count);
  await page.screenshot({ path: test.info().outputPath('viewed-second-confirmation.png'), fullPage: true });
  await expect(await say('确认移除已浏览题目')).toContainText('调整已完成');
  await expect.poll(async () => (await paper()).total_count).toBe(beforeViewedRemoval.total_count - 1);
  const current = await paper();
  const focused = current.items.find((item: { id: string }) => item.id === current.focus_item_id);
  expect(focused).toBeTruthy();
  const activity = page.waitForResponse(response => response.url().includes(`/practice-items/${focused.id}/activity`) && response.request().method() === 'POST');
  await page.getByTestId('option-A').check();
  await activity;
  await expect(await say(`删除第${focused.display_number}题`)).toContainText('系统保留了题目与历史记录');
  await page.getByTestId('submit-answer').click();
  await expect(page.getByTestId('answer-submission-notice')).toBeVisible();
  await expect(await say(`删除第${focused.display_number}题`)).toContainText('系统保留了题目与历史记录');
  const answered = (await paper()).items.find((item: { id: string }) => item.id === focused.id);
  expect(answered.completed).toBe(true);
  expect(answered.question_version_id).toBe(focused.question_version_id);
  await page.reload();
  expect((await paper()).items.find((item: { id: string }) => item.id === focused.id).completed).toBe(true);
  await page.screenshot({ path: test.info().outputPath('answered-item-preserved-after-refresh.png'), fullPage: true });
});


test('全卷阅读操作区在四视口滚动后保持可见', async ({ page }) => {
  await page.goto('/study');
  await page.getByTestId('confirm-home-paper').click();
  await expect(page.getByTestId('full-paper')).toBeVisible({timeout:30000});
  await page.getByTestId('full-paper').click();
  for (const width of [1440,430,390,360]) {
    await page.setViewportSize({width,height:900});
    const controls=page.getByTestId('paper-reading-controls');
    const content=page.getByTestId('paper-scroll-region');
    await expect(controls).toBeVisible();
    const before=await controls.boundingBox();
    expect(before).not.toBeNull();
    await content.evaluate(el=>{el.scrollTop=el.scrollHeight;});
    await expect.poll(()=>content.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
    await expect(page.getByTestId('paper-ask-frog')).toBeInViewport();
    await expect(page.getByTestId('mode-focus')).toBeInViewport();
    const after=await controls.boundingBox();
    expect(Math.abs(after!.y-before!.y)).toBeLessThan(3);
    await page.getByRole('button',{name:'跳转第 1 题',exact:true}).click();
    await expect.poll(()=>content.evaluate(el=>el.scrollTop)).toBeLessThan(60);
    await page.screenshot({path:test.info().outputPath(`paper-reader-${width}.png`)});
  }
  await page.getByTestId('paper-ask-frog').click();
  await expect(page.getByTestId('task-goal')).toBeVisible();
});
