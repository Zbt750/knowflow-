const {chromium,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const ROOT=path.resolve(__dirname,'../..'),AUDIT=path.join(ROOT,'storage/quality-audits/naiwa-v33-20261022');
const OUT=path.join(AUDIT,process.env.V33_TAG||'before-ui');fs.mkdirSync(OUT);
const RUN=path.join(AUDIT,process.env.NAIWA_V33_RECOVERY||'recovery-1'),BASE='http://127.0.0.1:63246';
const cases={C3:['有没有洛必达法则的题目？','把刚才那道题加入今日卷。'],C5:['先选一道洛必达让我看看，不要加入。','换一道同知识点的。'],D6:['讲清楚洛必达法则，如果没有符合资格的洛必达题，就只讲解，不要生成新题。'],D8:['先选一道洛必达让我看看，不要加入。','取消刚才的题，换一道洛必达的。'],F7:['我只想看看题库里有哪些洛必达法则的题，不要创建计划。']};
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const ctx=await browser.newContext({extraHTTPHeaders:{'x-naiwa-v31':JSON.parse(fs.readFileSync(path.join(RUN,'window.json'))).nonce}});
 await ctx.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63245','63246'].includes(u.port))?r.abort():r.continue()});
 const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 try{await page.goto(BASE+'/chat',{waitUntil:'networkidle'});
 for(const [label,inputs] of Object.entries(cases)){
  await page.getByRole('button',{name:'＋',exact:true}).click();
  for(let i=0;i<inputs.length;i++){
   const pending=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
   await page.locator('#chat-question').fill(inputs[i]);await page.locator('#chat-question').press('Enter');
   const response=await pending,raw=await response.text();await expect(page.locator('#chat-question')).toBeEnabled();
   const result={input:inputs[i],http:response.status(),sse:raw,body:await page.locator('.messages').innerText(),url:page.url(),errors:[...errors]};
   fs.writeFileSync(path.join(OUT,label+'-'+i+'.json'),JSON.stringify(result,null,2),{flag:'wx'});
   await page.screenshot({path:path.join(OUT,label+'-'+i+'.png'),fullPage:true});console.log(label,i,response.status());
  }
 }
 }finally{await browser.close();}
})().catch(e=>{fs.writeFileSync(path.join(OUT,'failure.txt'),String(e));console.error(e);process.exitCode=1});
