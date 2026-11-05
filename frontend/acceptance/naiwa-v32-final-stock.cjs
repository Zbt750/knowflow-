const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'storage/quality-audits/naiwa-v32-20261022'),dir=path.join(out,'stock-final10');fs.mkdirSync(dir);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),save=(n,v)=>fs.writeFileSync(path.join(dir,n),JSON.stringify(v,null,2),{flag:'wx'}),base='http://127.0.0.1:63246';
(async()=>{
 const b=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const c=await b.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':read(path.join(out,'runtime-10/window.json')).nonce}});
 await c.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63245','63246'].includes(u.port))?r.abort():r.continue()});
 const p=await c.newPage();await p.clock.install({time:new Date('2040-02-09T01:00:00Z')});
 try{
  const r=await c.request.get(base+'/api/plans/today');assert(r.ok());const before=await r.json();assert.equal(before.total_count,3);
  await p.goto(base+'/study',{waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();
  const pending=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  const input='讲讲洛必达法则，再从题库挑一道加入今日卷。';await p.locator('#frog-message-input').fill(input);await p.locator('#frog-message-input').press('Enter');
  const response=await pending,raw=await response.text();fs.writeFileSync(path.join(dir,'inventory-exhausted.sse'),raw,{flag:'wx'});
  const frames=raw.split('\n\n').filter(v=>v.includes('data: ')).map(v=>({event:v.match(/event: (.+)/)?.[1],data:JSON.parse(v.match(/data: (.+)/)[1])}));
  const task=frames.find(v=>v.event==='planner').data;assert.equal(task.status,'needs_info');assert.equal(task.draft,null);
  assert(task.message.includes('可新增 0 道'));assert(task.message.includes('去心邻域'));
  await expect(p.getByTestId('task-confirm')).toHaveCount(0);await expect(p.getByTestId('today-append-result')).toHaveCount(0);
  const after=await(await c.request.get(base+'/api/plans/today')).json();assert.deepEqual(after,before);
  await p.screenshot({path:path.join(dir,'inventory-exhausted.png'),fullPage:true});
  await p.reload({waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();await expect(p.getByTestId('task-confirm')).toHaveCount(0);
  await expect(p.getByTestId('frog-message-assistant').last()).toContainText('可新增 0 道');
  save('stock.json',{status:'PASS',input,before,after,task,frames,modelRequests:0});
  const receipt=read(path.join(out,'operations-9/lost-response-committed.json'));
  const proposal=read(path.join(out,'operations-9/handoff-'+receipt.task_id+'.json'));
  await p.setViewportSize({width:390,height:844});
  await p.goto(base+'/chat?session_id='+proposal.request.source_conversation_id,{waitUntil:'networkidle'});
  const card=p.locator(`[data-operation-id="${receipt.task_id}"]`);await expect(card).toBeVisible();await expect(card.locator('li')).toHaveCount(4);
  const text=await card.innerText();await p.reload({waitUntil:'networkidle'});assert.equal(await card.innerText(),text);
  const widths=await p.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth}));assert.equal(widths.width,widths.document);
  assert.equal(await p.locator('.katex-error').count(),0);await p.screenshot({path:path.join(dir,'mobile-390-restored.png'),fullPage:true});
  save('mobile.json',{status:'PASS',widths,refreshEqual:true,sessionId:proposal.request.source_conversation_id,browser:b.version(),visible:true});console.log('STOCK_AND_MOBILE_PASS');
 }catch(e){save('failure.json',{error:String(e),stack:e.stack});await p.screenshot({path:path.join(dir,'failure.png'),fullPage:true});console.error(e);process.exitCode=1;}
})();
