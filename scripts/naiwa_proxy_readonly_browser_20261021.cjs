// Real Vue rendering of persisted engineering fixtures; GET only, not a model test.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{createRequire}=require('node:module');
const {chromium}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-proxy-attribution-zero-20261021');
const cases=JSON.parse(fs.readFileSync(path.join(out,'asgi-regression.json'),'utf8')).cases;
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false}),results=[];
 try{
  for(const row of cases){
   const context=await browser.newContext({viewport:{width:1366,height:900}}),errors=[],blocked=[];
   await context.addInitScript(({sid,tid})=>{
    const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    localStorage.setItem('learning-assistant:study:'+day,sid);localStorage.setItem('learning-task:study:'+day,tid);
   },{sid:row.session_id,tid:row.task_id});
   await context.route('**/*',route=>{
    const req=route.request(),u=new URL(req.url());
    if(u.protocol.startsWith('http')&&(u.hostname!=='127.0.0.1'||u.port!=='63046'||!['GET','HEAD'].includes(req.method()))){blocked.push({method:req.method(),path:u.pathname});return route.abort();}
    return route.continue();
   });
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto('http://127.0.0.1:63046/study',{waitUntil:'networkidle'});
   await page.getByTestId('study-frog-launcher').click();
   await page.getByTestId('frog-message-assistant').first().waitFor();
   const before=await page.getByTestId('frog-message-assistant').allTextContents();
   fs.writeFileSync(path.join(out,'browser-last-observation.json'),JSON.stringify({case:row.case,actual:before,expected:row.task.message},null,2));
   // Markdown paragraph wrappers add a terminal newline; compare the entire
   // visible message modulo that renderer whitespace, not a partial phrase.
   assert(before.some(text=>text.trim()===row.task.message.trim()));
   if(row.case==='proxy')assert(!before.join('').includes('预算上限')&&before.join('').includes('尚未发送'));
   if(['proxy','budget','scene','closed','unknown','auth','retry'].includes(row.case)){
    assert.equal(await page.getByRole('button',{name:'重试这条回复',exact:true}).count(),0);
   }
   await page.screenshot({path:path.join(out,row.case+'-visible.png'),fullPage:true});
   await page.reload({waitUntil:'networkidle'});await page.getByTestId('study-frog-launcher').click();
   await page.getByTestId('frog-message-assistant').first().waitFor();
   assert.deepEqual(await page.getByTestId('frog-message-assistant').allTextContents(),before);
   if(row.case==='proxy')await page.screenshot({path:path.join(out,'proxy-after-refresh.png'),fullPage:true});
   assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
   results.push({case:row.case,status:'PASS',persisted_text:before,refresh_identical:true,errors,blocked});
   fs.writeFileSync(path.join(out,'browser-readonly.json'),JSON.stringify({status:'PASS',results,
    note:'Visible system Chrome automation; sessions were created via ASGI fixed-error integration, browser only rendered/read/refreshed actual Vue',real_model_requests:0},null,2));
   await context.close();
  }
  console.log(JSON.stringify({visible_chrome_readonly_cases:results.length,status:'PASS',real_calls:0}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
