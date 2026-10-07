import { test, expect, type Page } from "@playwright/test";

const A="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", B="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", S="cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const file=(id:string,title:string,status="ready")=>({id,title,status,source_type:"user",active_index_version:status==="ready"?"v1":null,original_filename:`${title}.md`,created_at:"2026-10-07T00:00:00Z",updated_at:"2026-10-07T00:00:00Z",last_error_code:null,file_size:50});
async function install(page:Page, empty=false) {
  let current={session_id:S,title:"我的资料搜索",mode:"user",purpose:"material_search",study_date:"2026-10-07",scope_mode:"all",selected_file_ids:[] as string[]};
  let messages:Array<Record<string,unknown>>=[];
  let files=empty?[]:[file(A,"相似笔记"),file(B,"合同笔记"),file("dddddddd-dddd-4ddd-8ddd-dddddddddddd","处理中","indexing")];
  let calls=0;
  let fail=false;
  let sourceDeleted=false;
  await page.route(/\/api\//,async route=>{
    const url=new URL(route.request().url());const method=route.request().method();
    if(url.pathname==="/api/health")return route.fulfill({json:{status:"ok",database:"connected"}});
    if(url.pathname==="/api/chat/material-search/session")return route.fulfill({json:current});
    if(url.pathname==="/api/chat/material-search/scope") {
      const body=route.request().postDataJSON();current={...current,scope_mode:body.scope_mode,selected_file_ids:body.selected_file_ids};
      return route.fulfill({json:current});
    }
    if(url.pathname.endsWith("/messages"))return route.fulfill({json:messages});
    if(url.pathname.endsWith("/answers:stream")) {
      calls++;const query=route.request().postDataJSON().question;
      const answer=empty?"目前还没有可检索的个人资料，请先上传并完成索引。":"你的笔记说明需要可逆矩阵 [C1]。";
      const citations=empty?[]:[{label:"C1",chunk_id:B,material_id:A,material_title:"相似笔记",heading_path:["相似条件"],ordinal:0,preview:"可逆矩阵"}];
      messages.push({message_id:crypto.randomUUID(),role:"user",content:query,status:"completed",citations:[],matched_kp_id:null});
      const reply={message_id:crypto.randomUUID(),role:"assistant",content:answer,status:"completed",citations,matched_kp_id:null};messages.push(reply);
      await new Promise(resolve=>setTimeout(resolve,120));
      const frame=(event:string,data:unknown)=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
      return route.fulfill({contentType:"text/event-stream",body:fail?frame("error",{message:"索引暂时不可用",code:"retrieval_unavailable"}):frame("meta",{message_id:reply.message_id})+frame("delta",{text:answer})+frame("citations",{citations})+frame("done",{message_id:reply.message_id,answer,citations})});
    }
    if(url.pathname==="/api/materials")return route.fulfill({json:{items:files,total:files.length,stats:{total:files.length,ready:empty?0:2}}});
    if(url.pathname===`/api/materials/${A}`&&sourceDeleted)return route.fulfill({status:404,json:{error:{code:"material_not_found",message:"资料已删除"}}});
    if(url.pathname.endsWith("/chunks"))return route.fulfill({json:{items:[{id:B,ordinal:0,heading_path:["相似条件"],preview:"可逆矩阵",char_count:5}],total:1}});
    if(url.pathname.endsWith("/content"))return route.fulfill({json:{title:"相似笔记",text:"# 相似条件\n需要可逆矩阵。"}});
    if(url.pathname.startsWith("/api/materials/")) {
      const id=url.pathname.split("/").at(-1);
      if(method==="DELETE") {files=files.filter(f=>f.id!==id);messages=messages.map(m=>({...m,citations:[]}));return route.fulfill({status:204});}
      return route.fulfill({json:{...files.find(f=>f.id===id),chunk_count:1,latest_job:null}});
    }
    return route.fulfill({json:[]});
  });
  return {calls:()=>calls,fail:()=>{fail=true;},deleteSource:()=>{sourceDeleted=true;},nextDay:()=>{current={...current,session_id:crypto.randomUUID(),study_date:"2026-10-08",scope_mode:"all",selected_file_ids:[]};messages=[];}};
}

