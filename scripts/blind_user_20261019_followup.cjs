const {createRequire}=require('node:module');const req=createRequire(require('node:path').resolve('frontend/package.json'));
const {chromium,expect}=req('@playwright/test');const fs=require('node:fs'),path=require('node:path');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL;
const read=n=>JSON.parse(fs.readFileSync(path.join(out,n),'utf8'));
const write=(n,v)=>fs.writeFileSync(path.join(out,n),JSON.stringify(v,null,2));
async function main(){
 const results=[],errors=[];const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({baseURL:base,viewport:{width:1366,height:900}});const page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 const original=read('browser-results.json');const qaId=original.find(x=>x.id==='A1').session_id;
 const studyId=original.find(x=>x.id==='B-current-version').session_id;const fixture=read('fixture.json');
 async function run(id,fn){try{results.push({id,status:'PASS',...await fn()});}catch(e){results.push({id,status:'FAIL',error:e.message});}
  await page.screenshot({path:path.join(out,id+'.png'),fullPage:true}).catch(()=>{});write('browser-followup-results.json',results);}
 try{
  await run('F1-history-formula',async()=>{
   const before=await(await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json();
   const n=read('provider-ledger.json').requests.length;await page.goto(`/chat?session_id=${qaId}`);
   await expect(page.locator('.message-row--assistant')).toHaveCount(4);
   await expect(page.locator('.message-row--assistant').last().locator('.math-block .katex')).toHaveCount(1);
   expect(await page.locator('.katex-error').count()).toBe(0);
   await page.reload();await expect(page.locator('.message-row--assistant')).toHaveCount(4);
   const after=await(await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json();expect(after).toEqual(before);
   expect(read('provider-ledger.json').requests.length).toBe(n);return {history_equal:true,model_requests_during_restore:0,messages:after};
  });
  await run('F2-server-session-isolation',async()=>{
   const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();
   const study=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=study')).json();
   expect(qa.some(s=>s.session_id===studyId)).toBe(false);expect(study.some(s=>s.session_id===studyId)).toBe(true);
   expect(qa.some(s=>s.session_id===qaId)).toBe(true);
   await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
   await expect(page.getByTestId('frog-message-user').first()).toContainText('类似题');return {qa,study,studyId,qaId};
  });
  await run('F3-tree-context-no-paid-generation',async()=>{
   await page.goto('/knowledge');await expect(page.getByTestId('knowledge-canvas')).toBeVisible();
   const root=page.getByTestId('tree-node-math.calculus');await root.click();
   await page.getByTestId('tree-node-math.calculus.series').click();
   await page.getByTestId('tree-node-math.calculus.series.power').click();
   await expect(page.getByTestId('detail-title')).toContainText('幂级数求和');
   const toes=await page.locator('.canvas-branches path.frog-toe').count();expect(toes).toBeGreaterThan(0);
   await page.getByTestId('knowledge-search').fill('幂级数');await expect(page.getByTestId('tree-node-math.calculus.series.power')).toBeVisible();
   await page.getByTestId('knowledge-search').fill('');await page.reload();await expect(page.getByTestId('detail-title')).toContainText('幂级数求和');
   const [url]=await Promise.all([page.waitForURL(/knowledge_node_id=/),page.getByTestId('knowledge-assistant-link').click()]);
   expect(new URL(page.url()).searchParams.get('knowledge_node_id')).toBe(fixture.node_id);
   await context.setExtraHTTPHeaders({'x-blind-case':'D-free-confirmation'});
   const n=read('provider-ledger.json').requests.length;
   const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream'));
   await page.locator('#chat-question').fill('请给我出一道这个知识点的练习题。');await page.locator('#chat-question').press('Enter');
   await(await response).text();await expect(page.getByTestId('generation-confirmation')).toBeVisible();
   await expect(page.getByTestId('generation-confirmation')).toContainText('计划生成 1 道题');
   expect(read('provider-ledger.json').requests.length).toBe(n);
   const card=await page.getByTestId('generation-confirmation').innerText();
   await page.reload();await expect(page.getByTestId('generation-confirmation')).toBeVisible();
   await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
   await page.screenshot({path:path.join(out,'F3-mobile.png'),fullPage:true});
   await page.setViewportSize({width:1366,height:900});return {toes,node_id:fixture.node_id,card,actual_generation:'NOT_RUN: stopped after independently confirmed bad answer in B',paid_requests:0};
  });
  await run('F4-real-A1-after-routing-fix',async()=>{
   const l=read('provider-ledger.json');expect(l.requests.length).toBeLessThan(10);expect(l.stop_reason).toBeNull();
   await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
   await context.setExtraHTTPHeaders({'x-blind-case':'A1-routing-retest'});
   const input='我最近在复习高等数学的幂级数，但是总是容易把求导和积分弄混，你能给我讲清楚吗？';
   const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream'));
   await page.locator('#chat-question').fill(input);await page.locator('#chat-question').press('Enter');
   const r=await response;const sse=await r.text();write('A1-routing-retest-sse.json',{input,url:r.url(),sse});
   await expect(page.locator('.message-row--assistant').last()).not.toContainText('已毕业节点复习风险');
   await expect(page.locator('.message-row--assistant').last()).toContainText('求导');
   return {input,visible:await page.locator('.message-row--assistant').last().innerText(),ledger:read('provider-ledger.json').summary};
  });
 }finally{write('browser-followup-results.json',results);write('browser-followup-errors.json',errors);await browser.close();}
}
main().catch(e=>{write('browser-followup-fatal.json',{error:e.stack});process.exitCode=1;});
