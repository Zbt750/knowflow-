import {test,expect} from '@playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';
const out=process.env.BUSINESS_AUDIT_DIR!;
const fixture=JSON.parse(readFileSync(`${out}/browser-fixture.json`,'utf8'));
test.beforeEach(async({context})=>{
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(!['127.0.0.1','localhost'].includes(url.hostname)&&!['data:','blob:'].includes(url.protocol))return route.abort();
  return route.continue();
 });
});

async function lostResponse({page}:any){
 await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
 const field=page.getByTestId('task-goal');
 await field.fill('帮我安排一道矩阵的秩的题到今日卷');await page.getByTestId('task-arrange').click();
 await expect(page.getByTestId('task-confirm')).toBeVisible();
 let attempts=0;
 await page.route('**/api/learning-tasks/*/confirm',async route=>{
  attempts++;const response=await route.fetch();expect(response.ok()).toBeTruthy();await route.abort('failed');
 });
 await page.getByTestId('task-confirm').click();
 const result=page.getByTestId('today-append-result');await expect(result).toHaveCount(1);
 expect(attempts).toBe(1);await expect(result).toContainText('矩阵的秩');await expect(result).toContainText('本次新增 1 道');
 await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
 const saved=await result.innerText();await page.reload();await page.getByTestId('study-frog-launcher').click();
 await expect(result).toHaveCount(1);expect(await result.innerText()).toBe(saved);expect(attempts).toBe(1);
 await page.screenshot({path:`${out}/lost-response-recovered.png`});
}
test('exact compound input → real lesson/tools → confirmed result → refresh/current ordering → independent QA',async({page})=>{
 const errors:string[]=[];const events:unknown[]=[];page.on('pageerror',e=>errors.push(e.message));
 const bodies:Promise<void>[]=[];
 page.on('response',response=>{
  if(response.url().endsWith('/assistant:stream'))bodies.push((async()=>events.push({input:response.request().postDataJSON(),raw:await response.text()}))().then(()=>{}));
 });
 await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();
 await page.getByTestId('study-frog-launcher').click();
 const field=page.getByTestId('task-goal');
 await field.fill('洛必达法则是怎么样的，帮我从题库里面拿出一道放进今日卷');await page.getByTestId('task-arrange').click();
 await expect(page.getByTestId('task-confirm')).toBeVisible();await expect(field).toBeEnabled();
 const message=page.getByTestId('frog-message-assistant').last();
 await expect(message).toContainText('去心邻域');await expect(message).not.toContainText('无法访问');
 await expect(message.locator('.katex').first()).toBeVisible();
 const math=await message.locator('math').evaluateAll(nodes=>nodes.map(n=>n.outerHTML));
 expect(math.some(m=>m.includes('<mfrac><mn>1</mn><mn>2</mn></mfrac>'))).toBeTruthy();
 expect(math.some(m=>m.includes('f')&&m.includes('g'))).toBeTruthy();
 await expect(message.locator('.math-load-note')).toHaveCount(0);
 await expect(page.getByTestId('today-append-result')).toHaveCount(0);
 await expect(page.getByTestId('pending-question-preview')).toContainText('隔离合成洛必达题');
 const card=page.getByTestId('task-result'),taskId=await card.getAttribute('data-task-id');
 const task=await (await page.request.get(`${process.env.E2E_API_BASE}/api/learning-tasks/${taskId}`)).json();
 expect(task.metrics.model_calls).toBe(0);
 expect(task.trace.map((s:any)=>s.tool)).toEqual(['read_lesson','get_learning_state','get_question_availability','find_questions','validate_plan']);
 expect(task.trace.find((s:any)=>s.tool==='find_questions').args_summary.kp_ids).toEqual([fixture.nodes['business.lhopital']]);
 const before=await (await page.request.get(`${process.env.E2E_API_BASE}/api/plans/today`)).json();expect(before.total_count).toBe(3);
 await page.screenshot({path:`${out}/pending-explanation-plan.png`});
 await page.getByTestId('task-confirm').click();
 const result=page.getByTestId('today-append-result');await expect(result).toHaveCount(1);
 await expect(result).toContainText('本次新增 1 道');await expect(result).toContainText('当前共 4 道');
 await expect(result).toContainText('第 2 题');await expect(result).toContainText('洛必达法则');
 await expect(result.locator('h4').first()).toBeInViewport({ratio:0.8});
 await expect(result.locator('li')).toHaveCount(4);
 await expect(result).toContainText('基础');await expect(result).toContainText('预计 5 分钟');
 const added=page.getByTestId('today-added-question');
 const version=await added.getAttribute('data-version-id');expect(version).toBe(fixture.lhopital_version);
 const after=await (await page.request.get(`${process.env.E2E_API_BASE}/api/plans/today`)).json();
 const item=after.items.find((i:any)=>i.id===undefined?false:i.id===null?false:i.question_id===fixture.questions['business.lhopital']);
 expect(item.display_number).toBe(2);expect(item.ordinal).toBe(15);expect(item.question_version_id).toBe(version);
 const savedCard=await result.innerText();const messageId=await card.getAttribute('data-owner-message-id');
 await page.screenshot({path:`${out}/committed-result.png`});
 await page.reload();await page.getByTestId('study-frog-launcher').click();await expect(result).toHaveCount(1);
 expect(await result.innerText()).toBe(savedCard);
 await field.fill('当前这道题怎么做');await page.getByTestId('task-arrange').click();
 await expect(field).toBeEnabled();await expect(page.getByTestId('frog-message-assistant').last()).toContainText('固定离线回答');
 await expect(result).toHaveCount(1);expect(await card.getAttribute('data-owner-message-id')).toBe(messageId);
 const duplicate=await page.request.post(`${process.env.E2E_API_BASE}/api/learning-tasks/${taskId}/confirm`,{data:{draft_version:task.draft_version}});
 expect(duplicate.ok()).toBeTruthy();const duplicateResult=await duplicate.json();expect(duplicateResult.append_result.total_count).toBe(4);
 await page.goto('/chat');await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
 await expect(result).toHaveCount(1);expect(await result.innerText()).toBe(savedCard);
 await page.screenshot({path:`${out}/restored-current-result.png`});await Promise.all(bodies);
 const turn=events.find((value:any)=>value.input.question==='洛必达法则是怎么样的，帮我从题库里面拿出一道放进今日卷') as any;
 const frames=turn.raw.split('\n\n').filter((frame:string)=>frame.includes('data: ')).map((frame:string)=>({
  event:frame.match(/event: (.+)/)?.[1],data:JSON.parse(frame.match(/data: (.+)/)![1])}));
 const done=frames.find((frame:any)=>frame.event==='done');
 expect(frames.filter((frame:any)=>frame.event==='delta').map((frame:any)=>frame.data.text).join('')).toBe(done.data.answer);
 const history=await (await page.request.get(`${process.env.E2E_API_BASE}/api/chat/sessions/${task.session_id}/messages`)).json();
 expect(history.find((m:any)=>m.message_id===messageId).content).toBe(done.data.answer);
 expect(errors).toEqual([]);
 writeFileSync(`${out}/composite-evidence.json`,JSON.stringify({events,task,before,after,duplicateResult,math,errors,fixedProvider:true,realModelCalls:0},null,2));
});

