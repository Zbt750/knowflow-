const {createRequire}=require('node:module'),path=require('node:path'),fs=require('node:fs');
const {chromium,expect}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL,part=path.join(out,'remaining-scenes');
const write=(n,v)=>fs.writeFileSync(path.join(part,n),JSON.stringify(v,null,2));
const results=[],streams=[],errors=[];let id='READONLY';
async function main(){
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const ctx=await browser.newContext({baseURL:base,viewport:{width:1366,height:900},storageState:path.join(out,'browser-state.json'),extraHTTPHeaders:{'x-blind-case':'READONLY'}});
 const page=await ctx.newPage();page.setDefaultTimeout(30000);page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(/\/(answers|assistant)(:|%3A)stream$/.test(r.url())){const c=id;void r.text().then(text=>{streams.push({id:c,url:r.url(),body:r.request().postDataJSON(),text});write('sse.json',streams);}).catch(()=>{});}});
 const ledger=()=>JSON.parse(fs.readFileSync(path.join(part,'provider-ledger.json'),'utf8'));
 async function run(name,fn){id=name;await ctx.setExtraHTTPHeaders({'x-blind-case':id});const before=ledger().requests.length;write('next-case.json',{id,total_before:4+before});
  try{results.push({id,status:'EXECUTED',...await fn(),physical_requests:ledger().requests.length-before});}catch(e){results.push({id,status:'BLOCKED',error:e.message,physical_requests:ledger().requests.length-before});}
  await page.screenshot({path:path.join(part,id+'.png'),fullPage:true}).catch(()=>{});write('browser-results.json',results);
 }
 try{
  await page.goto('/materials');await expect(page.getByTestId('materials-page')).toBeVisible();
  await page.getByRole('button',{name:'针对奶蛙真实体验测试：幂级数复习笔记提问'}).click();
  await expect(page.getByTestId('material-search-scope')).toContainText('已限定 1 份');
  for(const [name,text] of [['RAG1','根据这份笔记，我今天的20分钟具体怎么分配？请按先后顺序告诉我。'],['RAG2','那第二步有多少分钟？最后一步做什么？不要改成新的安排。'],['RAG3','这份笔记有没有说明操作系统的进程调度算法？如果没有，请直接说没有，不要用课外知识代替。']])await run(name,async()=>{
   const l=ledger();if(l.stop_reason||l.requests.length>=6)return {status:'NOT_RUN',reason:l.stop_reason||'shared 10 request ceiling'};
   await page.getByTestId('material-search-question').fill(text);await expect(page.getByTestId('material-search-send')).toBeEnabled();
   const waiting=page.waitForResponse(r=>/\/answers(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST');await page.getByTestId('material-search-send').click();const r=await waiting,sse=await r.text();await expect(page.getByTestId('material-search-question')).toBeEnabled({timeout:150000});
   return {input:text,http:r.status(),sse,visible:await page.getByTestId('material-search-assistant').last().innerText(),cleared:await page.getByTestId('material-search-question').inputValue()===''};
  });
  await run('RESTORE',async()=>{const before=await page.getByTestId('material-search-assistant').allTextContents();await page.reload();await expect(page.getByTestId('material-search-assistant')).toHaveCount(before.length);expect(await page.getByTestId('material-search-assistant').allTextContents()).toEqual(before);return {equal:true,count:before.length};});
  await run('CITATION',async()=>{const source=page.getByTestId('material-search-assistant').first().locator('details');if(!await source.count())return {status:'FAIL',reason:'no material citation control'};await source.locator('summary').click();await source.getByRole('button').first().click();await expect(page.getByTestId('material-reader')).toBeVisible();return {reader:await page.getByTestId('material-reader').innerText()};});
 }finally{write('browser-results.json',results);write('browser-errors.json',errors);await browser.close();}
}
main().catch(e=>{write('browser-fatal.json',{error:e.stack});process.exitCode=1;});
