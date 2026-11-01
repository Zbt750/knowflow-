// Actual Vue controls + real existing API, no chat/model actions or seeded rows.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const {chromium}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-freeze-preflight-20261021/stage1-closeout');
const run=path.resolve('storage/manual-experience/naiwa-real-20261020/restored-offline-20261020');
const permit=JSON.parse(fs.readFileSync(path.join(run,'study-setup-permit.json'),'utf8'));
const base='http://127.0.0.1:63046',kp='32a29e1e-8ae3-41fc-9322-43f727596819';
const target='9ba9c177-26a2-4918-bf84-b85159f9b002',version='92c57d4d-f0bf-4df2-b9b2-c949a3d43904';
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false});
 const context=await browser.newContext({viewport:{width:1366,height:900}});
 const page=await context.newPage(),requests=[],errors=[],blocked=[];
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());
  const record={method:request.method(),path:url.pathname};
  if(url.pathname.startsWith('/api/'))requests.push(record);
  if(url.protocol.startsWith('http')&&(url.hostname!=='127.0.0.1'||url.port!=='63046')){blocked.push(record);return route.abort();}
  if(request.method()==='POST'&&url.pathname==='/api/plans/today/generate'){
   const body=request.postDataJSON();
   assert.deepEqual(body,{selected_kp_ids:[kp],confirm_legacy_set_transition_ids:[],budget:'light'});
   record.body=body;
   return route.continue({headers:{...request.headers(),'X-Naiwa-Setup-Nonce':permit.nonce}});
  }
  if(!['GET','HEAD'].includes(request.method())){blocked.push(record);return route.abort();}
  return route.continue();
 });
 try{
  let healthy=false;
  for(let i=0;i<70;i++){
   try{const r=await context.request.get(base+'/api/health',{timeout:2500});if(r.ok()){healthy=true;break;}}catch{}
   await new Promise(resolve=>setTimeout(resolve,2000));
  }
  assert(healthy,'isolated backend not healthy');
  const h=await context.request.get(base+'/api/health');
  assert.equal(h.headers()['x-naiwa-preparation'],'read-only-archive-protected');
  const before=await(await context.request.get(base+'/api/plans/today')).json();
  assert.equal(before.status,'setup','do not overwrite existing today paper');
  await page.goto(base+'/study',{waitUntil:'networkidle'});
  await page.getByTestId('generate-plan').waitFor();
  await page.getByTestId('tree-kp-picker-open').click();
  await page.getByTestId('scope-picker-search').waitFor();
  for(const name of ['导数计算','线性表']){
   const remove=page.getByRole('button',{name:'从范围移出'+name,exact:true});
   if(await remove.count())await remove.click();
  }
  if(await page.getByTestId('scope-selected-'+kp).count()===0){
   await page.getByTestId('scope-picker-search').fill('洛必达法则');
   await page.getByRole('button',{name:'加入洛必达法则',exact:true}).click();
  }
  assert.equal(await page.locator('.scope-selected-list > li').count(),1);
  await page.getByTestId('close-tree-kp-picker').click();
  await page.locator('label').filter({has:page.getByTestId('budget-light')}).click();
  await page.screenshot({path:path.join(out,'study-setup-before-confirm.png'),fullPage:true});
  const responsePromise=page.waitForResponse(r=>r.url()===base+'/api/plans/today/generate'&&r.request().method()==='POST');
  await page.getByTestId('generate-plan').click();
  const response=await responsePromise,body=await response.json();
  fs.writeFileSync(path.join(out,'study-create-response.json'),JSON.stringify({status:response.status(),body},null,2));
  assert.equal(response.status(),201,JSON.stringify(body));
  const item=body.items.find(i=>i.question_id===target);
  assert(item,'expected original not selected');assert.equal(item.question_version_id,version);assert.equal(item.kp_id,kp);
  await page.getByTestId('study-active').waitFor();
  await page.getByTestId('focus-question').waitFor();
  await page.screenshot({path:path.join(out,'study-original-bound.png'),fullPage:true});
  await page.reload({waitUntil:'networkidle'});
  await page.getByTestId('focus-question').waitFor();
  const restored=await(await context.request.get(base+'/api/plans/today')).json();
  assert.equal(restored.plan_id,body.plan_id);
  assert.equal(restored.items.filter(i=>i.question_id===target).length,1);
  assert.equal(restored.items.find(i=>i.question_id===target).question_version_id,version);
  assert.equal(restored.completed_count,0);
  await page.screenshot({path:path.join(out,'study-after-refresh.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
  fs.writeFileSync(path.join(out,'study-setup-browser.json'),JSON.stringify({status:'PASS',
   label:'奶蛙最终复验·隔离今日学习测试卷',label_storage:'test manifest; DailyPlan has no name field',
   browser:'visible system Chrome automated; actual Vue selection and confirmation',plan_id:body.plan_id,
   question_id:target,question_version_id:version,practice_item_id:item.id,total_items:body.items.length,
   refreshed:true,requests,errors,blocked,real_model_requests:0,chat_messages_sent:0},null,2));
  console.log(JSON.stringify({status:'PASS',plan:body.plan_id,item:item.id,items:body.items.length,refresh:true,real_calls:0}));
 }catch(error){
  await page.screenshot({path:path.join(out,'study-setup-failure.png'),fullPage:true}).catch(()=>{});
  fs.writeFileSync(path.join(out,'study-setup-failure.json'),JSON.stringify({error:String(error),requests,errors,blocked},null,2));
  throw error;
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
