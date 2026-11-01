// Actual HTTP APIs + owned PostgreSQL + a fixed, non-network generation model.
// No route interception, qualification fabrication or real model quality claim.
import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('a self-reported easier result cannot satisfy a harder request or show a successful preview',async({page},testInfo)=>{
  expect(process.env.APP_ENV).toBe('test');
  await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
  await page.locator('#chat-question').fill(String.raw`帮我出一道类似的计算题，但是要更难一点。原题：当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。`);
  await page.locator('#chat-question').press('Enter');
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  await page.getByTestId('generation-node-select').selectOption({label:'级数求和（难度冲突隔离）'});
  await page.getByTestId('confirm-generation-node').click();
  await expect(page.getByTestId('generation-diagnostics')).toContainText('personal_generation_difficulty_mismatch');
  await expect(page.getByTestId('personal-generation-result')).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId('generation-diagnostics')).toContainText('难度要求检查');
  await page.screenshot({path:testInfo.outputPath('difficulty-conflict-not-saved.png')});
});

test('study assistant persists separately while QA history supports rename pin reload and delete',async({page},testInfo)=>{
  expect(process.env.APP_ENV).toBe('test');
  expect(Number(process.env.KAOYAN_OWNED_TEST_PORT)).toBeGreaterThan(18000);
  await page.clock.setFixedTime(new Date('2026-10-19T00:00:02+08:00'));
  let sentSession='';
  page.on('request',request=>{if(request.url().endsWith('/assistant:stream'))sentSession=request.url().match(/\/sessions\/([^/]+)\//)![1];});
  await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();
  const goal=String.raw`帮我出一道类似的练习题，难度更大一点。原题：当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。`;
  await page.getByTestId('task-goal').fill(goal);await page.getByTestId('task-goal').press('Enter');
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  const studyId=sentSession;
  expect(studyId).toBeTruthy();
  await page.reload();await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  await expect(page.getByTestId('frog-message-user').last()).toContainText('难度更大一点');
  await page.goto('/chat');
  const sessions=await (await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();
  expect(sessions.some((s:any)=>s.session_id===studyId)).toBe(false);
  await expect(page.locator('.conversation-row').filter({hasText:'今日学习'})).toHaveCount(0);
  await page.getByTitle('新建对话',{exact:true}).click();
  await page.locator('#chat-question').fill(goal);await page.locator('#chat-question').press('Enter');
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  const qaId=sentSession;expect(qaId).not.toBe(studyId);
  const row=page.locator('.conversation-row.selected');
  await row.click({button:'right'});
  await page.getByRole('menuitem',{name:'置顶',exact:true}).click();
  await expect(row).toContainText('置顶');
  await row.click({button:'right'});
  page.once('dialog',dialog=>dialog.accept('隔离验收：独立深入讨论'));
  await page.getByRole('menuitem',{name:'重命名',exact:true}).click();
  await expect(row).toContainText('隔离验收：独立深入讨论');
  await page.reload();
  await expect(page.locator('.conversation-row.selected')).toContainText('隔离验收：独立深入讨论');
  await expect(page.locator('.conversation-row.selected')).toContainText('置顶');
  await page.screenshot({path:testInfo.outputPath('separate-qa-history.png')});
  await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  const own=await (await page.request.get('/api/chat/sessions?mode=builtin&purpose=study')).json();
  expect(own.some((s:any)=>s.session_id===studyId&&s.purpose==='study')).toBe(true);
  await page.goto(`/chat?session_id=${qaId}`);
  await expect(page.locator('.conversation-row.selected')).toContainText('隔离验收：独立深入讨论');
  await page.locator('.conversation-row.selected').click({button:'right'});
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('menuitem',{name:'删除',exact:true}).click();
  await expect(page.locator('.conversation-row').filter({hasText:'隔离验收：独立深入讨论'})).toHaveCount(0);
  expect((await page.request.get(`/api/chat/sessions/${studyId}/messages`)).ok()).toBe(true);
});

test('harder similar request shows truncation diagnosis and persists it after refresh without regeneration', async ({page},testInfo)=>{
  expect(process.env.APP_ENV).toBe('test');
  expect(Number(process.env.KAOYAN_OWNED_TEST_PORT)).toBeGreaterThan(18000);
  await page.clock.setFixedTime(new Date('2026-10-19T00:00:02+08:00'));
  await page.goto('/chat');
  await page.getByTitle('新建对话',{exact:true}).click();
  const composer=page.locator('#chat-question');
  await composer.fill(String.raw`帮我出一道类似的题，但是要更难一点。原题：当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。`);
  await composer.press('Enter');
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  await page.getByTestId('generation-node-select').selectOption({label:'级数求和（截断诊断隔离）'});
  await page.getByTestId('confirm-generation-node').click();
  const notice=page.getByTestId('generation-diagnostics');
  await expect(notice).toContainText('personal_generation_output_truncated');
  await expect(notice).toContainText('不是已判定答案错误');
  await expect(page.getByTestId('personal-generation-result')).toHaveCount(0);
  await page.reload();
  await expect(notice).toContainText('personal_generation_output_truncated');
  await page.screenshot({path:testInfo.outputPath('truncation-diagnosis-history.png')});
});

test('variant request, pasted original, confirmed node, persisted preview and explicit idempotent append', async ({ page }, testInfo) => {
  expect(process.env.APP_ENV).toBe('test');
  expect(Number(process.env.KAOYAN_OWNED_TEST_PORT)).toBeGreaterThan(18000);
  expect(new URL(process.env.TEST_DATABASE_URL!.replace('postgresql+psycopg:', 'postgresql:')).port).not.toBe('5433');
  await page.clock.setFixedTime(new Date('2026-10-19T00:00:02+08:00'));
  await page.goto('/chat');
  await page.getByTitle('新建对话',{exact:true}).click();
  const composer = page.locator('#chat-question');
  await composer.fill('帮我生成一道难度更大一点的类似题'); await composer.press('Enter');
  await expect(page.getByText('请把原题贴过来', {exact:false})).toBeVisible();
  const original = String.raw`当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。`;
  await composer.fill(original); await composer.press('Enter');
  const confirmation = page.getByTestId('generation-confirmation');
  await expect(confirmation).toBeVisible();
  await page.getByTestId('generation-node-select').selectOption({label:'级数求和（隔离验收）'});
  await page.getByTestId('confirm-generation-node').click();
  const preview = page.getByTestId('personal-generation-result');
  await expect(preview).toContainText('级数求和（隔离验收）');
  await expect(preview).toContainText('逐项求导的适用范围');
  await expect(preview.locator('.katex')).not.toHaveCount(0);
  const difficulty=preview.getByTestId('generation-difficulty-summary');
  await expect(difficulty).toContainText('目标难度');
  await expect(difficulty).toContainText('较难');
  await expect(difficulty).toContainText('比原题更难');
  await expect(difficulty).toContainText('模型自评理由');
  await expect(difficulty).toContainText('尚无独立难度验证');
  await difficulty.scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('difficulty-preview-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await difficulty.scrollIntoViewIfNeeded();
  const bounds=await difficulty.boundingBox();
  expect(bounds).toBeTruthy();expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.width).toBeGreaterThan(300);
  expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(390);
  expect(await difficulty.locator('dl').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length)).toBe(1);
  await page.screenshot({path:testInfo.outputPath('difficulty-preview-mobile.png')});
  await page.setViewportSize({width:1366,height:768});
  const assertDatabase = (added:boolean) => {
    const code = `
import json, os
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from backend.models.learning import Question, QuestionVersion, PracticeItem
from backend.models.personal_generation import PersonalGenerationBatch
from scripts.prepare_e2e_learning import validate_test_target
url=validate_test_target(os.environ.get('TEST_DATABASE_URL'),os.environ.get('KAOYAN_OWNED_TEST_PORT'))
engine=create_engine(url)
with engine.connect() as c:
 c.exec_driver_sql('SET TRANSACTION READ ONLY')
 with Session(bind=c) as db:
  batch=db.scalar(select(PersonalGenerationBatch).order_by(PersonalGenerationBatch.created_at.desc()))
  ids=batch.result['question_ids']; assert len(ids)==1
  from uuid import UUID
  q=db.get(Question,UUID(ids[0])); v=db.get(QuestionVersion,q.current_version_id)
  assert q.bank_scope=='personal' and q.auto_review_event_id is None
  assert v.question_id==q.id and v.kp_id==q.kp_id
  items=list(db.scalars(select(PracticeItem).where(PracticeItem.question_id==q.id)))
  assert len(items)==${added ? 1 : 0}
  if items: assert items[0].question_version_id==v.id and items[0].kp_id==q.kp_id
  print(json.dumps({'question_id':str(q.id),'version_id':str(v.id),'kp_id':str(q.kp_id),'practice_items':len(items),'batch_status':batch.status}))
engine.dispose()
`;
    return execFileSync('python', ['-c',code], {cwd:fileURLToPath(new URL('../..',import.meta.url)), encoding:'utf8'});
  };
  const before = assertDatabase(false);
  await page.screenshot({path:testInfo.outputPath('persisted-before-add.png')});
  page.once('dialog', d => d.accept());
  await preview.getByRole('button',{name:'加入今日学习',exact:true}).click();
  await expect(preview).toContainText('这批题已加入今日学习');
  const after = assertDatabase(true);
  await page.reload();
  await expect(page.getByTestId('personal-generation-result')).toContainText('这批题已加入今日学习');
  assertDatabase(true);
  await testInfo.attach('database-proof',{body:JSON.stringify({before:JSON.parse(before),after:JSON.parse(after)}),contentType:'application/json'});
  await page.goto('/study');
  await expect(page.getByTestId('study-active')).toBeVisible();
  await expect(page.getByTestId('extend-plan')).toBeVisible();
  await page.getByTestId('extend-plan').click();
  await expect(page.getByTestId('study-setup')).toContainText('按知识点扩充今日卷');
  await expect(page.getByTestId('recommended-kp')).toBeVisible();
  await page.getByTestId('generate-plan').click();
  await expect(page.getByTestId('study-setup')).toHaveCount(0);
  await expect.poll(async () => {
    const response = await page.request.get('/api/plans/today');
    return (await response.json()).total_count;
  }).toBeGreaterThan(1);
  assertDatabase(true);
  await page.reload();
  await expect(page.getByTestId('extend-plan')).toBeVisible();
  await expect(page.getByTestId('append-questions')).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('midnight-personal-and-extended-paper.png')});
});
