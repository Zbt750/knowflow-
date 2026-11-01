// No model calls allowed: inspect the completed real run and persistence.
const {createRequire}=require('node:module');const req=createRequire(require('node:path').resolve('frontend/package.json'));
const {chromium,expect}=req('@playwright/test');const fs=require('node:fs'),path=require('node:path');
const out=process.env.BLIND_OUT,base=process.env.BLIND_FRONT_URL;
const read=n=>JSON.parse(fs.readFileSync(path.join(out,n),'utf8'));const write=(n,v)=>fs.writeFileSync(path.join(out,n),JSON.stringify(v,null,2));
async function main(){
 expect(read('provider-ledger.json').requests.length).toBe(10);
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const ctx=await browser.newContext({baseURL:base,viewport:{width:1366,height:900},storageState:path.join(out,'final-model-browser-state.json')});
 const page=await ctx.newPage(),results=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function run(id,fn){try{results.push({id,status:'PASS',...await fn()});}catch(e){results.push({id,status:'FAIL',error:e.message});}
  await page.screenshot({path:path.join(out,id+'.png'),fullPage:true}).catch(()=>{});write('closure-results.json',results);}
 try{
  const final=read('final-model-results.json'),qaId=final[0].url.match(/sessions\/([^/]+)\//)[1];
  await run('CLOSE-real-qa-history',async()=>{
   const before=await(await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json();
   await page.goto(`/chat?session_id=${qaId}`);await expect(page.locator('.message-row--assistant')).toHaveCount(1);
   await expect(page.locator('.message-row--assistant').last()).toContainText('求导');
   expect(await page.locator('.katex').count()).toBeGreaterThan(0);expect(await page.locator('.katex-error').count()).toBe(0);
   await page.reload();await expect(page.locator('.message-row--assistant')).toHaveCount(1);
   expect(await(await page.request.get(`/api/chat/sessions/${qaId}/messages`)).json()).toEqual(before);
   return {qaId,history_equal:true,katex:await page.locator('.katex').count()};
  });
  await run('CLOSE-real-generation-failure-restored',async()=>{
   await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
   await expect(page.getByTestId('generation-diagnostics').last()).toContainText('personal_generation_format_invalid');
   expect(await page.locator('.generated-question-result__item').count()).toBe(0);
   const before=await(await page.request.get('/api/plans/today')).json();
   await page.reload();await page.getByTestId('study-frog-launcher').click();
   await expect(page.getByTestId('generation-diagnostics').last()).toContainText('personal_generation_format_invalid');
   expect(await(await page.request.get('/api/plans/today')).json()).toEqual(before);
   return {not_saved:true,plan_unchanged:true,real_question_doing_closure:'BLOCKED: no qualified real generated question; no fake attempt'};
  });
  await run('CLOSE-study-link-not-exposed-as-QA',async()=>{
   const original=read('browser-results.json').find(x=>x.id==='B-current-version').session_id;
   await page.goto(`/chat?session_id=${original}`);
   await expect(page.getByTitle('新建对话',{exact:true})).toBeEnabled();
   await expect(page.getByTestId('personal-generation-result')).toHaveCount(0);
   const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();
   expect(qa.some(s=>s.session_id===original)).toBe(false);
   return {study_session_id:original,study_history_not_exposed_in_qa:true,
     note:'Earlier attempt incorrectly expected a study conversation to open as QA; purpose isolation correctly prevents it.'};
  });
  await run('CLOSE-purpose-isolation',async()=>{
   const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();
   const study=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=study')).json();
   expect(qa.every(s=>s.purpose==='qa')).toBe(true);expect(study.every(s=>s.purpose==='study')).toBe(true);
   const ids=new Set(qa.map(s=>s.session_id));expect(study.some(s=>ids.has(s.session_id))).toBe(false);
   return {qa,study,server_side_separated:true};
  });
 }finally{expect(read('provider-ledger.json').requests.length).toBe(10);write('closure-results.json',results);write('closure-errors.json',errors);await browser.close();}
}
main().catch(e=>{write('closure-fatal.json',{error:e.stack});process.exitCode=1;});
