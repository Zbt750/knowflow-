// Browser protocol fixtures: real Vue rendering, no real-model quality claim.
import { test, expect, type Page } from "@playwright/test";
test.setTimeout(30000);
const sid="11111111-1111-4111-8111-111111111111", qa="22222222-2222-4222-8222-222222222222", qb="33333333-3333-4333-8333-333333333333", taskId="44444444-4444-4444-8444-444444444444";
const frame=(event:string,data:unknown)=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
async function setup(page:Page) {
  const history:any[]=[]; const requests:any[]=[]; let confirms=0; let fail=false; let sequence=0;
  let task:any={task_id:taskId,session_id:sid,goal:"补一道题",budget_minutes:90,status:"ready",trace:[],metrics:{},message:"先安排一题",error_code:null,draft_version:"a".repeat(64),
    draft:{questions:[{question_id:qb,kp_id:qa,kp_name:"测试知识点",question_type:"single_choice",minutes:3}],review_minutes:0,review_nodes:[],rationale:"真实方案需确认",warnings:[]}};
  await page.route("**/api/**",async route=>{
    const path=new URL(route.request().url()).pathname;
    if(!path.startsWith("/api/")) return route.continue();
    if(path==="/api/health") return route.fulfill({json:{status:"ok",database:"connected",retrieval:"ready",worker:"running",llm_configured:true}});
    if(path==="/api/materials") return route.fulfill({json:{items:[],total:1,stats:{total:1,ready:1}}});
    if(path==="/api/knowledge/tree") return route.fulfill({json:{nodes:[]}});
    if(path==="/api/plans/today") return route.fulfill({json:{status:"setup",study_date:"2026-10-06",recommendations:[]}});
    if(path==="/api/practice-requests")return route.fulfill({json:[]});
    if(path===`/api/practice-requests/${taskId}`)return route.fulfill({json:{id:taskId,status:'draft',source_conversation_id:sid,user_request:'补一道题',details:{target_knowledge_node_ids:[qa]},planner_task_id:null}});
    if(path===`/api/practice-requests/${taskId}/send`)return route.fulfill({json:{id:taskId,status:'pending',source_conversation_id:sid,user_request:'补一道题',details:{target_knowledge_node_ids:[qa]},planner_task_id:null}});
    if(path==="/api/chat/sessions") return route.fulfill({json:route.request().method()==="POST"?{session_id:sid,title:"测试会话",mode:"builtin"}:[{session_id:sid,title:"测试会话",mode:"builtin"},{session_id:qb,title:'深入会话',mode:'builtin'}]});
    if(path==='/api/chat/deep-handoffs'){
      history.splice(0,history.length,{message_id:qa,role:'assistant',content:'从今日学习继续讨论知识点。',status:'completed',citations:[]});
      return route.fulfill({json:{session_id:qb,study_context:{surface:'chat',origin:'conversation'}}});
    }
    if(path.endsWith("/messages")) return route.fulfill({json:history});
    if(path.endsWith("/assistant:stream")) {
      const body=route.request().postDataJSON(); requests.push(body); const mid=sequence++===0?qa:qb;
      if(!body.retry_of_message_id) history.push({message_id:`u${sequence}`,role:"user",content:body.question,status:"completed",citations:[],matched_kp_id:null});
      const planning=body.question.includes("补一道");
      const text=fail?"":"这是当前学习问题的回复。";
      history.push({message_id:mid,role:"assistant",content:text,status:fail?"failed":"completed",citations:[],matched_kp_id:null,study_context:body.study_context,qa_action:body.qa_action,practice_request_id:planning?taskId:null});
      const sse=frame("route",{capability:planning?"planner":"qa"})+frame("meta",{message_id:mid})+
        (fail?frame("error",{code:"generation_failed",message:"测试模型暂不可用"}):frame("delta",{seq:1,text})+(planning?frame("practice_request",{id:taskId}):"")+frame("citations",{citations:[]})+frame("done",{message_id:mid,answer:text,citations:[]}));
      return route.fulfill({contentType:"text/event-stream",body:sse});
    }
    if(path===`/api/learning-tasks/${taskId}`) return route.fulfill({json:task});
    if(path===`/api/learning-tasks/${taskId}/confirm`) {confirms++;task={...task,metrics:{commit:{added_count:1}}};return route.fulfill({json:task});}
    return route.fulfill({status:404,json:{error:{code:"not_found",message:"未定义协议夹具"}}});
  });
  return {history,requests,get confirms(){return confirms;},set fail(value:boolean){fail=value;}};
}

