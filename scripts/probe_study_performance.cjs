// Actual Vue pages + real read-only API + restored isolated PostgreSQL.
const { chromium } = require('../frontend/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const output = path.resolve(__dirname, '../storage/quality-audits/study-read-performance-20261016');
  const runLabel = process.argv[2] || 'rollback';
  // Match the repository's Playwright configuration: installed system Chrome.
  const browser = await chromium.launch({ channel: 'chrome' });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.hostname !== '127.0.0.1') return route.abort();
    return route.continue();
  });
  const page = await context.newPage();
  const errors = [], failed = [], calls = [], starts = new Map();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) starts.set(request, Date.now());
  });
  page.on('requestfailed', request => failed.push(request.url()));
  page.on('response', response => {
    const pathname = new URL(response.url()).pathname;
    if (pathname.startsWith('/api/')) calls.push({ path: pathname,
      status: response.status(), headers_ms: Date.now() - starts.get(response.request()) });
  });
  const pages = [];
  try {
    const health = await context.request.get('http://127.0.0.1:5176/api/health');
    if (!health.ok() || (await health.json()).environment !== 'test') throw new Error('Refuse non-test backend');
    for (const [route, ready, tag] of [
      ['/study', 'study-setup', 'study-first'],
      ['/knowledge', 'knowledge-tree', 'knowledge'],
      ['/study', 'study-setup', 'study-revisit'],
    ]) {
      const start = Date.now(), offset = calls.length;
      await page.goto('http://127.0.0.1:5176' + route, { waitUntil: 'domcontentloaded' });
      await page.getByTestId(ready).waitFor({ state: 'visible', timeout: 15000 });
      const readyMs = Date.now() - start;
      await page.waitForLoadState('networkidle', { timeout: 15000 });
      if (tag === 'study-first') {
        await page.getByTestId('tree-kp-picker-open').click();
        await page.getByTestId('scope-tree-window').waitFor({ state: 'visible', timeout: 15000 });
        await page.waitForLoadState('networkidle', { timeout: 15000 });
      }
      pages.push({ route, ready_ms: readyMs, calls: calls.slice(offset) });
      await page.screenshot({ path: path.join(output, runLabel + '-' + tag + '.png'), fullPage: true });
    }
    const inventoryStart = Date.now();
    const inventory = await context.request.get('http://127.0.0.1:5176/api/question-availability');
    if (!inventory.ok()) throw new Error('Inventory API failed: ' + inventory.status());
    const inventoryData = await inventory.json();
    const availability = { status: inventory.status(), ms: Date.now() - inventoryStart,
      practice_eligible_count: inventoryData.practice_eligible_count };
    const evidence = { browser: browser.version(), pages, calls, availability, errors, failed };
    fs.writeFileSync(path.join(output, 'browser-smoke-' + runLabel + '-attempt.json'), JSON.stringify(evidence, null, 2));
    if (errors.length || failed.length || calls.some(call => call.status >= 400)) {
      throw new Error('Browser console, request, or HTTP error');
    }
    const result = { status: 'PASS', browser: browser.version(), pages, availability, errors, failed,
      boundary: 'GET-only UI smoke with outer transaction rollback; no plan creation, answers, RAG or model requests.' };
    fs.writeFileSync(path.join(output, 'browser-smoke.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
