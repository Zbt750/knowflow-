// Visible UI replay of the unchanged V3.2 utterance matrix on a NEW clean DB.
const {chromium,expect}=require('@playwright/test'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../..'),OUT=path.join(ROOT,'storage/quality-audits/naiwa-v33-continue-20261023');
const identity=JSON.parse(fs.readFileSync(path.join(ROOT,'storage/manual-experience/naiwa-clean-20261023/identity.json')));
const BASE=`http://127.0.0.1:${identity.web_port}`,DIR=path.join(OUT,'visible-matrix');fs.mkdirSync(DIR);
const old=fs.readFileSync(path.join(__dirname,'naiwa-v32-matrix.cjs'),'utf8');
const groups=vm.runInNewContext('('+old.match(/const groups=([\s\S]*?);\r?\n\(async/)[1]+')');
const save=(name,value)=>fs.writeFileSync(path.join(DIR,name),JSON.stringify(value,null,2),{flag:'wx'});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const ctx=await browser.newContext({viewport:{width:1366,height:900}});
 await ctx.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&[String(identity.api_port),String(identity.web_port)].includes(u.port))?r.abort():r.continue()});
 const page=await ctx.newPage(),results=[],errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.clock.install({time:new Date('2040-04-02T01:00:00Z')});
 try{
  await page.goto(BASE+'/chat',{waitUntil:'networkidle'});
  for(const [group,texts] of Object.entries(groups)){
   await page.getByRole('button',{name:'＋',exact:true}).click();
   for(let i=0;i<texts.length;i++){
    const label=group+(i+1),input=texts[i];
    const pending=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
    await page.locator('#chat-question').fill(input);await page.locator('#chat-question').press('Enter');const response=await pending,raw=await response.text();
    const frames=raw.split('\n\n').filter(f=>f.includes('data: ')).map(f=>({event:f.match(/event: (.+)/)?.[1],data:JSON.parse(f.match(/data: (.+)/)[1])}));
    await expect(page.locator('#chat-question')).toBeEnabled();
    const result={label,input,http:response.status(),frames,body:await page.locator('.messages>article').last().innerText(),url:page.url(),
     model:'FIXED-OFFLINE',realModelRequests:0,semanticStatus:'REQUIRES_REVIEW_NOT_AUTOMATIC_PASS',katexErrors:await page.locator('.katex-error').count()};
    save(label+'.json',result);await page.screenshot({path:path.join(DIR,label+'.png'),fullPage:true});results.push(result);console.log(label,response.status());
   }
   await page.reload({waitUntil:'networkidle'});
  }
  save('result.json',{inputs:results.length,results,errors,realModelRequests:0});assert.equal(results.length,48);assert.deepEqual(errors,[]);
 }catch(e){save('failure.json',{error:String(e),stack:e.stack,completed:results.map(r=>r.label),errors});console.error(e);process.exitCode=1;}
 finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
