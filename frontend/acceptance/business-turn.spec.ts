import { test, expect, type Page } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
const out=process.env.BUSINESS_AUDIT_DIR!;
const fixture=JSON.parse(readFileSync(`${out}/browser-fixture.json`,'utf8'));
const captures=new WeakMap<Page,{events:unknown[];errors:string[];pending:Promise<void>[]}>();

test.beforeEach(async ({context,page}) => {
  const capture={events:[] as unknown[],errors:[] as string[],pending:[] as Promise<void>[]};captures.set(page,capture);
  page.on('pageerror',error=>capture.errors.push(error.message));
  page.on('response',response=>{
    if (!response.url().includes('/api/')) return;
    capture.events.push({kind:'http',path:new URL(response.url()).pathname,status:response.status(),method:response.request().method()});
    if (response.url().includes('assistant') && response.url().includes('stream')) capture.pending.push((async()=>{
      capture.events.push({kind:'sse',path:new URL(response.url()).pathname,input:response.request().postDataJSON(),raw:await response.text(),provider:'FIXED OFFLINE; NOT REAL MODEL'});
    })());
  });
  await context.route('**/*',route => {
    const u=new URL(route.request().url());
    if (!['127.0.0.1','localhost'].includes(u.hostname) && !['data:','blob:'].includes(u.protocol)) return route.abort();
    return route.continue();
  });
});
test.afterEach(async ({page},info)=>{
  const capture=captures.get(page)!;await Promise.all(capture.pending);
  const id=createHash('sha256').update(info.title).digest('hex').slice(0,12);
  writeFileSync(`${out}/journey-${id}.json`,JSON.stringify({title:info.title,status:info.status,...capture,pending:undefined},null,2));
  expect(capture.errors).toEqual([]);
});

test('actual Vue→SSE→PG: query scope → confirmed append → independent QA → refresh',async ({page})=>{
  await page.goto('/study');
  await expect(page.getByTestId('study-active')).toBeVisible();
  await page.getByTestId('study-frog-launcher').click();
  const field=page.getByTestId('task-goal');
  await field.fill('有没有洛必达法则的题目？');await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('frog-message-assistant').last()).toContainText('洛必达法则');
  await expect(field).toBeEnabled();
  await field.fill('帮我安排一道到今日卷里');await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('task-confirm')).toBeVisible();
  const card=page.getByTestId('task-result');
  await expect(card).toContainText('洛必达法则');
  const owner=await card.getAttribute('data-owner-message-id');
  expect(owner).toBeTruthy();
  await page.getByTestId('task-confirm').click();
  await expect(card).toContainText('已加入今日学习');
  await expect(field).toBeEnabled();
  await field.fill('当前这道题怎么解？');await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('frog-message-assistant').last()).toContainText('固定离线回答');
  await expect(field).toBeEnabled();
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.getByTestId('frog-message-assistant').last()).toBeInViewport({ratio:0.6});
  await expect(page.getByTestId('frog-message-assistant').last().locator('.markdown-content p').first()).toBeInViewport({ratio:0.8});
  await expect(card).toHaveCount(1);
  expect(await card.getAttribute('data-owner-message-id')).toBe(owner);
  const latest=await page.getByTestId('frog-message-assistant').last().getAttribute('data-message-id');
  expect(latest).not.toBe(owner);
  const geometry=await page.getByTestId('frog-conversation').evaluate(element=>{
    const last=element.querySelector('.frog-message:last-of-type');
    const p=element.querySelectorAll('.frog-message--assistant .markdown-content p');
    const rect=(node:Element|null|undefined)=>node?.getBoundingClientRect().toJSON();
    return {scrollTop:element.scrollTop,scrollHeight:element.scrollHeight,clientHeight:element.clientHeight,
      container:rect(element),last:rect(last),paragraph:rect(p[p.length-1]),text:p[p.length-1]?.textContent};
  });
  writeFileSync(`${out}/conversation-geometry.json`,JSON.stringify(geometry,null,2));
  await page.screenshot({path:`${out}/desktop-viewport.png`,fullPage:false});
  await page.screenshot({path:`${out}/desktop-turn-ownership.png`,fullPage:true});
  await page.reload();
  await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('frog-message-assistant').last()).toContainText('固定离线回答');
  await expect(page.getByTestId('task-result')).toHaveCount(1);
  expect(await page.getByTestId('task-result').getAttribute('data-owner-message-id')).toBe(owner);
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  const messages=await page.request.get(`/api/chat/sessions?mode=builtin&purpose=study`);
  const sessions=await messages.json();expect(sessions.length).toBe(1);
  const saved=await (await page.request.get(`/api/chat/sessions/${sessions[0].session_id}/messages`)).json();
  const linked=saved.filter((m:any)=>m.planner_task_id);
  // One proposal plus its real confirmation receipt; QA has no task result.
  expect(linked).toHaveLength(2);
  expect(new Set(linked.map((m:any)=>m.planner_task_id)).size).toBe(1);
  expect(saved.at(-1).planner_task_id).toBeNull();
  expect(saved.at(-1).status).toBe('completed');
});

