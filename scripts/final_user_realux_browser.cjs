// One user-visible case at a time. No request is intercepted, fabricated, or retried.
const { chromium, expect } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'storage/quality-audits/final-real-user-20261016/realux-v1');
const plan = JSON.parse(fs.readFileSync(path.join(root, 'eval/final-user-realux-v1/plan.json')));
const cid = process.argv[2];
const testCase = plan.cases_in_priority_order.find(item => item.id === cid);
if (!testCase || !fs.existsSync(path.join(out, 'authorization.json'))) throw new Error('Frozen real-user case and run authorization required');
const dir = path.join(out, cid);
if (fs.existsSync(dir)) throw new Error('Case directory exists; never replay a paid user turn');
fs.mkdirSync(dir);
const write = (name, value) => fs.writeFileSync(path.join(dir, name), JSON.stringify(value, null, 2));
const writeRoot = (name, value) => fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2));

(async () => {
  const ledgerPath = path.join(out, 'provider-ledger.json');
  const ledger = JSON.parse(fs.readFileSync(ledgerPath));
  if (ledger.stop_reason || ledger.requests.length >= 20) throw new Error('Meter stopped or 20-request ceiling reached');
  const group = testCase.surface === 'materials' ? 'materials' : testCase.surface === 'chat' ? 'chat' : 'study';
  const storagePath = path.join(out, `${group}-browser-storage.json`);
  const sessionPath = path.join(out, `${group}-session.json`);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    baseURL: 'http://127.0.0.1:5184',
    extraHTTPHeaders: { 'X-Final-Eval-Case': cid },
    ...(fs.existsSync(storagePath) ? { storageState: storagePath } : {}),
  });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await context.tracing.start({ screenshots: true, snapshots: true });
  const startedAt = new Date().toISOString();
  const start = Date.now();
  try {
    const health = await (await context.request.get('/api/health')).json();
    expect(health.environment).toBe('test');
    expect(health.llm_model).toBe('deepseek-flash');
    write('case.json', { testCase, startedAt, health });

    if (testCase.action === 'confirm_previous_draft') {
      await page.goto('/study');
      await page.getByTestId('study-frog-launcher').click();
      await expect(page.getByTestId('task-confirm')).toBeVisible({ timeout: 15000 });
      const before = JSON.parse(fs.readFileSync(path.join(out, 'truth-after-Agent-06.json')));
      const confirmResponse = page.waitForResponse(r => r.request().method() === 'POST' && /\/api\/learning-tasks\/[^/]+\/confirm$/.test(new URL(r.url()).pathname), { timeout: 30000 });
      await page.getByTestId('task-confirm').click();
      const response = await confirmResponse;
      const body = await response.json();
      const after = await (await context.request.get('/api/plans/today')).json();
      write('confirmation.json', { http_status: response.status(), response: body, plan_after_confirmation: after,
        pre_confirmation_snapshot: before, user_clicked_confirm: true });
      await expect(page.getByTestId('task-result')).toContainText('已加入今日学习');
      await page.screenshot({ path: path.join(dir, 'after.png'), fullPage: false });
      await context.storageState({ path: storagePath });
      console.log(JSON.stringify({ id: cid, interaction: 'explicit_user_confirmation', http: response.status(), provider_requests: ledger.requests.length }));
      return;
    }

    if (testCase.surface === 'materials') {
      await page.goto('/materials');
      await expect(page.getByTestId('materials-page')).toBeVisible({ timeout: 30000 });
      if (testCase.action === 'upload_then_ask') {
        const title = `FINAL-REALUX-学生数学资料-${Date.now()}`;
        const uploaded = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/materials' && r.status() === 201, { timeout: 60000 });
        const chooser = page.waitForEvent('filechooser');
        await page.getByTestId('upload-toggle').click();
        await (await chooser).setFiles(path.join(root, 'seed/materials/gaoshu-lecture-01.md'));
        await expect(page.getByTestId('upload-title')).toHaveValue('gaoshu-lecture-01');
        await page.getByTestId('upload-title').fill(title);
        await page.getByTestId('upload-submit').click();
        const uploadResponse = await uploaded;
        const upload = await uploadResponse.json();
        const row = page.locator('.material-item').filter({ hasText: title });
        await expect(row).toBeVisible({ timeout: 30000 });
        await expect(row.locator('.material-status')).toHaveText('可检索', { timeout: 180000 });
        await page.getByTestId('material-search-scope').click();
        const label = page.locator('.scope-files label').filter({ hasText: title });
        await expect(label).toBeVisible();
        await label.locator('input').check();
        await page.getByTestId('material-search-scope-picker').getByRole('button', { name: '应用范围' }).click();
        write('upload.json', { http_status: uploadResponse.status(), material_id: upload.material.id,
          title, status: upload.material.status, job_id: upload.job_id });
      }
      await expect(page.getByTestId('material-search-send')).toBeVisible();
      await page.getByTestId('material-search-question').fill(testCase.input);
    } else if (testCase.surface === 'chat') {
      const prior = fs.existsSync(sessionPath) ? JSON.parse(fs.readFileSync(sessionPath, 'utf8')).session_id : null;
      await page.goto(prior ? `/chat?session_id=${encodeURIComponent(prior)}` : '/chat');
      await expect(page.locator('#chat-question')).toBeVisible({ timeout: 30000 });
      await page.locator('#chat-question').fill(testCase.input);
    } else {
      await page.goto('/study');
      if (testCase.action === 'refresh_then_ask') await page.reload();
      await page.getByTestId('study-frog-launcher').click();
      await expect(page.getByTestId('task-goal')).toBeEnabled();
      await page.getByTestId('task-goal').fill(testCase.input);
    }

    await page.screenshot({ path: path.join(dir, 'before.png') });
    // Ordinary chat is handled by ChatPage's assistant route; only the
    // dedicated materials-search surface posts to answers:stream.
    const target = testCase.surface === 'materials' ? '/answers:stream' : '/assistant:stream';
    const responsePromise = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith(target), { timeout: 240000 });
    await (testCase.surface === 'materials' ? page.getByTestId('material-search-send') :
      testCase.surface === 'chat' ? page.locator('.send-button') : page.getByTestId('task-arrange')).click();
    const response = await responsePromise;
    write('business-request.json', { url: response.url(), postData: response.request().postDataJSON(), http_status: response.status() });
    const raw = await response.text();
    fs.writeFileSync(path.join(dir, 'response.sse'), raw);
    const match = new URL(response.url()).pathname.match(/\/sessions\/([^/]+)\//);
    if (match && testCase.surface === 'chat') writeRoot(`${group}-session.json`, { session_id: match[1] });
    if (testCase.surface === 'chat' && match) {
      const restored = await context.request.get(`/api/chat/sessions/${match[1]}/messages`);
      write('restored-history.json', await restored.json());
    }
    if (testCase.surface === 'materials') await expect(page.getByTestId('material-search-question')).toBeEnabled({ timeout: 30000 });
    if (testCase.surface === 'study') await expect(page.getByTestId('task-goal')).toBeEnabled({ timeout: 30000 });
    if (testCase.surface === 'chat') await expect(page.locator('#chat-question')).toBeEnabled({ timeout: 30000 });
    const freshLedger = JSON.parse(fs.readFileSync(ledgerPath));
    write('visible-result.json', { latency_seconds: (Date.now() - start) / 1000, pageErrors,
      text: await page.locator('body').innerText(), terminalDone: raw.includes('event: done'),
      terminalError: raw.includes('event: error'), sseChars: raw.length,
      provider_requests_before: ledger.requests.length, provider_requests_after: freshLedger.requests.length });
    if (testCase.surface === 'study') await page.getByTestId('frog-conversation').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(dir, 'after.png'), fullPage: false });
    await context.storageState({ path: storagePath });
    console.log(JSON.stringify({ id: cid, http: response.status(), terminalDone: raw.includes('event: done'),
      terminalError: raw.includes('event: error'), providerRequests: freshLedger.requests.length }));
  } catch (error) {
    write('browser-error.json', { error: String(error), latency_seconds: (Date.now() - start) / 1000, pageErrors });
    await page.screenshot({ path: path.join(dir, 'failed.png') }).catch(() => undefined);
    console.error(error);
    process.exitCode = 1;
  } finally {
    await context.tracing.stop({ path: path.join(dir, 'trace.zip') });
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
