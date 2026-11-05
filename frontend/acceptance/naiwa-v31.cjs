const {chromium}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const ROOT=path.resolve(__dirname,'../..'),OUT=path.join(ROOT,'storage/quality-audits/naiwa-v31-20261022');
const epoch=process.env.NAIWA_V31_EPOCH||'1',RUN=path.join(OUT,'runtime-'+epoch);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const emit=v=>process.stdout.write(JSON.stringify(v)+'\n');
const save=(name,v)=>fs.writeFileSync(path.join(OUT,name),JSON.stringify(v,null,2),{encoding:'utf8',flag:'wx'});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':read(path.join(RUN,'window.json')).nonce}});
 await context.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63145','63146'].includes(u.port))?r.abort():r.continue()});
 const page=await context.newPage();
 page.on('response',async r=>{if(r.url().includes('/api/'))fs.appendFileSync(path.join(OUT,'ui-network-'+epoch+'.jsonl'),JSON.stringify({time:Date.now(),method:r.request().method(),url:r.url(),status:r.status()})+'\n')});
 page.on('pageerror',e=>fs.appendFileSync(path.join(OUT,'ui-errors-'+epoch+'.jsonl'),JSON.stringify({time:Date.now(),message:e.message})+'\n'));
 async function snapshot(label){
  const text=await page.locator('body').innerText();
  await page.screenshot({path:path.join(OUT,label+'.png'),fullPage:true});
  const controls=await page.locator('button,textarea,input,a').evaluateAll(ns=>ns.filter(e=>e.getBoundingClientRect().width>0).map(e=>({tag:e.tagName,text:e.innerText?.slice(0,85),testid:e.getAttribute('data-testid'),id:e.id,aria:e.getAttribute('aria-label'),placeholder:e.getAttribute('placeholder')})).slice(-85));
  const data={url:page.url(),text,controls,katex:await page.locator('.katex').count(),katexErrors:await page.locator('.katex-error').count(),overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),
   appendCards:await page.getByTestId('today-append-result').count(),previewCards:await page.getByTestId('request-question-preview').count(),
   lastMessage:await page.locator('.messages>article').last().innerText().catch(()=>''),
   mathMarkup:await page.locator('math').evaluateAll(ns=>ns.map(n=>n.outerHTML))};
  save(label+'.json',data);return data;
 }
 emit({ready:true,visible:true,chrome:browser.version(),epoch});
 for await(const line of readline.createInterface({input:process.stdin,crlfDelay:Infinity})){
  if(!line.trim())continue;
  try{const a=JSON.parse(line);
   if(a.op==='goto')await page.goto('http://127.0.0.1:63146'+a.path,{waitUntil:'networkidle'});
   if(a.op==='click')await page.getByRole(a.role||'button',{name:a.name,exact:a.exact!==false}).click();
   if(a.op==='testid')await page.getByTestId(a.id).click();
   if(a.op==='confirmLost'){
    await page.route('**/api/learning-tasks/*/confirm',async route=>{
     const response=await route.fetch();save(a.label+'-committed-response.json',{status:response.status(),body:await response.json()});
     await route.abort('failed');
    },{times:1});
    await page.getByTestId('task-confirm').click();await page.waitForTimeout(1400);
   }
   if(a.op==='refresh')await page.reload({waitUntil:'networkidle'});
   if(a.op==='send'){
    const input=page.locator(a.selector||'#chat-question');await input.fill(a.text);
    const pending=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
    await input.press('Enter');const r=await pending;const raw=await r.text();
    fs.writeFileSync(path.join(OUT,a.label+'.sse'),raw,{encoding:'utf8',flag:'wx'});
    save(a.label+'-request.json',{text:a.text,status:r.status(),url:r.url(),rawModelRequests:0,mode:'FIXED_PROVIDER_OR_DETERMINISTIC_BUSINESS'});
   }
   await page.waitForTimeout(700);const s=await snapshot(a.label);emit({ok:true,label:a.label,...s,text:s.text.slice(-6000),controls:s.controls.slice(-18),mathMarkup:undefined});
  }catch(e){emit({ok:false,error:String(e)});}
 }
})();