test('locked coverage, cancellation and new-scope expansion retain old item version',async ({page})=>{
  await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();
  const before=await (await page.request.get('/api/plans/today')).json();
  await page.getByTestId('extend-plan').click();
  await expect(page.getByTestId('covered-plan-scope')).toContainText('等比级数');
  await page.getByTestId('tree-kp-picker-open').click();
  await expect(page.getByTestId('pick-node-business.geometric')).toBeDisabled();
  for (const item of before.items) {
    const code=Object.keys(fixture.nodes).find(code=>fixture.nodes[code]===item.kp_id)!;
    await expect(page.getByTestId(`pick-node-${code}`)).toBeDisabled();
  }
  await page.getByRole('button',{name:'返回当前卷'}).click();
  const cancelled=await (await page.request.get('/api/plans/today')).json();
  expect(cancelled.items).toEqual(before.items);
  await page.getByTestId('extend-plan').click();
  if (await page.getByTestId('tree-kp-picker-open').getAttribute('aria-expanded')!=='true') await page.getByTestId('tree-kp-picker-open').click();
  // Explicitly select only the new rank node, regardless of prior test success.
  const lhopital=page.getByTestId('pick-node-business.lhopital');
  if (!(await lhopital.isDisabled()) && await lhopital.getAttribute('aria-pressed')==='true') await lhopital.click();
  const rank=page.getByTestId('pick-node-business.rank');
  if (await rank.getAttribute('aria-pressed')!=='true') await rank.click();
  await page.getByTestId('close-tree-kp-picker').click();
  const [response]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith('/api/plans/today/generate') && r.request().method()==='POST'),
    page.getByTestId('generate-plan').click(),
  ]);
  expect(response.status()).toBe(201);
  await expect(page.getByTestId('study-setup')).toHaveCount(0);
  await expect(page.getByTestId('study-active')).toBeVisible();
  const after=await (await page.request.get('/api/plans/today')).json();
  expect(after.items.length).toBe(before.items.length+1);
  expect(after.items.slice(0,before.items.length)).toEqual(before.items);
  expect(after.items.at(-1).kp_id).toBe(fixture.nodes['business.rank']);
  await page.reload();await page.getByTestId('extend-plan').click();
  await expect(page.getByTestId('covered-plan-scope')).toContainText('矩阵的秩');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:`${out}/mobile-locked-scope.png`,fullPage:true});
});

test('real failure stays on its own message; new success and refresh do not inherit it',async ({page})=>{
  await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
  const field=page.getByTestId('task-goal');
  await field.fill('请解释当前这道题，模拟连接失败');await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('frog-turn-error')).toBeVisible();await expect(field).toBeEnabled();
  const failed=page.getByTestId('frog-message-assistant').last();
  await expect(failed).toHaveAttribute('data-status','failed');
  const failedId=await failed.getAttribute('data-message-id');
  await field.fill('当前这道题怎么解？');await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('frog-message-assistant').last()).toHaveAttribute('data-status','completed');
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.locator(`[data-message-id="${failedId}"]`)).toHaveAttribute('data-status','failed');
  await page.reload();await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('frog-message-assistant').last()).toHaveAttribute('data-status','completed');
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.locator(`[data-message-id="${failedId}"]`)).toHaveAttribute('data-status','failed');
  await expect(page.locator(`[data-message-id="${failedId}"]`).getByTestId('frog-message-failed-status')).toBeVisible();
});

test('explicit safe retry succeeds without duplicating the user or erasing failure history',async ({page})=>{
  await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
  const question='请解释当前这道题，模拟可恢复失败';
  await page.getByTestId('task-goal').fill(question);await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('frog-turn-error')).toBeVisible();
  const failedId=await page.getByTestId('frog-message-assistant').last().getAttribute('data-message-id');
  await page.getByRole('button',{name:'重试这条回复',exact:true}).click();
  await expect(page.getByTestId('frog-message-assistant').last()).toHaveAttribute('data-status','completed');
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.getByTestId('frog-message-user').filter({hasText:question})).toHaveCount(1);
  await expect(page.locator(`[data-message-id="${failedId}"]`)).toHaveAttribute('data-status','failed');
  await page.reload();await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('frog-message-assistant').last()).toHaveAttribute('data-status','completed');
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.getByTestId('frog-message-user').filter({hasText:question})).toHaveCount(1);
});
