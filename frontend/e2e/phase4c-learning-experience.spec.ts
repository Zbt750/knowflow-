// Actual browser + stateful protocol fixtures; DB/RAG/model semantics are tested separately.
import {test,expect,type Page} from "@playwright/test";
test.setTimeout(30000);
const sid="11111111-1111-4111-8111-111111111111",study="22222222-2222-4222-8222-222222222222",deep="33333333-3333-4333-8333-333333333333",
  node="44444444-4444-4444-8444-444444444444",rid="55555555-5555-4555-8555-555555555555",mid="66666666-6666-4666-8666-666666666666",qid="77777777-7777-4777-8777-777777777777",taskId="88888888-8888-4888-8888-888888888888";
const frame=(event:string,data:unknown)=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
async function setup(page:Page){
  const state={sessions:[] as any[],histories:new Map<string,any[]>(),asks:[] as any[],creates:[] as any[],sends:0,plans:0,confirms:0,deep:0,
    fail:false,abnormal:false,insufficient:false,lostSend:false,lostPlan:false,multiMaterials:false,
    privateScope:[] as string[],request:null as any,task:null as any};
  const materialSession=()=>({session_id:'99999999-9999-4999-8999-999999999999',title:'我的资料搜索',
    mode:'user',purpose:'material_search',study_date:'2026-10-09',
    scope_mode:state.privateScope.length?'selected':'all',selected_file_ids:state.privateScope});
  const request=()=>({id:rid,status:"draft",source_conversation_id:sid,user_request:"再练两道积分题",
    details:{target_knowledge_node_ids:[node],requested_question_count:2,available_minutes:90},planner_task_id:null,daily_plan_id:null,error_code:null});
  const draft=()=>({task_id:taskId,session_id:study,goal:"补两道积分",budget_minutes:90,status:"ready",trace:[{tool:"find_questions",status:"completed"},{tool:"validate_plan",status:"completed"}],
    metrics:{},message:"建议追加积分选择题2道，确认后加入。",error_code:null,draft_version:"a".repeat(64),
    draft:{questions:[{question_id:qid,kp_id:node,kp_name:"积分",question_type:"single_choice",minutes:3},{question_id:mid,kp_id:node,kp_name:"积分",question_type:"single_choice",minutes:3}],review_minutes:0,review_nodes:[],total_minutes:6,budget_minutes:90,rationale:"根据现有状态和题库",warnings:[]}});
  await page.route("**/api/**",async route=>{
    const path=new URL(route.request().url()).pathname,method=route.request().method();if(!path.startsWith('/api/'))return route.continue();
    if(path==='/api/health')return route.fulfill({json:{status:'ok',database:'connected',retrieval:'ready',worker:'running',llm_configured:true}});
    if(path==='/api/knowledge/tree')return route.fulfill({json:{nodes:[]}});
    if(path==='/api/chat/material-search/session')return route.fulfill({json:materialSession()});
    if(path==='/api/chat/material-search/scope'){
      state.privateScope=route.request().postDataJSON().selected_file_ids;
      return route.fulfill({json:materialSession()});
    }
    if(path==='/api/materials')return route.fulfill({json:{items:[{id:mid,title:'私人笔记',source_type:'user',status:'ready',active_index_version:'v1',original_filename:'笔记.md'},...(state.multiMaterials?[{id:qid,title:'第二份笔记',source_type:'user',status:'ready',active_index_version:'v1',original_filename:'第二份.md'}]:[])],total:state.multiMaterials?2:1,stats:{total:state.multiMaterials?2:1,ready:state.multiMaterials?2:1}}});
    if(path==='/api/plans/today')return route.fulfill({json:state.task?.metrics.commit?{status:'active',plan_id:node,study_date:'2026-10-07',total_count:2,completed_count:0,remaining_minutes:6,estimated_minutes:6,type_summary:{single_choice:2},summary_kps:[],items:[{id:'i1',question_id:qid,kp_id:node,kp_name:'积分',ordinal:1,question_type:'single_choice',stem:'正式题干',options:{A:'1',B:'2'},skill_tags:[],completed:false,is_variant:false,is_review:false,estimated_minutes:3}]}:{status:'setup',study_date:'2026-10-07',recommendations:[]}});
    if(path==='/api/chat/sessions'){
      if(method==='GET')return route.fulfill({json:state.sessions.filter(s=>s.purpose!=='study'&&(!new URL(route.request().url()).searchParams.get('mode')||s.mode===new URL(route.request().url()).searchParams.get('mode')))});
      const body=route.request().postDataJSON();state.creates.push(body);const session={session_id:body.purpose==='study'?study:sid,title:body.title,mode:body.mode,purpose:body.purpose,material_scope_ids:body.material_scope_ids??[]};state.sessions.push(session);return route.fulfill({json:session});
    }
    if(path==='/api/chat/deep-handoffs'){
      state.deep++;const body=route.request().postDataJSON();expect(body.source_session_id).toBe(study);
      state.sessions.push({session_id:deep,title:'深入讲解',mode:'builtin',purpose:'qa'});
      const ctx={...body.study_context,conversation_id:deep,task_id:undefined};
      state.histories.set(deep,[{message_id:mid,role:'assistant',content:'从今日学习继续讨论积分。',status:'completed',citations:[],study_context:ctx}]);
      return route.fulfill({json:{session_id:deep,study_context:ctx}});
    }
    if(path.endsWith('/messages')){const id=path.split('/')[4];return route.fulfill({json:state.histories.get(id)??[]});}
    if(path.endsWith('/answers:stream')){
      const body=route.request().postDataJSON();state.asks.push(body);
      const text='所选资料范围没有足够依据。';
      return route.fulfill({contentType:'text/event-stream',body:frame('meta',{message_id:mid})+
        frame('delta',{text})+frame('citations',{citations:[]})+frame('done',{message_id:mid,answer:text,citations:[]})});
    }
    if(path.endsWith('/assistant:stream')){
      const id=path.split('/')[4],body=route.request().postDataJSON();state.asks.push({id,...body});const history=state.histories.get(id)??[];
      const privateMode=state.sessions.find(s=>s.session_id===id)?.mode==='user';
      const practice=!privateMode&&id!==study&&/练|补.*题|安排/.test(body.question);
      if(practice)state.request=request();
      if(id===study&&body.question.includes('少一点')){state.task=draft();state.task.message='重新校验，只保留一题。';state.task.draft.questions=state.task.draft.questions.slice(0,1);state.task.draft_version='b'.repeat(64);}
      const web=/最新|2027|联网/.test(body.question),builtin=/系统资料/.test(body.question);
      const privateRequest=/我上传.*PDF/.test(body.question);
      const text=privateMode?'所选资料范围没有足够依据。':privateRequest?'请到资料库选择对应私人资料，这里不会自动搜索。':web?'当前未配置联网搜索，无法核验最新内容。':practice?'把练习需求交给奶蛙？':id===study?'先检查条件，不直接给答案。':'通用知识参考：这是学习解释。';
      const citations=builtin?[{label:'C1',chunk_id:node,material_id:mid,material_title:'系统合成讲义',heading_path:['环形队列'],ordinal:0,preview:'count判断队满队空'}]:[];
      history.push({message_id:'u'+state.asks.length,role:'user',content:body.question,status:'completed',citations:[]});
      history.push({message_id:mid,role:'assistant',content:state.fail?'':text,status:state.fail?'failed':'completed',citations,practice_request_id:practice?rid:null});state.histories.set(id,history);
      return route.fulfill({contentType:'text/event-stream',body:frame('meta',{message_id:mid})+(state.fail?frame('error',{code:'generation_failed',message:'模型暂不可用'}):frame('information_source',{source:privateMode?'private_material':web?'web':builtin?'builtin_rag':'general'})+frame('delta',{seq:1,text})+(practice?frame('practice_request',state.request):'')+(id===study&&state.task?frame('planner',state.task):'')+frame('citations',{citations})+(state.abnormal?'':frame('done',{message_id:mid,answer:text,answer_source:privateMode||web||practice?'notice':builtin?'knowledge_base':'general',citations})))});
    }
    if(path==='/api/practice-requests')return route.fulfill({json:state.request&&['pending','planning','proposed','failed','expired'].includes(state.request.status)?[state.request]:[]});
    if(path===`/api/practice-requests/${rid}`)return route.fulfill({json:state.request});
    if(path.endsWith('/send')){state.sends++;state.request.status='pending';return state.lostSend?route.abort('failed'):route.fulfill({json:state.request});}
    if(path.endsWith('/decline')){state.request.status='declined';return route.fulfill({json:state.request});}
    if(path.endsWith('/plan')){expect(route.request().postDataJSON().study_session_id).toBe(study);state.plans++;state.task=draft();state.request.status=state.insufficient?'failed':'proposed';state.request.planner_task_id=taskId;
      if(state.insufficient)state.task={...state.task,status:'needs_info',draft:null,message:'当前正式练习库存不足。'};
      return state.lostPlan?route.abort('failed'):route.fulfill({json:{request:state.request,task:state.task}});}
    if(path===`/api/learning-tasks/${taskId}`)return route.fulfill({json:state.task});
    if(path===`/api/learning-tasks/${taskId}/confirm`){expect(route.request().postDataJSON().draft_version).toBe(state.task.draft_version);state.confirms++;state.task.metrics.commit={plan_id:node,added_count:state.task.draft.questions.length};state.request.status='accepted';return route.fulfill({json:state.task});}
    return route.fulfill({status:404,json:{error:{code:'not_found',message:'未定义隔离夹具'}}});
  });return state;
}
async function ask(page:Page,text:string){await page.locator('#chat-question').fill(text);await page.locator('#chat-question').press('Enter');}
async function practice(page:Page){await page.goto('/chat');await ask(page,'我想再练两道积分题');await expect(page.getByTestId('request-send')).toBeEnabled();}
test('General QA无需模式切换与资料，且无练习需求',async({page})=>{const s=await setup(page);await page.goto('/chat');await expect(page.getByTestId('scope-switch')).toHaveCount(0);await ask(page,'Python async/await为什么存在？');await expect(page.locator('.message-row--assistant')).toContainText('学习解释');expect(s.request).toBeNull();expect(s.plans).toBe(0);});
test('时间敏感问题明确Web不可用，不伪造网络来源',async({page})=>{await setup(page);await page.goto('/chat');await ask(page,'2027考研最新政策');await expect(page.locator('.message-row--assistant')).toContainText('未配置联网搜索');await expect(page.getByText('网络来源',{exact:true})).toHaveCount(0);});
test('资料库就地检索且快捷提问绑定指定文件',async({page})=>{
  const s=await setup(page);await page.goto('/materials');await page.getByRole('button',{name:'针对私人笔记提问'}).click();
  await expect(page).toHaveURL(/\/materials$/);await expect(page.getByTestId('material-search-scope')).toContainText('已限定 1 份');
  await page.getByTestId('material-search-question').fill('这份资料怎么定义极限？');await page.getByTestId('material-search-send').click();
  await expect(page.getByTestId('material-search-assistant')).toContainText('所选资料范围');
  expect(s.privateScope).toEqual([mid]);expect(s.asks[0].question).toBe('这份资料怎么定义极限？');expect(s.creates).toHaveLength(0);
});
test('Today进入深入问答仅建草稿，实际发送后才建立正式QA',async({page})=>{
  const s=await setup(page);await page.goto('/study');await page.getByTestId('study-frog-launcher').click();
  await page.getByTestId('task-goal').fill('给我一点提示');await page.getByTestId('task-arrange').click();
  await expect(page.getByTestId('frog-conversation')).toContainText('检查条件');expect(s.creates).toHaveLength(1);expect(s.creates[0].purpose).toBe('study');
  await page.getByRole('button',{name:'深入问答 ↗'}).click();await expect(page).toHaveURL(/study_draft=/);
  expect(s.deep).toBe(0);expect(s.creates).toHaveLength(1);await expect(page.locator('.message-row')).toHaveCount(0);
  await ask(page,'请详细讲解积分的计算过程');await expect(page).toHaveURL(new RegExp('/chat.*'+deep));
  await expect(page.locator('.message-row--assistant').first()).toContainText('从今日学习');expect(s.deep).toBe(1);
});
test('确认A仅发送，仍可继续QA且不强制跳转',async({page})=>{const s=await setup(page);await practice(page);expect(s.sends).toBe(0);expect(s.plans).toBe(0);await page.getByTestId('request-send').click();await expect(page.getByTestId('practice-request-card')).toContainText('已发送');await expect(page).toHaveURL(/\/chat$/);expect(s.confirms).toBe(0);await ask(page,'再解释一下这个条件');await expect.poll(()=>s.asks.length).toBe(2);expect(s.plans).toBe(0);});
test('需求送达Today，方案等待第二次确认才写卷',async({page})=>{const s=await setup(page);await practice(page);await page.getByTestId('request-send').click();await page.getByRole('link',{name:'去今日学习查看'}).click();await expect(page.getByTestId('request-notification')).toContainText('1 条');await page.getByTestId('study-frog-launcher').click();await page.getByRole('button',{name:'查看安排建议'}).click();await expect(page.getByTestId('task-confirm')).toBeEnabled();expect(s.confirms).toBe(0);expect(s.plans).toBe(1);await page.getByTestId('task-confirm').click();await expect(page.getByTestId('focus-stem')).toHaveText('正式题干');expect(s.confirms).toBe(1);await expect(page.getByTestId('task-confirm')).toHaveCount(0);});
test('合法草案可以修改，重新校验后再确认',async({page})=>{const s=await setup(page);await practice(page);await page.getByTestId('request-send').click();await page.goto('/study');await page.getByTestId('study-frog-launcher').click();await page.getByRole('button',{name:'查看安排建议'}).click();await expect(page.getByTestId('task-confirm')).toBeEnabled();await page.getByTestId('task-goal').fill('少一点');await page.getByTestId('task-arrange').click();await expect(page.getByTestId('task-draft-summary')).toContainText('1 道');expect(s.confirms).toBe(0);});
test('库存不足不假装加题、不生成题',async({page})=>{const s=await setup(page);s.insufficient=true;await practice(page);await page.getByTestId('request-send').click();await page.goto('/study');await page.getByTestId('study-frog-launcher').click();await page.getByRole('button',{name:'查看安排建议'}).click();await expect(page.getByTestId('pending-practice-requests')).toContainText('库存不足');await expect(page.getByTestId('task-confirm')).toHaveCount(0);expect(s.confirms).toBe(0);});
test('用户可以拒绝发送需求，未送达Today',async({page})=>{const s=await setup(page);await practice(page);await page.getByRole('button',{name:'不用',exact:true}).click();await expect(page.getByTestId('practice-request-card')).toContainText('已撤回');expect(s.sends).toBe(0);await page.goto('/study');await expect(page.getByTestId('request-notification')).toHaveCount(0);});
test('流缺少终止帧先读取已保存回复，不回填已发送输入或自动再请求',async({page})=>{const s=await setup(page);s.abnormal=true;await page.goto('/chat');await ask(page,'解释TCP');await expect(page.locator('.message-row--assistant')).toContainText('学习解释');await expect(page.locator('#chat-question')).toHaveValue('');await expect(page.locator('#chat-question')).toBeEnabled();expect(s.asks).toHaveLength(1);await expect(page.getByTestId('chat-turn-recovery')).toHaveCount(0);await expect(page.getByRole('button',{name:'重试这条回复',exact:true})).toHaveCount(0);});
test('学习问答隐藏引用片段和归因信息，后台消息仍保留引用',async({page})=>{
  await setup(page);await page.goto('/chat');await ask(page,'根据系统资料讲解环形队列');
  await expect(page.locator('.message-row--assistant')).toContainText('学习解释');
  await expect(page.locator('.citation-toggle,.citation-card,.attribution-box')).toHaveCount(0);
  await page.reload();await expect(page.locator('.citation-toggle,.citation-card,.attribution-box')).toHaveCount(0);
});
test('主问答请求私人PDF时不自动绑定私人文件',async({page})=>{
  const s=await setup(page);await page.goto('/chat');await ask(page,'我上传的PDF里怎么说？');await expect(page.locator('.message-row--assistant')).toContainText('资料库');
  expect(s.creates[0].mode).toBe('builtin');expect(s.asks[0].study_context.material_id).toBeUndefined();
});
test('可选择多份私人文件，范围绑定在会话而非全库',async({page})=>{
  const s=await setup(page);s.multiMaterials=true;await page.goto('/materials');await page.getByTestId('material-search-scope').click();
  const picker=page.getByTestId('material-search-scope-picker');await picker.getByRole('checkbox').nth(0).check();await picker.getByRole('checkbox').nth(1).check();
  await picker.getByRole('button',{name:'应用范围'}).click();await page.getByTestId('material-search-question').fill('比较这两份资料');
  await page.getByTestId('material-search-send').click();await expect.poll(()=>s.asks.length).toBe(1);
  expect(s.privateScope).toEqual([mid,qid]);expect(s.creates).toHaveLength(0);
});
test('发送响应丢失只读恢复pending，不重复触发Planner',async({page})=>{
  const s=await setup(page);s.lostSend=true;await practice(page);await page.getByTestId('request-send').click();
  await expect(page.getByTestId('practice-request-card')).toContainText('已发送');expect(s.sends).toBe(1);expect(s.plans).toBe(0);expect(s.confirms).toBe(0);
});
test('Planner响应丢失恢复已保存草案，不再次运行',async({page})=>{
  const s=await setup(page);s.lostPlan=true;await practice(page);await page.getByTestId('request-send').click();await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();await page.getByRole('button',{name:'查看安排建议'}).click();await expect(page.getByTestId('task-confirm')).toBeEnabled();expect(s.plans).toBe(1);expect(s.confirms).toBe(0);
});
test('过期需求不给运行按钮，失败需求仅显式重新生成',async({page})=>{
  const s=await setup(page);await practice(page);await page.getByTestId('request-send').click();s.request.status='expired';await page.goto('/study');
  await page.getByTestId('study-frog-launcher').click();await expect(page.getByTestId('pending-practice-requests')).toContainText('过期');
  await expect(page.getByRole('button',{name:'查看安排建议'})).toHaveCount(0);expect(s.plans).toBe(0);
});
