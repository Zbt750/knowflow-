// Read-only actual Chrome + actual localhost application. No model calls or
// real messages are created; restoration uses the existing study session.
import {createRequire} from 'node:module';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const output=resolve('storage/quality-audits/generation-rejection-20261019/live-readonly');
mkdirSync(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
const result={checks:[],errors:[],model_requests:0,business_writes:0};
page.on('pageerror',error=>result.errors.push(error.message));
await context.route(/^http:\/\/127\.0\.0\.1:5173\/api\//,async route=>{
  if(route.request().method()==='GET')return route.continue();
  result.errors.push('Blocked unexpected write: '+new URL(route.request().url()).pathname);
  return route.abort();
});
const get=async path=>{const response=await context.request.get('http://127.0.0.1:8000'+path);expect(response.ok()).toBe(true);return response.json();};
try{
  const health=await get('/api/health');result.health={status:health.status,database:health.database,model:health.llm_model};
  const studies=await get('/api/chat/sessions?mode=builtin&purpose=study');
  const qa=await get('/api/chat/sessions?mode=builtin&purpose=qa');
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  expect(studies.every(s=>s.purpose==='study')).toBe(true);
  expect(qa.every(s=>s.purpose==='qa')).toBe(true);
  expect(qa.some(q=>studies.some(s=>s.session_id===q.session_id))).toBe(false);
  result.checks.push('actual server purpose queries return disjoint QA and study sessions');
  const today=studies.find(s=>s.study_date===day);expect(today).toBeTruthy();
  result.study_session=today.session_id;
  await page.addInitScript(({day,id})=>localStorage.setItem(`learning-assistant:study:${day}`,id),{day,id:today.session_id});
  await page.goto('http://127.0.0.1:5173/study');
  await page.getByTestId('study-frog-launcher').click();
  const history=await get(`/api/chat/sessions/${today.session_id}/messages`);
  const truncated=history.find(m=>m.personal_generation?.diagnostics?.some(d=>d.code==='personal_generation_output_truncated'));
  expect(truncated).toBeTruthy();
  await expect(page.getByTestId('generation-diagnostics').last()).toContainText('personal_generation_output_truncated');
  await expect(page.getByTestId('generation-diagnostics').last()).toContainText('不是已判定答案错误');
  await page.screenshot({path:resolve(output,'actual-study-truncation-diagnostic.png')});
  result.checks.push('actual failed study generation history shows truncation stage and stable code');
  await page.reload();await page.getByTestId('study-frog-launcher').click();
  await expect(page.getByTestId('generation-diagnostics').last()).toContainText('personal_generation_output_truncated');
  result.checks.push('study purpose/session restoration preserves diagnostic after refresh');
  await page.goto('http://127.0.0.1:5173/chat');
  await expect(page.locator('.conversation-row')).toHaveCount(qa.length,{timeout:15000});
  await expect(page.locator('.conversation-row').filter({hasText:'今日学习'})).toHaveCount(0);
  await page.screenshot({path:resolve(output,'actual-qa-separate-history.png')});
  await page.reload();
  await expect(page.locator('.conversation-row')).toHaveCount(qa.length,{timeout:15000});
  result.checks.push('actual QA sidebar and refresh match server QA-only list, with study sessions absent');
  expect(result.errors).toEqual([]);result.status='PASS_READONLY_NO_REAL_MODEL';
}catch(error){result.errors.push(String(error));result.status='FAILED';await page.screenshot({path:resolve(output,'failed.png')});process.exitCode=1;}
finally{writeFileSync(resolve(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();}