test('historical real response replay: compact fractions and multiline TeX survive SSE and refresh',async({page})=>{
 await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
 const field=page.getByTestId('task-goal');await field.fill('请回放历史公式用于排版回归');await page.getByTestId('task-arrange').click();
 await expect(field).toBeEnabled();
 const answer=page.getByTestId('frog-message-assistant').last();await expect(answer).toContainText('洛必达法则的核心');
 await expect(answer.locator('.math-block')).toHaveCount(7);
 const rawOutsideMath=await answer.locator('.markdown-content').evaluate(element=>{
  const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);const leaks:string[]=[];
  while(walker.nextNode()){
   const node=walker.currentNode;
   if(!node.parentElement?.closest('.katex,pre,code')&&/\\(?:lim|frac)/.test(node.textContent??''))leaks.push(node.textContent??'');
  }
  return leaks;
 });
 expect(rawOutsideMath).toEqual([]);
 await expect(answer.locator('.math-load-note')).toHaveCount(0);
 const math=await answer.locator('math').evaluateAll(nodes=>nodes.map(n=>n.outerHTML));
 expect(math.some(m=>m.includes('<mfrac><mn>1</mn><mn>2</mn></mfrac>'))).toBeTruthy();
 expect(math.some(m=>m.includes('<mfrac><mn>0</mn><mn>0</mn></mfrac>'))).toBeTruthy();
 expect(math.some(m=>m.includes('∞'))).toBeTruthy();
 const count=await answer.locator('.katex').count();expect(count).toBeGreaterThan(10);
 const bars=await answer.locator('.frac-line').evaluateAll(nodes=>nodes.map(node=>({width:node.getBoundingClientRect().width,border:getComputedStyle(node).borderBottomStyle})));
 expect(bars.some(bar=>bar.width>0&&bar.border==='solid')).toBeTruthy();
 const original=await answer.innerText();await page.screenshot({path:`${out}/historical-math-replayed.png`});
 await page.reload();await page.getByTestId('study-frog-launcher').click();
 await expect(answer).toContainText('洛必达法则的核心');expect(await answer.locator('.katex').count()).toBe(count);
 expect(await answer.innerText()).toBe(original);
 writeFileSync(`${out}/math-replay-evidence.json`,JSON.stringify({mode:'HISTORICAL_RESPONSE_REPLAY_NOT_NEW_MODEL',math,count},null,2));
});
test('commit succeeded but response lost: read original operation, one result card, no second append',lostResponse);

