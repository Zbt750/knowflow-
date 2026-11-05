// Actual Vue, SSE and HTTP API on owned PostgreSQL; fixed Provider, no fee.
import {test,expect,type Page} from '@playwright/test';
const source=String.raw`原题：当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。`;
async function send(page:Page,text:string){const box=page.locator('#chat-question');await box.fill(text);await box.press('Enter');}
async function confirm(page:Page,label:string,count:number){
  const card=page.getByTestId('generation-confirmation');await expect(card).toBeVisible();
  await expect(card).toContainText(`计划生成 ${count} 道题`);
  await page.getByTestId('generation-node-select').selectOption({label});
  await page.getByTestId('confirm-generation-node').click();
}
function frames(text:string){return text.trim().split('\n\n').map(frame=>{
  const lines=frame.split('\n');return {event:lines.find(x=>x.startsWith('event: '))?.slice(7),
    data:JSON.parse(lines.find(x=>x.startsWith('data: '))?.slice(6)||'{}')};});}

test('old two-question request cannot override the next explicit single harder question',async({page},info)=>{
  expect(process.env.APP_ENV).toBe('test');expect(Number(process.env.KAOYAN_OWNED_TEST_PORT)).toBeGreaterThan(18000);
  await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
  await send(page,'那给我再生成2道都是中等的类似题。'+source);
  await confirm(page,'数量核对成功隔离',2);
  await expect(page.getByTestId('personal-generation-result').last().locator('.generated-question-result__item')).toHaveCount(2);
  await send(page,'你帮我生成一道比这道更难的题');
  // 问答页没有当前练习定位，上一回合生成了两题，指代确实有歧义。
  // 先澄清原题，不能为绕过安全确认而随机挑选其中一题。
  await expect(page.locator('.message-row--assistant').last()).toContainText('请指出要作为原题');
  await send(page,source);
  await confirm(page,'数量核对成功隔离',1);
  await expect(page.getByTestId('personal-generation-result')).toHaveCount(2);
  await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
  const preview=page.getByTestId('personal-generation-result').last();
  await expect(preview.locator('.generated-question-result__item')).toHaveCount(1);
  await expect(preview.getByTestId('generation-outcome-summary')).toContainText('请求 1 道 · 已保存 1 道 · 未保存 0 道');
  await expect(preview).toContainText('模型请求 1 次');
  await page.reload();
  await expect(page.getByTestId('personal-generation-result').last().locator('.generated-question-result__item')).toHaveCount(1);
  await page.screenshot({path:info.outputPath('two-then-one-keeps-explicit-count.png')});
});

