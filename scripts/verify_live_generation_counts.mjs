// Read-only actual application verification. All non-GET browser API requests
// are blocked; existing user history is never rewritten or generated again.
import {createRequire} from 'node:module';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const output=resolve('storage/quality-audits/generation-count-20261019/live-readonly');
mkdirSync(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
const result={checks:[],errors:[],paid_requests:0,business_writes:0};
page.on('pageerror',error=>result.errors.push(error.message));
await context.route(/^http:\/\/127\.0\.0\.1:5173\/api\//,async route=>{
  if(route.request().method()==='GET')return route.continue();
  result.errors.push('Blocked unexpected write: '+new URL(route.request().url()).pathname);
  return route.abort();
});
const get=async path=>{const response=await context.request.get('http://127.0.0.1:8000'+path);expect(response.ok()).toBe(true);return response.json();};
try{
  const health=await get('/api/health');result.health={status:health.status,database:health.database};
  const sessions=await get('/api/chat/sessions?mode=builtin&purpose=study');
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const today=sessions.find(s=>s.study_date===day);expect(today).toBeTruthy();
  const history=await get(`/api/chat/sessions/${today.session_id}/messages`);
  const generated=history.filter(m=>m.personal_generation?.question_ids?.length);
  expect(generated.length).toBeGreaterThan(0);
  const last=generated.at(-1).personal_generation;
  expect(last.outcome_summary.requested_count).toBe(last.requested);
  expect(last.outcome_summary.saved_count).toBe(new Set(last.question_ids).size);
  result.latest_existing_outcome=last.outcome_summary;
  await page.addInitScript(({day,id})=>localStorage.setItem(`learning-assistant:study:${day}`,id),{day,id:today.session_id});
  await page.goto('http://127.0.0.1:5173/study');
  await page.getByTestId('study-frog-launcher').click();
  const summary=page.getByTestId('personal-generation-result').last().getByTestId('generation-outcome-summary');
  const label=`请求 ${last.requested} 道 · 已保存 ${last.question_ids.length} 道 · 未保存 ${last.outcome_summary.failed_count} 道`;
  await expect(summary).toContainText(label);
  await page.screenshot({path:resolve(output,'actual-study-restored-counts.png')});
  await page.reload();await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('personal-generation-result').last().getByTestId('generation-outcome-summary')).toContainText(label);
  result.checks.push('actual updated API returns execution-based counts for existing history',
    'actual Vue study drawer displays matching saved and rejected counts',
    'refresh preserves original records and counts without POST or model calls');
  expect(result.errors).toEqual([]);result.status='PASS_READONLY_NO_REAL_MODEL';
}catch(error){result.errors.push(String(error));result.status='FAILED';await page.screenshot({path:resolve(output,'failed.png')});process.exitCode=1;}
finally{writeFileSync(resolve(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();}
