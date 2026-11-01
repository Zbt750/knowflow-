/* Visible Chrome, real Vue actions, real local API/SSE and retained PostgreSQL.
 * Model is fixed/offline. GETs inspect persisted facts; no message API shortcut.
 */
const {chromium,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../..'),BASE='http://127.0.0.1:63146';
const AUDIT=path.join(ROOT,'storage/quality-audits/naiwa-v31-20261022');
const suffix=process.env.NAIWA_V31_EPOCH||'7';
const OUT=path.join(AUDIT,suffix==='7'?'browser-final':'browser-final-'+suffix),RUN=path.join(AUDIT,'runtime-'+suffix);
fs.mkdirSync(OUT);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const save=(name,value)=>fs.writeFileSync(path.join(OUT,name),JSON.stringify(value,null,2),{encoding:'utf8',flag:'wx'});
const cases=[
 '讲讲洛必达法则，再从题库挑一道加入今日卷。',
 '洛必达法则是什么？先给我讲清楚，题目可以先选好但不要加入。',
 '帮我找一道洛必达的题，先给我看看。','给我安排一道洛必达题。',
 '先别加题，只解释洛必达法则。','我说的是题库已有的题，不要生成新题。',
 '没有合格题也没关系，你先讲解。','先讲知识点，再问我是否要安排题目。'];
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':read(path.join(RUN,'window.json')).nonce}});
 await context.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63145','63146'].includes(u.port))?r.abort():r.continue()});
 const page=await context.newPage(),errors=[],results=[];
 page.on('pageerror',e=>errors.push(e.message));
 async function get(p){const r=await context.request.get(BASE+p);assert(r.ok());return r.json();}
 async function screenshot(label){await page.screenshot({path:path.join(OUT,label+'.png'),fullPage:true});}
 async function send(text,label,selector='#chat-question'){
  const field=page.locator(selector);await field.fill(text);
  const pending=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/assistant:stream'));
  await field.press('Enter');const response=await pending,raw=await response.text();assert.equal(response.status(),200);
  fs.writeFileSync(path.join(OUT,label+'.sse'),raw,{encoding:'utf8',flag:'wx'});
  const frames=raw.split('\n\n').filter(f=>f.includes('data: ')).map(f=>({event:f.match(/event: (.+)/)?.[1],data:JSON.parse(f.match(/data: (.+)/)[1])}));
  assert(!frames.some(f=>f.event==='error'),JSON.stringify(frames));
  assert(frames.some(f=>f.event==='done'));
  await expect(field).toBeEnabled();await page.waitForTimeout(150);
  await screenshot(label);
  const result={input:text,label,frames,url:page.url(),text:await page.locator('body').innerText(),realModelRequests:0};
  save(label+'.json',result);results.push(result);console.log('UI_DONE',label);return result;
 }
 try{
  await page.goto(BASE+'/chat',{waitUntil:'networkidle'});await page.getByRole('button',{name:'＋',exact:true}).click();
  for(let i=0;i<cases.length;i++){
   const r=await send(cases[i],'case-'+(i+1));
   const latest=page.locator('.messages>article').last();
   if([0,1,2,3,5].includes(i)){
    await expect(latest.getByTestId('request-question-preview')).toHaveCount(1);
    await expect(latest).toContainText('尚未加入今日卷');
    await expect(latest.getByTestId('today-append-result')).toHaveCount(0);
    const draft=r.frames.find(f=>f.event==='practice_request').data;
    assert.equal(draft.details.preview_status,'ready');assert.equal(draft.details.preview_draft.questions.length,1);
    assert.equal(draft.details.preview_draft.questions[0].kp_name,'洛必达法则');
    assert.equal(Object.keys(draft.details.preview_draft.questions[0].options).length,4);
   }else{
    await expect(latest).toContainText('去心邻域');
    await expect(latest.getByTestId('practice-request-card')).toHaveCount(0);
   }
   assert.equal(await latest.locator('.katex-error').count(),0);
  }
  await page.reload({waitUntil:'networkidle'});await screenshot('eight-cases-restored');
  // Isolate the intentional lost-response test in another actual QA session.
  await page.getByRole('button',{name:'＋',exact:true}).click();
  const original='洛必达法则是怎么样的，帮我从题库里面拿出一道放进今日卷。';
  const preview=await send(original,'loss-preview');
  const request=preview.frames.find(f=>f.event==='practice_request').data;
  const before=await get('/api/plans/today');assert.equal(before.total_count,Number(process.env.V31_EXPECT_BEFORE||'1'));
  const sent=page.waitForResponse(r=>r.url().endsWith('/send')&&r.request().method()==='POST');
  await page.getByTestId('request-send').click();const sendResponse=await sent;assert(sendResponse.ok());
  const sentRequest=await sendResponse.json();assert(sentRequest.details.target_study_session_id);
  await page.goto(BASE+'/study',{waitUntil:'networkidle'});await page.getByTestId('study-frog-launcher').click();
  const planned=page.waitForResponse(r=>r.url().endsWith('/plan')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'查看安排建议',exact:true}).click();
  const planningResponse=await planned;assert(planningResponse.ok());const proposal=await planningResponse.json();
  assert.equal(proposal.task.session_id,sentRequest.details.target_study_session_id);
  assert.equal(proposal.task.metrics.model_calls,0);await expect(page.getByTestId('task-confirm')).toBeVisible();
  assert.equal((await get('/api/plans/today')).total_count,before.total_count);
  let confirms=0;let receipt;
  await page.route('**/api/learning-tasks/*/confirm',async route=>{
   confirms++;const response=await route.fetch();assert(response.ok());receipt=await response.json();
   save('committed-but-response-lost.json',{status:response.status(),receipt});await route.abort('failed');
  },{times:1});
  await page.getByTestId('task-confirm').click();
  const card=page.getByTestId('today-append-result');await expect(card).toBeVisible({timeout:15000});
  await expect(card).toHaveCount(1);assert.equal(confirms,1);await expect(page.getByTestId('frog-turn-error')).toHaveCount(0);
  const after=await get('/api/plans/today');assert.equal(after.total_count,before.total_count+1);
  const added=receipt.append_result.items[0];const actual=after.items.find(v=>v.id===added.item_id);
  assert(actual);assert.equal(actual.question_version_id,added.question_version_id);assert.equal(actual.display_number,added.number);
  await expect(card).toContainText('第 '+actual.display_number+' 题');
  await expect(card.locator('li')).toHaveCount(4);await screenshot('lost-response-recovered');
  const text=await card.innerText();await page.reload({waitUntil:'networkidle'});await page.getByTestId('study-frog-launcher').click();
  await expect(card).toBeVisible();await expect(card).toHaveCount(1);assert.equal(await card.innerText(),text);
  await screenshot('committed-refresh');
  // Direct local HTTP is used ONLY for idempotence/negative protocol checks.
  // It does not replace the UI message/confirmation journey above.
  const duplicate=await context.request.post(BASE+'/api/learning-tasks/'+proposal.task.task_id+'/confirm',
   {headers:{origin:BASE},data:{draft_version:proposal.task.draft_version}});
  assert(duplicate.ok());assert.equal((await get('/api/plans/today')).total_count,after.total_count);
  const rejected=await context.request.post(BASE+'/api/practice-requests/'+request.id+'/send',
   {headers:{origin:BASE},data:{source_conversation_id:request.source_conversation_id,target_study_session_id:sentRequest.details.target_study_session_id}});
  assert.equal(rejected.status(),403);
  const unknown=await context.request.post(BASE+'/api/not-authorized',{headers:{origin:BASE},data:{}});assert.equal(unknown.status(),403);
  save('commit-evidence.json',{before,after,receipt,proposal,sentRequest,duplicate:await duplicate.json(),rejected:await rejected.json(),confirms});
  // Explicit topic beats the visible Lhopital question; missing node lessons are not fabricated.
  const switched=await send('讲讲导数计算，再从题库挑一道加入今日卷。','explicit-topic-switch','#frog-message-input');
  const task=switched.frames.find(f=>f.event==='planner').data;
  assert.equal(task.draft.questions[0].kp_name,'导数计算');assert.equal(task.metrics.model_calls,0);
  assert.equal((await get('/api/plans/today')).total_count,after.total_count);
  await expect(page.getByTestId('frog-message-assistant').last().getByTestId('today-append-result')).toHaveCount(0);
  save('summary.json',{status:'PASS',cases:8,lostResponseRecovery:true,repeatConfirm:true,
   exactVersion:true,officialNumber:true,topicSwitch:true,modelRequests:0,errors,
   browser:'visible-system-Chrome',version:browser.version(),rowsAreIsolatedTestData:true});
  assert.deepEqual(errors,[]);console.log('FINAL_UI_PASS');
 }catch(error){save('failure.json',{error:String(error),stack:error.stack,completed:results.map(r=>r.label),modelRequests:0,errors});
  await screenshot('failure');console.error(error);process.exitCode=1;
 }finally{
  // Keep the visible browser available to the user; the host remains offline.
  save('sessions-view.json',{url:page.url(),retained:true,provider:'fixed/offline'});
  console.log('EVIDENCE_SAVED',OUT);
 }
})();
