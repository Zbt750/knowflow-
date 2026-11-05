import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = fileURLToPath(new URL('../..', import.meta.url));
function snapshot(id: string) {
  return JSON.parse(execFileSync(process.env.QUERY_FOLLOWUP_PYTHON!,
    ['-m', 'tests.integration.query_followup_backend', id], { cwd: root, encoding: 'utf8' }));
}

test('数学二→洛必达→真题→已做→错题：真实数据库五轮收窄与刷新恢复', async ({ page }, info) => {
  const errors: string[] = [];
  const network: { input: string; sse: string }[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const before = snapshot('00000000-0000-0000-0000-000000000000').counts;
  await info.attach('database-before', { body: JSON.stringify(before), contentType: 'application/json' });
  await page.goto('/chat');
  const input = page.locator('#chat-question');
  const replies = page.locator('.message-row--assistant .message-bubble');
  let sid = '';
  const steps = [
    ['我题库里有多少道数学二的可练题？', '4 道符合当前可练资格', 'question_count', 4],
    ['那其中洛必达法则的题有多少道？', '3 道符合当前可练资格', 'question_count', 3],
    ['其中多少道是真题？', '2 道符合当前可练资格', 'question_count', 2],
    ['这些题我做过几道？', '涉及 2 道题', 'distinct_question_count', 2],
    ['那里面我做错过哪些？', '洛必达真题甲', 'distinct_question_count', 1],
  ] as const;
  for (const [index, [message, visible, field, count]] of steps.entries()) {
    await input.fill(message);
    const responsePromise = page.waitForResponse(r => r.url().endsWith('/assistant:stream'));
    await input.press('Enter');
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    sid = new URL(response.url()).pathname.split('/').at(-2)!;
    const sse = await response.text();
    network.push({ input: message, sse });
    const frames = sse.trim().split(/\r?\n\r?\n/).map(frame => {
      const lines = frame.split(/\r?\n/);
      return { event: lines[0].slice(7), data: JSON.parse(lines[1].slice(6)) };
    });
    expect(frames.some(f => f.event === 'meta' && f.data.capability === 'data_query' && f.data.model_called === false)).toBe(true);
    expect(frames.filter(f => f.event === 'error')).toEqual([]);
    await expect(replies).toHaveCount(index + 1);
    await expect(replies.last()).toContainText(visible);
    const db = snapshot(sid);
    const evidence = db.messages.filter((m: any) => m.role === 'assistant').at(-1).evidence;
    expect(evidence[field]).toBe(count);
    expect(evidence.query_state.subject).toBe('考研数学');
    expect(evidence.model_called).toBe(false);
    expect(db.counts).toEqual(before);
    await info.attach(`database-round-${index + 1}`, { body: JSON.stringify(db, null, 2), contentType: 'application/json' });
    await page.screenshot({ path: info.outputPath(`round-${index + 1}.png`), fullPage: true });
  }
  await page.reload();
  await expect(replies).toHaveCount(5);
  await expect(replies.last()).toContainText('洛必达真题甲');
  await expect(replies.last()).not.toContainText('洛必达原创丙');
  expect(snapshot(sid).counts).toEqual(before);
  expect(errors).toEqual([]);
  const calls = JSON.parse(readFileSync(join(process.env.QUERY_FOLLOWUP_OUTPUT!, 'model-calls.json'), 'utf8'));
  expect(calls).toEqual([]);
  const sql = readFileSync(join(process.env.QUERY_FOLLOWUP_OUTPUT!, 'read-sql.jsonl'), 'utf8');
  for (const table of ['questions', 'question_attempts', 'learning_events']) expect(sql).toContain(table);
  await info.attach('executed-read-sql', { body: sql, contentType: 'application/x-ndjson' });
  await info.attach('actual-sse', { body: JSON.stringify(network, null, 2), contentType: 'application/json' });
  await page.screenshot({ path: info.outputPath('refresh-restored.png'), fullPage: true });
});
