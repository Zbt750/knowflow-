import {test,expect,type Page} from '@playwright/test';
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
function node(n:number,code:string,name:string,children:any[]=[]):any{return {id:id(n),code,name,children,subject:code.startsWith('cs')?'408':'数学二',
  ordinal:n,is_assessable:children.length===0,is_reference_only:false,state:children.length?null:'unseen',
  practice_eligible_question_count:children.length?0:3,required_question_types:{},required_skill_tags:[],excluded_question_types:[],gap_items:[]};}
const leaf=node(5,'math.curvature','曲率与曲率半径：隐函数连续求导及长知识点名称换行验证');
const roots=[
  node(10,'cs408','408 计算机学科专业基础',[node(11,'cs.ds','数据结构',[node(12,'cs.tree','树与二叉树',[node(13,'cs.binary','二叉树遍历与存储结构')])])]),
  node(1,'math.calculus','高等数学',[node(3,'math.derivatives','导数与微分',[node(4,'math.implicit','隐函数求导',[leaf])])]),
  node(6,'math.linear-algebra','线性代数',[node(7,'math.matrix','矩阵与线性方程组')]),
];
const nodes=roots.flatMap(function flatten(n):any[]{return [n,...n.children.flatMap(flatten)];});
const title=(page:Page,code:string)=>page.getByTestId(`tree-node-${code}`);
const row=(page:Page,code:string)=>title(page,code).locator('xpath=../..');
let writes:any[]=[];let unexpected:string[]=[];
test.beforeEach(async({page})=>{
  writes=[];unexpected=[];
  await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(request.method()!=='GET')writes.push({path,body:request.postDataJSON()});
    if(path==='/api/health')return route.fulfill({json:{status:'ok',database:'connected'}});
    if(path.startsWith('/api/settings/'))return route.fulfill({status:403,json:{error:{code:'settings_local_only',message:'隔离导航测试不读取模型设置'}}});
    if(path==='/api/knowledge/tree')return route.fulfill({json:{nodes:roots}});
    if(path==='/api/plans/today')return route.fulfill({json:{status:'setup',recommendations:[]}});
    if(path==='/api/materials')return route.fulfill({json:{items:[],total:0}});
    if(path==='/api/chat/sessions' && request.method()==='GET')return route.fulfill({json:[{session_id:id(90),mode:'builtin',purpose:'qa',title:'另一节点的历史出题确认',updated_at:new Date().toISOString()}]});
    if(path==='/api/chat/sessions' && request.method()==='POST')return route.fulfill({json:{session_id:id(91),mode:'builtin',purpose:'qa'}});
    if(path.endsWith('/assistant:stream')){
      const answer='这是当前知识点的讲解，不生成题目。';
      return route.fulfill({contentType:'text/event-stream',body:`event: meta\ndata: ${JSON.stringify({message_id:id(92)})}\n\nevent: delta\ndata: ${JSON.stringify({seq:1,text:answer})}\n\nevent: done\ndata: ${JSON.stringify({message_id:id(92),answer,status:'completed'})}\n\n`});
    }
    if(path===`/api/chat/sessions/${id(91)}/messages`)return route.fulfill({json:[{message_id:id(92),role:'assistant',status:'completed',content:'这是当前知识点的讲解，不生成题目。'}]});
    if(path.endsWith('/messages')){unexpected.push(path);return route.fulfill({json:[]});}
    const found=nodes.find(n=>path===`/api/knowledge/${n.id}`);
    if(found)return route.fulfill({json:{node:found,questions:[],attempts:[],exam_references:[],lesson_available:true,materials_ready:false}});
    unexpected.push(path);return route.fulfill({status:503,json:{error:{code:'unexpected_test_request',message:'测试不允许连接真实API'}}});
  });
});
test.afterEach(()=>{expect(unexpected).toEqual([]);});

