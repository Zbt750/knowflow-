// Real system Chrome, real Vue controls. No HTTP mocking or inserted messages.
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');
const {chromium,expect}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-real-retest-20261020-budget7');
const old=path.resolve('storage/quality-audits/naiwa-real-20261020');
const mode=process.argv[2],base='http://127.0.0.1:63046';
const read=n=>JSON.parse(fs.readFileSync(path.join(out,n),'utf8'));
const save=(n,x)=>{const p=path.join(out,n);fs.writeFileSync(p+'.tmp',JSON.stringify(x,null,2));fs.renameSync(p+'.tmp',p);};
const ledger=()=>read('provider-ledger.json');
const rows=fs.existsSync(path.join(out,'journeys.json'))?read('journeys.json'):[];
function seal(reason){save('control.json',{paid_enabled:false,active_scene:null,closed_reason:reason,time:Date.now()/1000});}
function enable(scene){const l=ledger();if(l.stop_reason)throw Error('GLOBAL STOP '+l.stop_reason);
 if(l.scene_counts[scene]>=l.scene_limits[scene])throw Error('scene exhausted');
 save('next-operation.json',{scene,physical_before:l.requests.length,remaining:7-l.requests.length,time:new Date().toISOString()});
 save('control.json',{paid_enabled:true,active_scene:scene});}
async function main(){
 const browser=await chromium.launch({channel:'chrome',headless:false});
 const state=path.join(out,'browser-state.json');
 const context=await browser.newContext({baseURL:base,viewport:{width:1366,height:900},...(fs.existsSync(state)?{storageState:state}:{})});
 const page=await context.newPage();page.setDefaultTimeout(30000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function scope(scene){await context.setExtraHTTPHeaders({'x-naiwa-retest-case':scene,'x-naiwa-retest-nonce':fs.readFileSync(path.join(out,'browser-nonce.txt'),'utf8').trim()});}
 async function capture(response,input,scene,before){
  const sse=await response.text();
  const frames=sse.trim().split(/\r?\n\r?\n/).filter(Boolean).map(part=>{
    const lines=part.split(/\r?\n/),ev=lines.find(l=>l.startsWith('event:'))?.slice(6).trim(),raw=lines.find(l=>l.startsWith('data:'))?.slice(5).trim();
    try{return {event:ev,data:JSON.parse(raw)}}catch{return {event:ev,raw}}});
  const sid=response.url().match(/sessions\/([^/]+)\//)?.[1];
  await page.waitForTimeout(700);
  const result={scene,input,session_id:sid,url:response.url(),request:response.request().postDataJSON(),http:response.status(),
    frames,sse,physical_requests:ledger().requests.length-before,cumulative:ledger().requests.length,
    final_ui:await page.locator('body').innerText(),page_errors:errors.slice(),timestamp:new Date().toISOString()};
  if(sid){const r=await page.request.get(`/api/chat/sessions/${sid}/messages`);result.persisted_messages=await r.json();}
  rows.push(result);save('journeys.json',rows);
  fs.writeFileSync(path.join(out,`${scene}-${rows.length}-full-chat.txt`),result.final_ui);
  await page.screenshot({path:path.join(out,`${scene}-${rows.length}.png`),fullPage:true});
  if(sid){await page.reload();await page.waitForTimeout(1000);
   if(scene!=='TEACH')await page.getByTestId('study-frog-launcher').click();
   result.refreshed_ui=await page.locator('body').innerText();
   await page.screenshot({path:path.join(out,`${scene}-${rows.length}-refresh.png`),fullPage:true});save('journeys.json',rows);}
  seal('operation_complete');
  return result;
 }
 async function send(scene,input,study){
  await scope(scene);const field=study?page.getByTestId('task-goal'):page.locator('#chat-question');
  await expect(field).toBeEnabled();await field.fill(input);
  const before=ledger().requests.length;enable(scene);
  const wait=page.waitForResponse(r=>/\/(assistant|answers)(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST',{timeout:45000});wait.catch(()=>{});
  if(study)await page.getByTestId('task-arrange').click();else await field.press('Enter');
  return capture(await wait,input,scene,before);
 }
 async function study(){await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible({timeout:60000});
  await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('task-goal')).toBeVisible();}
 try{
  const health=await page.request.get('/api/health');expect(health.headers()['x-naiwa-experience']).toBe('real-retest-budget7');
  expect((await health.json()).llm_model).toBe('deepseek-flash');
  if(mode==='AGENT'){
   await study();await send('AGENT','【本轮最小复验】我今天只有90分钟，请结合隔离题库里数学二的真实可练题、最近错题和薄弱知识点，给我一份有依据的复习安排。只给建议，不创建或追加任何学习计划。',true);
  }else if(mode==='TEACH'){
   const refs=JSON.parse(fs.readFileSync(path.join(old,'sessions.json'),'utf8'));
   await page.goto('/chat?session_id='+refs.A1);await expect(page.locator('.message-row--assistant').first()).toBeVisible();
   await send('TEACH','【本轮最小复验】洛必达法则我还是不太懂，换一种简单方式讲一下。哪些情况能用、哪些不能直接用？请简洁但不要省略关键条件。',false);
  }else if(mode==='GENERATE'){
   await study();
   const stem=page.getByTestId('focus-stem');
   for(let n=0;n<12&&!((await stem.innerText()).includes('e^x'));n++){
    const prev=page.getByTestId('previous-question');if(await prev.isEnabled())await prev.click();else break;
   }
   await expect(stem).toContainText('e^x');
   save('source-screen.json',{stem:await stem.innerText(),fixture:JSON.parse(fs.readFileSync(path.join(old,'fixture.json'),'utf8'))});
   await page.screenshot({path:path.join(out,'GENERATE-source.png'),fullPage:true});
   await send('GENERATE','【本轮最小复验】帮我生成一道比当前这题难一点的类似题。保留洛必达极限的核心考点，不只是替换数字。',true);
   const confirm=page.getByTestId('generation-confirmation');
   if(await confirm.count()){
    await scope('GENERATE');const select=page.getByTestId('generation-node-select');
    if(await select.count())await select.selectOption({label:'洛必达法则'});
    await page.screenshot({path:path.join(out,'GENERATE-confirm.png'),fullPage:true});
    const before=ledger().requests.length;enable('GENERATE');
    const wait=page.waitForResponse(r=>/assistant(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST',{timeout:45000});wait.catch(()=>{});
    await page.getByTestId('confirm-generation-node').click();await capture(await wait,'点击确认知识点并生成（1题）','GENERATE',before);
   }
  }else if(mode==='EXPLAIN'){
   const review=read('independent-math-review.json');expect(review.correct).toBe(true);
   await study();await send('EXPLAIN','刚才生成的那道题怎么做？请核对答案并清楚解释关键步骤，不要再生成新题。',true);
  }else throw Error('invalid scene');
  await context.storageState({path:state});
  save('browser-last-run.json',{mode,status:'COMPLETED_NOT_QUALITY_VERDICT',errors,physical_total:ledger().requests.length});
 }catch(e){seal('browser_failure');await page.screenshot({path:path.join(out,`${mode}-failure.png`),fullPage:true}).catch(()=>{});
  save('browser-last-run.json',{mode,status:'FAIL',error:String(e),errors,physical_total:ledger().requests.length});throw e;
 }finally{seal('browser_end');await context.storageState({path:state}).catch(()=>{});await browser.close();}
}
main().catch(e=>{console.error(String(e));process.exitCode=1;});
