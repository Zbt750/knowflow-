// Explicit offline dependency faults. No fake API responses and no external calls.
const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const epoch=process.env.NAIWA_V32_EPOCH||'6';
const root=path.resolve(__dirname,'../..'),out=path.join(root,'storage/quality-audits/naiwa-v32-20261022'),run=path.join(out,'runtime-'+epoch),dir=path.join(out,'fault-ui-'+epoch);fs.mkdirSync(dir);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),save=(n,v)=>fs.writeFileSync(path.join(dir,n),JSON.stringify(v,null,2),{flag:'wx'}),base='http://127.0.0.1:63246';
const fault=mode=>fs.writeFileSync(path.join(run,'fault.json'),JSON.stringify({mode,simulation:true}));
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':read(path.join(run,'window.json')).nonce}});
 await context.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63245','63246'].includes(u.port))?r.abort():r.continue()});
 const p=await context.newPage();await p.clock.install({time:new Date(`2040-02-${String(2+Number(epoch)).padStart(2,'0')}T01:00:00Z`)});
 const results=[];
 async function get(url){const r=await context.request.get(base+url);assert(r.ok());return r.json()}
 async function send(text,label){
  const wait=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  await p.locator('#chat-question').fill(text);await p.locator('#chat-question').press('Enter');const response=await wait,raw=await response.text();
  fs.writeFileSync(path.join(dir,label+'.sse'),raw,{flag:'wx'});
  const frames=raw.split('\n\n').filter(v=>v.includes('data: ')).map(v=>({event:v.match(/event: (.+)/)?.[1],data:JSON.parse(v.match(/data: (.+)/)[1])}));
  await expect(p.locator('#chat-question')).toBeEnabled();const data={input:text,status:response.status(),frames,body:await p.locator('.messages>article').last().innerText()};
  save(label+'.json',data);await p.screenshot({path:path.join(dir,label+'.png'),fullPage:true});results.push(data);return data;
 }
 try{
  fault('none');await p.goto(base+'/chat',{waitUntil:'networkidle'});await p.getByRole('button',{name:'＋',exact:true}).click();
  for(const [mode,code] of [['egress_closed','provider_egress_closed'],['stream_broken','provider_network']]){
   fault(mode);const data=await send('我最近在复习幂级数，总是把求导和积分弄混，能帮我梳理一下吗？',mode);
   const error=data.frames.find(v=>v.event==='error');assert(error,'missing real SSE error');
   // Keep the exact code evidence; an unrelated/generic classification fails.
   assert.equal(error.data.code,code);
   const messages=await p.locator('.messages').innerText();await p.reload({waitUntil:'networkidle'});
   assert.equal(await p.locator('.messages').innerText(),messages);save(mode+'-refresh.json',{equal:true});
   fault('none');const good=await send('先别加题，只解释洛必达法则。',mode+'-next-success');
   assert(!good.frames.some(v=>v.event==='error'));assert(good.body.includes('去心邻域'));
   await expect(p.getByText('重试这条回复',{exact:true})).toHaveCount(0);
  }
  fault('tool_failure');await p.getByRole('button',{name:'＋',exact:true}).click();
  const partial=await send('讲讲洛必达法则，再从题库挑一道加入今日卷。','tool-failure');
  const draft=partial.frames.find(v=>v.event==='practice_request').data;
  assert.equal(draft.details.preview_status,'failed');assert.equal(draft.details.preview_draft,null);assert(partial.body.includes('去心邻域'));
  assert.equal((await get('/api/plans/today')).status,'setup');
  fault('none');await p.getByRole('button',{name:'＋',exact:true}).click();
  await send('讲讲洛必达法则，再从题库挑一道加入今日卷。','rollback-preview');
  await p.getByTestId('request-send').click();await expect(p.getByText('✓ 已发送给奶蛙',{exact:true})).toBeVisible();
  await p.goto(base+'/study',{waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();
  await p.getByRole('button',{name:'查看安排建议',exact:true}).click();await expect(p.getByTestId('task-confirm')).toBeVisible();
  const before=await get('/api/plans/today');fault('db_rollback');
  const failed=p.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');await p.getByTestId('task-confirm').click();
  const response=await failed;save('rollback-http.json',{status:response.status(),body:await response.text()});assert.equal(response.status(),500);
  fault('none');await expect(p.getByTestId('task-confirm')).toBeEnabled();
  const after=await get('/api/plans/today');assert.deepEqual(after,before);await expect(p.getByTestId('today-append-result')).toHaveCount(0);
  await p.reload({waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();await expect(p.getByTestId('today-append-result')).toHaveCount(0);
  save('rollback-preserved.json',{before,after});await p.screenshot({path:path.join(dir,'rollback-refresh.png'),fullPage:true});
  save('result.json',{status:'PASS',cases:4,realModelRequests:0,externalRequests:0,simulation:true,results});console.log('FAULT_UI_PASS');
 }catch(e){save('failure.json',{error:String(e),stack:e.stack,completed:results.length});await p.screenshot({path:path.join(dir,'failure.png'),fullPage:true});console.error(e);process.exitCode=1;}
 finally{fault('none');console.log('FAULT_MODE_NONE_RESTORED')}
})();
