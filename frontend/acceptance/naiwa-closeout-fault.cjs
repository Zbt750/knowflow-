const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const DIR=path.resolve(__dirname,'../../storage/quality-audits/naiwa-v33-closeout-20261023/query-fault-ui');fs.mkdirSync(DIR);const BASE='http://127.0.0.1:55222';
const save=(name,value)=>fs.writeFileSync(path.join(DIR,name),JSON.stringify(value,null,2),{flag:'wx'});
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});const ctx=await browser.newContext();const p=await ctx.newPage(),errors=[];p.on('pageerror',e=>errors.push(String(e)));
 await ctx.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['55221','55222'].includes(u.port))?r.abort():r.continue()});
 try{
  await p.clock.install({time:new Date('2040-04-03T01:00:00Z')});const before=await (await ctx.request.get(BASE+'/api/plans/today')).json();
  await p.goto(BASE+'/chat',{waitUntil:'networkidle'});await p.getByRole('button',{name:'＋',exact:true}).click();
  const input='讲清楚洛必达法则，如果没有符合资格的洛必达题，就只讲解，不要生成新题。';
  const pending=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');await p.locator('#chat-question').fill(input);await p.locator('#chat-question').press('Enter');
  const response=await pending,raw=await response.text();fs.writeFileSync(path.join(DIR,'raw.sse'),raw,{flag:'wx'});
  const frames=raw.split('\n\n').filter(f=>f.includes('data: ')).map(f=>({event:f.match(/event: (.+)/)?.[1],data:JSON.parse(f.match(/data: (.+)/)[1])}));
  const answer=frames.find(f=>f.event==='done').data.answer;
  assert(answer.includes('系统节点讲解'));assert(answer.includes('查询或方案校验未完成'));assert(!answer.includes('可新增 0 道'));assert(!frames.some(f=>['practice_request','personal_generation','planner'].includes(f.event)));
  await expect(p.locator('#chat-question')).toBeEnabled();const body=await p.locator('.messages').innerText();await p.reload({waitUntil:'networkidle'});assert.equal(await p.locator('.messages').innerText(),body);
  const after=await (await ctx.request.get(BASE+'/api/plans/today')).json();assert.deepEqual(after,before);
  assert.equal(await p.locator('.katex-error').count(),0);await p.setViewportSize({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.screenshot({path:path.join(DIR,'query-failure-refresh-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);
  save('result.json',{status:'PASS',input,answer,frames,before,after,refreshEqual:true,errors,realModelRequests:0,fault:'local test dependency exception, not real network evidence'});console.log('QUERY_FAULT_UI_PASS');
 }catch(e){save('failure.json',{error:String(e),stack:e.stack,errors});console.error(e);process.exitCode=1}finally{await browser.close()}
})();
