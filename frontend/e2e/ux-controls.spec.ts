import { test, expect, type Page } from '@playwright/test';
test.setTimeout(30000);

// UI协议夹具；真正的核验、判题与证据隔离由后端独立PG测试覆盖。
const sid='11111111-1111-4111-8111-111111111111';
const rootId='22222222-2222-4222-8222-222222222222';
const chapterId='33333333-3333-4333-8333-333333333333';
const leafId='44444444-4444-4444-8444-444444444444';
function node(id:string,code:string,name:string,children:any[]=[]) {
  return {id,code,name,children,subject:'考研数学',state:'unseen',is_active:true,is_assessable:!children.length,
    is_reference_only:false,online_question_count:0,practice_eligible_question_count:0,
    gap_items:[],required_question_types:{},excluded_question_types:[],required_skill_tags:[]};
}
async function install(page:Page) {
  const leaf=node(leafId,'math.leaf','隐函数求导');
  const chapter=node(chapterId,'math.chapter','微分学',[leaf]);
  const root=node(rootId,'math.root','数学二',[chapter]);
  const all=[root,chapter,leaf];
  const history:any[]=[];
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(!path.startsWith('/api/'))return route.continue();
    if(path==='/api/health')return route.fulfill({json:{status:'ok',database:'connected'}});
    if(path==='/api/materials')return route.fulfill({json:{items:[],total:0,stats:{total:0,ready:0}}});
    if(path==='/api/knowledge/tree')return route.fulfill({json:{nodes:[root]}});
    if(path.startsWith('/api/knowledge/')){
      const selected=all.find(item=>item.id===path.split('/')[3]);
      return route.fulfill({json:{node:selected,questions:[],attempts:[],exam_references:[],lesson_available:false,materials_ready:false,capability_profile:null}});
    }
    if(path==='/api/chat/sessions')return route.fulfill({json:route.request().method==='POST'?{session_id:sid,mode:'builtin',purpose:'qa',title:'排版'}:[]});
    if(path.endsWith('/messages'))return route.fulfill({json:history});
    if(path.endsWith('/assistant:stream')){
      const answer='曲率半径为：\n\n```math\nR=\\frac{5\\sqrt{10}}{2}\n```\n\n继续按条件推导即可 [C1]。';
      const data={message_id:leafId,role:'assistant',content:answer,status:'completed',
        citations:[{label:'C1',chunk_id:leafId,material_id:chapterId,material_title:'合成资料',heading_path:[],ordinal:0,preview:'不应展示的片段'}]};
      history.push(data);
      const frame=(event:string,data:unknown)=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
      return route.fulfill({contentType:'text/event-stream',body:frame('meta',{message_id:leafId})+frame('delta',{text:answer})+frame('citations',{citations:data.citations})+frame('done',{answer,status:'completed'})});
    }
    return route.fulfill({json:[]});
  });
}
test('点击章节名称可反复展开收起，叶子可以打开详情',async({page},testInfo)=>{
  await install(page);await page.goto('/knowledge');
  const chapter=page.getByTestId('tree-node-math.chapter');
  await expect(chapter).toBeVisible();await expect(page.getByTestId('tree-node-math.leaf')).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath('knowledge-overview.png'),fullPage:true});
  await chapter.click();await expect(page.getByTestId('tree-node-math.leaf')).toBeVisible();
  await chapter.click();await expect(page.getByTestId('tree-node-math.leaf')).toHaveCount(0);
  await page.getByTestId(`tree-joint-${chapterId}`).click();
  await expect(page.getByTestId('tree-node-math.leaf')).toBeVisible();
  await page.getByTestId(`tree-joint-${chapterId}`).click();
  await expect(page.getByTestId('tree-node-math.leaf')).toHaveCount(0);
  await chapter.click();await page.getByTestId('tree-node-math.leaf').click();
  await expect(page).toHaveURL(/node=math.leaf/);
  await expect(page.locator('.detail')).toContainText('隐函数求导');
  await expect(page.getByRole('button',{name:'放大',exact:true})).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath('knowledge-expanded.png'),fullPage:true});
});
test('math围栏正确渲染，问答页不再展示引用片段或编号',async({page},testInfo)=>{
  await install(page);await page.goto('/chat');
  await page.locator('#chat-question').fill('请解释曲率半径的计算');await page.locator('.send-button').click();
  const reply=page.locator('.message-row--assistant');
  await expect(reply.locator('.katex-display')).toBeVisible();
  await expect(reply.locator('pre')).toHaveCount(0);
  await expect(reply.locator('.citation-box,.citation-card,.attribution-box')).toHaveCount(0);
  await expect(reply).not.toContainText('[C1]');await expect(reply).not.toContainText('不应展示的片段');
  await expect(reply.locator('.assistant-message-heading .study-mascot')).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('chat-clean-math.png'),fullPage:true});
});
