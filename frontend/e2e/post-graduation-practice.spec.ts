// Protocol rendering only, not a human or supplier-model acceptance claim.
import {test,expect,type Page} from '@playwright/test';
test.setTimeout(30000);
const kp='22222222-2222-4222-8222-222222222222';
const progress={version:'post-graduation-practice-v1',applicable:true,status:'CONSOLIDATE',label:'建议巩固',reason:'近期两道不同题独立错误，基础毕业不撤销。',evidence_summary:'最近30天：2道独立错误。',last_reliable_practice_at:'2026-10-09T04:00:00Z',next_action:'targeted_practice',limitations:[],foundation_unchanged:true};
async function setup(page:Page,applicable=true){
  let calls=0;const p={...progress,applicable};const n={id:kp,code:'test.graduated',name:'定积分的计算',subject:'考研数学',ordinal:1,is_assessable:true,is_reference_only:false,state:applicable?'mastered':'unseen',children:[],post_graduation:p,post_graduation_review_count:applicable?1:0};
  await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;if(!path.startsWith('/api/'))return route.continue();
    if(path==='/api/health')return route.fulfill({json:{status:'ok',database:'connected'}});
    if(path==='/api/knowledge/tree')return route.fulfill({json:{nodes:[{id:'root',code:'root',name:'合成数学',is_assessable:false,state:null,children:[n],post_graduation_review_count:applicable?1:0}]}});
    if(path===`/api/knowledge/${kp}`)return route.fulfill({json:{node:n,questions:[],attempts:[],lesson_available:false,personal_questions:{count:3,latest:{message:'奶蛙新增3道个人题，可进入练习。'}},capability_profile:null}});
    if(path==='/api/plans/today')return route.fulfill({json:{status:'setup',study_date:'2026-10-09',recommendations:[]}});
    if(path==='/api/question-bank')return route.fulfill({json:{items:[],total:0}});
    if(path==='/api/practice-requests')return route.fulfill({json:[]});
    if(path.includes('assistant:stream')||path.includes('/generate'))calls++;
    return route.fulfill({json:[]});
  });return {get calls(){return calls;},p};
}
test('foundation and recent risk are separate; personal AI inventory is no longer duplicated in overview',async({page})=>{
  const state=await setup(page);await page.goto('/knowledge?node=test.graduated');
  const card=page.getByTestId('post-graduation-practice');await expect(card).toContainText('基础毕业：已通过');await expect(card).toContainText('建议巩固');
  await expect(page.getByTestId('personal-generation-activity')).toHaveCount(0);
  await expect(page.getByTestId('node-personal-count')).toHaveCount(0);expect(state.calls).toBe(0);
  const graduatedLeaf = page.getByTestId('tree-node-test.graduated').locator("xpath=ancestor::*[@role='treeitem'][1]");
  await expect(graduatedLeaf.locator('.canvas-node-status')).toHaveText('已毕业 · 建议巩固');
  await page.getByRole('link',{name:'让奶蛙提出复习方案'}).click();
  await expect(page).toHaveURL(new RegExp(`review_node_id=${kp}`));
  await expect(page.getByTestId('task-goal')).toHaveValue('帮我安排这个知识点的复习');
  await expect(page.getByTestId('learning-task-panel')).toHaveAttribute('open','');expect(state.calls).toBe(0);
});
test('ungraduated node does not display passed foundation or post practice card',async({page})=>{
  await setup(page,false);await page.goto('/knowledge?node=test.graduated');
  await expect(page.getByTestId('knowledge-detail')).toBeVisible();await expect(page.getByTestId('post-graduation-practice')).toHaveCount(0);
});
test('returning to knowledge reloads recent state instead of reusing stale risk',async({page})=>{
  const state=await setup(page);await page.goto('/knowledge?node=test.graduated');await expect(page.getByTestId('post-graduation-practice')).toContainText('建议巩固');
  await page.getByRole('link',{name:'让奶蛙提出复习方案'}).click();state.p.status='GOOD';state.p.label='保持良好';state.p.reason='不同题目独立正确，已有跨日覆盖。';
  await page.goto('/knowledge?node=test.graduated');await expect(page.getByTestId('post-graduation-practice')).toContainText('保持良好');
});
