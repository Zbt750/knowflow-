// Read-only real Vue review of the preserved failure; no messages can be sent.
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');
const {chromium}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-final-real-retest-20261021');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false});
 const context=await browser.newContext({viewport:{width:1366,height:900},storageState:path.join(out,'AGENT-browser-state.json')});
 await context.route('**/*',route=>{
  const req=route.request(),u=new URL(req.url());
  if(u.protocol.startsWith('http')&&(u.hostname!=='127.0.0.1'||u.port!=='63046'||!['GET','HEAD'].includes(req.method())))return route.abort();
  return route.continue();
 });
 const page=await context.newPage();await page.goto('http://127.0.0.1:63046/study',{waitUntil:'networkidle'});
 await page.getByTestId('study-frog-launcher').click();await page.getByTestId('task-goal').waitFor();
 await page.screenshot({path:path.join(out,'fixed-provider-readonly-review.png'),fullPage:true});
 fs.writeFileSync(path.join(out,'review-window.json'),JSON.stringify({status:'OPEN',node_pid:process.pid,read_only:true,
  real_vue:true,url:page.url(),history_session:'b1fe2665-e248-4918-95d0-25c39d1266df',model_requests:0},null,2));
 await new Promise(resolve=>browser.on('disconnected',resolve));
})().catch(error=>{console.error(String(error));process.exitCode=1;});
