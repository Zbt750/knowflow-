import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
const root=resolve('..');
function snapshot(id:string){return JSON.parse(execFileSync(process.env.QUERY_FOLLOWUP_PYTHON!,['-m','tests.integration.scope_math_backend',id],{cwd:root,encoding:'utf8'}));}
const facts=()=>JSON.parse(readFileSync(resolve(process.env.QUERY_FOLLOWUP_OUTPUT!,'scope-math-fixture.json'),'utf8'));
test.beforeEach(async({page})=>{await page.clock.setFixedTime(new Date('2026-10-20T02:00:00Z'));});
async function study(page:any){await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();await page.getByTestId('study-frog-launcher').click();}
async function send(page:any,input:string){await page.getByTestId('task-goal').fill(input);
 const pending=page.waitForResponse((r:any)=>/assistant(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST');
 await page.getByTestId('task-arrange').click();const response=await pending;
 const raw=await response.text();return {raw,body:response.request().postDataJSON(),frames:raw.trim().split(/\r?\n\r?\n/).map((p:string)=>{
  const lines=p.split(/\r?\n/);return {event:lines.find(l=>l.startsWith('event:'))?.slice(6).trim(),data:JSON.parse(lines.find(l=>l.startsWith('data:'))!.slice(5))};})};}
test('真实Vue五类范围与明确切换：任务goal、库存、学习记录和刷新证据一致',async({page},info)=>{
 await study(page);const before=snapshot('scope-before');
 const cases=[
  ['根据最近错题和薄弱点，给我90分钟数学二整体复习建议，不创建计划','explicit_subject_scope',2],
  ['改成只复习洛必达法则30分钟，只给建议，不创建计划','explicit_user_scope',1],
  ['围绕当前题目给我30分钟复习建议，只给建议，不创建计划','explicit_current_question',1],
  ['按最近错题涉及的多个知识点，给我数学二30分钟复习建议，不创建计划','explicit_recent_wrong_scope',2],
  ['切回数学二整体90分钟复习，只给建议，不创建计划','explicit_subject_scope',2],
  ['时间减少到30分钟，继续给我建议，不创建计划','same_session_explicit_scope',2]];
 for(const [index,[input,origin,minimum]] of cases.entries()){
  const wire=await send(page,String(input));expect(wire.frames.filter(f=>f.event==='error')).toEqual([]);
  const planner=wire.frames.find(f=>f.event==='planner')!.data;expect(planner.status).toBe('answered');
  const db=snapshot('scope-'+index),task=db.learning_tasks.find((r:any)=>r.id===planner.task_id);
  const handoff=task.context.planner_handoff;expect(handoff.constraints.scope_origin).toBe(origin);
  const allowed=handoff.constraints.resolved_scope_node_ids;
  const inventory=planner.trace.find((t:any)=>t.tool==='get_question_availability');
  expect(inventory.status).toBe('completed');expect(inventory.result.practice_eligible_count).toBe(minimum===1?3:4);
  expect(inventory.result.scope_node_ids.every((id:string)=>allowed.includes(id))).toBe(true);
  const state=planner.trace.find((t:any)=>t.tool==='get_learning_state');expect(state.result.states.length).toBeGreaterThanOrEqual(Number(minimum));
  if(minimum===1)expect(allowed).toEqual([facts().lhopital_id]);
  else expect(allowed.length).toBeGreaterThan(1);
  expect(db.daily_plans).toEqual(before.daily_plans);expect(db.practice_items).toEqual(before.practice_items);
  await info.attach('scope-'+index,{body:JSON.stringify({wire,task,inventory},null,2),contentType:'application/json'});
  await page.screenshot({path:info.outputPath('scope-'+index+'.png'),fullPage:true});
 }
 const text=await page.getByTestId('frog-conversation').innerText();await page.reload();await page.getByTestId('study-frog-launcher').click();
 await expect.poll(()=>page.getByTestId('frog-conversation').innerText()).toBe(text);
 await page.screenshot({path:info.outputPath('scope-refresh.png'),fullPage:true});
});

test('真实历史错误响应拒绝保存：版本、今日卷与学习证据无副作用',async({page},info)=>{
 await study(page);await page.getByTestId('continue-question').click();
 await expect(page.getByTestId('focus-stem')).toContainText('错误样本');
 const before=snapshot('bad-before');await send(page,'帮我生成一道比当前题更难的类似题');
 await expect(page.getByTestId('generation-confirmation')).toBeVisible();
 await page.getByTestId('generation-node-select').selectOption(facts().lhopital_id);
 const wait=page.waitForResponse(r=>/assistant(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST');
 await page.getByTestId('confirm-generation-node').click();const wire=await (await wait).text();
 await expect(page.getByTestId('frog-conversation')).toContainText('未保存');
 const after=snapshot('bad-after');
 for(const key of ['questions','question_versions','practice_items','question_attempts','learning_events','daily_plans'])expect(after[key]).toEqual(before[key]);
 expect(wire).toContain('personal_generation_answer_conflict');
 await page.reload();await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('frog-conversation')).toContainText('未保存');
 await info.attach('bad-persistence',{body:JSON.stringify({wire,before,after}),contentType:'application/json'});
 await page.screenshot({path:info.outputPath('bad-rejected-refresh.png'),fullPage:true});
});

test('正确变式经真实API保存为参考个人题：不自动加入、不冒充数学全题认证',async({page},info)=>{
 await study(page);const before=snapshot('good-before');
 await send(page,'帮我生成一道比当前题更难的类似题');
 await expect(page.getByTestId('generation-confirmation')).toBeVisible();await page.getByTestId('generation-node-select').selectOption(facts().lhopital_id);
 const wait=page.waitForResponse(r=>/assistant(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST');
 await page.getByTestId('confirm-generation-node').click();const wire=await (await wait).text();
 const preview=page.getByTestId('personal-generation-result');await expect(preview).toContainText('加入今日学习与保存题目是两个独立操作');
 await expect(preview.getByRole('button',{name:'加入今日学习',exact:true})).toBeEnabled();
 const after=snapshot('good-after');const added=after.questions.filter((q:any)=>!before.questions.some((p:any)=>p.id===q.id));
 expect(added).toHaveLength(1);const q=added[0];expect(q.kp_id).toBe(facts().lhopital_id);expect(q.correct_answer).toBe('A');
 const check=q.grading_config.generation.bounded_calculus_check;
 expect(check.status).toBe('CONSISTENT_FRAGMENT');expect(check.expected).toBe('0');expect(check.whole_question_verified).toBe(false);
 expect(q.grading_config.generation.answer_independently_verified).toBe(false);expect(q.bank_scope).toBe('personal');
 expect(after.question_versions.length).toBe(before.question_versions.length+1);
 expect(after.practice_items).toEqual(before.practice_items);expect(after.learning_events).toEqual(before.learning_events);
 await page.reload();await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('personal-generation-result')).toContainText('加入今日学习与保存题目是两个独立操作');
 await info.attach('good-persistence',{body:JSON.stringify({wire,question:q,before,after}),contentType:'application/json'});
 await page.screenshot({path:info.outputPath('good-reference-saved.png'),fullPage:true});
});