test("重开正式问答恢复最新学习位置，显式退出后刷新不恢复旧题",async({page})=>{
  const s=await setup(page);
  s.history.push({message_id:qa,role:"assistant",content:"之前的题目讲解",status:"completed",citations:[],
    study_context:{version:"study-context-v1",surface:"chat",origin:"conversation",conversation_id:sid,question_id:qa,knowledge_node_ids:[qb]}});
  await page.goto(`/chat?session_id=${sid}`);
  await expect(page).toHaveURL(new RegExp(`question_id=${qa}`));
  await page.locator("#chat-question").fill("这题条件是什么意思？");await page.locator(".send-button").click();
  await expect.poll(()=>s.requests.length).toBe(1);expect(s.requests[0].study_context.question_id).toBe(qa);
  await expect(page.locator(".message-row--assistant").last()).toContainText("当前学习问题的回复");
  await page.getByRole("button",{name:"退出题目上下文"}).click();await page.reload();
  await expect(page.getByRole("button",{name:"退出题目上下文"})).toHaveCount(0);
});

test("同一conversation切换题目时传递新的StudyContext和提示动作",async({page})=>{
  const state=await setup(page); await page.goto(`/chat?session_id=${sid}&question_id=${qa}`);
  await page.getByRole("button",{name:"一点提示",exact:true}).click();
  await expect.poll(()=>state.requests.length).toBe(1);
  expect(state.requests[0].qa_action).toBe("hint_1");expect(state.requests[0].study_context.question_id).toBe(qa);
  await expect(page.locator(".message-row--assistant")).toContainText("当前学习问题");
  await page.goto(`/chat?session_id=${sid}&question_id=${qb}`);
  await page.getByRole("button",{name:"下一步",exact:true}).click();
  await expect.poll(()=>state.requests.length).toBe(2);
  expect(state.requests[1].study_context.question_id).toBe(qb);expect(state.requests[1].study_context.conversation_id).toBe(sid);
});

test("正式QA只确认发送需求，不直接确认DailyPlan",async({page})=>{
  const state=await setup(page);await page.goto(`/chat?session_id=${sid}&question_id=${qa}`);
  await page.locator("#chat-question").fill("给我补一道这种题");await page.locator("#chat-question").press("Enter");
  await expect(page.getByTestId("practice-request-card")).toContainText("奶蛙");expect(state.confirms).toBe(0);
  await page.getByRole("button",{name:"发送给奶蛙",exact:true}).click();
  await expect(page.getByTestId("practice-request-card")).toContainText("已发送给奶蛙");expect(state.confirms).toBe(0);
  await expect(page.getByRole("button",{name:"确认加入今日学习",exact:true})).toHaveCount(0);
});

test("失败保留输入，显式重试带原message和StudyContext",async({page})=>{
  const state=await setup(page);state.fail=true;await page.goto(`/chat?session_id=${sid}&question_id=${qa}`);
  await page.locator("#chat-question").fill("这题考什么？");await page.locator("#chat-question").press("Enter");
  await expect(page.getByRole("button",{name:"重试这条回复"})).toBeVisible();await expect(page.locator("#chat-question")).toHaveValue("这题考什么？");
  state.fail=false;await page.getByRole("button",{name:"重试这条回复"}).click();
  await expect.poll(()=>state.requests.length).toBe(2);expect(state.requests[1].retry_of_message_id).toBe(qa);expect(state.requests[1].study_context.question_id).toBe(qa);
  expect(state.history.filter(m=>m.role==="user")).toHaveLength(1);
});

test("今日学习显式深入后新建正式conversation，不复制日内raw history",async({page})=>{
  const state=await setup(page);await page.goto("/study");await page.getByTestId("study-frog-launcher").click();
  await page.getByTestId("task-goal").fill("解释一下洛必达法则");await page.getByTestId("task-arrange").click();
  await expect(page.getByTestId("frog-conversation")).toContainText("当前学习问题");
  await page.getByRole("button",{name:"深入问答 ↗"}).click();await expect(page).toHaveURL(new RegExp(`/chat\\?session_id=${qb}`));
  await expect(page.locator(".message-row--assistant")).toContainText("从今日学习继续");
  await page.locator("#chat-question").fill("我还是不懂这个条件");await page.locator("#chat-question").press("Enter");
  await expect.poll(()=>state.requests.length).toBe(2);expect(state.requests[1].study_context.conversation_id).toBe(qb);
});

test("正式QA练习需求保留当前位置而不出现直接加题按钮",async({page})=>{
  const state=await setup(page);await page.goto(`/chat?session_id=${sid}&question_id=${qa}`);
  await page.locator("#chat-question").fill("给我补一道这种题");await page.locator("#chat-question").press("Enter");
  await expect(page.getByTestId('request-send')).toBeEnabled();
  expect(state.requests[0].study_context.question_id).toBe(qa);
  expect(state.requests[0].study_context.conversation_id).toBe(sid);
  await expect(page.getByRole('button',{name:'确认加入今日学习',exact:true})).toHaveCount(0);
  expect(state.confirms).toBe(0);
});
