// Real Chrome + Vue + FastAPI + sealed-bank clone. No API response interception.
const { chromium, expect } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'storage/quality-audits/final-real-user-20261015');
const fixture = JSON.parse(fs.readFileSync(path.join(out, 'fixture.json'), 'utf8'));
const runId = process.argv[2];
if (!runId || !/^[a-z0-9-]+$/.test(runId)) throw new Error('Explicit new run ID required');
const evidenceDir = path.join(out, runId);
fs.mkdirSync(evidenceDir); // Refuse to overwrite previous failed evidence.
const results = [];
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, baseURL: 'http://127.0.0.1:5184' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await context.tracing.start({ screenshots: true, snapshots: true });
  async function api(url, options) {
    const response = await context.request.fetch('/api' + url, options);
    expect(response.ok(), `${url}: ${await response.text()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  }
  async function step(id, action) {
    try {
      const evidence = await action();
      await page.screenshot({ path: path.join(evidenceDir, `${id}.png`), fullPage: true });
      results.push({ id, result: 'PASS', evidence });
    } catch (e) {
      await page.screenshot({ path: path.join(evidenceDir, `${id}-failed.png`), fullPage: true });
      results.push({ id, result: 'FAIL', error: String(e) });
      throw e;
    } finally {
      fs.writeFileSync(path.join(evidenceDir, 'browser-results.json'), JSON.stringify({ results, pageErrors: errors, paidRequests: 0, provider: 'offline protocol fixture; not real model quality' }, null, 2));
    }
  }
  try {
    const health = await api('/health');
    expect(health.environment).toBe('test');
    expect(health.llm_model).toBe('e2e-offline-fixture');
    let plan, item;
    if (!process.argv.includes('--resume')) {
    await step('01-first-open', async () => {
      const before = await api('/plans/today');
      expect(before.status).toBe('setup');
      await page.goto('/study');
      await expect(page.getByTestId('study-setup')).toBeVisible();
      await page.reload();
      await expect(page.getByTestId('study-setup')).toBeVisible();
      const after = await api('/plans/today');
      expect(after.status).toBe('setup');
      return { getDoesNotCreatePlan: true, recommendations: before.recommendations?.length };
    });
    let materialId;
    await step('02-upload-index-read', async () => {
      await page.goto('/materials');
      await expect(page.getByTestId('materials-page')).toBeVisible();
      const chooser = page.waitForEvent('filechooser');
      await page.getByTestId('upload-toggle').click();
      await (await chooser).setFiles(path.join(root, 'seed/materials/gaoshu-lecture-01.md'));
      const title = 'FINAL-学生个人数学笔记-20261015-' + runId;
      await page.getByTestId('upload-title').fill(title);
      const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/materials' && r.request().method() === 'POST' && r.status() === 201);
      await page.getByTestId('upload-submit').click();
      materialId = (await (await response).json()).material.id;
      const row = page.locator('.material-item').filter({ hasText: title });
      await expect(row.locator('.material-status')).toHaveText('可检索', { timeout: 180000 });
      await row.locator('.material-view').click();
      await expect(page.getByTestId('material-reader')).toContainText('极限');
      const search = await api('/materials/search', { method: 'POST', data: { query: '等价无穷小替换条件', top_k: 5, material_ids: [materialId] } });
      expect(search.hits.length).toBeGreaterThan(0);
      expect(search.hits.every(h => h.material_id === materialId)).toBeTruthy();
      return { materialId, realEmbeddingRetrievalHits: search.hits.length, hitChunks: search.hits.map(h => h.chunk_id ?? h.id), modelUsed: false };
    });
    await step('05-knowledge-real-bank', async () => {
      await page.goto('/knowledge?node=' + fixture.nodes.integral.code);
      await expect(page.getByTestId('knowledge-detail')).toBeVisible();
      const detail = await api('/knowledge/' + fixture.nodes.integral.id);
      expect(detail.questions.length).toBeGreaterThan(0);
      return { node: fixture.nodes.integral, questions: detail.questions.length, capability: detail.capability_profile };
    });
    await step('09-explicit-confirmation', async () => {
      expect((await api('/plans/today')).status).toBe('setup');
      await page.goto('/study');
      await expect(page.getByTestId('generate-plan')).toBeEnabled();
      const generated = page.waitForResponse(r => r.url().endsWith('/api/plans/today/generate') && r.request().method() === 'POST');
      await page.getByTestId('generate-plan').click();
      const response = await generated;
      expect(response.ok(), await response.text()).toBeTruthy();
      plan = await response.json();
      await expect(page.getByTestId('study-active')).toBeVisible();
      item = plan.items.find(i => ['fill_blank', 'calculation', 'single_choice'].includes(i.question_type));
      expect(item).toBeTruthy();
      return { planId: plan.plan_id, count: plan.items.length, confirmedBy: 'actual Start practice button; not Agent confirmation' };
    });
    } else {
      plan = await api('/plans/today');
      expect(plan.status).toBe('active');
      item = plan.items.find(i => !i.completed && ['fill_blank', 'calculation', 'single_choice'].includes(i.question_type));
      expect(item).toBeTruthy();
      await page.goto('/study');
      await expect(page.getByTestId('study-active')).toBeVisible();
    }
    await step('06-answer-explanation-history', async () => {
      await page.getByTestId('full-paper').click();
      // Read correct answer only through the persisted immutable version in the test evidence file.
      const answer = JSON.parse(fs.readFileSync(path.join(out, 'answers.json'), 'utf8'))[item.question_id];
      expect(answer).toBeTruthy();
      // The submit button disappears on success; use the persistent input as row identity.
      const row = page.locator('li.paper-item').filter({ has: page.getByTestId(item.question_type === 'single_choice'
        ? `paper-option-${item.id}-${answer}` : 'paper-raw-answer-' + item.id) });
      if (item.question_type === 'single_choice') {
        await row.locator(`input[type=radio][value="${answer}"]`).check();
      } else {
        await page.getByTestId('paper-raw-answer-' + item.id).fill(answer);
      }
      await page.getByTestId('paper-submit-answer-' + item.id).click();
      await expect(page.getByTestId('paper-submission-' + item.id)).toHaveText('✓');
      await row.getByRole('button', { name: '查看答案详解' }).click();
      await expect(page.getByTestId('answer-' + item.id)).toContainText('参考解析');
      const saved = await api('/plans/today');
      const submission = saved.items.find(i => i.id === item.id).answer_submission;
      expect(submission.result).toBe('right');
      expect(submission.assisted).toBe(false);
      return { itemId: item.id, questionId: item.question_id, submission };
    });
    await step('10-reopen-resume', async () => {
      const before = await api('/plans/today');
      await page.goto('/knowledge');
      await page.goto('/study');
      await expect(page.getByTestId('study-active')).toBeVisible();
      await page.reload();
      await expect(page.getByTestId('study-active')).toBeVisible();
      const after = await api('/plans/today');
      expect(after.plan_id).toBe(before.plan_id);
      expect(after.items.map(i => i.id)).toEqual(before.items.map(i => i.id));
      expect(after.completed_count).toBe(before.completed_count);
      return { samePlan: true, sameItems: true, completed: after.completed_count };
    });
    expect(errors).toEqual([]);
  } finally {
    await context.tracing.stop({ path: path.join(evidenceDir, 'browser-trace.zip') });
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
