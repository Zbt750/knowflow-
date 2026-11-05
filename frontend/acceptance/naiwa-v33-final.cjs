// Visible Chrome, actual input events and formal routes. No model answers injected.
const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../..'),OUT=path.join(ROOT,'storage/quality-audits/naiwa-v33-final-20261023'),RUN=path.join(OUT,'runtime-final-1'),BASE='http://127.0.0.1:63246';
const DIR=path.join(OUT,'visible-ui-1');fs.mkdirSync(DIR);const save=(n,v)=>fs.writeFileSync(path.join(DIR,n),JSON.stringify(v,null,2),{flag:'wx'});
const frames=raw=>raw.split('\n\n').filter(x=>x.includes('data: ')).map(x=>({event:x.match(/event: (.+)/)?.[1],data:JSON.parse(x.match(/data: (.+)/)[1])}));
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const ctx=await browser.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':JSON.parse(fs.readFileSync(path.join(RUN,'window.json'))).nonce}});
 await ctx.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63245','63246'].includes(u.port))?r.abort():r.continue()});
 const page=await ctx.newPage();await page.clock.install({time:new Date('2040-03-02T01:00:00Z')});const errors=[],results=[];page.on('pageerror',e=>errors.push(String(e)));
 async function get(url){const r=await ctx.request.get(BASE+url);assert(r.ok(),url+':'+r.status());return r.json();}
 async function fresh(){await page.goto(BASE+'/chat',{waitUntil:'networkidle'});await page.getByRole('button',{name:'＋',exact:true}).click();}
 async function talk(label,text){const pending=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  await page.locator('#chat-question').fill(text);await page.locator('#chat-question').press('Enter');const r=await pending,raw=await r.text(),f=frames(raw);
  assert(r.ok());assert(!f.some(x=>x.event==='error'),raw);await expect(page.locator('#chat-question')).toBeEnabled();
  save(label+'.json',{input:text,http:r.status(),frames:f,body:await page.locator('.messages').innerText(),url:page.url()});
  await page.screenshot({path:path.join(DIR,label+'.png'),fullPage:true});return f;}
 const pr=f=>f.find(x=>x.event==='practice_request')?.data;
 try{
  const before=await get('/api/plans/today');save('plan-before.json',before);assert.equal(before.total_count||0,0);
  await fresh();await talk('C3-preview','有没有洛必达法则的题目？');
  const messagesUrl=page.url();const f=await talk('C3-reference','把刚才那道题加入今日卷');const req=pr(f);assert(req);
  const preview=req.details.preview_draft.questions[0];assert.equal((await get('/api/plans/today')).total_count||0,0);
  await page.getByTestId('request-send').click();await expect(page.getByText('✓ 已发送给奶蛙',{exact:true})).toBeVisible();
  await page.goto(BASE+'/study',{waitUntil:'networkidle'});await page.getByTestId('study-frog-launcher').click();
  const pending=page.waitForResponse(r=>r.url().endsWith('/plan')&&r.request().method()==='POST');
  await page.locator(`[data-practice-request-id="${req.id}"]`).getByRole('button',{name:'查看安排建议',exact:true}).click();
  const planned=await pending;assert(planned.ok());const task=(await planned.json()).task;save('C3-task.json',task);
  assert.equal(task.draft.questions[0].question_id,preview.question_id);assert.equal(task.draft.questions[0].question_version,preview.question_version);
  const confirm=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');
  await page.locator(`[data-task-id="${task.task_id}"]`).getByTestId('task-confirm').click();const committed=await confirm;assert(committed.ok());const receipt=await committed.json();save('C3-receipt.json',receipt);
  const today=await get('/api/plans/today');save('plan-after-C3.json',today);assert.equal(today.total_count,1);
  const item=receipt.append_result.items[0],actual=today.items.find(i=>i.id===item.item_id);assert.equal(actual.question_version_id,preview.question_version);assert.equal(actual.display_number,item.number);
  await expect(page.locator(`[data-operation-id="${task.task_id}"]`)).toBeVisible();await page.reload({waitUntil:'networkidle'});await page.getByTestId('study-frog-launcher').click();await expect(page.locator(`[data-operation-id="${task.task_id}"]`)).toBeVisible();results.push('C3 exact commit and refresh');
  for(const [label,text] of [['C5','换一道同知识点的'],['D8','取消刚才的题，换一道洛必达的']]){
   await fresh();const a=pr(await talk(label+'-preview','先选一道洛必达让我看看，不要加入。'));
   const b=pr(await talk(label+'-replace',text));assert(a&&b);assert.notEqual(a.details.preview_draft.questions[0].question_id,b.details.preview_draft.questions[0].question_id);
   await expect(page.getByText('已撤回这份练习需求。',{exact:true})).toHaveCount(1);await expect(page.getByTestId('request-send')).toHaveCount(1);
   assert.equal((await get('/api/practice-requests/'+a.id)).status,'declined');await page.reload({waitUntil:'networkidle'});await expect(page.getByTestId('request-send')).toHaveCount(1);results.push(label+' retired old card and refresh');
  }
  await fresh();const d=pr(await talk('D6','讲清楚洛必达法则，如果没有符合资格的洛必达题，就只讲解，不要生成新题。'));assert(d);await expect(page.getByText('系统节点讲解',{exact:false}).first()).toBeVisible();results.push('D6 positive inventory');
  await fresh();const readonly=await talk('F7','我只想看看题库里有哪些洛必达法则的题，不要创建计划。');assert(!pr(readonly));await expect(page.getByTestId('request-send')).toHaveCount(0);assert.equal((await get('/api/plans/today')).total_count,1);results.push('F7 read only');
  await page.reload({waitUntil:'networkidle'});await expect(page.getByTestId('request-send')).toHaveCount(0);save('result.json',{results,errors,modelCalls:0});assert.deepEqual(errors,[]);console.log('V33_VISIBLE_CORE_PASS');
 }catch(e){save('failure.json',{error:String(e),stack:e.stack,results,errors});await page.screenshot({path:path.join(DIR,'failure.png'),fullPage:true});console.error(e);process.exitCode=1;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
