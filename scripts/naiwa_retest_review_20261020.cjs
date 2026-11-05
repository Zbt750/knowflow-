// Read-only review of retained real-model conversations AFTER paid egress is sealed.
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');
const {chromium,expect}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-real-retest-20261020-budget7');
async function main(){
 const context=await chromium.launchPersistentContext(path.join(out,'review-chrome-profile'),{channel:'chrome',headless:false,
  baseURL:'http://127.0.0.1:63046',viewport:{width:1366,height:900}});
 const page=context.pages()[0]||await context.newPage();
 const state=JSON.parse(fs.readFileSync(path.join(out,'browser-state.json'),'utf8'));
 await context.addInitScript(origins=>{const entry=origins.find(o=>o.origin===location.origin);
  if(entry&&!localStorage.getItem('naiwa-retest-review-initialized')){
   for(const {name,value} of entry.localStorage)localStorage.setItem(name,value);
   localStorage.setItem('naiwa-retest-review-initialized','true');
  }},state.origins);
 const health=await page.request.get('/api/health');expect(health.headers()['x-naiwa-experience']).toBe('restored-archive-fixed-provider-egress-sealed');
 const journeys=JSON.parse(fs.readFileSync(path.join(out,'journeys.json'),'utf8'));
 const study=journeys.find(r=>r.scene==='AGENT').session_id,qa=journeys.find(r=>r.scene==='TEACH').session_id;
 const checks=[];
 for(const sid of [study,qa]){
  const r=await page.request.get(`/api/chat/sessions/${sid}/messages`);const items=await r.json();
  const expected=journeys.filter(r=>r.session_id===sid).at(-1).persisted_messages;
  expect(items).toEqual(expected);checks.push({session_id:sid,persisted_messages:items.length,unchanged_after_isolated_restart:true});
 }
 const list=await (await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();
 expect(JSON.stringify(list)).not.toContain(study);
 await page.goto('/chat?session_id='+qa);await expect(page.locator('.message-row--assistant').last()).toContainText('导数比极限不存在');
 await page.reload();await expect(page.locator('.message-row--assistant').last()).toContainText('导数比极限不存在');
 await page.screenshot({path:path.join(out,'final-teaching-retained.png'),fullPage:true});
 const qaPage=page;
 const studyPage=await context.newPage();await studyPage.goto('/study');await studyPage.getByTestId('study-frog-launcher').click();
 await expect(studyPage.getByTestId('frog-conversation')).toContainText('答案或解析校验不一致');
 await studyPage.screenshot({path:path.join(out,'final-study-retained.png'),fullPage:true});
 const control=JSON.parse(fs.readFileSync(path.join(out,'control.json'),'utf8'));expect(control.paid_enabled).toBe(false);
 const ledger=JSON.parse(fs.readFileSync(path.join(out,'provider-ledger.json'),'utf8'));expect(ledger.requests.length).toBe(5);
 const report={status:'PASS',mode:'read-only browser review; fixed provider and network sealed',checks,qa_study_isolated:true,
   historical_refresh_restored:true,model_requests_during_review:0,physical_total:5,paid_enabled:false,
   qa_url:qaPage.url(),study_url:studyPage.url(),chrome_profile:path.join(out,'review-chrome-profile')};
 fs.writeFileSync(path.join(out,'final-readonly-browser-review.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report));
 if(process.argv.includes('--open'))await new Promise(resolve=>context.on('close',resolve));else await context.close();
}
main().catch(e=>{console.error(String(e));process.exitCode=1;});
