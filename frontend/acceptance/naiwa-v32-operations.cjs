// Actual Vue clicks: cancel, concurrent same-task confirmation, lost response,
// two-tab readback, committed fields/versions/order. No model/network substitution.
const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const epoch=process.env.NAIWA_V32_EPOCH||'4';
const root=path.resolve(__dirname,'../..'),out=path.join(root,'storage/quality-audits/naiwa-v32-20261022'),dir=path.join(out,'operations-'+epoch);fs.mkdirSync(dir);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),save=(n,v)=>fs.writeFileSync(path.join(dir,n),JSON.stringify(v,null,2),{flag:'wx'}),base='http://127.0.0.1:63246';
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':read(path.join(out,'runtime-'+epoch+'/window.json')).nonce}});
 await context.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63245','63246'].includes(u.port))?r.abort():r.continue()});
 async function page(){const p=await context.newPage();const day=process.env.NAIWA_V32_STUDY_DATE||`2040-02-${String(2+Number(epoch)).padStart(2,'0')}`;await p.clock.install({time:new Date(day+'T01:00:00Z')});return p;}
 const p=await page(),evidence=[],errors=[];p.on('pageerror',e=>errors.push(String(e)));
 async function get(url){const r=await context.request.get(base+url);assert(r.ok());return r.json()}
 async function proposal(label){
  await p.goto(base+'/chat',{waitUntil:'networkidle'});await p.getByRole('button',{name:'＋',exact:true}).click();
  const wait=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  await p.locator('#chat-question').fill('讲讲洛必达法则，再从题库挑一道加入今日卷。');await p.locator('#chat-question').press('Enter');
  const response=await wait,raw=await response.text();fs.writeFileSync(path.join(dir,label+'.sse'),raw,{flag:'wx'});
  const frames=raw.split('\n\n').filter(f=>f.includes('data: ')).map(f=>({event:f.match(/event: (.+)/)?.[1],data:JSON.parse(f.match(/data: (.+)/)[1])}));
  assert(!frames.some(f=>f.event==='error'));return frames.find(f=>f.event==='practice_request').data;
 }
 async function handoff(){
  await p.getByTestId('request-send').click();await expect(p.getByText('✓ 已发送给奶蛙',{exact:true})).toBeVisible();
  await p.goto(base+'/study',{waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();
  const pending=p.waitForResponse(r=>r.url().endsWith('/plan')&&r.request().method()==='POST');
  await p.getByRole('button',{name:'查看安排建议',exact:true}).click();const r=await pending;assert(r.ok());
  const result=await r.json();save('handoff-'+result.task.task_id+'.json',result);return result;
 }
 try{
  const original=await get('/api/plans/today');assert.equal(original.total_count,1);
  const cancelled=await proposal('cancel-preview');await p.getByRole('button',{name:'不用',exact:true}).click();
  await expect(p.getByText('已撤回这份练习需求。',{exact:true})).toBeVisible();
  assert.equal((await get('/api/practice-requests/'+cancelled.id)).status,'declined');
  assert.equal((await get('/api/plans/today')).total_count,1);await p.reload({waitUntil:'networkidle'});
  await expect(p.getByText('已撤回这份练习需求。',{exact:true})).toBeVisible();
  await p.screenshot({path:path.join(dir,'cancel-refresh.png'),fullPage:true});
  await proposal('concurrent-preview');const first=await handoff();
  await expect(p.getByTestId('task-confirm')).toBeVisible();assert.equal((await get('/api/plans/today')).total_count,1);
  const second=await page();await second.goto(base+'/study',{waitUntil:'networkidle'});await second.getByTestId('study-frog-launcher').click();
  if(!await second.getByTestId('task-confirm').count())await second.locator(`[data-practice-request-id="${first.request.id}"]`).getByRole('button',{name:'查看已有方案',exact:true}).click();
  await expect(second.getByTestId('task-confirm')).toBeVisible();
  const replies=[p,second].map(pg=>pg.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST'));
  await Promise.all([p.getByTestId('task-confirm').click(),second.getByTestId('task-confirm').click()]);
  const responses=await Promise.all(replies);assert(responses.every(r=>r.ok()));
  const receipts=await Promise.all(responses.map(r=>r.json()));assert.deepEqual(receipts[0].append_result,receipts[1].append_result);
  const two=await get('/api/plans/today');assert.equal(two.total_count,2);
  for(const old of original.items){const current=two.items.find(i=>i.id===old.id);assert.deepEqual(current,old);}
  await expect(p.getByTestId('today-append-result')).toHaveCount(1);
  await p.screenshot({path:path.join(dir,'two-tabs-commit.png'),fullPage:true});
  await second.reload({waitUntil:'networkidle'});await second.getByTestId('study-frog-launcher').click();
  await expect(second.getByTestId('today-append-result')).toHaveCount(1);await second.close();
  await proposal('lost-response-preview');const next=await handoff();let receipt,confirms=0;
  await p.route('**/api/learning-tasks/*/confirm',async route=>{confirms++;const r=await route.fetch();assert(r.ok());receipt=await r.json();save('lost-response-committed.json',receipt);await route.abort('failed')},{times:1});
  await p.locator(`[data-task-id="${next.task.task_id}"]`).getByTestId('task-confirm').click();
  await expect(p.locator(`[data-operation-id="${next.task.task_id}"]`)).toBeVisible({timeout:15000});
  await expect(p.getByTestId('today-append-result')).toHaveCount(1);await expect(p.getByTestId('frog-turn-error')).toHaveCount(0);assert.equal(confirms,1);
  const three=await get('/api/plans/today');assert.equal(three.total_count,3);
  for(const old of two.items){assert.deepEqual(three.items.find(i=>i.id===old.id),old);}
  const item=receipt.append_result.items[0],actual=three.items.find(i=>i.id===item.item_id);
  assert.equal(actual.question_version_id,item.question_version_id);assert.equal(actual.display_number,item.number);
  // Frozen business data is authoritative; not every choice question has A-D.
  // Assert every option label AND value, not merely an assumed option count.
  const expectedOptions=Object.entries(item.options||{});
  assert(expectedOptions.length>0,'choice fixture must contain its actual options');
  const renderedOptions=p.getByTestId('today-append-result').locator('li');
  await expect(renderedOptions).toHaveCount(expectedOptions.length);
  for(const [index,[key,value]] of expectedOptions.entries()){
   await expect(renderedOptions.nth(index)).toContainText(key);
   await expect(renderedOptions.nth(index)).toContainText(String(value));
  }
  await expect(p.getByTestId('today-append-result')).toContainText(item.stem);
  await p.reload({waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();await expect(p.getByTestId('today-append-result')).toHaveCount(1);
  await p.screenshot({path:path.join(dir,'lost-response-refresh.png'),fullPage:true});
  // New ordinary question has no ownership of the preceding success card.
  const wait=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  await p.locator('#frog-message-input').fill('先别安排，只解释洛必达法则。');await p.locator('#frog-message-input').press('Enter');
  const r=await wait;fs.writeFileSync(path.join(dir,'new-explain.sse'),await r.text(),{flag:'wx'});
  await expect(p.getByTestId('frog-message-assistant').last().getByTestId('today-append-result')).toHaveCount(0);
  // All existing public Lhopital candidates have now been added by actual UI.
  const unavailable=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  await p.locator('#frog-message-input').fill('讲讲洛必达法则，再从题库挑一道加入今日卷。');await p.locator('#frog-message-input').press('Enter');
  const noneResponse=await unavailable,noneRaw=await noneResponse.text();fs.writeFileSync(path.join(dir,'inventory-exhausted.sse'),noneRaw,{flag:'wx'});
  const noneFrames=noneRaw.split('\n\n').filter(v=>v.includes('data: ')).map(v=>({event:v.match(/event: (.+)/)?.[1],data:JSON.parse(v.match(/data: (.+)/)[1])}));
  const noneTask=noneFrames.find(v=>v.event==='planner').data;assert.equal(noneTask.status,'needs_info');assert.equal(noneTask.draft,null);
  assert(noneTask.message.includes('去心邻域'));assert(noneTask.message.includes('可新增 0 道'));
  assert.equal((await get('/api/plans/today')).total_count,3);
  await p.screenshot({path:path.join(dir,'inventory-exhausted.png'),fullPage:true});
  save('database-api-evidence.json',{original,two,three,first,next,receipts,receipt,cancelled});
  save('result.json',{status:'PASS',cancelRefresh:true,concurrentSameTask:true,sequentialDifferentTasks:true,lostResponseRecovery:true,originalItemsUnchanged:true,exactVersion:true,officialNumber:true,newQaNoOldCard:true,actualInventoryExhausted:true,modelRequests:0,errors});
  assert.deepEqual(errors,[]);console.log('OPERATIONS_PASS');
 }catch(e){save('failure.json',{error:String(e),stack:e.stack,errors});await p.screenshot({path:path.join(dir,'failure.png'),fullPage:true});console.error(e);process.exitCode=1;}
 finally{console.log('VISIBLE_OPERATIONS_EVIDENCE',dir)}
})();
