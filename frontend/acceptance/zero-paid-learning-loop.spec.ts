// Real Chrome/Vue/API/owned PG, fixed Provider only. Never a live-model claim.
import {test,expect} from '@playwright/test';

test('零付费：当前版本生题、预览、确认加入、作答锁定、历史与会话隔离',async({page},info)=>{
 const capture=async(name:string)=>{const r=await page.request.get('/api/__zero/evidence');expect(r.ok()).toBe(true);const data=await r.json();await info.attach(name,{body:JSON.stringify(data,null,2),contentType:'application/json'});return data;};
 const before=await capture('database-before');
 await page.clock.setFixedTime(new Date('2026-10-19T00:00:02+08:00'));
 await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();
 await expect(page.getByTestId('focus-stem')).toContainText('隔离原题');
 const source=before.questions.find((q:any)=>q.stem.includes('隔离原题'));
 await page.getByTestId('study-frog-launcher').click();
 await page.getByTestId('task-goal').fill('帮我生成一道比当前题难一点的类似题');await expect(page.getByTestId('task-arrange')).toBeEnabled();await page.getByTestId('task-arrange').click();
 const card=page.getByTestId('generation-confirmation');await expect(card).toBeVisible();await expect(card).toContainText('计划生成 1 道题');
 const select=page.getByTestId('generation-node-select');if(await select.count())await select.selectOption({label:'级数求和（隔离验收）'});
 await page.getByTestId('confirm-generation-node').click();
 const preview=page.getByTestId('personal-generation-result');await expect(preview).toContainText('逐项求导的适用范围');await expect(preview.locator('.generated-question-result__item')).toHaveCount(1);
 const saved=await capture('database-saved-not-added');
 expect(saved.practice_items.length).toBe(before.practice_items.length);
 expect(saved.fixed_provider_requests).toHaveLength(1);
 expect(JSON.stringify(saved.fixed_provider_requests[0])).toContain(source.current_version_id);
 const q=saved.questions.find((r:any)=>!before.questions.some((b:any)=>b.id===r.id));expect(q).toBeTruthy();expect(q.bank_scope).toBe('personal');expect(q.kp_id).toBe(source.kp_id);
 const v=saved.question_versions.find((r:any)=>r.id===q.current_version_id);expect(v.question_id).toBe(q.id);
 await page.screenshot({path:info.outputPath('01-saved-preview.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await preview.getByRole('button',{name:'加入今日学习',exact:true}).scrollIntoViewIfNeeded();
 const composerBox=await page.locator('.frog-composer').boundingBox();expect(composerBox!.y+composerBox!.height).toBeLessThanOrEqual(780);
 expect(await page.getByTestId('task-goal').evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el;})).toBe(true);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('01-preview-mobile.png'),fullPage:true});
 await preview.getByRole('button',{name:'加入今日学习',exact:true}).click();await expect(preview).toContainText('这批题已加入今日学习');
 await page.setViewportSize({width:1366,height:768});
 const added=await capture('database-added');const item=added.practice_items.find((r:any)=>r.question_id===q.id);expect(item.question_version_id).toBe(v.id);expect(item.kp_id).toBe(q.kp_id);
 // Repeating the same business append is idempotent; no extra PracticeItem.
 const replay=await page.request.post('/api/personal-questions/append',{data:{question_ids:[q.id],plan_id:item.plan_id}});expect(replay.ok()).toBe(true);expect((await replay.json()).added).toBe(0);
 await page.reload();await expect(page.getByTestId('study-active')).toBeVisible();
 // Source first, previously wrong item second, new generated item third.
 while(!(await page.getByTestId('focus-stem').innerText()).includes('逐项求导的适用范围'))await page.getByTestId('continue-question').click();
 await page.getByTestId('raw-answer').fill('x*(1+x)/(1-x)^3');await page.getByTestId('submit-answer').click();
 await expect(page.getByTestId('answer-result-label')).toBeVisible();await expect(page.getByText('本次答案已提交并锁定，可以继续查看解析。',{exact:true})).toBeVisible();
 await expect(page.getByTestId('submit-answer')).toHaveCount(0);await expect(page.getByTestId('raw-answer')).toBeDisabled();
 await page.getByTestId('answer-explanation').click();await expect(page.getByTestId('focus-answer')).toContainText('参考解析');
 const done=await capture('database-attempt-event');const attempts=done.question_attempts.filter((r:any)=>r.practice_item_id===item.id || r.question_id===q.id);expect(attempts).toHaveLength(1);expect(attempts[0].question_version_id).toBe(v.id);
 expect(done.learning_events.some((r:any)=>r.question_version_id===v.id)).toBe(true);
 expect(attempts[0].objective_result).toBe('unknown'); // Reference-only is never independently correct.
 expect(done.real_model_http_requests).toBe(0);expect(done.blocked_network).toEqual([]);
 await page.screenshot({path:info.outputPath('02-submitted-locked.png'),fullPage:true});
 await page.reload();while(!(await page.getByTestId('focus-stem').innerText()).includes('逐项求导的适用范围'))await page.getByTestId('continue-question').click();
 await expect(page.getByTestId('answer-result-label')).toBeVisible();await expect(page.getByTestId('submit-answer')).toHaveCount(0);
 await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('personal-generation-result')).toContainText('这批题已加入今日学习');
 await page.getByRole('button',{name:'收起奶蛙对话',exact:true}).click();
 for(let n=0;n<3 && !(await page.getByTestId('focus-stem').innerText()).includes('隔离原题');n++){
   const previousText=await page.getByTestId('focus-stem').innerText();await expect(page.getByTestId('previous-question')).toBeEnabled();await page.getByTestId('previous-question').click();await expect(page.getByTestId('focus-stem')).not.toHaveText(previousText);
 }
 await expect(page.getByTestId('focus-stem')).toContainText('隔离原题');await page.getByTestId('study-frog-launcher').click();
 await page.getByTestId('task-goal').fill('请解释当前题的求和思路，不要生成新题');
 const contextRequest=page.waitForRequest(r=>r.url().endsWith('/assistant:stream')&&r.method()==='POST');await page.getByTestId('task-arrange').click();
 expect((await contextRequest).postDataJSON().study_context.question_id).toBe(source.id);
 await expect(page.getByTestId('frog-message-assistant').last()).toContainText('先独立思考');
 const study=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=study')).json();
 await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();await page.locator('#chat-question').fill('请用一个例子讲解幂级数求导和积分。');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.locator('.message-row--assistant').last()).toContainText('先独立思考');
 await expect(page.locator('.message-bubble--collapsed')).toHaveCount(0);await expect(page.getByRole('heading',{name:'通用知识参考',exact:true})).toHaveCount(1);
 await page.getByRole('button',{name:'收起回答',exact:true}).click();await expect(page.locator('.message-bubble--collapsed')).toHaveCount(1);await page.getByRole('button',{name:'展开完整回答',exact:true}).click();
 await page.locator('#chat-question').fill('我还是不懂，接着刚才的例子再解释一次。');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.message-row--assistant')).toHaveCount(2);await expect(page.locator('.message-row--assistant').last()).toContainText('先独立思考');
 await expect(page.getByRole('heading',{name:'通用知识参考',exact:true})).toHaveCount(2);
 await page.reload();await expect(page.locator('.message-bubble--collapsed')).toHaveCount(0);await expect(page.locator('.katex')).not.toHaveCount(0);await page.evaluate(()=>document.fonts.ready);
 const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();expect(qa.every((r:any)=>!study.some((s:any)=>s.session_id===r.session_id))).toBe(true);
 await page.screenshot({path:info.outputPath('03-readable-qa.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('04-mobile-qa.png'),fullPage:true});
 await capture('database-final');
});

for(const [fault,expectedCode] of [['网络中断','provider_network'],['超时','provider_timeout'],['截断','answer_truncated']] as const)test(`Agent ${fault} 后保留证据并给出受限建议，刷新不产生计划副作用`,async({page},info)=>{
 await page.clock.setFixedTime(new Date('2026-10-19T00:00:02+08:00'));await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
 const before=await(await page.request.get('/api/__zero/evidence')).json();
 await page.getByTestId('task-goal').fill(`结合学习记录安排20分钟复习，只给建议不要创建计划。模拟${fault}`);await page.getByTestId('task-arrange').click();
 const assistant=page.getByTestId('frog-message-assistant').last();
 await expect(assistant).toContainText('我只根据本轮已读取到的学习记录和题库数据整理了有限建议');
 await expect(assistant).toContainText('没有创建或追加今日学习');
 await expect(page.getByTestId('task-result')).toContainText('查询完成');
 const afterFailure=await(await page.request.get('/api/__zero/evidence')).json();
 const task=afterFailure.learning_tasks.find((r:any)=>!before.learning_tasks.some((b:any)=>b.id===r.id));
 expect(task).toBeTruthy();expect(task.status).toBe('answered');expect(task.error_code).toBe(expectedCode);expect(task.trace.length).toBeGreaterThan(0);
 expect(task.trace.some((step:any)=>step.status==='completed'&&['get_learning_state','get_question_availability'].includes(step.tool))).toBe(true);
 await page.reload();await page.getByTestId('study-frog-launcher').click();
 await expect(page.getByTestId('frog-message-assistant').last()).toContainText('我只根据本轮已读取到的学习记录和题库数据整理了有限建议');
 const after=await(await page.request.get('/api/__zero/evidence')).json();
 expect(after.learning_tasks.length).toBe(afterFailure.learning_tasks.length);expect(after.daily_plans.length).toBe(before.daily_plans.length);expect(after.practice_items.length).toBe(before.practice_items.length);
 await info.attach('evidence-preserved-without-write',{body:JSON.stringify({task,after}),contentType:'application/json'});await page.screenshot({path:info.outputPath('partial-advice-restored.png'),fullPage:true});
});

test('真实错误数学响应被拒绝，全部学习实体不增长',async({page},info)=>{
 const before=await(await page.request.get('/api/__zero/evidence')).json();await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
 await page.locator('#chat-question').fill(String.raw`帮我生成一道更难的类似计算题。原题：错误样本，当 |x|<1 时求 \(\sum_{n=1}^{\infty}nx^n\) 的和。`);await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.getByTestId('generation-confirmation')).toBeVisible();await page.getByTestId('generation-node-select').selectOption({label:'级数求和（隔离验收）'});await page.getByTestId('confirm-generation-node').click();
 await expect(page.getByTestId('generation-diagnostics')).toBeVisible();await expect(page.getByTestId('personal-generation-result')).toHaveCount(0);
 await expect(page.getByTestId('generation-diagnostics')).not.toContainText('网络连接失败');
 const after=await(await page.request.get('/api/__zero/evidence')).json();for(const name of ['questions','question_versions','practice_items','question_attempts','learning_events'])expect(after[name].length).toBe(before[name].length);
 await info.attach('quality-rejected-no-learning-writes',{body:JSON.stringify({before,after}),contentType:'application/json'});await page.screenshot({path:info.outputPath('quality-rejected.png'),fullPage:true});
});

test('知识树忍者脚趾分支保留，桌面和手机真实节点可展开选中',async({page},info)=>{
 await page.goto('/knowledge');await expect(page.getByTestId('knowledge-canvas')).toBeVisible();await expect(page.locator('.frog-tree-figure')).toBeAttached();await expect(page.locator('.frog-tree-mascot')).toBeAttached();
 const paths=await page.locator('.canvas-branches path').count();expect(paths).toBeGreaterThan(0);
 await page.getByTestId('tree-node-math.calculus').click();await page.getByTestId('tree-node-math.calculus.limit').click();await page.getByTestId('tree-node-math.calculus.limit.lhopital').click();await expect(page.getByTestId('detail-title')).toContainText('洛必达');
 await page.screenshot({path:info.outputPath('tree-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('tree-mobile.png'),fullPage:true});
});
