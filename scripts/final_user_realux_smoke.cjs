const { chromium } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'storage/quality-audits/final-real-user-20261016/realux-v1');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const pages = [];
  try {
    for (const route of ['/', '/knowledge', '/materials', '/study']) {
      const response = await page.goto(`http://127.0.0.1:5184${route}`, { waitUntil: 'networkidle', timeout: 45000 });
      await page.locator('body').waitFor({ state: 'visible' });
      const body = await page.locator('body').innerText();
      pages.push({ route, status: response?.status() ?? null, final_url: page.url(), body_chars: body.length });
      if (!response || response.status() >= 400 || body.trim().length < 5) throw new Error(`page_smoke_failed:${route}`);
    }
    if (errors.length) throw new Error(`page_errors:${errors.join(' | ')}`);
    const result = { status: 'PASS', pages, page_errors: errors, model_requests: 0, database: 'phase5_final_user_realux_20261016_test' };
    fs.writeFileSync(path.join(out, 'preflight-browser-smoke.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
