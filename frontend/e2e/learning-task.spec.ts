// Existing LearningTask UX regression adapted to Phase 4 assistant transport.
// Real Vue + stateful protocol fixtures; no real-model quality claim.
import { test, expect, type Page } from "@playwright/test";
test.setTimeout(30000);
const id="11111111-1111-4111-8111-111111111111", sid="22222222-2222-4222-8222-222222222222";
const frame=(event:string,data:unknown)=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const view=(status="created")=>({task_id:id,session_id:sid,goal:"洛必达比较弱",budget_minutes:90,status,trace:[],draft:null,message:"",error_code:null,metrics:{}} as any);
const ready=()=>({...view("ready"),message:"先检查适用条件。",draft_version:"a".repeat(64),trace:[{tool:"find_questions",status:"completed"}],
  draft:{total_minutes:3,budget_minutes:90,can_commit:true,review_minutes:0,review_nodes:[],
    questions:[{question_id:"q1",kp_id:"kp1",kp_name:"洛必达法则",question_type:"single_choice",stem:"不应展开的题干",minutes:3}],rationale:"先检查适用条件",warnings:[]}});
async function setup(page:Page){
  const s={task:view(),history:[] as any[],requests:[] as any[],confirms:0,reads:0,planReads:0,
    failReads:false,lostConfirm:false,lostStream:false,failTurn:false,streamDelay:0,readDelay:0,
    activeReads:0,maxReads:0,failedReads:0,staleRead:false,autoReadyAfter:0,warnings:[] as string[]};
  await page.route("**/api/**",async route=>{
    const path=new URL(route.request().url()).pathname;
    if(!path.startsWith("/api/")) return route.continue();
    if(path==="/api/health") return route.fulfill({json:{status:"ok",database:"connected",retrieval:"ready",worker:"running",llm_configured:true}});
    if(path==="/api/materials") return route.fulfill({json:{items:[],total:0,stats:{total:0,ready:0}}});
    if(path==="/api/knowledge/tree") return route.fulfill({json:{nodes:[]}});
    if(path==="/api/practice-requests")return route.fulfill({json:[]});
    if(path==="/api/plans/today"){
      if(!s.task.metrics.commit) return route.fulfill({json:{status:"setup",study_date:"2026-10-06",recommendations:[]}});
      s.planReads++;
      return route.fulfill({json:{status:"active",plan_id:id,study_date:"2026-10-06",total_count:1,completed_count:0,remaining_minutes:3,estimated_minutes:3,type_summary:{fill_blank:1},summary_kps:[],
        items:[{id:"arranged-item",question_id:"q1",ordinal:1,kp_id:"kp1",kp_name:"洛必达法则",question_type:"fill_blank",stem:"安排后的练习题",skill_tags:[],options:null,completed:false,is_variant:false,is_review:false,estimated_minutes:3}]}});
    }
    if(path==="/api/chat/sessions") return route.fulfill({json:route.request().method()==="POST"?{session_id:sid,title:"测试会话",mode:"builtin"}:[{session_id:sid,title:"测试会话",mode:"builtin"}]});
    if(path.endsWith("/messages")) return route.fulfill({json:s.history});
    if(path.endsWith("/assistant:stream")){
      const body=route.request().postDataJSON();s.requests.push(body);const seq=s.requests.length;
      s.task={...view("running"),goal:body.question};
      const prefix=frame("meta",{message_id:`m${seq}`,task_id:id});
      s.history.push({message_id:`u${seq}`,role:"user",content:body.question,status:"completed",citations:[]});
      if(s.lostStream){s.task=s.autoReadyAfter?{...view("running"),goal:body.question}:{...ready(),goal:body.question};return route.fulfill({contentType:"text/event-stream",body:prefix});}
      if(s.streamDelay) await new Promise(resolve=>setTimeout(resolve,s.streamDelay));
      if(s.task.status==="cancelled") return route.fulfill({contentType:"text/event-stream",body:prefix+frame("planner",ready())});
      s.task=s.failTurn?{...view("failed"),goal:body.question,message:"安排未完成，可修改要求重试。"}:{...ready(),goal:body.question,
        message:seq===1?"先练基础题。":"已减少题量，只保留选择题。",draft_version:String(seq).repeat(64)};
      if(s.task.draft) s.task.draft.warnings=s.warnings;
      s.history.push({message_id:`m${seq}`,role:"assistant",content:s.task.message,status:s.failTurn?"failed":"completed",citations:[],planner_task_id:id});
      return route.fulfill({contentType:"text/event-stream",body:prefix+frame("delta",{seq:1,text:s.task.message})+frame("planner",s.task)+
        (s.failTurn?frame("error",{message:"安排未完成，可修改要求重试。"}):frame("done",{answer:s.task.message,citations:[]}))});
    }
    if(path===`/api/learning-tasks/${id}`){
      s.reads++;s.activeReads++;s.maxReads=Math.max(s.maxReads,s.activeReads);
      const snapshot={...s.task};
      try{if(s.readDelay) await new Promise(resolve=>setTimeout(resolve,s.readDelay));if(s.failReads){s.failedReads++;return await route.abort("failed");}
        if(s.autoReadyAfter&&s.reads>=s.autoReadyAfter) s.task=ready();return await route.fulfill({json:s.staleRead?snapshot:s.task});
      }finally{s.activeReads--;}
    }
    if(path===`/api/learning-tasks/${id}/confirm`){expect(route.request().postDataJSON().draft_version).toBe(s.task.draft_version);
      s.confirms++;s.task={...s.task,metrics:{commit:{plan_id:id,added_count:1}}};return s.lostConfirm?route.abort("failed"):route.fulfill({json:s.task});}
    if(path===`/api/learning-tasks/${id}/cancel`){s.task={...view("cancelled"),message:"已取消，没有写入今日学习。"};return route.fulfill({json:s.task});}
    return route.fulfill({status:404,json:{error:{code:"not_found",message:"未定义夹具"}}});
  });return s;
}
async function open(page:Page){await page.goto("/study");await page.getByTestId("study-frog-launcher").click();}
async function send(page:Page,text="洛必达比较弱"){await page.getByTestId("task-goal").fill(text);await page.getByTestId("task-arrange").click();}
test("奶蛙连续调整同一任务，收起重开不重新调用",async({page})=>{
  const s=await setup(page);await open(page);await send(page);await expect(page.getByTestId("task-confirm")).toBeEnabled();
  await send(page,"少一点，只做选择题");await expect(page.getByTestId("frog-conversation")).toContainText("已减少题量");expect(s.requests[1].study_context.task_id).toBe(id);
  await page.getByRole("button",{name:"收起奶蛙对话"}).click();await page.getByTestId("study-frog-launcher").click();
  await expect(page.getByTestId("frog-message-user")).toHaveCount(2);expect(s.requests).toHaveLength(2);
  expect(await page.getByRole("region",{name:"奶蛙学习助手对话"}).evaluate(el=>el.getBoundingClientRect().width)).toBeLessThanOrEqual(680);
});
for(const lost of [false,true]) test(`确认后原地显示新卷${lost?"，响应丢失恢复回执":""}`,async({page})=>{
  const s=await setup(page);s.lostConfirm=lost;await open(page);await send(page);await expect(page.getByTestId("task-confirm")).toBeEnabled();expect(s.planReads).toBe(0);expect(s.confirms).toBe(0);
  await page.getByTestId("task-confirm").click();await expect(page.getByTestId("focus-stem")).toHaveText("安排后的练习题");
  await expect(page.getByTestId("study-frog-launcher").locator("img")).toHaveAttribute("src",/study-frog-prone/);await expect(page.getByTestId("task-confirm")).toHaveCount(0);expect(s.confirms).toBe(1);
});
test("草案保留证据边界提醒，不自动写卷",async({page})=>{
  const s=await setup(page);s.warnings=["AI参考答案不等于可靠毕业证据。"];
  await open(page);await send(page);await expect(page.getByTestId("task-result")).toContainText(s.warnings[0]);await expect(page.getByTestId("task-result")).toContainText("尚未加入今日学习");expect(s.confirms).toBe(0);
});
test("编辑新要求时禁止确认旧草案",async({page})=>{
  await setup(page);await open(page);await send(page);await expect(page.getByTestId("task-confirm")).toBeEnabled();
  await page.getByTestId("task-goal").fill("只做填空题");await expect(page.getByTestId("task-confirm")).toBeDisabled();await page.getByTestId("task-goal").fill("");await expect(page.getByTestId("task-confirm")).toBeEnabled();
});
test("安排入口默认收起，问答页不重复显示宠物面板",async({page})=>{
  await setup(page);await page.goto("/study");await expect(page.getByTestId("task-goal")).not.toBeVisible();await page.goto("/chat");await expect(page.getByTestId("learning-task-panel")).toHaveCount(0);
});
test("草案默认摘要，刷新恢复原任务及会话，不重新调用",async({page})=>{
  const s=await setup(page);await open(page);await send(page);await expect(page.getByTestId("task-draft-summary")).toContainText("洛必达法则");await expect(page.getByTestId("task-result")).not.toContainText("不应展开的题干");
  await page.getByText("查看安排步骤",{exact:true}).click();await expect(page.getByTestId("task-result")).toContainText("查找可练题 · 完成");
  await page.reload();await page.getByTestId("study-frog-launcher").click();await expect(page.getByTestId("task-confirm")).toBeEnabled();await expect(page.getByTestId("frog-message-user")).toHaveCount(1);expect(s.requests).toHaveLength(1);expect(s.confirms).toBe(0);
});
test("运行失败保留目标，修改要求后可以重试",async({page})=>{
  const s=await setup(page);s.failTurn=true;await open(page);await send(page);await expect(page.getByTestId("task-goal")).toHaveValue("洛必达比较弱");await expect(page.getByTestId("task-result")).toContainText("本次未完成");
  s.failTurn=false;await send(page,"改成基础题");await expect(page.getByTestId("task-confirm")).toBeEnabled();expect(s.requests[1].question).toBe("改成基础题");
});
test("恢复运行任务后可取消，迟到读取不能覆盖取消状态",async({page})=>{
  const s=await setup(page);s.task=view("running");
  await page.addInitScript(([taskId,session])=>{const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());localStorage.setItem(`learning-task:study:${day}`,taskId);localStorage.setItem(`learning-assistant:study:${day}`,session);},[id,sid]);
  await open(page);await expect(page.getByTestId("task-cancel")).toBeVisible();await page.getByTestId("task-cancel").click();
  await expect(page.getByTestId("task-result")).toContainText("已取消");
  await page.getByTestId("task-goal").fill("再安排基础题");await expect(page.getByTestId("task-arrange")).toBeEnabled();expect(s.confirms).toBe(0);
});
test("流响应丢失只读恢复草案，刷新保留未保存目标",async({page})=>{
  const s=await setup(page);s.lostStream=true;await open(page);await send(page);await expect(page.getByTestId("task-confirm")).toBeEnabled();
  await page.getByTestId("task-goal").fill("只做填空题");await page.getByTestId("task-refresh").click();await expect(page.getByTestId("task-goal")).toHaveValue("只做填空题");await expect(page.getByTestId("task-confirm")).toBeDisabled();expect(s.requests).toHaveLength(1);
});
test("恢复读取失败，手动恢复不重新运行",async({page})=>{
  const s=await setup(page);s.task=view("running");s.failReads=true;
  await page.addInitScript(([taskId,session])=>{const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());localStorage.setItem(`learning-task:study:${day}`,taskId);localStorage.setItem(`learning-assistant:study:${day}`,session);},[id,sid]);
  await open(page);await expect(page.getByRole("alert")).toContainText("上次学习任务暂时无法读取");s.failReads=false;s.task=ready();await page.getByTestId("task-refresh").click();await expect(page.getByTestId("task-confirm")).toBeEnabled();expect(s.requests).toHaveLength(0);
});
test("慢进度请求串行读取，不重叠且可恢复最终草案",async({page})=>{
  const s=await setup(page);s.lostStream=true;s.autoReadyAfter=3;s.readDelay=1800;await open(page);await send(page);
  await expect(page.getByTestId("task-confirm")).toBeEnabled({timeout:20000});expect(s.maxReads).toBe(1);expect(s.reads).toBe(3);expect(s.requests).toHaveLength(1);
});
test("取消后迟到的旧进度读取不会覆盖已取消状态",async({page})=>{
  const s=await setup(page);s.task=view("running");
  await page.addInitScript(([taskId,session])=>{const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());localStorage.setItem(`learning-task:study:${day}`,taskId);localStorage.setItem(`learning-assistant:study:${day}`,session);},[id,sid]);
  await open(page);await expect(page.getByTestId("task-cancel")).toBeVisible();s.readDelay=2500;s.staleRead=true;
  await expect.poll(()=>s.activeReads).toBe(1);await page.getByTestId("task-cancel").click();
  await expect(page.getByTestId("task-result")).toContainText("已取消");await expect.poll(()=>s.activeReads).toBe(0);
  await expect(page.getByTestId("task-result")).toContainText("已取消");expect(s.confirms).toBe(0);
});
test("轮询连续三次失败停止，手动只读恢复",async({page})=>{
  const s=await setup(page);s.task=view("running");
  await page.addInitScript(([taskId,session])=>{const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());localStorage.setItem(`learning-task:study:${day}`,taskId);localStorage.setItem(`learning-assistant:study:${day}`,session);},[id,sid]);
  await open(page);await expect(page.getByTestId("task-cancel")).toBeVisible();s.failReads=true;
  await expect(page.getByRole("alert")).toContainText("暂时无法读取进度",{timeout:15000});expect(s.failedReads).toBe(3);
  const reads=s.reads;await page.waitForTimeout(1800);expect(s.reads).toBe(reads);
  s.failReads=false;s.task=ready();await page.getByTestId("task-refresh").click();await expect(page.getByTestId("task-confirm")).toBeEnabled();expect(s.requests).toHaveLength(0);
});
