const {createRequire}=require('node:module');const req=createRequire(require('node:path').resolve('frontend/package.json'));
const {chromium,expect}=req('@playwright/test');const fs=require('node:fs'),path=require('node:path');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL;
const read=n=>JSON.parse(fs.readFileSync(path.join(out,n),'utf8'));const write=(n,v)=>fs.writeFileSync(path.join(out,n),JSON.stringify(v,null,2));
async function main(){
 const browser=await chromium.launch({channel:'chrome',headless:true});const ctx=await browser.newContext({baseURL:base,viewport:{width:1366,height:900},extraHTTPHeaders:{'x-blind-case':'FREE-browser-regression'}});
 const page=await ctx.newPage(),results=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 const before=read('provider-ledger.json').requests.length;let studyId;
 async function run(id,fn){try{results.push({id,status:'PASS',...await fn()});}catch(e){results.push({id,status:'FAIL',error:e.message});}
  await page.screenshot({path:path.join(out,id+'.png'),fullPage:true}).catch(()=>{});write('browser-free-results.json',results);}
 try{
 await run('FREE-init-enter-guard',async()=>{
  let release;const gate=new Promise(r=>release=r);let sent=0;
  page.on('request',r=>{if(r.url().endsWith('/assistant:stream'))sent++;});
  await page.route('**/api/materials?**',async route=>{await gate;await route.continue();});
  try {
   await page.goto('/chat');await expect(page.locator('#chat-question')).toBeDisabled();
   // Probe the handler itself even if a synthetic IME/queued key reaches it
   // while the native disabled control correctly blocks ordinary typing.
   await page.locator('#chat-question').evaluate(el=>{el.value='奶蛙真实体验测试：帮我出一道练习题。';el.dispatchEvent(new Event('input',{bubbles:true}));});
   await page.locator('#chat-question').dispatchEvent('keydown',{key:'Enter',code:'Enter'});
   expect(sent).toBe(0);await expect(page.locator('#chat-question')).not.toHaveValue('');
  } finally {release();await page.unrouteAll({behavior:'wait'});}
  await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled();
  return {model_requests:0,user_draft_preserved:true,method:'real API response delayed, not model mocked'};
 });
 await run('FREE-tree-card-desktop-mobile',async()=>{
  await page.goto('/knowledge');await expect(page.getByTestId('knowledge-canvas')).toBeVisible();
  await page.getByTestId('tree-node-math.calculus').click();await page.getByTestId('tree-node-math.calculus.series').click();
  await page.getByTestId('tree-node-math.calculus.series.power').click();await expect(page.getByTestId('detail-title')).toContainText('幂级数求和');
  const toes=await page.locator('.canvas-branches path.frog-toe').count();expect(toes).toBeGreaterThan(0);
  await page.screenshot({path:path.join(out,'FREE-tree-ninja.png'),fullPage:true});
  await page.getByTestId('knowledge-search').fill('幂级数');await expect(page.getByTestId('tree-node-math.calculus.series.power')).toBeVisible();await page.getByTestId('knowledge-search').fill('');
  await page.reload();await expect(page.getByTestId('detail-title')).toContainText('幂级数求和');
  await Promise.all([page.waitForURL(/knowledge_node_id=/),page.getByTestId('knowledge-assistant-link').click()]);
  const fixture=read('fixture.json');expect(new URL(page.url()).searchParams.get('knowledge_node_id')).toBe(fixture.node_id);
  await page.locator('#chat-question').fill('请给我出一道这个知识点的练习题。');await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled();
  const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream'));await page.locator('#chat-question').press('Enter');const r=await response;const sse=await r.text();
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();await expect(page.getByTestId('generation-confirmation')).toContainText('计划生成 1 道题');
  const sid=r.url().match(/sessions\/([^/]+)\//)[1];
  await page.goto(`/chat?session_id=${sid}`);await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:path.join(out,'FREE-tree-card-mobile.png'),fullPage:true});await page.setViewportSize({width:1366,height:900});
  return {sid,node_id:fixture.node_id,toes,confirmation_restored:true,sse,model_generation:'NOT_RUN: quality gate issue, no confirm click'};
 });
 await run('FREE-study-persistence-isolation',async()=>{
  await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
  const box=page.getByTestId('task-goal');await expect(box).toBeEnabled();await box.fill('奶蛙真实体验测试：帮我出一道当前知识点的练习题。');
  const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream'));await box.press('Enter');const r=await response;await r.text();studyId=r.url().match(/sessions\/([^/]+)\//)[1];
  await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  const prior=await(await page.request.get(`/api/chat/sessions/${studyId}/messages`)).json();
  await page.reload();await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('generation-confirmation')).toBeVisible();
  await expect(page.getByTestId('frog-message-user').first()).toContainText('奶蛙真实体验测试');
  const restored=await(await page.request.get(`/api/chat/sessions/${studyId}/messages`)).json();expect(restored).toEqual(prior);
  const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();const study=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=study')).json();
  expect(qa.some(s=>s.session_id===studyId)).toBe(false);expect(study.some(s=>s.session_id===studyId)).toBe(true);
  await page.goto('/chat');await expect(page.locator('.conversation-row').filter({hasText:'奶蛙真实体验测试：帮我出一道当前'})).toHaveCount(0);
  return {studyId,qa,study,messages:restored,history_equal:true};
 });
 }finally{expect(read('provider-ledger.json').requests.length).toBe(before);write('browser-free-results.json',results);write('browser-free-errors.json',errors);await browser.close();}
}
main().catch(e=>{write('browser-free-fatal.json',{error:e.stack});process.exitCode=1;});
