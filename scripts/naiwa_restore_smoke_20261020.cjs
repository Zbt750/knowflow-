// Restore smoke only: existing Vue + production APIs + sealed fixed Provider.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const {chromium, expect} = createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const root = path.resolve('storage/quality-audits/naiwa-restore-20261020');
const old = path.resolve('storage/quality-audits/naiwa-real-20261020');
const base = 'http://127.0.0.1:63046';
const refs = JSON.parse(fs.readFileSync(path.join(old, 'sessions.json'), 'utf8'));
const baseline = JSON.parse(fs.readFileSync(path.join(root, 'database-before.json'), 'utf8'));
const report = {mode:'fixed Provider, sealed egress, no live model', checks:[], page_errors:[], console_errors:[], real_model_requests:0};
const save = () => fs.writeFileSync(path.join(root,'browser-smoke.json'), JSON.stringify(report,null,2));
async function run(){
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const state=path.join(old,'browser-state.json');
 const context=await browser.newContext({baseURL:base,viewport:{width:1366,height:900},...(fs.existsSync(state)?{storageState:state}:{})});
 const page=await context.newPage(); page.setDefaultTimeout(25000);
 page.on('pageerror',e=>report.page_errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')report.console_errors.push(m.text());});
 try {
  const health=await page.request.get('/api/health');expect(health.ok()).toBe(true);
  expect(health.headers()['x-naiwa-experience']).toBe('restored-archive-fixed-provider-egress-sealed');
  expect((await health.json()).llm_model).toBe('FIXED-OFFLINE-NO-PAID-MODEL');
  report.checks.push({name:'frontend proxy, owned backend and fixed mode',status:'PASS'});
  for(const [label,session,route] of [['qa',refs.A1,'/chat'],['materials',refs.D1,'/materials/qa']]){
   const response=await page.request.get(`/api/chat/sessions/${session}/messages`);expect(response.ok()).toBe(true);
   const items=await response.json();
   const previous=baseline.chat_messages.filter(m=>m.session_id===session).sort((a,b)=>a.seq-b.seq);
   expect(items.map(m=>[m.message_id,m.role,m.content,m.status])).toEqual(previous.map(m=>[m.id,m.role,m.content,m.status]));
   await page.goto(`${route}?session_id=${session}`);
   const rows=label==='materials'?page.getByTestId('material-search-assistant'):page.locator('.message-row--assistant');
   await expect(rows).toHaveCount(items.filter(m=>m.role==='assistant').length);
   const visible=await rows.allTextContents();
   await page.screenshot({path:path.join(root,`historical-${label}.png`),fullPage:true});
   await page.reload();
   await expect(rows).toHaveCount(visible.length);
   expect(await rows.allTextContents()).toEqual(visible);
   report.checks.push({name:`historical ${label} messages and refresh`,status:'PASS',session_id:session,messages:items.length});
  }
  await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();
  const studyApi=await page.request.get(`/api/chat/sessions/${refs.B1}/messages`);expect(studyApi.ok()).toBe(true);
  const studyItems=await studyApi.json();
  const oldStudy=baseline.chat_messages.filter(m=>m.session_id===refs.B1).sort((a,b)=>a.seq-b.seq);
  expect(studyItems.map(m=>[m.message_id,m.content,m.status])).toEqual(oldStudy.map(m=>[m.id,m.content,m.status]));
  await page.waitForTimeout(500);
  const visibleStudy=await page.getByTestId('frog-message-assistant').count();
  await page.screenshot({path:path.join(root,'historical-study.png'),fullPage:true});
  report.checks.push({name:'historical study persisted messages',status:'PASS',session_id:refs.B1,messages:studyItems.length,
   visible_assistant_messages:visibleStudy,restored_from_previous_browser_state:fs.existsSync(state)});
  await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
  await page.locator('#chat-question').fill('【恢复冒烟·固定Provider】请用一个例子说明幂级数逐项求导。');
  const responsePromise=page.waitForResponse(r=>/\/(?:assistant|answers)(?::|%3A)stream$/.test(r.url())&&r.request().method()==='POST');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  const answerResponse=await responsePromise;expect(answerResponse.ok()).toBe(true);
  const session=answerResponse.url().match(/sessions\/([^/]+)/)[1];
  expect(baseline.chat_sessions.some(s=>s.id===session)).toBe(false);
  await expect(page.locator('.message-row--assistant').last()).toContainText('固定 Provider 体验模式');
  await expect(page.locator('.katex')).not.toHaveCount(0);
  const title='奶蛙恢复冒烟·固定Provider·零付费';
  expect((await page.request.patch(`/api/chat/sessions/${session}`,{data:{title}})).ok()).toBe(true);
  const messageText=await page.locator('.message-row--assistant').last().innerText();
  await page.reload();await expect(page.locator('.message-row--assistant')).toHaveCount(1);
  expect(await page.locator('.message-row--assistant').last().innerText()).toBe(messageText);
  await page.screenshot({path:path.join(root,'fixed-smoke-refresh.png'),fullPage:true});
  report.checks.push({name:'fixed Provider QA HTTP/SSE, formula and persisted refresh',status:'PASS',session_id:session,title});
  await context.storageState({path:path.join(root,'restored-browser-state.json')});
  expect(report.page_errors).toEqual([]);
  report.status='PASS';save();
 }catch(e){report.status='FAIL';report.error=String(e);await page.screenshot({path:path.join(root,'smoke-failure.png'),fullPage:true});save();throw e;}
 finally{await browser.close();}
}
async function openManual(){
 const profile=path.resolve('storage/manual-experience/naiwa-real-20261020/restored-offline-20261020/chrome-profile');
 const context=await chromium.launchPersistentContext(profile,{channel:'chrome',headless:false,viewport:null});
 const statePath=path.join(root,'restored-browser-state.json');
 const stored=JSON.parse(fs.readFileSync(statePath,'utf8'));
 await context.addInitScript(({origins})=>{
  const original=origins.find(o=>o.origin===location.origin);
  if(original)for(const item of original.localStorage)if(localStorage.getItem(item.name)===null)localStorage.setItem(item.name,item.value);
 },{origins:stored.origins});
 const page=context.pages()[0]||await context.newPage();
 await page.goto(base+'/study');
 console.log(JSON.stringify({mode:'visible Chrome, restored local session pointers',url:base+'/study',profile}));
 await new Promise(resolve=>context.on('close',resolve));
}
(process.argv[2]==='open'?openManual():run().then(()=>console.log(JSON.stringify(report))))
 .catch(e=>{console.error(String(e));process.exitCode=1;});
