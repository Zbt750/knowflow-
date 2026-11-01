// Actual Chrome + current Vue + actual HTTP/SSE. No page routes or Provider mocks.
const {createRequire}=require('node:module'),path=require('node:path'),fs=require('node:fs');
const {chromium,expect}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL;
const write=(n,v)=>fs.writeFileSync(path.join(out,n),JSON.stringify(v,null,2));
const results=[],errors=[],streams=[];let current='READONLY',qaId,materialId,studyId;
const ledger=()=>JSON.parse(fs.readFileSync(path.join(out,'provider-ledger.json'),'utf8'));
async function main(){
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const ctx=await browser.newContext({baseURL:base,viewport:{width:1366,height:900},extraHTTPHeaders:{'x-blind-case':'READONLY'}});
 const page=await ctx.newPage();page.setDefaultTimeout(30000);
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(/\/(assistant|answers)(:|%3A)stream$/.test(r.url())){const id=current;void r.text().then(text=>{streams.push({id,url:r.url(),http:r.status(),body:r.request().postDataJSON(),text});write('sse.json',streams);}).catch(()=>{});}});
 const shot=async id=>page.screenshot({path:path.join(out,id+'.png'),fullPage:true});
 async function run(id,fn){current=id;await ctx.setExtraHTTPHeaders({'x-blind-case':id});
  const before=ledger().requests.length;write('next-case.json',{id,request_count_before:before,time:new Date().toISOString()});
  try{results.push({id,status:'EXECUTED',...await fn(),physical_requests:ledger().requests.length-before});}
  catch(e){results.push({id,status:'BLOCKED',error:e.message,physical_requests:ledger().requests.length-before});await shot(id+'-blocked').catch(()=>{});}
  write('browser-results.json',results);write('browser-errors.json',errors);
 }
 async function send(selector,button,text){
  if(ledger().stop_reason||ledger().requests.length>=10)throw Error('physical budget stopped');
  const input=page.locator(selector);await expect(input).toBeEnabled();await input.fill(text);
  await expect(button).toBeEnabled();const response=page.waitForResponse(r=>/\/(assistant|answers)(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST',{timeout:30000});
  await button.click();const r=await response;const sse=await r.text();
  await expect(input).toBeEnabled({timeout:150000});
  return {input:text,http:r.status(),session_id:r.url().match(/sessions\/([^/]+)\//)?.[1],sse,cleared:await input.inputValue()===''};
 }
 try{
  await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
  for(const [id,text] of [['QA1','我总把幂级数逐项求导和逐项积分弄混，能用一个简单例子讲清楚吗？'],['QA2','我还是不懂，能不能换一种方式讲？尤其是刚才例子里求导和积分的区别。']])await run(id,async()=>{
   const r=await send('#chat-question',page.getByRole('button',{name:'发送',exact:true}),text);qaId=r.session_id||qaId;
   await shot(id);return {...r,visible:await page.locator('.message-row--assistant').last().innerText(),katex:await page.locator('.message-row--assistant').last().locator('.katex').count()};
  });
  await run('QA-history',async()=>{const before=await(await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json();await page.reload();await expect(page.locator('.message-row--assistant').last()).toBeVisible();const after=await(await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json();expect(after).toEqual(before);await shot('QA-history');return {equal:true,qaId,messages:after};});
  await run('UPLOAD',async()=>{
   await page.goto('/materials');await expect(page.getByTestId('materials-page')).toBeVisible();
   const content='# 奶蛙真实体验测试：幂级数复习笔记\n\n## 逐项求导与积分\n在收敛区间内部，幂级数可以逐项求导与逐项积分，收敛半径不变，端点需要重新检查。\n几何级数为 $\\sum_{n=0}^{\\infty}x^n=1/(1-x)$，其中 $|x|<1$。逐项求导得到 $\\sum_{n=1}^{\\infty}nx^{n-1}=1/(1-x)^2$，再乘以 $x$ 得到 $\\sum_{n=1}^{\\infty}nx^n=x/(1-x)^2$。\n\n## 我的20分钟安排\n今天复习主题是幂级数。先用4分钟回忆几何级数，再用10分钟独立练习，最后用6分钟订正。合计20分钟。\n\n## 资料边界\n这份笔记没有记录408操作系统的进程调度算法，也没有提供今年考试日期。\n';
   fs.writeFileSync(path.join(out,'study-note.md'),content);
   const chooser=page.waitForEvent('filechooser');await page.getByTestId('upload-toggle').click();await(await chooser).setFiles(path.join(out,'study-note.md'));
   await page.getByTestId('upload-title').fill('奶蛙真实体验测试：幂级数复习笔记');
   const posted=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/materials'&&r.request().method()==='POST');await page.getByTestId('upload-submit').click();const r=await posted,created=await r.json();materialId=created.material?.id;expect(r.status()).toBe(201);expect(materialId).toBeTruthy();
   const row=page.locator('.material-item').filter({hasText:'奶蛙真实体验测试：幂级数复习笔记'});await expect(row.locator('.material-status')).toHaveText('可检索',{timeout:180000});
   await row.locator('.material-view').click();await expect(page.getByTestId('material-reader')).toContainText('10分钟');await shot('UPLOAD');
   if(await page.getByRole('button',{name:'关闭资料',exact:true}).count())await page.getByRole('button',{name:'关闭资料',exact:true}).click();
   await page.getByRole('button',{name:'针对奶蛙真实体验测试：幂级数复习笔记提问'}).click();
   return {materialId,created};
  });
  if(materialId)for(const [id,text] of [['RAG1','根据这份笔记，我今天的20分钟具体怎么分配？请按先后顺序告诉我。'],['RAG2','那第二步有多少分钟？最后一步做什么？不要改成新的安排。'],['RAG3','这份笔记有没有说明操作系统的进程调度算法？如果没有，请直接说没有，不要用课外知识代替。']])await run(id,async()=>{
   const r=await send('[data-testid="material-search-question"]',page.getByTestId('material-search-send'),text);
   await shot(id);return {...r,visible:await page.getByTestId('material-search-assistant').last().innerText()};
  });
  await run('RAG-history',async()=>{const rows=await page.getByTestId('material-search-assistant').allTextContents();await page.reload();await expect(page.getByTestId('material-search-assistant')).toHaveCount(rows.length);expect(await page.getByTestId('material-search-assistant').allTextContents()).toEqual(rows);await shot('RAG-history');return {equal:true,count:rows.length};});
  await run('AGENT20',async()=>{
   const l=ledger();if(l.stop_reason||l.requests.length>7)return {status:'NOT_RUN',reason:'fewer than 3 physical requests remain; do not start an unbounded scene'};
   await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();await page.getByTestId('study-frog-launcher').click();
   const r=await send('#frog-message-input',page.getByTestId('task-arrange'),'我今天只有20分钟，结合我的学习记录和当前真实题库，帮我安排幂级数复习。不要创建学习计划，先给我建议。');studyId=r.session_id;
   await shot('AGENT20');return {...r,visible:await page.getByTestId('learning-task-panel').innerText()};
  });
  await run('ISOLATION',async()=>{
   const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json(),study=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=study')).json();
   if(studyId)expect(qa.some(s=>s.session_id===studyId)).toBe(false);expect(qa.some(s=>s.session_id===qaId)).toBe(true);
   return {qa,study,qaId,studyId};
  });
 }finally{await ctx.storageState({path:path.join(out,'browser-state.json')});write('browser-results.json',results);write('browser-errors.json',errors);await browser.close();}
}
main().catch(e=>{write('browser-fatal.json',{error:e.stack});process.exitCode=1;});
