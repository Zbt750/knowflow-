const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../..'),OUT=path.join(ROOT,'storage/quality-audits/naiwa-v33-closeout-20261023'),DIR=path.join(OUT,'race-ui-2');fs.mkdirSync(DIR);
const BASE='http://127.0.0.1:55222';const save=(n,v)=>fs.writeFileSync(path.join(DIR,n),JSON.stringify(v,null,2),{flag:'wx'});
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});const ctx=await browser.newContext({viewport:{width:1366,height:900}});
 await ctx.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['55221','55222'].includes(u.port))?r.abort():r.continue()});
 const pages=await Promise.all([ctx.newPage(),ctx.newPage()]),errors=[];
 try{
  for(const p of pages){p.on('pageerror',e=>errors.push(String(e)));await p.clock.install({time:new Date('2040-04-03T01:00:00Z')});}
  const p=pages[0];await p.goto(BASE+'/chat',{waitUntil:'networkidle'});await p.getByRole('button',{name:'＋',exact:true}).click();
  const pending=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  await p.locator('#chat-question').fill('讲讲洛必达法则，再从题库挑一道加入今日卷。');await p.locator('#chat-question').press('Enter');const stream=await pending;fs.writeFileSync(path.join(DIR,'proposal.sse'),await stream.text(),{flag:'wx'});
  await p.getByTestId('request-send').click();await expect(p.getByText('✓ 已发送给奶蛙',{exact:true})).toBeVisible();
  await p.goto(BASE+'/study',{waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();
  const plan=p.waitForResponse(r=>r.url().endsWith('/plan')&&r.request().method()==='POST');await p.getByRole('button',{name:'查看安排建议',exact:true}).click();assert((await plan).ok());
  await pages[1].goto(BASE+'/study',{waitUntil:'networkidle'});await pages[1].getByTestId('study-frog-launcher').click();
  if(!await pages[1].getByTestId('task-confirm').count())await pages[1].getByRole('button',{name:'查看已有方案',exact:true}).last().click();
  const [a,b]=pages;await expect(a.getByTestId('task-confirm')).toHaveCount(1);await expect(b.getByTestId('task-confirm')).toHaveCount(1);
  const taskId=await a.getByTestId('task-confirm').locator('xpath=ancestor::section[@data-task-id]').getAttribute('data-task-id');
  assert.equal(await b.getByTestId('task-confirm').locator('xpath=ancestor::section[@data-task-id]').getAttribute('data-task-id'),taskId);
  const original=await (await ctx.request.get(BASE+'/api/plans/today')).json();
  const cancel=b.getByTestId('task-cancel');if(!await cancel.isVisible())await b.locator('details').filter({has:cancel}).locator('summary').click();
  const waits=[a.waitForResponse(r=>r.url().endsWith('/'+taskId+'/confirm')&&r.request().method()==='POST'),b.waitForResponse(r=>r.url().endsWith('/'+taskId+'/cancel')&&r.request().method()==='POST')];
  await Promise.all([a.getByTestId('task-confirm').click(),cancel.click()]);const replies=await Promise.all(waits);
  const results=await Promise.all(replies.map(async r=>({status:r.status(),body:await r.json()})));save('responses.json',{taskId,results});
  assert.deepEqual(results.map(r=>r.status).sort(),[200,409]);
  const task=await (await ctx.request.get(BASE+'/api/learning-tasks/'+taskId)).json(),today=await (await ctx.request.get(BASE+'/api/plans/today')).json();
  const committed=Boolean(task.metrics.commit);assert.equal(today.total_count,original.total_count+(committed?1:0));assert.equal(task.status,committed?'ready':'cancelled');
  for(const item of original.items)assert.deepEqual(today.items.find(r=>r.id===item.id),item);
  for(let i=0;i<pages.length;i++){await pages[i].reload({waitUntil:'networkidle'});await pages[i].getByTestId('study-frog-launcher').click();await expect(pages[i].getByTestId('task-confirm')).toHaveCount(0);await pages[i].screenshot({path:path.join(DIR,'refresh-'+i+'.png'),fullPage:true});}
  assert.deepEqual(errors,[]);save('result.json',{status:'PASS',original,today,task,committed,errors,realModelRequests:0});console.log('RACE_UI_PASS',committed?'confirmation_won':'cancellation_won');
 }catch(e){save('failure.json',{error:String(e),stack:e.stack,errors});await pages[0].screenshot({path:path.join(DIR,'failure.png'),fullPage:true});console.error(e);process.exitCode=1}finally{await browser.close()}
})();
