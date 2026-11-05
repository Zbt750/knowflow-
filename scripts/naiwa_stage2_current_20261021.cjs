// No model/API response mocking. Session titles alone are marked in the real
// creation request; messages are typed unchanged into the actual Vue composer.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const {chromium}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-current-baseline-real5-20261021');
const round=path.resolve('storage/quality-audits/naiwa-freeze-preflight-20261021/round5');
const base='http://127.0.0.1:63046',scene=process.argv[2];
assert(['AGENT','GENERATE'].includes(scene));
if(scene==='GENERATE')assert(fs.existsSync(path.join(out,'agent-quality-pass.json')),'Agent must pass independent review first');
const input=scene==='AGENT'?'根据最近错题和薄弱点，给出90分钟数学二复习建议，未经确认不要创建计划。':'这道题不错，帮我生成一道更难的类似题。';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
function save(name,value){const p=path.join(out,name),t=p+'.tmp';fs.writeFileSync(t,JSON.stringify(value,null,2));fs.renameSync(t,p);}
const ledger=()=>read(path.join(round,'provider-ledger.json'));
function seal(reason){require('node:child_process').execFileSync('python',['scripts/naiwa_close_round5_20261021.py',reason],{cwd:process.cwd(),windowsHide:true,timeout:5000});}
function enable(){
 const l=ledger();assert(!l.stop_reason,l.stop_reason);assert(l.requests.length<5);
 assert((l.scene_counts[scene]||0)<(scene==='AGENT'?4:1));
 assert(l.requests.every(r=>r.finished&&r.state==='COMPLETED_USAGE_OBSERVED'&&r.finish_reason==='stop'&&r.http_status===200));
 save('next-operation.json',{scene,input,cumulative_before:l.requests.length,remaining_global:5-l.requests.length,time:new Date().toISOString()});
 const p=path.join(round,'control.json'),t=p+'.browser.tmp';
 fs.writeFileSync(t,JSON.stringify({paid_enabled:true,authorization_received:true,active_scene:scene}));fs.renameSync(t,p);
 console.log(JSON.stringify({before_user_operation:scene,used:l.requests.length,scene_used:l.scene_counts[scene],input}));
}
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false});
 const context=await browser.newContext({viewport:{width:1366,height:900},baseURL:base});
 await context.setExtraHTTPHeaders({'x-naiwa-final-scene':scene,'x-naiwa-final-nonce':fs.readFileSync(path.join(out,'browser-nonce.txt'),'utf8').trim()});
 const page=await context.newPage();page.setDefaultTimeout(30000);
 const errors=[],blocked=[],api=[],journeys=fs.existsSync(path.join(out,'journeys.json'))?read(path.join(out,'journeys.json')):[];
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());
  try{
   if(u.protocol.startsWith('http')&&(u.hostname!=='127.0.0.1'||u.port!=='63046'))throw Error('browser external request forbidden');
   if(u.pathname.startsWith('/api/'))api.push({method:req.method(),path:u.pathname});
   if(req.method()==='POST'&&u.pathname==='/api/chat/sessions'){
    const body=req.postDataJSON();assert.equal(body.purpose,'study');assert.equal(body.mode,'builtin');
    const marked={...body,title:'奶蛙最终真实复验·'+(scene==='AGENT'?'数学二整体90分钟':'当前题更难变式')+'·20261021'};
    const response=await route.fetch({postData:JSON.stringify(marked)});assert.equal(response.status(),201);
    const created=await response.json(),sessions=read(path.join(out,'sessions.json'));
    assert(!sessions[scene],'do not recreate/retry a scene');sessions[scene]=created.session_id;save('sessions.json',sessions);
    save(scene+'-session-created.json',{actual_creation_body:marked,response:created,model_requests:0});
    return route.fulfill({response});
   }
   if(req.method()==='POST'&&/\/assistant(?::|%3A)stream$/.test(u.pathname)){
    const body=req.postDataJSON();assert.equal(body.question,input);
    assert.equal(body.study_context.question_id,'9ba9c177-26a2-4918-bf84-b85159f9b002');
    assert.equal(body.study_context.question_version_id,'92c57d4d-f0bf-4df2-b9b2-c949a3d43904');
    assert(body.study_context.knowledge_node_ids.includes('32a29e1e-8ae3-41fc-9322-43f727596819'));
    return route.continue();
   }
   if(!['GET','HEAD'].includes(req.method()))throw Error('unexpected browser write');
   return route.continue();
  }catch(error){blocked.push({method:req.method(),path:u.pathname,error:String(error)});seal('browser_request_validation_failed');return route.abort();}
 });
 async function capture(response,action,before){
  const text=await response.text();seal('user_operation_response_finished');
  const frames=text.trim().split(/\r?\n\r?\n/).filter(Boolean).map(part=>{
   const lines=part.split(/\r?\n/),event=lines.find(l=>l.startsWith('event:'))?.slice(6).trim(),raw=lines.find(l=>l.startsWith('data:'))?.slice(5).trim();
   try{return {event,data:JSON.parse(raw)}}catch{return {event,raw}};
  });
  const sid=read(path.join(out,'sessions.json'))[scene];
  const messages=await(await context.request.get('/api/chat/sessions/'+sid+'/messages')).json();
  const tasks=frames.filter(f=>f.event==='planner').map(f=>f.data);
  const taskId=tasks.at(-1)?.task_id;
  const task=taskId?await(await context.request.get('/api/learning-tasks/'+taskId)).json():null;
  await page.waitForTimeout(600);
  const row={scene,input,action,session_id:sid,http_status:response.status(),request:response.request().postDataJSON(),
   frames,persisted_messages:messages,task,physical_requests:ledger().requests.length-before,cumulative:ledger().requests.length,
   rendered_text:await page.locator('body').innerText(),errors:errors.slice(),blocked:blocked.slice(),api:api.slice()};
  journeys.push(row);save('journeys.json',journeys);
  fs.writeFileSync(path.join(out,scene+'-'+journeys.length+'.sse'),text);
  await page.screenshot({path:path.join(out,scene+'-'+journeys.length+'.png'),fullPage:true});
  if(scene==='AGENT')save('agent-final-answer.json',{session_id:sid,task,assistant_messages:messages.filter(m=>m.role==='assistant'),technical_completed:task?.status==='answered'||task?.status==='ready'});
  return row;
 }
 async function send(action,button){
  const before=ledger().requests.length;enable();
  const wait=page.waitForResponse(r=>/\/assistant(?::|%3A)stream$/.test(r.url())&&r.request().method()==='POST',{timeout:45000});wait.catch(()=>{});
  await button.click();return capture(await wait,action,before);
 }
 const watchdog=setTimeout(()=>{seal('browser_total_watchdog');page.close().catch(()=>{});},300000);
 try{
  let healthy=false;
  for(let i=0;i<70;i++){
   try{const r=await context.request.get('/api/health',{timeout:2500});if(r.ok()){healthy=true;assert.equal(r.headers()['x-naiwa-experience'],'current-baseline-real5');assert.equal((await r.json()).llm_model,'deepseek-flash');break;}}catch(error){if(String(error).includes('Assertion'))throw error;}
   await new Promise(resolve=>setTimeout(resolve,2000));
  }
  assert(healthy,'explicit real runtime not healthy');
  const today=await(await context.request.get('/api/plans/today')).json();
  const source=today.items.find(i=>i.question_id==='9ba9c177-26a2-4918-bf84-b85159f9b002');
  assert(source);assert.equal(source.question_version_id,'92c57d4d-f0bf-4df2-b9b2-c949a3d43904');assert.equal(today.focus_item_id,source.id);
  save(scene+'-source-context.json',{today_plan_id:today.plan_id,source});
  await page.goto('/study',{waitUntil:'networkidle'});await page.getByTestId('focus-stem').waitFor();
  await page.screenshot({path:path.join(out,scene+'-source.png'),fullPage:true});
  await page.getByTestId('study-frog-launcher').click();await page.getByTestId('task-goal').fill(input);
  let result=await send('原始用户输入',page.getByTestId('task-arrange'));
  if(scene==='GENERATE'&&ledger().scene_counts.GENERATE===0&&await page.getByTestId('generation-confirmation').count()){
   const select=page.getByTestId('generation-node-select');if(await select.count())await select.selectOption('32a29e1e-8ae3-41fc-9322-43f727596819');
   await page.screenshot({path:path.join(out,'GENERATE-confirmation.png'),fullPage:true});
   result=await send('明确确认洛必达知识点并生成1题',page.getByTestId('confirm-generation-node'));
  }
  const sid=result.session_id,beforeRefresh=await(await context.request.get('/api/chat/sessions/'+sid+'/messages')).json();
  const countBefore=ledger().requests.length;
  await page.reload({waitUntil:'networkidle'});await page.getByTestId('study-frog-launcher').click();await page.getByTestId('task-goal').waitFor();
  await page.waitForTimeout(800);
  const afterRefresh=await(await context.request.get('/api/chat/sessions/'+sid+'/messages')).json();
  assert.deepEqual(afterRefresh,beforeRefresh);assert.equal(ledger().requests.length,countBefore);
  await page.screenshot({path:path.join(out,scene+'-refresh.png'),fullPage:true});
  save(scene+'-refresh.json',{history_identical:true,physical_count_unchanged:true,messages:afterRefresh,
    rendered_text:await page.locator('body').innerText()});
  await context.storageState({path:path.join(out,scene+'-browser-state.json')});
  save(scene+'-browser-result.json',{status:'EXECUTED_NOT_QUALITY_VERDICT',errors,blocked,requests:ledger().requests.length,
    scenario_requests:ledger().scene_counts[scene],task_status:result.task?.status,history_refresh:true});
  console.log(JSON.stringify({scene,requests:ledger().requests.length,scenario_requests:ledger().scene_counts[scene],task_status:result.task?.status,history_refresh:true}));
 }catch(error){
  seal('browser_failure');await page.screenshot({path:path.join(out,scene+'-failure.png'),fullPage:true}).catch(()=>{});
  save(scene+'-browser-result.json',{status:'FAIL',error:String(error),errors,blocked,api,ledger_count:ledger().requests.length});throw error;
 }finally{clearTimeout(watchdog);seal('browser_end');await browser.close();}
})().catch(error=>{console.error(String(error));process.exitCode=1;});
