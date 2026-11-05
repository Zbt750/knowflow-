// One frozen user turn, through real Vue UI. Never intercepts an API or retries a turn.
const { chromium, expect } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'storage/quality-audits/final-real-user-20261015/paid-v2');
const plan = JSON.parse(fs.readFileSync(path.join(root, 'eval/final-user-acceptance-v1/plan.json')));
const cid = process.argv[2];
const turn = plan.turns_in_priority_order.find(t => t.id === cid);
if (!turn || !fs.existsSync(path.join(out, 'authorization.json'))) throw new Error('Authorized frozen case required');
const dir = path.join(out, cid);
fs.mkdirSync(dir); // No paid replay, even if a previous attempt failed.
const write = (name, value) => fs.writeFileSync(path.join(dir, name), JSON.stringify(value, null, 2));
(async () => {
  const ledger = JSON.parse(fs.readFileSync(path.join(out, 'provider-ledger.json')));
  if (ledger.stop_reason || ledger.requests.length >= 20) throw new Error('Meter stopped; do not send another user request');
  const group = cid.startsWith('USER-R') ? 'materials' : cid === 'USER-A2' ? 'sources' : 'study';
  const statePath = path.join(out, `${group}-browser-storage.json`);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, baseURL: 'http://127.0.0.1:5184',
    extraHTTPHeaders: { 'X-Final-Eval-Case': cid }, ...(fs.existsSync(statePath) ? { storageState: statePath } : {}) });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.tracing.start({ screenshots: true, snapshots: true });
  const start = Date.now();
  try {
    const health = await (await context.request.get('/api/health')).json();
    expect(health.environment).toBe('test');
    expect(health.llm_model).toBe('deepseek-flash');
    write('case.json', { turn, started_at: new Date().toISOString(), health });
    if (turn.surface === 'materials') {
      await page.goto('/materials');
      await expect(page.getByTestId('material-search-send')).toBeVisible();
      if (cid === 'USER-R1') {
        const row = page.locator('.material-item').filter({ hasText: 'FINAL-学生个人数学笔记-20261015-run-v4' });
        await expect(row).toHaveCount(1);
        await row.getByRole('button', { name: '针对FINAL-学生个人数学笔记-20261015-run-v4提问', exact: true }).click();
        await expect(page.getByTestId('material-search-scope')).toContainText('已限定 1 份资料');
      } else {
        await expect(page.getByTestId('material-search-user').last()).toContainText(plan.turns_in_priority_order[0].input);
      }
      await page.getByTestId('material-search-question').fill(turn.input);
    } else {
      await page.goto('/study');
      await page.getByTestId('study-frog-launcher').click();
      await expect(page.getByTestId('task-goal')).toBeEnabled();
      await page.getByTestId('task-goal').fill(turn.input);
    }
    await page.screenshot({ path: path.join(dir, 'before.png') });
    const responsePromise = page.waitForResponse(r => r.request().method() === 'POST' &&
      new URL(r.url()).pathname.endsWith(turn.surface === 'materials' ? '/answers:stream' : '/assistant:stream'), { timeout: 240000 });
    await page.getByTestId(turn.surface === 'materials' ? 'material-search-send' : 'task-arrange').click();
    const response = await responsePromise;
    write('business-request.json', { url: response.url(), body: response.request().postDataJSON(), http_status: response.status() });
    const raw = await response.text();
    fs.writeFileSync(path.join(dir, 'response.sse'), raw);
    if (turn.surface === 'study') await expect(page.getByTestId('task-goal')).toBeEnabled({ timeout: 20000 });
    else await expect(page.getByTestId('material-search-question')).toBeEnabled({ timeout: 20000 });
    const matches = new URL(response.url()).pathname.match(/\/sessions\/([^/]+)\//);
    if (matches) {
      const history = await context.request.get(`/api/chat/sessions/${matches[1]}/messages`);
      write('restored-history.json', await history.json());
    }
    write('visible-result.json', { latency_seconds: (Date.now() - start) / 1000, pageErrors: errors,
      text: await page.locator('body').innerText(), terminalDone: raw.includes('event: done'), terminalError: raw.includes('event: error') });
    if (turn.surface === 'study') await page.getByTestId('frog-conversation').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(dir, 'after.png'), fullPage: false });
    await context.storageState({ path: statePath });
    console.log(JSON.stringify({ id: cid, http: response.status(), terminalDone: raw.includes('event: done'), terminalError: raw.includes('event: error') }));
  } catch (error) {
    write('browser-error.json', { error: String(error), latency_seconds: (Date.now() - start) / 1000, pageErrors: errors });
    await page.screenshot({ path: path.join(dir, 'failed.png') });
    throw error;
  } finally {
    await context.tracing.stop({ path: path.join(dir, 'trace.zip') });
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
