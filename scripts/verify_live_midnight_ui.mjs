// Actual localhost UI verification. No model call or plan/question mutation.
// --verify-confirmation explicitly permits creating ONE test conversation and
// expiring its own confirmation metadata; no user conversation is changed.
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const output = resolve(process.argv.includes('--verify-confirmation') ? 'storage/quality-audits/midnight-live-20261019-v3' : 'storage/quality-audits/midnight-live-final-readonly-20261019-v2');
mkdirSync(output, {recursive:true});
const browser = await chromium.launch({channel:'chrome', headless:true});
const context = await browser.newContext({viewport:{width:1440,height:1000}});
const page = await context.newPage();
const result = {model_requests:0, created_test_session:null, checks:[], errors:[], writes:[]};
page.on('pageerror', error => result.errors.push(error.message));
await context.route(/^http:\/\/127\.0\.0\.1:5173\/api\//, async route => {
  const request = route.request();
  if (request.method() === 'GET') return route.continue();
  const path = new URL(request.url()).pathname;
  if (process.argv.includes('--verify-confirmation') && path === '/api/chat/sessions') return route.continue();
  if (process.argv.includes('--verify-confirmation') && path.endsWith('/assistant:stream')) {
    const body = request.postDataJSON();
    if (!body.personal_generation_confirmed_kp_id && /生成|出.{0,10}题/.test(body.question)) return route.continue();
  }
  result.errors.push('Prevented unexpected write/model path: '+path);
  return route.abort('blockedbyclient');
});
try {
  const health = await context.request.get('http://127.0.0.1:8000/api/health');
  result.health = {status:health.status(), ...(await health.json())};
  // Only publish safe health fields, not settings or credentials.
  result.health = {status:result.health.status,database:result.health.database,environment:result.health.environment,llm_model:result.health.llm_model};
  const spec = await (await context.request.get('http://127.0.0.1:8000/openapi.json')).json();
  expect(spec.paths['/api/plans/today/recommendations']).toBeTruthy();
  expect(spec.components.schemas.GeneratePlanRequest.properties.extend_existing).toBeTruthy();
  result.checks.push('live backend exposes new recommendation and explicit extension contracts');
  const before = await (await context.request.get('http://127.0.0.1:8000/api/plans/today')).json();
  result.plan_before = {id:before.plan_id,date:before.study_date,count:before.total_count,item_ids:before.items?.map(i=>i.id)};
  await page.goto('http://127.0.0.1:5173/study');
  await expect(page.getByTestId('study-active')).toBeVisible({timeout:30000});
  await page.getByTestId('extend-plan').click();
  await expect(page.getByTestId('study-setup')).toBeVisible({timeout:30000});
  await expect(page.getByTestId('generate-plan')).toContainText('确认扩充今日卷');
  await expect(page.getByTestId('tree-kp-picker-open')).toBeVisible();
  await page.getByTestId('tree-kp-picker-open').click();
  await expect(page.getByTestId('tree-kp-picker')).toBeVisible();
  await expect(page.getByTestId('scope-tree-window')).toBeVisible({timeout:30000});
  result.checks.push('actual one-question paper can reopen recommendations and select knowledge scope');
  await page.screenshot({path:resolve(output,'live-recommendation-extension.png')});
  await page.getByRole('button',{name:'返回当前卷',exact:true}).click();
  await page.reload();
  await expect(page.getByTestId('extend-plan')).toBeVisible({timeout:30000});
  result.checks.push('reload preserves paper and extension entry');
  if (process.argv.includes('--verify-confirmation')) {
    let originalRequest;
    let requestSession;
    page.on('request', request => {
      if(request.method()==='POST' && request.url().endsWith('/assistant:stream')) {
        originalRequest=request.postDataJSON();
        requestSession=request.url().match(/\/sessions\/([^/]+)\/assistant:stream/)[1];
      }
    });
    await page.goto('http://127.0.0.1:5173/chat');
    await page.getByTitle('新建对话',{exact:true}).click();
    const composer = page.locator('#chat-question');
    const question = String.raw`帮我出一道类似的练习题难度更大的。原题：当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。`;
    await composer.fill(question); await composer.press('Enter');
    result.writes.push('submitted first confirmation-only user turn');
    await expect(page.getByTestId('generation-confirmation')).toBeVisible({timeout:30000});
    const sid = requestSession;
    expect(sid).toBeTruthy(); result.created_test_session=sid;
    const historyUrl=`http://127.0.0.1:8000/api/chat/sessions/${sid}/messages`;
    const history=await (await context.request.get(historyUrl)).json();
    const card=history.findLast(m=>m.personal_generation_confirmation);
    expect(card.personal_generation_confirmation.reference_text).toContain('nx^n');
    expect(card.study_context.knowledge_node_ids).toHaveLength(0);
    result.checks.push('live original user wording creates a real confirmation card with original statement');
    // Intentionally change only this test card's location. Rejection occurs in
    // begin_turn before provider setup; no confirmed valid request is sent.
    const kp=card.personal_generation_confirmation.nodes[0].kp_id;
    const stale=await context.request.post(`http://127.0.0.1:8000/api/chat/sessions/${sid}/assistant:stream`, {data:{
      ...originalRequest,request_key:crypto.randomUUID(),
      personal_generation_confirmation_message_id:card.message_id,personal_generation_confirmed_kp_id:kp,
      study_context:{...originalRequest.study_context,knowledge_node_ids:[kp]},
    }});
    expect(await stale.text()).toContain('personal_generation_confirmation_invalid');
    await page.goto(`http://127.0.0.1:5173/chat?session_id=${sid}`);
    await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
    const expired=await (await context.request.get(historyUrl)).json();
    expect(expired.find(m=>m.message_id===card.message_id).personal_generation_confirmation_status).toBe('expired');
    result.checks.push('live invalid card remains expired after history reload');
    await composer.fill(question+'这次改成计算题。'); await composer.press('Enter');
    await expect(page.getByTestId('generation-confirmation')).toBeVisible({timeout:30000});
    const fresh=await (await context.request.get(historyUrl)).json();
    expect(fresh.findLast(m=>m.personal_generation_confirmation).message_id).not.toBe(card.message_id);
    result.checks.push('new independent request creates an operable fresh card after expiry');
    result.writes.push('one new test ChatSession, user/assistant confirmation messages, expiry metadata on its own old card');
    await page.screenshot({path:resolve(output,'live-fresh-confirmation-after-expiry.png')});
  }
  const after = await (await context.request.get('http://127.0.0.1:8000/api/plans/today')).json();
  result.plan_after={id:after.plan_id,date:after.study_date,count:after.total_count,item_ids:after.items?.map(i=>i.id)};
  expect(result.plan_after).toEqual(result.plan_before);
  result.checks.push('real paper ID and every item unchanged by live verification');
  expect(result.errors).toEqual([]);
  result.status='PASS_WITH_NO_REAL_MODEL_GENERATION';
} catch(error) {
  result.status='FAIL'; result.failure=String(error);
  await page.screenshot({path:resolve(output,'live-failure.png')}).catch(()=>{});
  process.exitCode=1;
} finally {
  writeFileSync(resolve(output,'live-browser-result.json'),JSON.stringify(result,null,2),'utf8');
  console.log(JSON.stringify(result));
  await browser.close();
}