test('multiple appended items each show their real bound details and current positions',async({page})=>{
 await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
 const field=page.getByTestId('task-goal');
 await field.fill('讲解洛必达法则，从题库取出两道添加今日卷');await page.getByTestId('task-arrange').click();
 await expect(page.getByTestId('task-confirm')).toBeVisible();
 await expect(page.getByTestId('today-append-result')).toHaveCount(0);
 await page.getByTestId('task-confirm').click();
 const result=page.getByTestId('today-append-result');await expect(result).toHaveCount(1);
 await expect(page.getByTestId('today-added-question')).toHaveCount(2);
 await expect(result).toContainText('本次新增 2 道');
 const paper=await (await page.request.get(`${process.env.E2E_API_BASE}/api/plans/today`)).json();
 for(const article of await page.getByTestId('today-added-question').all()){
  const id=await article.getAttribute('data-item-id');const actual=paper.items.find((i:any)=>i.id===id);
  expect(actual).toBeTruthy();await expect(article).toContainText(`第 ${actual.display_number} 题`);
  await expect(article).toContainText('预计 7 分钟');expect(await article.getAttribute('data-version-id')).toBe(actual.question_version_id);
  await expect(article).toContainText('隔离多题样本');await expect(article.locator('li')).toHaveCount(0);
 }
 const text=await result.innerText();await page.reload();await page.getByTestId('study-frog-launcher').click();
 await expect(page.getByTestId('today-added-question')).toHaveCount(2);expect(await result.innerText()).toBe(text);
 await page.screenshot({path:`${out}/multiple-real-positions.png`});
});

test('personal question fixture → explicit append → one persisted result, no duplicate preview after refresh',async({page})=>{
 await page.addInitScript((session)=>{
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  localStorage.setItem(`learning-assistant:study:${day}`,session);
 },fixture.personal_session);
 await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
 const preview=page.locator('.generated-question-result__item');await expect(preview).toHaveCount(1);
 await expect(page.getByTestId('today-append-result')).toHaveCount(0);
 await page.getByRole('button',{name:'加入今日学习',exact:true}).click();
 const result=page.getByTestId('today-append-result');await expect(result).toHaveCount(1);
 await expect(result).toContainText('个人 AI 练习');await expect(result).toContainText('本次新增 1 道');
 await expect(result.locator('li')).toHaveCount(4);await expect(preview).toHaveCount(0);
 const paper=await (await page.request.get(`${process.env.E2E_API_BASE}/api/plans/today`)).json();
 const actual=paper.items.filter((i:any)=>i.question_id===fixture.personal_question);expect(actual).toHaveLength(1);
 await expect(result).toContainText(`第 ${actual[0].display_number} 题`);
 expect(await page.getByTestId('today-added-question').getAttribute('data-version-id')).toBe(actual[0].question_version_id);
 const text=await result.innerText();await page.reload();await page.getByTestId('study-frog-launcher').click();
 await expect(result).toHaveCount(1);await expect(preview).toHaveCount(0);expect(await result.innerText()).toBe(text);
 const batch=await (await page.request.get(`${process.env.E2E_API_BASE}/api/personal-questions/batches/${fixture.personal_batch}`)).json();
 expect(batch.append_results).toHaveLength(1);
 await page.screenshot({path:`${out}/personal-result-restored.png`});
 writeFileSync(`${out}/personal-result-evidence.json`,JSON.stringify({fixture:'NORMAL_GENERATION_SERVICE_WITH_FIXED_PROVIDER; HISTORY_IS_LABELED_FIXTURE',paper,batch},null,2));
});
