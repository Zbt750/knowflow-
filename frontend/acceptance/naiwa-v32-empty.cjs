const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'storage/quality-audits/naiwa-v32-20261022');
const epoch=process.env.NAIWA_V32_EPOCH||'1',dir=path.join(out,'empty-'+epoch);fs.mkdirSync(dir);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),save=(n,v)=>fs.writeFileSync(path.join(dir,n),JSON.stringify(v,null,2),{flag:'wx'});
(async()=>{
 const b=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const c=await b.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':read(path.join(out,'runtime-'+epoch,'window.json')).nonce}});
 await c.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63245','63246'].includes(u.port))?r.abort():r.continue()});
 const p=await c.newPage(),base='http://127.0.0.1:63246';
 // Match the server's explicit isolated test clock, not the host system clock.
 await p.clock.install({time:new Date(`2040-02-${String(2+Number(epoch)).padStart(2,'0')}T01:00:00Z`)});
 async function get(url){const r=await c.request.get(base+url);assert(r.ok());return r.json()}
 try{
  const before=await get('/api/plans/today');save('before.json',before);assert.equal(before.status,'setup');
  await p.goto(base+'/chat',{waitUntil:'networkidle'});await p.getByRole('button',{name:'＋',exact:true}).click();
  const pending=p.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
  await p.locator('#chat-question').fill('讲讲洛必达法则，再从题库挑一道加入今日卷。');await p.locator('#chat-question').press('Enter');
  const stream=await pending;fs.writeFileSync(path.join(dir,'preview.sse'),await stream.text(),{flag:'wx'});
  await p.getByTestId('request-send').click();await expect(p.getByText('✓ 已发送给奶蛙',{exact:true})).toBeVisible();
  await p.goto(base+'/study',{waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();
  await p.getByRole('button',{name:'查看安排建议',exact:true}).click();await expect(p.getByTestId('task-confirm')).toBeVisible();
  await p.screenshot({path:path.join(dir,'before-confirm.png'),fullPage:true});
  await p.getByTestId('task-confirm').click();await p.waitForTimeout(1200);
  const after=await get('/api/plans/today');save('after.json',after);assert.equal(after.total_count,1);
  await p.screenshot({path:path.join(dir,'after-confirm.png'),fullPage:true});
  const opened=await p.getByTestId('learning-task-panel').evaluate(e=>e.open);
  save('state.json',{opened,cards:await p.getByTestId('today-append-result').count(),text:await p.locator('body').innerText(),modelRequests:0});
  assert(opened,'first creation must preserve open assistant');
  await expect(p.getByTestId('today-append-result')).toBeVisible();
  await p.reload({waitUntil:'networkidle'});await p.getByTestId('study-frog-launcher').click();await expect(p.getByTestId('today-append-result')).toBeVisible();
  save('result.json',{status:'PASS',firstCreationImmediate:true,refreshRestored:true});
 }catch(e){save('failure.json',{error:String(e),stack:e.stack});console.error(e);process.exitCode=1;}
 finally{console.log('EMPTY_EVIDENCE',dir)}
})();
