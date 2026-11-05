const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const DIR=path.resolve(__dirname,'../../storage/quality-audits/naiwa-v33-closeout-20261023/context-ui-retest3');fs.mkdirSync(DIR);const BASE='http://127.0.0.1:55222';
const inputs=['洛必达有多少道可练题？','这些题我做过几道？','那里面哪些做错了？','给我安排一道。','这次只想看题库，不要创建计划。'];
const save=(n,v)=>fs.writeFileSync(path.join(DIR,n),JSON.stringify(v,null,2),{flag:'wx'});
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});const ctx=await browser.newContext({viewport:{width:1366,height:900}});const p=await ctx.newPage(),errors=[],results=[];let createdSessionId=null;
 p.on('response',async r=>{if(r.url().endsWith('/api/chat/sessions')&&r.request().method()==='POST'&&r.ok()){try{createdSessionId=(await r.json()).session_id}catch{}}});
 await ctx.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['55221','55222'].includes(u.port))?r.abort():r.continue()});p.on('pageerror',e=>errors.push(String(e)));
 try{await p.clock.install({time:new Date('2040-04-03T01:00:00Z')});await p.goto(BASE+'/chat',{waitUntil:'networkidle'});await p.getByRole('button',{name:'＋',exact:true}).click();let sid=null,planBefore,prBefore;
  planBefore=await (await ctx.request.get(BASE+'/api/plans/today')).json();prBefore=(await ctx.request.get(BASE+'/api/practice-requests')).status();
  for(let i=0;i<inputs.length;i++){const responsePromise=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST',{timeout:60000});await p.locator('#chat-question').fill(inputs[i]);await p.locator('#chat-question').press('Enter');const response=await responsePromise,raw=await response.text();if(i===0)sid=createdSessionId;
   const frames=raw.split('\n\n').filter(f=>f.includes('data: ')).map(f=>({event:f.match(/event: (.+)/)?.[1],data:JSON.parse(f.match(/data: (.+)/)[1])}));
   await expect(p.locator('#chat-question')).toBeEnabled();
   const entry={input:inputs[i],http:response.status(),frames,body:await p.locator('.messages>article').last().innerText()};results.push(entry);fs.writeFileSync(path.join(DIR,`turn-${i+1}.sse`),raw,{flag:'wx'});
   if(i===0)assert(entry.body.includes('洛必达法则范围'));
   if(i===1||i===2)assert(entry.body.includes('洛必达法则'));
   if(i===3)assert(frames.some(f=>f.event==='practice_request'));
   if(i===4){assert(!frames.some(f=>['practice_request','planner','personal_generation'].includes(f.event)));assert(entry.body.includes('真实题库当前符合查询条件 3 道'));assert(entry.body.includes('洛必达原创丙'));
    const afterPr=(await ctx.request.get(BASE+`/api/practice-requests?source_conversation_id=${sid}`)).json();const pRows=await afterPr;assert.equal(pRows.length,1,'read-only query must not add another practice request');}
  }
  const hist=await (await ctx.request.get(BASE+`/api/chat/sessions/${sid}/messages`)).json();save('history.json',hist);
  const planAfter=await (await ctx.request.get(BASE+'/api/plans/today')).json();assert.deepEqual(planAfter,planBefore);
  await p.reload({waitUntil:'networkidle'});assert.deepEqual(errors,[]);await p.screenshot({path:path.join(DIR,'final.png'),fullPage:true});
  save('result.json',{status:'PASS',sessionId:sid,results,planBefore,planAfter,historyCount:hist.length,errors,realModelRequests:0,assertions:{f7StayedOnLhopital:true,readonlyNoNewPracticeRequest:true,planUnchanged:true}});console.log('CONTEXT_UI_PASS');
 }catch(e){save('failure.json',{error:String(e),stack:e.stack,results,errors});console.error(e);process.exitCode=1}finally{await browser.close()}
})();
