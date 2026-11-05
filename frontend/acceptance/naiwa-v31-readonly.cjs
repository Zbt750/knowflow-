// Read-only visible Chrome inspection of persisted V31 QA on a phone viewport.
const {chromium,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const out=path.resolve(__dirname,'../../storage/quality-audits/naiwa-v31-20261022');
const evidence=JSON.parse(fs.readFileSync(path.join(out,'browser-final-9/case-1.json'),'utf8'));
const request=evidence.frames.find(f=>f.event==='practice_request').data;
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:390,height:844}});
 await context.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63145','63146'].includes(u.port))?r.abort():r.continue()});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:63146/chat?session_id='+request.source_conversation_id,{waitUntil:'networkidle'});
 await expect(page.getByTestId('request-question-preview').first()).toBeVisible();
 const before=await page.locator('.messages').innerText();
 await page.reload({waitUntil:'networkidle'});
 await expect(page.getByTestId('request-question-preview').first()).toBeVisible();
 assert.equal(await page.locator('.messages').innerText(),before);
 const width=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
 assert(width.document<=width.viewport);assert.deepEqual(errors,[]);
 await page.screenshot({path:path.join(out,'mobile-restored-390.png'),fullPage:true});
 fs.writeFileSync(path.join(out,'mobile-readonly.json'),JSON.stringify({status:'PASS',width,errors,refreshEqual:true,sessionId:request.source_conversation_id,requestsSent:0,browser:browser.version()},null,2),{flag:'wx'});
 console.log('READONLY_MOBILE_PASS');await browser.close();
})();
