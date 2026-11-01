// Real Chrome/Vue/production HTTP APIs. No request interception or model stubs.
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module'),{execFileSync}=require('node:child_process');
const {chromium,expect}=createRequire(path.resolve('frontend/package.json'))('@playwright/test');
const out=path.resolve('storage/quality-audits/naiwa-real-20261020'),home=path.resolve('storage/manual-experience/naiwa-real-20261020');
const mode=process.argv[2],runtime=JSON.parse(fs.readFileSync(path.join(home,'runtime.json'),'utf8'));
const file=n=>path.join(out,n),read=n=>JSON.parse(fs.readFileSync(file(n),'utf8')),write=(n,x)=>fs.writeFileSync(file(n),JSON.stringify(x,null,2));
const ledger=()=>read('provider-ledger.json');
const records=fs.existsSync(file('journeys.json'))?read('journeys.json'):[];
const references=fs.existsSync(file('sessions.json'))?read('sessions.json'):{};
function snapshot(name){execFileSync(process.env.PYTHON_EXE||'C:/Users/ZBT/AppData/Local/Programs/Python/Python312/python.exe',['scripts/naiwa_acceptance_20261020.py','snapshot'],{cwd:process.cwd()});fs.copyFileSync(file('database-latest.json'),file('database-'+name+'.json'));return read('database-latest.json');}
async function main(){
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const stateFile=file('browser-state.json');
 const ctx=await browser.newContext({baseURL:runtime.frontend_url,viewport:{width:1366,height:900},...(fs.existsSync(stateFile)?{storageState:stateFile}:{})});
 const page=await ctx.newPage();page.setDefaultTimeout(25000);let current=mode;
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function shot(id){await page.screenshot({path:file(id+'.png'),fullPage:true});}
 async function caseHeader(id){current=id;await ctx.setExtraHTTPHeaders({'x-acceptance-case':id});write('next-request.json',{case:id,physical_before:ledger().requests.length,remaining:20-ledger().requests.length,time:new Date().toISOString()});}
 async function capture(response,input,id,before){
  const sse=await response.text();const sid=response.url().match(/sessions\/([^/]+)\//)?.[1];
  const frames=sse.trim().split(/\r?\n\r?\n/).filter(Boolean).map(part=>{const lines=part.split(/\r?\n/);return {event:lines[0].slice(7),data:JSON.parse(lines.find(l=>l.startsWith('data: ')).slice(6))};});
  const last=frames.findLast(f=>f.event==='done');
  const row={id,input,session_id:sid,request:response.request().postDataJSON(),http:response.status(),frames,sse,answer:last?.data.answer,status:frames.some(f=>f.event==='error')?'ERROR':'REPLIED',physical_requests:ledger().requests.length-before,cumulative:ledger().requests.length};
  records.push(row);write('journeys.json',records);
  if(sid){references[id]=sid;write('sessions.json',references);await page.request.patch(`/api/chat/sessions/${sid}`,{data:{title:'奶蛙真实体验测试·'+id.replace(/\d+$/,'')}});}
  await page.waitForTimeout(300);await shot(id);snapshot(id);
  return row;
 }
 async function send(id,input,selector='#chat-question',button){
  await caseHeader(id);const before=ledger().requests.length;
  const field=page.locator(selector);await expect(field).toBeEnabled({timeout:180000});await field.fill(input);
  const wait=page.waitForResponse(r=>/\/(assistant|answers)(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST',{timeout:30000});wait.catch(()=>{});
  if(button)await button.click();else await field.press('Enter');
  return capture(await wait,input,id,before);
 }
 async function newQA(){await page.goto('/chat');await page.getByTitle('新建对话',{exact:true}).click();}
 async function study(){await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible({timeout:45000});await page.getByTestId('study-frog-launcher').click();await expect(page.locator('#frog-message-input')).toBeVisible();}
 try{
  // The isolated retrieval model loads after Vite. Don't mistake that startup
  // window for a broken study page or consume a model call before readiness.
  await expect.poll(async()=>{try{const r=await page.request.get('/api/health');return r.ok()?(await r.json()).database:'not-ready';}catch{return 'not-ready';}},{timeout:180000,intervals:[1000,2000]}).toBe('connected');
  if(mode==='zero'){
   const initial=ledger().requests.length;expect(initial).toBe(0);await newQA();const evidence=[];
   for(const [index,input] of ['我题库里有多少道数学二的可练题？','那其中洛必达法则的题有多少道？','其中多少道是真题？','这些题我做过几道？','那里面我做错过哪些？'].entries()){
    const row=await send('ZERO'+(index+1),input);expect(row.status).toBe('REPLIED');expect(ledger().requests.length).toBe(0);
    const db=read('database-latest.json'),answer=db.chat_messages.filter(m=>m.session_id===row.session_id&&m.role==='assistant').sort((a,b)=>a.seq-b.seq).at(-1);
    const trace=answer.metadata.read_only_data_query;expect(trace.model_called).toBe(false);expect(trace.query_state.subject).toBe('考研数学');evidence.push(trace);
    const value=index<3?trace.question_count:trace.distinct_question_count;
    expect(value).toBe([4,3,2,2,1][index]);
   }
   const text=await page.locator('.message-row--assistant').allTextContents();await page.reload();await expect(page.locator('.message-row--assistant')).toHaveCount(5);expect(await page.locator('.message-row--assistant').allTextContents()).toEqual(text);await shot('ZERO-refresh');
   write('zero-results.json',{status:'PASS',physical_requests:ledger().requests.length-initial,evidence,errors});
  }
  if(mode==='A'){
   await newQA();for(const [index,input] of ['洛必达法则什么时候可以用？','那为什么有些极限不能直接用？','你给我举一个容易用错的例子。'].entries()){
    const row=await send('A'+(index+1),input);if(row.status!=='REPLIED'||ledger().stop_reason)break;
   }
   await page.reload();await shot('A-refresh');snapshot('A-refresh');
  }
  if(mode==='Arepair'){
   await page.goto('/chat?session_id='+references.A1);
   await send('R1','那为什么有些极限不能直接用？');
   if(!ledger().stop_reason)await send('A3','你给我举一个容易用错的例子。');
   await page.reload();await shot('A-repaired-refresh');snapshot('A-repaired-refresh');
  }
  if(mode==='B'){
   await study();for(const [index,input] of ['这道题先给我一点提示，别告诉我答案。','为什么第一步要这样处理？','我还是不懂，换个简单的方法讲。','现在给我完整解答。'].entries()){
    const row=await send('B'+(index+1),input,'#frog-message-input',page.getByTestId('task-arrange'));if(row.status!=='REPLIED'||ledger().stop_reason)break;
   }
   await page.reload();await shot('B-refresh');snapshot('B-refresh');
  }
  if(mode==='C'){
   await newQA();await send('C0','根据洛必达法则给我出一道稍难一点的题。');
   if(await page.getByTestId('generation-confirmation').count()){
    const select=page.getByTestId('generation-node-select');if(await select.count())await select.selectOption({label:'洛必达法则'});
    await caseHeader('C1');const before=ledger().requests.length;const wait=page.waitForResponse(r=>/assistant(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST');await page.getByTestId('confirm-generation-node').click();await capture(await wait,'点击确认洛必达法则并生成一道题','C1',before);
   }
   await shot('C-preview');snapshot('C-preview');
  }
  if(mode==='Cexplain'){
   await page.goto('/chat?session_id='+references.C1);
   for(const [id,text] of [['C2','刚才生成的题怎么做？讲解一下。'],['C3','你检查一下刚才的答案有没有算错，尤其是适用条件和计算步骤。']]){
    const row=await send(id,text);if(row.status!=='REPLIED'||ledger().stop_reason)break;
   }
   await page.reload();await shot('C-refresh');snapshot('C-refresh');
  }
  if(mode==='Cvariant'||mode==='Rvariantfix'){
   const generationCase=mode==='Rvariantfix'?'R2':'C4';
   await study();
   for(let n=0;n<10&&!((await page.getByTestId('focus-stem').innerText()).includes('e^x'));n++){
    if(await page.getByTestId('previous-question').isEnabled())await page.getByTestId('previous-question').click();
    else if(await page.getByTestId('continue-question').isEnabled())await page.getByTestId('continue-question').click();
    else break;
   }
   await expect(page.getByTestId('focus-stem')).toContainText('e^x');await shot('C-variant-source-question');
   const before=snapshot('C-variant-before');const source=before.questions.find(q=>q.id==='9ba9c177-26a2-4918-bf84-b85159f9b002');
   expect(source.current_version_id).toBe('92c57d4d-f0bf-4df2-b9b2-c949a3d43904');
   const row=await send(generationCase,'这道题我觉得还不错，帮我生成一道比它难一点的类似题。','#frog-message-input',page.getByTestId('task-arrange'));
   const confirm=page.getByTestId('generation-confirmation');
   if(await confirm.count()){
    const select=page.getByTestId('generation-node-select');if(await select.count())await select.selectOption({label:'洛必达法则'});
    await caseHeader(generationCase);const prior=ledger().requests.length;const wait=page.waitForResponse(r=>/assistant(:|%3A)stream$/.test(r.url())&&r.request().method()==='POST');wait.catch(()=>{});
    await page.getByTestId('confirm-generation-node').click();await capture(await wait,'确认洛必达法则并生成一道基于当前题的变式',generationCase,prior);
   }
   await expect.poll(()=>ledger().requests.filter(x=>x.case_id===generationCase).length).toBeLessThanOrEqual(1);
   await shot('C-variant-result');const after=snapshot('C-variant-result');
   write('current-question-variant-'+generationCase+'.json',{user_input:row.input,source_question_id:source.id,source_version_id:source.current_version_id,source_kp_id:source.kp_id,ledger_requests:ledger().requests.filter(x=>x.case_id===generationCase).length,question_count_before:before.questions.length,question_count_after:after.questions.length,practice_items_before:before.practice_items.length,practice_items_after:after.practice_items.length,session_id:row.session_id});
  }
  if(mode==='Cadd'){
   const approval=read('independent-math-review.json');expect(approval.correct).toBe(true);
   const before=snapshot('C-before-add');const question=before.questions.find(q=>q.id===approval.question_id);
   expect(question.current_version_id).toBe(approval.question_version_id);expect(question.correct_answer).toBe(approval.correct_option);
   await caseHeader('ZERO-CADD');await page.goto('/chat?session_id='+references.C1);
   const preview=page.getByTestId('personal-generation-result');await expect(preview).toBeVisible();
   await preview.getByRole('button',{name:'加入今日学习',exact:true}).click();await expect(preview).toContainText('这批题已加入今日学习');
   const added=snapshot('C-added');expect(added.practice_items.length).toBe(before.practice_items.length+1);
   const item=added.practice_items.find(i=>i.question_id===question.id);expect(item.question_version_id).toBe(question.current_version_id);expect(item.kp_id).toBe(question.kp_id);
   await shot('C-added');await page.goto('/study');await expect(page.getByTestId('study-active')).toBeVisible();
   for(let n=0;n<10&&!((await page.getByTestId('focus-stem').innerText()).includes('二阶连续可导'));n++)await page.getByTestId('continue-question').click();
   await expect(page.getByTestId('focus-stem')).toContainText('二阶连续可导');await page.getByTestId('option-'+approval.correct_option).check();await page.getByTestId('submit-answer').click();
   await expect(page.getByTestId('answer-result-label')).toBeVisible();await page.getByTestId('answer-explanation').click();await expect(page.getByTestId('focus-answer')).toBeVisible();await shot('C-answered');
   const answered=snapshot('C-answered');const attempts=answered.question_attempts.filter(a=>a.question_id===question.id);expect(attempts.length).toBe(1);expect(attempts[0].question_version_id).toBe(question.current_version_id);expect(attempts[0].objective_result).toBe('unknown');
   expect(answered.learning_events.some(e=>e.question_version_id===question.current_version_id)).toBe(true);
   await page.reload();for(let n=0;n<10&&!((await page.getByTestId('focus-stem').innerText()).includes('二阶连续可导'));n++)await page.getByTestId('continue-question').click();
   await expect(page.getByTestId('answer-result-label')).toBeVisible();await expect(page.getByTestId('submit-answer')).toHaveCount(0);await shot('C-answer-refreshed');
   const final=snapshot('C-answer-refreshed');expect(final.question_attempts.filter(a=>a.question_id===question.id).length).toBe(1);
   write('learning-loop.json',{status:'PASS',question_id:question.id,question_version_id:question.current_version_id,item_id:item.id,attempt:attempts[0],events:answered.learning_events.filter(e=>e.question_version_id===question.current_version_id),physical_model_requests:0,grading_boundary:'reference-only remains unknown, not formal graduation evidence'});
  }
  if(mode==='Dupload'){
   await caseHeader('ZERO-UPLOAD');await page.goto('/materials');const title='奶蛙真实体验测试·洛必达复习笔记';
   const chooser=page.waitForEvent('filechooser');await page.getByTestId('upload-toggle').click();await(await chooser).setFiles(file('lhopital-note.md'));await page.getByTestId('upload-title').fill(title);await page.getByTestId('upload-submit').click();
   const item=page.locator('.material-item').filter({hasText:title});await expect(item.locator('.material-status')).toHaveText('可检索',{timeout:180000});
   await page.getByRole('button',{name:'针对'+title+'提问',exact:true}).click();await shot('D-uploaded');snapshot('D-uploaded');
  }
  if(mode==='D'){
   await page.goto('/materials');for(const [index,text] of ['这份资料里洛必达法则在哪一部分？','这部分讲了哪些重点？','我的题库里有没有对应的练习题？'].entries()){
    const row=await send('D'+(index+1),text,'[data-testid="material-search-question"]',page.getByTestId('material-search-send'));if(row.status!=='REPLIED'||ledger().stop_reason)break;
   }
   await page.reload();await shot('D-refresh');snapshot('D-refresh');
  }
  if(mode==='Drepair'){
   await page.goto('/materials');const row=await send('ZERO-D3-repaired','我的题库里有没有对应的练习题？','[data-testid="material-search-question"]',page.getByTestId('material-search-send'));
   expect(row.physical_requests).toBe(0);expect(row.answer).toContain('洛必达法则');expect(row.answer).toContain('系统题库');expect(row.answer).not.toContain('[C1]');
   const db=read('database-latest.json'),message=db.chat_messages.filter(m=>m.session_id===row.session_id&&m.role==='assistant').sort((a,b)=>a.seq-b.seq).at(-1);
   expect(message.metadata.read_only_data_query.scope_node_names).toEqual(['洛必达法则']);expect(message.metadata.read_only_data_query.question_count).toBe(4);
   await page.reload();await shot('D3-repaired-refresh');snapshot('D3-repaired-refresh');
  }
  if(mode==='E'){
   await study();const row=await send('E1','我今天只有90分钟，根据我最近的错题和薄弱知识点安排数学二复习。先给出建议，未经我确认不要创建或追加今日学习。','#frog-message-input',page.getByTestId('task-arrange'));
   if(row.status==='REPLIED'&&ledger().requests.filter(r=>r.case_id.startsWith('E')).length<4&&!ledger().stop_reason)await send('E2','为什么你把洛必达法则放在前面？','#frog-message-input',page.getByTestId('task-arrange'));
   await page.reload();await shot('E-refresh');snapshot('E-refresh');
  }
  if(mode==='Erepair'){
   await study();await send('E3','我今天只有90分钟，根据我最近的错题和薄弱知识点安排数学二复习。先给出建议，未经我确认不要创建或追加今日学习。','#frog-message-input',page.getByTestId('task-arrange'));
   await page.reload();await shot('E-repaired-refresh');snapshot('E-repaired-refresh');
  }
  if(mode==='inspect'){
   await caseHeader('ZERO-INSPECT');const before=ledger().requests.length;
   const studyId=references.B1;const qa=await(await page.request.get('/api/chat/sessions?mode=builtin&purpose=qa')).json();
   expect(JSON.stringify(qa)).not.toContain(studyId);
   await page.goto('/chat?session_id='+references.C1);await expect(page.getByTestId('personal-generation-result')).toBeVisible();
   await expect(page.getByTestId('personal-generation-result')).toContainText('这批题已加入今日学习');
   const bubbles=page.locator('.message-row--assistant .message-bubble');const answers=await bubbles.allTextContents();await page.reload();await expect(bubbles).toHaveCount(answers.length);expect(await bubbles.allTextContents()).toEqual(answers);await expect(page.getByTestId('personal-generation-result')).toContainText('这批题已加入今日学习');await shot('inspection-QA-history');
   await page.goto('/knowledge');await expect(page.getByTestId('knowledge-canvas')).toBeVisible({timeout:45000});
   await expect(page.locator('.frog-tree-mascot')).toHaveCount(1);await expect(page.locator('path.frog-limb').first()).toBeAttached();await shot('knowledge-desktop');
   const initialNodes=await page.locator('.canvas-node-name').allTextContents();
   await page.locator('.canvas-toggle').first().click();await expect.poll(()=>page.locator('path.frog-toe').count()).toBeGreaterThan(0);
   await page.getByTestId('knowledge-search').fill('洛必达法则');await page.getByTestId('tree-node-math.calculus.limit.lhopital').click();await expect(page.getByTestId('detail-title')).toHaveText('洛必达法则');await shot('knowledge-searched');
   await page.getByTestId('knowledge-search').fill('');
   await page.setViewportSize({width:390,height:844});await page.reload();await expect(page.getByTestId('knowledge-canvas')).toBeVisible();await shot('knowledge-mobile');
   const overflow=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}));
   await page.goto('/chat?session_id='+references.C1);await expect(page.getByTestId('personal-generation-result')).toBeVisible();await shot('generated-preview-mobile');
   await page.goto('/materials');await expect(page.getByTestId('material-search-question')).toBeVisible();await shot('materials-mobile-history');
   expect(ledger().requests.length).toBe(before);
   write('inspection.json',{status:'PASS',chrome:'system Chrome, headless automation (not human operated)',initialNodes,knowledge_document_width:overflow,qa_study_isolated:true,refresh_answers_equal:true,physical_model_requests:0});
  }
 }catch(e){await shot('failure-'+mode);write('browser-failure-'+mode+'.json',{error:e.stack,url:page.url(),body:await page.locator('body').innerText()});throw e;}finally{await ctx.storageState({path:stateFile});write('browser-errors-'+mode+'.json',errors);write('journeys.json',records);await browser.close();}
}
main().catch(e=>{write('browser-failure-'+mode+'.json',{error:e.stack});process.exitCode=1;});