test('first entry shows exactly the three roots; every child is folded until its own parent is opened',async({page})=>{
  await page.goto('/knowledge');
  await expect(page.getByTestId('knowledge-canvas')).toBeVisible();
  await expect(page.locator('.frog-tree-figure')).toBeAttached();
  await expect(page.locator('.frog-tree-mascot')).toBeAttached();
  for(const root of ['cs408','math.calculus','math.linear-algebra']){
    await expect(title(page,root)).toBeVisible();await expect(row(page,root)).toHaveAttribute('aria-expanded','false');
  }
  await expect(title(page,'math.derivatives')).toHaveCount(0);await expect(title(page,'cs.ds')).toHaveCount(0);
  await title(page,'math.calculus').click();await expect(title(page,'math.derivatives')).toBeVisible();
  await expect(row(page,'math.calculus')).toHaveAttribute('aria-expanded','true');
  await expect(title(page,'math.implicit')).toHaveCount(0);
  await title(page,'math.linear-algebra').click();await expect(title(page,'math.matrix')).toBeVisible();
  await expect(row(page,'math.matrix')).not.toHaveAttribute('aria-expanded');
  await title(page,'math.calculus').click();await expect(title(page,'math.derivatives')).toHaveCount(0);
  await expect(title(page,'math.matrix')).toBeVisible();
  await page.getByRole('button',{name:'收起分支',exact:true}).click();
  await expect(title(page,'cs408')).toBeVisible();await expect(title(page,'math.calculus')).toBeVisible();await expect(title(page,'math.linear-algebra')).toBeVisible();
  await expect(title(page,'math.derivatives')).toHaveCount(0);await expect(title(page,'math.matrix')).toHaveCount(0);expect(writes).toEqual([]);
});
test('search reveals complete path then restores previous expansion; subjects stay independent',async({page})=>{
  await page.goto('/knowledge');await title(page,'math.linear-algebra').click();
  await page.getByTestId('knowledge-search').fill('曲率');
  await expect(title(page,'math.curvature')).toBeVisible();await expect(title(page,'math.implicit')).toBeVisible();
  await title(page,'math.curvature').click();await expect(page.getByTestId('detail-title')).toHaveText(leaf.name);
  await page.getByRole('button',{name:'清除搜索',exact:true}).click();
  await expect(title(page,'math.curvature')).toHaveCount(0);await expect(title(page,'math.matrix')).toBeVisible();
  await page.getByLabel('知识树学科范围').selectOption(id(10));await expect(title(page,'math.linear-algebra')).toHaveCount(0);
  await expect(title(page,'cs.ds')).toHaveCount(0);await title(page,'cs408').click();
  await expect(row(page,'cs.ds')).toHaveAttribute('aria-expanded','false');await title(page,'cs.ds').click();
  await page.getByLabel('知识树学科范围').selectOption(id(6));await expect(title(page,'math.matrix')).toBeVisible();
  expect(writes).toEqual([]);
});
test('deep links, refresh and browser history reveal only required ancestors',async({page})=>{
  await page.goto('/knowledge?node=math.curvature');await expect(title(page,'math.curvature')).toBeVisible();
  await expect(row(page,'math.calculus')).toHaveAttribute('aria-expanded','true');await expect(row(page,'math.linear-algebra')).toHaveAttribute('aria-expanded','false');
  await page.reload();await expect(page.getByTestId('detail-title')).toHaveText(leaf.name);
  await page.evaluate(()=>{history.pushState({},'', '/knowledge?node=cs.binary');window.dispatchEvent(new PopStateEvent('popstate'));});
  await expect(page.getByTestId('detail-title')).toHaveText('二叉树遍历与存储结构');await expect(title(page,'cs.binary')).toBeVisible();
  await page.goBack();await expect(page.getByTestId('detail-title')).toHaveText(leaf.name);expect(writes).toEqual([]);
});
test('one assistant entry sends current node, not previous-node history or confirmation',async({page})=>{
  for(const code of ['math.curvature','cs.binary']){
    await page.goto(`/knowledge?node=${code}`);await expect(page.getByTestId('knowledge-assistant-entry')).toHaveCount(1);
    await page.getByTestId('knowledge-assistant-link').click();await expect(page).toHaveURL(new RegExp(`knowledge_node_id=${nodes.find(n=>n.code===code).id}`));
    await expect(page.getByTestId('generation-confirmation')).toHaveCount(0);
    await expect(page.locator('.message-row')).toHaveCount(0);
    const input=page.locator('#chat-question');await input.fill('解释当前知识点');await input.press('Enter');
    await expect(page.locator('.message-row--assistant').last()).toContainText('这是当前知识点的讲解');
    const sent=writes.filter(w=>w.path.endsWith('/assistant:stream')).at(-1);
    expect(sent.body.study_context.knowledge_node_ids).toEqual([nodes.find(n=>n.code===code).id]);
    expect(sent.body.personal_generation_confirmation_message_id).toBeFalsy();
  }
});

