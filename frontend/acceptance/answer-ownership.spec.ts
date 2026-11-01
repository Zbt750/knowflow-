// Existing four business assertions remain unchanged and run first.
import './business-turn.spec';
import {test,expect} from '@playwright/test';
import {writeFileSync} from 'node:fs';
const out=process.env.BUSINESS_AUDIT_DIR!;

test('partial failed math has ONE Markdown owner, refresh and next success reconcile independently',async({page})=>{
  await page.goto('/study');
  await expect(page.getByTestId('study-active')).toBeVisible();
  await page.getByTestId('study-frog-launcher').click();
  const field=page.getByTestId('task-goal');
  await field.fill('请解释当前这道题，模拟历史诊断');
  await page.getByTestId('task-arrange').click();
  await expect(field).toBeEnabled();
  const body=page.getByTestId('frog-message-assistant').last();
  await expect(body).toContainText('固定离线未完成正文');
  await expect(body.locator('.katex')).toHaveCount(1);
  await expect(page.getByTestId('frog-turn-error')).toBeVisible();
  await expect(page.getByTestId('frog-turn-error')).not.toContainText('固定离线未完成正文');
  await expect(page.getByTestId('frog-turn-error')).not.toContainText('\\frac');
  await page.reload();
  await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('frog-message-assistant').last()).toContainText('固定离线未完成正文');
  await expect(page.getByTestId('frog-turn-error')).not.toContainText('固定离线未完成正文');
  await page.screenshot({path:`${out}/partial-failure-one-owner.png`});
  await field.fill('当前这道题怎么做');await page.getByTestId('task-arrange').click();
  await expect(field).toBeEnabled();
  await expect(page.getByTestId('frog-message-assistant').last()).toContainText('固定离线回答');
  await expect(page.getByTestId('frog-message-assistant').last().locator('.katex')).toHaveCount(1);
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'重试这条回复',exact:true})).toHaveCount(0);
  await page.screenshot({path:`${out}/success-one-owner.png`});
  const before=await page.getByTestId('frog-conversation').innerText();
  await page.reload();await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'重试这条回复',exact:true})).toHaveCount(0);
  expect(await page.getByTestId('frog-conversation').innerText()).toBe(before);
  await page.screenshot({path:`${out}/success-restored.png`});
  writeFileSync(`${out}/restored-conversation.txt`,before,'utf8');
});

test('late error after successful real SSE cannot reattach a retry or overwrite saved success',async({page})=>{
  let injected=0;
  await page.route('**/api/chat/**/assistant:stream',async route=>{
    const response=await route.fetch();
    const body=await response.text();
    expect(body).toContain('event: done');injected++;
    await route.fulfill({response,body:body+'event: error\ndata: '+JSON.stringify({code:'generation_failed',message:'迟到的旧失败'})+'\n\n'});
  });
  await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();
  await page.getByTestId('study-frog-launcher').click();
  const field=page.getByTestId('task-goal');
  await field.fill('当前这道题怎么做');await page.getByTestId('task-arrange').click();
  await expect(field).toBeEnabled();
  expect(injected).toBe(1);
  await expect(page.getByTestId('frog-message-assistant').last()).toContainText('固定离线回答');
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'重试这条回复',exact:true})).toHaveCount(0);
  await page.reload();await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  await expect(page.getByTestId('frog-message-assistant').last()).toContainText('固定离线回答');
});

test('independent QA renders one formula answer, refresh and session switch preserve it',async({page})=>{
  await page.goto('/chat');
  const field=page.locator('#chat-question');
  await expect(field).toBeEnabled();
  await field.fill('当前这道题怎么做');await field.press('Enter');
  await expect(field).toBeEnabled();
  const answer=page.locator('.message-row--assistant');
  await expect(answer).toHaveCount(1);
  await expect(answer).toContainText('固定离线回答');
  await expect(answer.locator('.katex')).toHaveCount(1);
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
  const history=await answer.innerText();
  const url=page.url();
  await page.reload();await expect(page.locator('.message-row--assistant')).toHaveCount(1);
  await expect(page.locator('.message-row--assistant')).toContainText('固定离线回答');
  await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();
  await page.goto(url);
  await expect(page.locator('.message-row--assistant')).toHaveCount(1);
  expect(await page.locator('.message-row--assistant').innerText()).toBe(history);
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
  await page.screenshot({path:`${out}/qa-one-owner-restored.png`});
});