for(const scenario of [
  {label:'数量核对部分成功隔离',count:2,saved:1,code:'personal_generation_answer_conflict'},
  {label:'数量核对单题失败隔离',count:1,saved:0,code:'personal_generation_output_truncated'},
])test(`SSE and restored preview agree: ${scenario.label}`,async({page},info)=>{
  expect(process.env.APP_ENV).toBe('test');
  const streams:string[]=[];
  page.on('response',response=>{if(response.url().endsWith('/assistant:stream'))void response.text().then(text=>streams.push(text));});
  await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
  await send(page,`帮我生成${scenario.count===1?'一':'两'}道更难的类似计算题。`+source);
  await confirm(page,scenario.label,scenario.count);
  await expect(page.getByTestId('generation-diagnostics')).toContainText(scenario.code);
  await expect(page.locator('.generated-question-result__item')).toHaveCount(scenario.saved);
  await expect(page.getByTestId('generation-outcome-summary')).toContainText(`请求 ${scenario.count} 道 · 已保存 ${scenario.saved} 道 · 未保存 1 道`);
  await expect.poll(()=>streams.some(s=>s.includes('event: personal_generation\n'))).toBe(true);
  const data=frames(streams.findLast(s=>s.includes('event: personal_generation\n'))!);
  const result=data.find(f=>f.event==='personal_generation')!.data;
  expect(result.requested).toBe(scenario.count);expect(result.question_ids).toHaveLength(scenario.saved);
  expect(result.outcome_summary.provider_calls).toBe(scenario.count);
  expect(result.outcome_summary.not_attempted_count).toBe(0);
  expect(result.message).not.toContain('未通过检查或未生成');
  if(scenario.saved)expect(data.find(f=>f.event==='done')?.data.status).toBe('completed');
  else expect(data.at(-1)?.event).toBe('error');
  await page.reload();
  await expect(page.locator('.generated-question-result__item')).toHaveCount(scenario.saved);
  await expect(page.getByTestId('generation-diagnostics')).toContainText(scenario.code);
  await info.attach('actual-sse-result',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  await page.screenshot({path:info.outputPath('counts-preview-and-failure-stage.png')});
});

for(const scenario of [
  {label:'默认单题网络失败隔离',text:'帮我生成比这题还难的题。',count:1},
  {label:'多题网络失败隔离',text:'生成 3 道更难的类似题。',count:3},
])test(`network failure counts, history and explicit new request: ${scenario.label}`,async({page},info)=>{
  expect(process.env.APP_ENV).toBe('test');
  const streams:string[]=[];
  page.on('response',response=>{if(response.url().endsWith('/assistant:stream'))void response.text().then(text=>streams.push(text));});
  await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();
  await send(page,scenario.text+source);
  await confirm(page,scenario.label,scenario.count);
  const summary=page.getByTestId('generation-outcome-summary').last();
  await expect(page.getByTestId('generation-diagnostics').last()).toContainText('域名解析失败');
  await expect(summary).toContainText(`请求 ${scenario.count} 道 · 已保存 0 道 · 未保存 1 道`);
  await expect(summary).toContainText('模型网络请求失败 1 次；质量检查拒绝 0 道');
  await expect(page.locator('.generated-question-result__item')).toHaveCount(0);
  if(scenario.count===1)await expect(summary).not.toContainText('尚未执行');
  else await expect(summary).toContainText('另有 2 道尚未执行');
  await expect.poll(()=>streams.some(s=>s.includes('event: personal_generation\n'))).toBe(true);
  const result=frames(streams.findLast(s=>s.includes('event: personal_generation\n'))!).find(f=>f.event==='personal_generation')!.data;
  expect(result.outcome_summary).toMatchObject({requested_count:scenario.count,attempted_count:1,
    saved_count:0,network_failed_count:1,quality_rejected_count:0,not_executed_count:scenario.count-1});
  expect(result.calls).toHaveLength(1);expect(result.calls[0].usage_observed).toBe(false);
  await page.reload();
  await expect(summary).toContainText(`请求 ${scenario.count} 道 · 已保存 0 道 · 未保存 1 道`);
  await expect(summary).toContainText('模型请求 1 次');
  await info.attach('network-failure-sse',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  await page.screenshot({path:info.outputPath('network-failure-counts-restored.png')});
  if(scenario.count===1){
    // Editing is free. Only the next explicit send + node confirmation starts
    // a new paid-equivalent call; reading the old failed batch never does.
    await page.getByRole('button',{name:'编辑原提问',exact:true}).click();
    await expect(page.locator('#chat-question')).toHaveValue(scenario.text+source);
    await page.locator('#chat-question').press('Enter');
    await confirm(page,scenario.label,1);
    await expect(page.getByTestId('personal-generation-result')).toHaveCount(1);
    await expect(page.getByTestId('personal-generation-result').getByTestId('generation-outcome-summary')).toContainText('请求 1 道 · 已保存 1 道 · 未保存 0 道');
    await expect(page.locator('.generated-question-result__item')).toHaveCount(1);
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await page.screenshot({path:info.outputPath('explicit-new-single-request-saved-mobile.png'),fullPage:true});
  }
});