test("default all, Enter submission, no duplicate while loading, same-day restore",async({page})=>{
  const state=await install(page);await page.goto("/materials");
  await expect(page.getByTestId("material-search-scope")).toHaveText(/全部资料/);
  await page.getByTestId("material-search-question").fill("矩阵相似的条件是什么？");
  await expect(page.getByTestId("material-search-send")).toBeEnabled();
  await page.getByTestId("material-search-question").press("Enter");
  await expect(page.getByTestId("material-search-assistant")).toContainText("可逆矩阵");
  expect(state.calls()).toBe(1);
  await page.reload();await expect(page.getByTestId("material-search-user")).toContainText("矩阵相似");
  await expect(page.getByTestId("material-search-assistant")).toContainText("可逆矩阵");
  await page.getByTestId("material-search-question").fill("那它和合同有什么区别？");await page.getByTestId("material-search-send").click();
  await expect(page.getByTestId("material-search-assistant")).toHaveCount(2);expect(state.calls()).toBe(2);
});

test("optional scope, processing disabled, clear back to all, file-specific shortcut",async({page})=>{
  await install(page);await page.goto("/materials");await page.getByTestId("material-search-scope").click();
  const picker=page.getByTestId("material-search-scope-picker");await expect(picker.getByRole("checkbox").nth(2)).toBeDisabled();
  await picker.getByRole("checkbox").first().check();await picker.getByRole("button",{name:"应用范围"}).click();
  await expect(page.getByTestId("material-search-scope")).toContainText("已限定 1 份");
  await page.getByTestId("material-search-scope").click();await picker.getByRole("button",{name:"全部资料",exact:true}).click();
  await expect(page.getByTestId("material-search-scope")).toContainText("全部资料");
  await page.getByRole("button",{name:"针对合同笔记提问"}).click();await expect(page.getByTestId("material-search-scope")).toContainText("已限定 1 份");
});

test("sources collapsed by default, locator works, deleted source handled",async({page})=>{
  const state=await install(page);await page.goto("/materials");await page.getByTestId("material-search-question").fill("相似是什么？");await page.getByTestId("material-search-send").click();
  const source=page.getByTestId("material-search-assistant").locator("details");await expect(source).not.toHaveAttribute("open");
  await source.locator("summary").click();await source.getByRole("button").click();
  await expect(page.getByTestId("material-reader")).toBeVisible();await page.getByRole("button",{name:"关闭资料"}).click();
  state.deleteSource();await source.getByRole("button").click();await expect(source).toContainText("来源已删除");
});

test("empty corpus allows asking and exposes upload; errors remain recoverable",async({page})=>{
  const state=await install(page,true);await page.goto("/materials");await page.getByTestId("material-search-question").fill("红黑树怎么解释？");await page.getByTestId("material-search-send").click();
  await expect(page.getByTestId("material-search-assistant")).toContainText("还没有可检索的个人资料");
  await expect(page.getByTestId("material-search-assistant").getByRole("button",{name:"添加资料"})).toBeVisible();
  state.fail();await page.getByTestId("material-search-question").fill("再找一次");await page.getByTestId("material-search-send").click();
  await expect(page.getByTestId("material-search-error")).toContainText("索引暂时不可用");
  await expect(page.getByTestId("material-search-question")).toBeEnabled();
});

test("new daily session replaces old displayed context while files remain",async({page})=>{
  const state=await install(page);await page.goto("/materials");await page.getByTestId("material-search-question").fill("矩阵相似");await page.getByTestId("material-search-send").click();
  await expect(page.getByTestId("material-search-assistant")).toContainText("可逆矩阵");state.nextDay();await page.reload();
  await expect(page.getByTestId("material-search-user")).toHaveCount(0);await expect(page.getByTestId("material-list")).toContainText("相似笔记");
  await expect(page.getByTestId("material-search-scope")).toContainText("全部资料");
});

test("legacy file link applies once; restoring all survives refresh",async({page})=>{
  await install(page);await page.goto(`/materials/qa?material_id=${A}`);
  await expect(page.getByTestId("material-search-scope")).toContainText("已限定 1 份");
  await expect(page).toHaveURL(/\/materials$/);
  await page.getByTestId("material-search-scope").click();await page.getByTestId("material-search-scope-picker").getByRole("button",{name:"全部资料",exact:true}).click();
  await page.reload();await expect(page.getByTestId("material-search-scope")).toContainText("全部资料");
});
