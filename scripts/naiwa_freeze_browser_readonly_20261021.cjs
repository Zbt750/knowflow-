// Stage1: real visible system Chrome, GET only, no chat/model actions.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const {chromium}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-freeze-preflight-20261021');
const baseline=JSON.parse(fs.readFileSync(path.join(out,'database-before.json'),'utf8'));
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false});
 const context=await browser.newContext({viewport:{width:1366,height:900}});
 const page=await context.newPage(),errors=[],blocked=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',async r=>{
  const req=r.request(),u=new URL(req.url());
  if(u.protocol.startsWith('http')&&(u.hostname!=='127.0.0.1'||u.port!=='63046'||!['GET','HEAD'].includes(req.method()))){blocked.push({method:req.method(),url:req.url()});return r.abort();}
  if(u.pathname.startsWith('/api/'))requests.push({method:req.method(),path:u.pathname});
  return r.continue();
 });
 const base='http://127.0.0.1:63046';
 try{
  const health=await context.request.get(base+'/api/health');assert.equal(health.status(),200);
  assert.equal(health.headers()['x-naiwa-experience'],'restored-archive-fixed-provider-egress-sealed');
  const h=await health.json();assert.equal(h.llm_model,'FIXED-OFFLINE-NO-PAID-MODEL');
  const sessions=[];
  for(const s of baseline.chat_sessions){
   const res=await context.request.get(base+`/api/chat/sessions/${s.id}/messages`);
   if(res.status()===409&&s.purpose==='material_search'){
    const error=await res.json();assert.equal(error.error.code,'material_search_expired');
    sessions.push({id:s.id,title:s.title,purpose:s.purpose,messages:baseline.chat_messages.filter(m=>m.session_id===s.id).length,
     api_status:'BLOCKED_EXPIRED',error,preserved_in_database:true});continue;
   }
   assert.equal(res.status(),200);
   const messages=await res.json(),expected=baseline.chat_messages.filter(m=>m.session_id===s.id).sort((a,b)=>a.seq-b.seq);
   assert.deepEqual(messages.map(m=>[m.message_id,m.role,m.content,m.status]),expected.map(m=>[m.id,m.role,m.content,m.status]));
   sessions.push({id:s.id,title:s.title,purpose:s.purpose,messages:messages.length,identical:true});
  }
  const sid='9e39b237-d512-4ff0-9126-cab30b5471b4';
  const count=baseline.chat_messages.filter(m=>m.session_id===sid).length;
  await page.goto(base+'/chat?session_id='+sid,{waitUntil:'networkidle'});
  await page.locator('.message-row').last().waitFor();assert.equal(await page.locator('.message-row').count(),count);
  const before=await page.locator('.message-row').allTextContents();
  await page.screenshot({path:path.join(out,'qa-history-before-refresh.png'),fullPage:true});
  await page.reload({waitUntil:'networkidle'});await page.locator('.message-row').last().waitFor();
  assert.deepEqual(await page.locator('.message-row').allTextContents(),before);
  await page.screenshot({path:path.join(out,'qa-history-after-refresh.png'),fullPage:true});
  const today=await context.request.get(base+'/api/plans/today');
  const todayBody=await today.json();
  await page.goto(base+'/study',{waitUntil:'networkidle'});
  await page.screenshot({path:path.join(out,'study-current-day-readonly.png'),fullPage:true});
  assert.equal(errors.length,0,JSON.stringify(errors));assert.equal(blocked.length,0,JSON.stringify(blocked));
  fs.writeFileSync(path.join(out,'browser-readonly.json'),JSON.stringify({status:'PARTIAL',browser:'visible system Chrome, automated, GET only',health:h,sessions,
   qa_refresh_identical:true,qa_message_count:count,today_status:today.status(),today:todayBody,requests,errors,blocked,real_model_requests:0,
   material_ui:'NOT_RUN: opening current daily material-search would POST and may create a new session; retained material history checked byte-for-byte via actual API instead'},null,2));
  console.log(JSON.stringify({status:'PARTIAL',sessions:sessions.length,messages:sessions.reduce((n,s)=>n+s.messages,0),qa_refresh:true,material_history:'API expired; DB retained',today_status:today.status(),real_calls:0}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
