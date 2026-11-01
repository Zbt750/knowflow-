// Real Vue clicks -> real SSE -> real DeepSeek. No routes/Provider are mocked.
const {createRequire}=require('node:module');
const req=createRequire(require('node:path').resolve('frontend/package.json'));
const {chromium,expect}=req('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL;
const write=(name,data)=>fs.writeFileSync(path.join(out,name),JSON.stringify(data,null,2));
const fixture=JSON.parse(fs.readFileSync(path.join(out,'fixture.json'),'utf8'));
const results=[],errors=[],streams=[];
let caseId='READONLY',qaId=null,studyId=null;
async function main(){
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-blind-case':'READONLY'}});
 const page=await context.newPage();
 page.on('pageerror',e=>errors.push({type:'pageerror',message:e.message}));
 page.on('response',r=>{if(r.url().endsWith('/assistant:stream'))void r.text().then(text=>{streams.push({case:caseId,url:r.url(),status:r.status(),text});write('sse.json',streams);});});
 async function run(id,fn){caseId=id;await context.setExtraHTTPHeaders({'x-blind-case':id});
  try{const detail=await fn();results.push({id,status:'EXECUTED',...detail});}
  catch(e){results.push({id,status:'BLOCKED',error:e.message});await page.screenshot({path:path.join(out,id+'-blocked.png'),fullPage:true}).catch(()=>{});}
  write('browser-results.json',results);write('browser-errors.json',errors);
 }
 async function shot(id){await page.screenshot({path:path.join(out,id+'.png'),fullPage:true});}
 async function send(selector,text){const box=page.locator(selector);await box.fill(text);
  const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST',{timeout:15000});
  await box.press('Enter');const r=await response;const body=await r.text();
  const match=r.url().match(/sessions\/([^/]+)\//);
  return {input:text,status:r.status(),session_id:match?.[1],sse:body};
 }
 async function ledger(){return JSON.parse(fs.readFileSync(path.join(out,'provider-ledger.json'),'utf8'));}
 try{
 await page.goto(base+'/chat');await page.getByTitle('新建对话',{exact:true}).click();
 const turns=[
  '我最近在复习高等数学的幂级数，但是总是容易把求导和积分弄混，你能给我讲清楚吗？',
  '我还是不太懂，你能用一个具体例子讲一下吗？',
  '那刚才这个例子里，为什么要先求导？',
  '你再给我一个简单点的例子，我自己试试。'];
 for(let i=0;i<turns.length;i++)await run('A'+(i+1),async()=>{
  const l=await ledger();if(l.stop_reason||l.requests.length>=7)return {status:'NOT_RUN',reason:l.stop_reason||'reserve_generation_calls'};
  const r=await send('#chat-question',turns[i]);qaId=r.session_id||qaId;
  await shot('A'+(i+1));return {...r,visible:await page.locator('.message-row--assistant').last().innerText(),katex:await page.locator('.message-row--assistant').last().locator('.katex').count(),ledger_summary:(await ledger()).summary};
 });
 await run('A-history',async()=>{
  const before=await (await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json();
  await page.reload();await expect(page.locator('.message-row--assistant').last()).toBeVisible();
  const after=await (await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json();
  expect(after).toEqual(before);await shot('A-history');return {qaId,history_equal:true,history:after};
 });
 await run('B-current-version',async()=>{
  await page.goto(base+'/study');await expect(page.getByTestId('study-active')).toBeVisible();
  await page.getByTestId('study-frog-launcher').click();
  const r=await send('#frog-message-input','这道题我感觉还不错，帮我出一道比这题难一点的类似题。');studyId=r.session_id;
  const card=page.getByTestId('generation-confirmation');
  if(await card.count()){
   await expect(card).toContainText('计划生成 1 道题');await shot('B-confirmation');
   const selector=page.getByTestId('generation-node-select');if(await selector.count())await selector.selectOption({value:fixture.node_id});
   const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST',{timeout:15000});
   await page.getByTestId('confirm-generation-node').click();const generated=await response;await generated.text();
  }
  await shot('B-result');
  return {...r,result:await page.locator('[role="region"][aria-label="奶蛙学习助手对话"]').innerText(),preview_count:await page.locator('.generated-question-result__item').count(),ledger_summary:(await ledger()).summary};
 });
 await run('C-save-add-answer',async()=>{
  const preview=page.getByTestId('personal-generation-result').last();
  if(!await preview.count()||!await preview.locator('.generated-question-result__item').count())return {status:'BLOCKED',reason:'B did not save a quality-approved question; do not lower quality gate'};
  await shot('C-before-add');page.once('dialog',d=>d.accept());
  await preview.getByRole('button',{name:'加入今日学习',exact:true}).click();
  await expect(preview).toContainText('这批题已加入今日学习');
  const plan=await (await page.request.get('/api/plans/today')).json();write('C-plan-after-add.json',plan);
  await page.reload();await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('personal-generation-result')).toContainText('这批题已加入今日学习');
  await page.getByRole('button',{name:'收起奶蛙对话',exact:true}).click();
  await shot('C-paper');return {added:true,refreshed:true,plan,body:await page.locator('main').innerText()};
 });
 await run('D-tree',async()=>{
  await page.goto(base+'/knowledge');await expect(page.getByTestId('knowledge-canvas')).toBeVisible();await shot('D-roots');
  await page.getByTestId('tree-node-math.calculus').click();
  await page.getByTestId('tree-node-math.calculus.series').click();
  await page.getByTestId('tree-node-math.calculus.series.power').click();
  await expect(page.getByTestId('detail-title')).toContainText('幂级数求和');
  const frog=await page.locator('.frog-tree-figure').count();const toes=await page.locator('.canvas-branches path.frog-toe').count();
  await shot('D-selected');await page.reload();await expect(page.getByTestId('detail-title')).toContainText('幂级数求和');
  await page.getByTestId('knowledge-assistant-link').click();
  expect(new URL(page.url()).searchParams.get('knowledge_node_id')).toBe(fixture.node_id);
  const l=await ledger();if(l.stop_reason||l.requests.length>=10)return {frog,toes,context_link:page.url(),status:'PARTIAL',generation_blocked:l.stop_reason||'request_cap'};
  const r=await send('#chat-question','请给我出一道这个知识点的练习题。');
  const card=page.getByTestId('generation-confirmation');
  if(await card.count()){
   await shot('D-confirmation');const selector=page.getByTestId('generation-node-select');if(await selector.count())await selector.selectOption({value:fixture.node_id});
   const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST',{timeout:15000});
   await page.getByTestId('confirm-generation-node').click();await (await response).text();
  }
  await shot('D-result');return {...r,frog,toes,node:fixture.node_id,visible:await page.locator('.message-row--assistant').last().innerText()};
 });
 await run('E-isolation',async()=>{
  const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();
  const study=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=study')).json();
  expect(qa.some(s=>s.session_id===studyId)).toBe(false);expect(study.some(s=>s.session_id===studyId)).toBe(true);
  expect(qa.some(s=>s.session_id===qaId)).toBe(true);
  await page.goto(base+`/chat?session_id=${qaId}`);await expect(page.locator('.message-row--user').first()).toContainText('幂级数');await shot('E-qa');
  await page.goto(base+'/study');await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('frog-message-user').first()).toContainText('类似题');await shot('E-study');
  return {qaId,studyId,qa,study,server_side_purpose_isolation:true};
 });
 }finally{write('browser-results.json',results);write('browser-errors.json',errors);await browser.close();}
}
main().catch(e=>{write('browser-fatal.json',{error:e.stack});process.exitCode=1;});
