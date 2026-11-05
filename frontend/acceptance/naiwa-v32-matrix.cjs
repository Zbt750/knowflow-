// New visible-browser evidence, 48 natural utterances. Fixed Provider is NOT an accuracy oracle.
const {chromium,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const ROOT=path.resolve(__dirname,'../..'),AUDIT=path.join(ROOT,'storage/quality-audits/naiwa-v32-20261022');
const OUT=process.env.NAIWA_V32_RUN_TAG?path.join(AUDIT,process.env.NAIWA_V32_RUN_TAG):AUDIT;
if(OUT!==AUDIT)fs.mkdirSync(OUT);
const RUN=path.join(AUDIT,'runtime-'+(process.env.NAIWA_V32_EPOCH||'1')),BASE='http://127.0.0.1:63246';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const save=(n,v)=>fs.writeFileSync(path.join(OUT,n),JSON.stringify(v,null,2),{flag:'wx'});
const groups={
 A:['洛必达法则是什么？','什么时候不能用洛必达？','给我讲一个最简单的例子。','这和等价无穷小有什么区别？','我还是没听懂，再讲简单一点。','先别加题，只解释洛必达法则。','无穷比无穷也能用这个法则吗？','给我讲讲导数计算，不要安排题目。'],
 B:['我题库里有多少道数学二的可练题？','那其中洛必达法则的题有多少道？','其中选择题有多少道？','这些题我做过几道？','那里面哪些做错了？','只看我做错过的真题。','不要个人 AI 生成题，只要已有公共题库题。','有没有历年真题？'],
 C:['给我安排一道洛必达题。','先选一道洛必达让我看看，不要加入。','把刚才那道题加入今日卷。','不要加入，先给我解释洛必达。','换一道同知识点的。','只加入一道洛必达题，不要多加。','我改变主意了，取消刚才的安排。','刚才已经加过了，再点一次会怎样？'],
 D:['讲清楚洛必达法则，再从题库挑一道放进今日卷。','先讲解洛必达，再给我一个可以确认的选题方案。','找一道洛必达题，但不要现在加入。','先解释洛必达法则，等我确认后再安排。','从已有题库拿一道洛必达题，不要生成新题。','如果没有符合资格的洛必达题，就只讲解。','我问的是导数计算，不是当前这道等比级数。','刚才的题取消，换一道洛必达的。'],
 E:['有没有洛必达的题？','其中选择题有多少道？','我做过几道？','那里面哪些做错了？','给我安排一道。','换个知识点。','先不管刚才的，帮我看看导数应用。','回到上一轮的题目。'],
 F:['先别安排题目，讲讲洛必达法则。','刚才没看懂，请继续解释洛必达的适用条件。','我重新打开页面了，先只解释导数计算。','先不管之前的安排，讲讲幂级数。','不要生成，帮我查查洛必达可练题数量。','这些题我做过几道？','这次只想看题库，不要创建计划。','我换个问题：导数计算有多少道题？']};
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:false,args:['--disable-background-networking']});
 const context=await browser.newContext({viewport:{width:1366,height:900},extraHTTPHeaders:{'x-naiwa-v31':read(path.join(RUN,'window.json')).nonce}});
 await context.route('**/*',r=>{const u=new URL(r.request().url());return ['http:','https:'].includes(u.protocol)&&!(u.hostname==='127.0.0.1'&&['63245','63246'].includes(u.port))?r.abort():r.continue()});
 const page=await context.newPage(),results=[],errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 const originalCount=(await (await context.request.get(BASE+'/api/plans/today')).json()).total_count||0;
 fs.mkdirSync(path.join(OUT,'matrix'));
 try{
  await page.goto(BASE+'/chat',{waitUntil:'networkidle'});
  for(const [group,inputs] of Object.entries(groups)){
   await page.getByRole('button',{name:'＋',exact:true}).click();
   for(let i=0;i<inputs.length;i++){
    const label=group+(i+1),text=inputs[i],field=page.locator('#chat-question');
    const pending=page.waitForResponse(r=>r.url().endsWith('/assistant:stream')&&r.request().method()==='POST');
    await field.fill(text);await field.press('Enter');const response=await pending,raw=await response.text();
    fs.writeFileSync(path.join(OUT,'matrix',label+'.sse'),raw,{flag:'wx'});
    const frames=raw.split('\n\n').filter(s=>s.includes('data: ')).map(s=>({event:s.match(/event: (.+)/)?.[1],data:JSON.parse(s.match(/data: (.+)/)[1])}));
    await expect(field).toBeEnabled({timeout:15000});
    const last=page.locator('.messages>article').last(),body=await last.innerText();
    const today=await(await context.request.get(BASE+'/api/plans/today')).json();
    assert.equal(today.total_count||0,originalCount,'unexpected unconfirmed write: '+label);
    const row={label,input:text,http:response.status(),url:page.url(),frames,body,
     previewCards:await last.getByTestId('request-question-preview').count(),successCards:await last.getByTestId('today-append-result').count(),
     katexErrors:await last.locator('.katex-error').count(),todayCount:today.total_count||0,
     engineeringTerminal:frames.some(f=>f.event==='error')?'FAIL':'COMPLETED_REQUIRES_SEMANTIC_REVIEW',
     answerQuality:body.includes('固定 Provider')?'BLOCKED_FIXED_PROVIDER_NOT_REAL_UNDERSTANDING':'REVIEW_SYSTEM_DATA_OR_LESSON',realModelRequests:0};
    assert.equal(row.successCards,0,'unconfirmed success card '+label);
    save('matrix/'+label+'.json',row);results.push(row);
    await page.screenshot({path:path.join(OUT,'matrix',label+'.png'),fullPage:true});
    if(group==='F'&&[0,2,4,7].includes(i)){
      const before=await page.locator('.messages').innerText();await page.reload({waitUntil:'networkidle'});
      assert.equal(await page.locator('.messages').innerText(),before,'refresh changed history '+label);
      save('matrix/'+label+'-refresh.json',{equal:true,url:page.url()});
    }
    console.log(label,frames.find(f=>f.event==='route')?.data?.intent,row.engineeringTerminal);
   }
   await page.reload({waitUntil:'networkidle'});
  }
  save('matrix-results.json',{inputs:results.length,results,errors,realModelRequests:0,browser:browser.version(),visible:true});
  console.log('MATRIX_EXECUTED',results.length);
 }catch(e){save('matrix-failure.json',{error:String(e),stack:e.stack,completed:results.map(r=>r.label),errors});console.error(e);process.exitCode=1;}
 finally{console.log('VISIBLE_BROWSER_RETAINED');}
})();