test('return immediately retains real nodes, reports refresh failure and allows retry',async({page})=>{
  let count=0;let fail=false;
  await page.route('**/api/knowledge/tree',route=>{count++;return fail
    ?route.fulfill({status:503,json:{error:{code:'test_unavailable',message:'隔离网络不可用'}}})
    :route.fulfill({json:{nodes:roots}});});
  await page.goto('/knowledge');await expect(title(page,'cs408')).toBeVisible();expect(count).toBe(1);
  await page.getByRole('link',{name:'设置',exact:true}).click();await expect(page).toHaveURL(/settings/);fail=true;
  await page.getByRole('link',{name:'知识树',exact:true}).click();
  await expect(page.getByTestId('knowledge-error')).toContainText('隔离网络不可用');
  await expect(title(page,'cs408')).toBeVisible();
  fail=false;await page.getByTestId('knowledge-error').getByRole('button',{name:'重试',exact:true}).click();
  await expect(page.getByTestId('knowledge-error')).toHaveCount(0);expect(count).toBe(3);
  expect(writes).toEqual([]);
});

test('return refreshes tree and selected detail in parallel without blanking the canvas',async({page})=>{
  await page.goto('/knowledge?node=math.curvature');await expect(page.getByTestId('detail-title')).toHaveText(leaf.name);
  await page.getByRole('link',{name:'设置',exact:true}).click();
  await expect(page).toHaveURL(/settings/);
  let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});let tree=0,detail=0;
  await page.route('**/api/knowledge/tree',async route=>{tree++;await gate;await route.fulfill({json:{nodes:roots}});});
  await page.route(`**/api/knowledge/${leaf.id}`,async route=>{detail++;await gate;await route.fulfill({json:{node:leaf,questions:[],attempts:[],lesson_available:true}});});
  await page.goBack();
  try{
    await expect.poll(()=>({tree,detail})).toEqual({tree:1,detail:1});
    await expect(page.getByTestId('knowledge-canvas')).toBeVisible();
    await expect(title(page,'math.curvature')).toBeVisible();
  }finally{release();}
  await expect(page.getByTestId('detail-title')).toHaveText(leaf.name);expect(writes).toEqual([]);
});

test('leaving during the initial tree request does not prevent loading on return',async({page})=>{
  let first=true;let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/knowledge/tree',async route=>{if(first){first=false;await gate;}await route.fulfill({json:{nodes:roots}});});
  await page.goto('/knowledge');await expect(page.getByTestId('knowledge-loading')).toBeVisible();
  await page.getByRole('link',{name:'设置',exact:true}).click();
  await expect(page).toHaveURL(/settings/);
  await page.getByRole('link',{name:'知识树',exact:true}).click();
  try{await expect(title(page,'cs408')).toBeVisible();}finally{release();}
  expect(writes).toEqual([]);
});
for(const size of [{width:1366,height:768},{width:390,height:844}])test(`ninja frog canvas and long node interaction ${size.width}x${size.height}`,async({page},info)=>{
  await page.setViewportSize(size);await page.goto('/knowledge');
  await expect(page.getByTestId('knowledge-canvas')).toBeVisible();
  for(const root of ['cs408','math.calculus','math.linear-algebra']){
    await expect(title(page,root)).toBeVisible();
    if(size.width<600)await expect(title(page,root)).toBeInViewport({ratio:.8});
  }
  await page.screenshot({path:info.outputPath(`collapsed-${size.width}.png`),fullPage:true});
  for(const code of ['math.calculus','math.derivatives','math.implicit']){
    await title(page,code).click();
    if(size.width<600)await page.locator('.knowledge-detail-close').click();
  }
  const box=await row(page,'math.curvature').boundingBox();expect(box!.width).toBeGreaterThan(size.width<600?150:135);
  await title(page,'math.curvature').click();await expect(page.getByTestId('detail-title')).toHaveText(leaf.name);
  await expect(page.getByTestId('knowledge-assistant-link')).toBeVisible();
  if(size.width<600)await expect(page.getByTestId('detail-title')).toBeInViewport({ratio:.8});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
  if(size.width>=900){const overlap=await page.evaluate(()=>{const tree=document.querySelector('[data-testid="knowledge-tree"]')!.getBoundingClientRect();const detail=document.querySelector('[aria-label="知识节点详情"]')!.getBoundingClientRect();return Math.min(tree.right,detail.right)>Math.max(tree.left,detail.left)+1 && Math.min(tree.bottom,detail.bottom)>Math.max(tree.top,detail.top)+1;});expect(overlap).toBe(false);}
  expect(await page.locator('.canvas-branches path.frog-limb').count()).toBeGreaterThan(0);
  expect(await page.locator('.canvas-branches path.frog-toe').count()).toBeGreaterThan(0);
  await page.screenshot({path:info.outputPath(`selected-${size.width}.png`),fullPage:true});expect(writes).toEqual([]);
});
