// Same global ledger, at most three additional useful business turns, no retries.
const {createRequire}=require('node:module');const req=createRequire(require('node:path').resolve('frontend/package.json'));
const {chromium,expect}=req('@playwright/test');const fs=require('node:fs'),path=require('node:path');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL;
const finalTwo=process.env.BLIND_FINAL_TWO==='1',prefix=finalTwo?'final-model':'continuation';
const read=n=>JSON.parse(fs.readFileSync(path.join(out,n),'utf8'));const write=(n,v)=>fs.writeFileSync(path.join(out,n),JSON.stringify(v,null,2));
async function main(){
 const ledger=read('provider-ledger.json');expect(ledger.requests.length).toBe(finalTwo?8:5);expect(ledger.stop_reason).toBeNull();
 const browser=await chromium.launch({channel:'chrome',headless:true});const ctx=await browser.newContext({baseURL:base,viewport:{width:1366,height:900}});const page=await ctx.newPage(),results=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 async function run(id,fn){await ctx.setExtraHTTPHeaders({'x-blind-case':id});
  try{results.push({id,status:'EXECUTED',...await fn()});}catch(e){results.push({id,status:'FAIL',error:e.message});}
  await page.screenshot({path:path.join(out,id+'.png'),fullPage:true}).catch(()=>{});write(prefix+'-results.json',results);}
 async function send(selector,input){
  const l=read('provider-ledger.json');expect(l.stop_reason).toBeNull();expect(l.requests.length).toBeLessThan(10);
  await page.locator(selector).fill(input);
  if(selector==='#chat-question')await expect(page.getByRole('button',{name:'发送',exact:true})).toBeEnabled();
  const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream'));await page.locator(selector).press('Enter');
  const r=await response;return {input,url:r.url(),status:r.status(),sse:await r.text()};
 }
 try{
  await page.goto('/chat');await expect(page.getByTitle('新建对话',{exact:true})).toBeEnabled();await page.getByTitle('新建对话',{exact:true}).click();
  await run(finalTwo?'FINAL-A1-concept':'CONT-A1-concept',async()=>{
   const r=await send('#chat-question','我最近在复习高等数学的幂级数，但是总是容易把求导和积分弄混，你能给我讲清楚吗？');
   await expect(page.locator('.message-row--assistant').last()).toContainText('求导');
   return {...r,visible:await page.locator('.message-row--assistant').last().innerText()};
  });
  if(!finalTwo)await run('CONT-A2-context',async()=>{
   if(read('provider-ledger.json').stop_reason)return {status:'NOT_RUN',reason:'provider stop'};
   const r=await send('#chat-question','我还是不太懂，你能用一个具体例子讲一下吗？');
   await expect(page.locator('.message-row--assistant').last()).toContainText('级数');
   const sid=r.url.match(/sessions\/([^/]+)\//)[1];
   const before=await(await page.request.get(`/api/chat/sessions/${sid}/messages`)).json();
   await page.reload();await expect(page.locator('.message-row--assistant')).toHaveCount(2);
   const after=await(await page.request.get(`/api/chat/sessions/${sid}/messages`)).json();expect(after).toEqual(before);
   return {...r,visible:await page.locator('.message-row--assistant').last().innerText(),history_equal:true};
  });
  await run(finalTwo?'FINAL-B-generation':'CONT-B-generation',async()=>{
   if(read('provider-ledger.json').stop_reason)return {status:'NOT_RUN',reason:'provider stop'};
   await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();
   await page.getByTestId('study-frog-launcher').click();
   const r=await send('#frog-message-input','这道题我感觉还不错，帮我出一道比这题难一点的类似题。');
   await expect(page.getByTestId('generation-confirmation')).toBeVisible();await expect(page.getByTestId('generation-confirmation')).toContainText('计划生成 1 道题');
   await page.getByTestId('generation-node-select').selectOption({value:read('fixture.json').node_id});
   const response=page.waitForResponse(r=>r.url().endsWith('/assistant:stream'));
   await page.getByTestId('confirm-generation-node').click();const sse=await(await response).text();
   const count=await page.locator('.generated-question-result__item').count();
   return {...r,generation_sse:sse,preview_count:count,visible:await page.getByTestId('frog-conversation').innerText()};
  });
 }finally{
  await ctx.storageState({path:path.join(out,prefix+'-browser-state.json')});write(prefix+'-results.json',results);write(prefix+'-errors.json',errors);await browser.close();
 }
}
main().catch(e=>{write('continuation-fatal.json',{error:e.stack});process.exitCode=1;});
