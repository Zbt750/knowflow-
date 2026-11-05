import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {h} from 'vue';
import {all, deferred, flush, mountStateComponent, text} from '../components/stateTestHost';
import {ApiError} from '../api/client';
import type {PlanItemView,TodayActive} from '../types/practice';
const mocks=vi.hoisted(()=>({activity:vi.fn(),today:vi.fn(),submit:vi.fn(),retry:vi.fn(),readRetry:vi.fn(),trainingRead:vi.fn(),trainingReport:vi.fn(),tree:vi.fn(),route:{query:{}}}));
vi.mock('../api/study',async original=>({...await original<typeof import('../api/study')>(),recordPracticeActivity:mocks.activity,fetchToday:mocks.today,submitAnswer:mocks.submit,createPracticeRetry:mocks.retry,fetchPracticeRetry:mocks.readRetry,fetchKnowledgeTree:mocks.tree}));
vi.mock('../api/personalTrainings',()=>({readPersonalTraining:mocks.trainingRead,readPersonalTrainingReport:mocks.trainingReport,savePersonalTrainingDraft:vi.fn(),answerPersonalTrainingItem:vi.fn(),transitionPersonalTraining:vi.fn()}));
vi.mock('vue-router',()=>({useRoute:()=>mocks.route}));
vi.mock('../components/LearningTaskPanel.vue',()=>({default:{setup:()=>()=>h('div')}}));
vi.mock('../components/ProcessReview.vue',()=>({default:{setup:()=>()=>h('div')}}));
vi.mock('../components/MarkdownContent.vue',()=>({default:{props:['text'],setup:(p:{text:string})=>()=>h('article',p.text)}}));
import StudyPage from './StudyPage.vue';

function paper():TodayActive{return {status:'active',plan_id:'plan',study_date:'2026-10-24',completed_count:0,total_count:1,
  items:[{id:'item',ordinal:1,kp_id:'kp',kp_name:'SYNTHETIC 洛必达',question_id:'question',question_version_id:'version',
    question_type:'single_choice',question_role:'basic',difficulty:'basic',stem:'SYNTHETIC：求 ln(x)/x 的极限',
    options:{A:'0',B:'1'},skill_tags:[],is_variant:false,estimated_minutes:3,is_review:false,completed:false,
    completed_at:null,latest_self_grade:null,is_external_reference:false,exam_reference:null,answer_grading_method:'single_choice'}],
  focus_item_id:'item',summary_kps:[],type_summary:{single_choice:1},estimated_minutes:3,remaining_minutes:3};}
function paperItems(items:PlanItemView[]):TodayActive{
  const value=paper();value.items=items;value.total_count=items.length;value.completed_count=items.filter(item=>item.completed).length;
  value.status=value.total_count>0&&value.completed_count===value.total_count?'completed':'active';
  value.focus_item_id=items.find(item=>!item.completed)?.id??null;return value;
}
function item(id:string,ordinal:number,done=false,result?:'right'|'wrong',assisted=false):PlanItemView{
  return {...paper().items[0],id,ordinal,display_number:ordinal,question_id:`question-${id}`,
    question_version_id:`version-${id}`,completed:done,completed_at:done?'2026-10-25T01:00:00Z':null,
    answer_submission:result?{result,selected_option:result==='right'?'A':'B',raw_answer:null,assisted} as never:undefined};
}
let unmount:(()=>void)|undefined;
let browser:{url:()=>string;back:()=>void;forward:()=>void}|undefined;
function installBrowser(initial='http://127.0.0.1/study'){
  let current=initial;let entries=[initial];let index=0;const listeners=new Map<string,Set<()=>void>>();
  const resolve=(value:unknown)=>new URL(String(value),current).href;
  const emit=(name:string)=>{for(const callback of listeners.get(name)??[])callback();};
  const location={get href(){return current;},set href(value:string){current=resolve(value);}};
  const history={state:null as unknown,replaceState:vi.fn((_state:unknown,_title:string,url:unknown)=>{
      current=resolve(url);entries[index]=current;
    }),pushState:vi.fn((_state:unknown,_title:string,url:unknown)=>{
      current=resolve(url);entries=entries.slice(0,index+1);entries.push(current);index+=1;
    })};
  vi.stubGlobal('window',{addEventListener:(name:string,callback:()=>void)=>{const group=listeners.get(name)??new Set();group.add(callback);listeners.set(name,group);},
    removeEventListener:(name:string,callback:()=>void)=>listeners.get(name)?.delete(callback),location,history});
  browser={url:()=>current,back:()=>{if(index>0){index-=1;current=entries[index];emit('popstate');}},
    forward:()=>{if(index+1<entries.length){index+=1;current=entries[index];emit('popstate');}}};
  return browser;
}
beforeEach(()=>{
  mocks.activity.mockImplementation(async(_id,kind)=>({event_id:'activity-event',kind}));
  mocks.route.query={};browser=installBrowser();
  vi.stubGlobal('document',{querySelector:()=>null,getElementById:()=>null});
  mocks.today.mockImplementation(async()=>paper());
});
afterEach(()=>{unmount?.();vi.unstubAllGlobals();vi.resetAllMocks();browser=undefined;});
async function mounted(){const view=mountStateComponent(StudyPage,{});unmount=view.unmount;await flush();return view;}
it('saves an explicit skip before moving and does not submit an answer',async()=>{
  mocks.today.mockResolvedValue(paperItems([item('q1',1),item('q2',2)]));
  const view=await mounted();
  const skip=all(view.root).find(n=>n.props['data-testid']==='skip-question')!;
  (skip.props.onClick as ()=>void)();await flush();
  expect(mocks.activity.mock.calls.some(c=>c[0]==='q1'&&c[1]==='skipped')).toBe(true);
  expect(mocks.submit).not.toHaveBeenCalled();
  expect(all(view.root).find(n=>n.props['data-testid']==='focus-question')!.props['data-item-id']).toBe('q2');
});

it('retains the question and retry key when skip persistence fails',async()=>{
  mocks.today.mockResolvedValue(paperItems([item('q1',1),item('q2',2)]));
  mocks.activity.mockImplementation(async(_id,kind)=>{if(kind==='skipped')throw new Error('offline');return {event_id:'ok',kind};});
  const view=await mounted();
  const click=()=>{(all(view.root).find(n=>n.props['data-testid']==='skip-question')!.props.onClick as ()=>void)();};
  click();await flush();click();await flush();
  const calls=mocks.activity.mock.calls.filter(c=>c[1]==='skipped');
  expect(calls).toHaveLength(2);expect(calls[0][2]).toBe(calls[1][2]);
  expect(text(view.root)).toContain('学习行为保存失败');
  expect(all(view.root).find(n=>n.props['data-testid']==='focus-question')!.props['data-item-id']).toBe('q1');
});
it('wrong answers are accessible from a first-level disclosure rather than hidden in paper records',async()=>{
  mocks.today.mockResolvedValue(paperItems([item('wrong',1,true,'wrong')]));
  const view=await mounted();
  const records=all(view.root).find(n=>n.props['data-testid']==='practice-result-summary')!;
  const review=all(view.root).find(n=>n.props['data-testid']==='wrong-answer-review')!;
  expect(review).toBeDefined();
  expect(all(records).some(n=>n===review)).toBe(false);
  expect(all(review).some(n=>n.props['data-testid']==='revisit-wrong-wrong')).toBe(true);
});
it('opens in today mode by default without a duplicate top label',async()=>{
  const view=await mounted();
  // 2026-11-02：顶部“今日学习”标签与标题重复已移除；专项入口仍停用。
  expect(all(view.root).some(n=>n.props['data-testid']==='mode-today')).toBe(false);
  expect(all(view.root).some(n=>n.props['data-testid']==='mode-personal-training')).toBe(false);
});
it('keeps the existing daily full-paper preview on the shared paper-preview component',async()=>{
  const view=await mounted();
  (all(view.root).find(n=>n.props['data-testid']==='full-paper')!.props.onClick as ()=>void)();await flush();
  expect(all(view.root).find(n=>n.props['data-testid']==='paper-list')).toBeDefined();
  expect(all(view.root).find(n=>n.props.id==='paper-item-item')).toBeDefined();
  expect(text(view.root)).toContain('求 ln(x)/x 的极限');
});
// 临时停用专项练习（2026-11-02）：保留用例代码，恢复功能后去掉 skip 即可。
it.skip('loads a chat-linked training inside /study and can switch back without touching the daily plan',async()=>{
  const owner='11111111-1111-4111-8111-111111111111';const trainingId='22222222-2222-4222-8222-222222222222';
  installBrowser(`http://127.0.0.1/study?mode=personal&owner_session_id=${owner}&training_id=${trainingId}`);
  mocks.trainingRead.mockResolvedValue({training_id:trainingId,owner_session_id:owner,request_key:'chat-request',title:'专项练习',status:'active',version:1,
    knowledge_point_ids:['kp'],selection_basis:'selected',requested_count:1,target_minutes:30,actual_minutes:5,inventory_shortfall:0,minutes_shortfall:0,
    item_count:1,completed_count:0,remaining_count:1,progress_percent:0,started_at:'2026-10-30T00:00:00Z',paused_at:null,finished_at:null,
    adapted_from_training_id:null,items:[{item_id:'training-item',ordinal:1,question_id:'q',question_version_id:'qv',kp_id:'kp',question_type:'calculation',
      difficulty:'basic',estimated_minutes:5,stem:'专项题目',options:null,completed:false,draft_answer:null,draft_selected_option:null,draft_revision:0,draft_saved_at:null,completed_at:null,latest_result:null}]});
  mocks.tree.mockResolvedValue({nodes:[]});
  const view=await mounted();await flush();
  const dailyReadCount=mocks.today.mock.calls.length;
  expect(mocks.trainingRead).toHaveBeenCalledWith(trainingId,owner);
  expect(text(view.root)).toContain('专项练习');expect(text(view.root)).toContain('专项题目');
  expect(all(view.root).find(n=>n.props['data-testid']==='mode-personal-training')?.props.class).toBe('active');
  const back=all(view.root).find(n=>n.props['data-testid']==='return-today-mode')!;(back.props.onClick as ()=>void)();await flush();
  expect(all(view.root).find(n=>n.props['data-testid']==='mode-today')?.props.class).toBe('active');
  const personal=all(view.root).find(n=>n.props['data-testid']==='mode-personal-training')!;(personal.props.onClick as ()=>void)();await flush();
  expect(new URL(browser!.url()).searchParams.get('mode')).toBe('personal');
  expect(text(view.root)).toContain('0 / 1');
  expect(mocks.today).toHaveBeenCalledTimes(dailyReadCount);
  expect(mocks.submit).not.toHaveBeenCalled();
});
// 临时停用专项练习（2026-11-02）：保留用例代码，恢复功能后去掉 skip 即可。
it.skip('restores the chat-linked personal mode from the URL after a fresh page mount',async()=>{
  const owner='11111111-1111-4111-8111-111111111111';const trainingId='22222222-2222-4222-8222-222222222222';
  installBrowser(`http://127.0.0.1/study?mode=personal&owner_session_id=${owner}&training_id=${trainingId}`);
  mocks.trainingRead.mockResolvedValue({training_id:trainingId,owner_session_id:owner,request_key:'chat-request',title:'恢复专项',status:'paused',version:2,
    knowledge_point_ids:['kp'],selection_basis:'selected',requested_count:1,target_minutes:30,actual_minutes:5,inventory_shortfall:0,minutes_shortfall:0,
    item_count:1,completed_count:0,remaining_count:1,progress_percent:0,started_at:'2026-10-30T00:00:00Z',paused_at:'2026-10-30T00:02:00Z',finished_at:null,
    adapted_from_training_id:null,items:[{item_id:'training-item',ordinal:1,question_id:'q',question_version_id:'qv',kp_id:'kp',question_type:'calculation',
      difficulty:'basic',estimated_minutes:5,stem:'恢复后的专项题',options:null,completed:false,draft_answer:'草稿已恢复',draft_selected_option:null,draft_revision:1,draft_saved_at:'2026-10-30T00:01:00Z',completed_at:null,latest_result:null}]});
  mocks.tree.mockResolvedValue({nodes:[]});
  const view=await mounted();await flush();
  expect(mocks.trainingRead).toHaveBeenCalledWith(trainingId,owner);
  expect(all(view.root).find(n=>n.props['data-testid']==='mode-personal-training')?.props.class).toBe('active');
  expect(text(view.root)).toContain('恢复后的专项题');
  const restoredDraft=all(view.root).find(n=>n.props['data-testid']==='raw-answer');
  expect(restoredDraft?.props.value).toBe('草稿已恢复');
  expect(restoredDraft?.props.disabled).toBe(true);
});
it('shows wrong standalone retries in review and opens the persisted retry without creating another one',async()=>{
  const done=paperItems([item('root',1,true,'wrong')]);
  const retryWrong={...item('retry-wrong',1,true,'wrong'),retry_source_id:'root'};
  done.retry_wrong_items=[retryWrong];
  mocks.today.mockResolvedValue(done);
  const view=await mounted();
  const review=all(view.root).find(n=>n.props['data-testid']==='wrong-answer-review')!;
  expect(text(review)).toContain('2');
  const entry=all(review).find(n=>n.props['data-testid']==='revisit-wrong-retry-wrong')!;
  expect(text(entry)).toContain('第 1 题');expect(text(entry)).toContain('重练');
  await (entry.props.onClick as ()=>void)();await flush();
  expect(text(view.root)).toContain('正在单独重练');
  expect(text(view.root)).toContain('本次重练错误已保留');
  expect(mocks.retry).not.toHaveBeenCalled();
  expect(new URL(browser!.url()).searchParams.get('retry_id')).toBe('retry-wrong');
});
async function chooseAndSubmit(view:ReturnType<typeof mountStateComponent>){
  (all(view.root).find(n=>n.props['data-testid']==='option-A')!.props.onChange as ()=>void)();
  await flush();(all(view.root).find(n=>n.props['data-testid']==='submit-answer')!.props.onClick as ()=>void)();await flush();
}
it('explains a missing learning state and requires a read refresh instead of blind submission retries',async()=>{
  mocks.submit.mockRejectedValue(new ApiError('knowledge point state not found',409,'kp_state_not_found'));
  const view=await mounted();await chooseAndSubmit(view);
  expect(text(view.root)).toContain('学习状态');expect(text(view.root)).toContain('kp_state_not_found');
  expect(text(view.root)).not.toContain('请先运行');
  expect(all(view.root).find(n=>n.props['data-testid']==='submit-answer')!.props.disabled).toBe(true);
  const refresh=all(view.root).find(n=>n.props['data-testid']==='refresh-answer-state')!;
  expect(refresh).toBeDefined();await (refresh.props.onClick as ()=>void)();await flush();
  expect(mocks.submit).toHaveBeenCalledTimes(1);expect(mocks.today).toHaveBeenCalledTimes(2);
  expect(all(view.root).find(n=>n.props['data-testid']==='option-A')!.props.checked).toBe(true);
});
it('reconciles a lost response with the saved receipt before offering another write',async()=>{
  mocks.submit.mockRejectedValue(new TypeError('response lost'));
  const view=await mounted();await chooseAndSubmit(view);
  expect(text(view.root)).toContain('结果暂未确认');expect(text(view.root)).not.toContain('本次答案已提交并锁定');
  const saved=paper();saved.items[0].completed=true;saved.items[0].answer_submission={result:'right',selected_option:'A',raw_answer:null,assisted:false} as never;
  mocks.today.mockResolvedValue(saved);
  const refresh=all(view.root).find(n=>n.props['data-testid']==='refresh-answer-state')!;
  expect(refresh).toBeDefined();await (refresh.props.onClick as ()=>void)();await flush();
  expect(text(view.root)).toContain('本次答案已提交并锁定');
  expect(mocks.submit).toHaveBeenCalledTimes(1);
  expect(all(view.root).filter(n=>n.props['data-testid']==='submit-answer')).toHaveLength(0);
});
it('keeps validation failures editable and does not label them delivery-unknown',async()=>{
  mocks.submit.mockRejectedValue(new ApiError('请选择有效选项',422,'validation_failed'));
  const view=await mounted();await chooseAndSubmit(view);
  expect(text(view.root)).toContain('请选择有效选项');expect(text(view.root)).not.toContain('提交未确认');
  expect(all(view.root).find(n=>n.props['data-testid']==='submit-answer')!.props.disabled).toBe(false);
});
it('opens a separate retry through the formal endpoint and reconciles its saved assisted receipt',async()=>{
  const original=paper();original.items[0].completed=true;original.items[0].answer_submission={result:'wrong',selected_option:'A',raw_answer:null,assisted:false} as never;
  mocks.today.mockResolvedValue(original);
  // The real retry endpoint returns the source PracticeItem id. Keep this
  // field in the fixture so refresh reconciliation exercises the same
  // source-and-version ownership check as the live response.
  const separate={...original.items[0],id:'standalone-retry',retry_source_id:'item',completed:false,answer_submission:undefined};
  mocks.retry.mockResolvedValue(separate);
  const view=await mounted();
  expect(text(view.root)).toContain('今日卷已完成');
  expect(all(view.root).filter(n=>n.props['data-testid']==='focus-question')).toHaveLength(0);
  (all(view.root).find(n=>n.props['data-testid']==='full-paper')!.props.onClick as ()=>void)();await flush();
  const button=all(view.root).find(n=>n.props['data-testid']==='completed-retry-item')!;
  expect(button).toBeDefined();await (button.props.onClick as ()=>void)();await flush();
  expect(mocks.retry).toHaveBeenCalledWith('item',expect.any(String));
  expect(text(view.root)).toContain('错题重练（不计入今日卷题号）');
  expect(text(view.root)).toContain('原始作答保留');
  const receipt={result:'right',selected_option:'A',raw_answer:null,assisted:true,submitted_at:'2026-10-25T01:00:00Z'};
  mocks.submit.mockResolvedValue(receipt);
  mocks.readRetry.mockResolvedValue({...separate,completed:true,answer_submission:receipt});
  await chooseAndSubmit(view);
  expect(mocks.submit.mock.calls[0][0]).toBe('standalone-retry');
  expect(text(view.root)).toContain('本次答案已提交并锁定');
  expect(mocks.today).toHaveBeenCalledTimes(2);
  const back=all(view.root).find(n=>n.type==='button'&&text(n)==='返回今日卷')!;
  expect(back).toBeDefined();await (back.props.onClick as ()=>void)();await flush();
  expect(text(view.root)).toContain('今日卷已完成');expect(text(view.root)).not.toContain('正在单独重练');
});
it('a completed paper exposes the wrong question even when the final question was correct',async()=>{
  const done=paper();done.items[0].completed=true;done.items[0].answer_submission={result:'wrong',assisted:false} as never;
  done.items.push({...done.items[0],id:'last-right',ordinal:2,answer_submission:{result:'right',assisted:false} as never});
  done.total_count=2;done.completed_count=2;mocks.today.mockResolvedValue(done);
  mocks.retry.mockResolvedValue({...done.items[0],id:'new-retry',completed:false,answer_submission:undefined});
  const view=await mounted();
  const actions=all(view.root).find(n=>n.props['data-testid']==='completed-paper-actions')!;
  expect(text(actions)).toContain('1 道错题');
  expect(all(actions).some(n=>n.props['data-testid']==='completed-retry-last-right')).toBe(false);
  await (all(actions).find(n=>n.props['data-testid']==='completed-retry-item')!.props.onClick as ()=>void)();await flush();
  expect(mocks.retry).toHaveBeenCalledWith('item',expect.any(String));
});
it('an obsolete refresh cannot unlock another submission while the latest read is unresolved',async()=>{
  mocks.submit.mockRejectedValue(new TypeError('response lost'));
  const view=await mounted();await chooseAndSubmit(view);
  const earlier=deferred<TodayActive>(), latest=deferred<TodayActive>();
  mocks.today.mockReturnValueOnce(earlier.promise).mockReturnValueOnce(latest.promise);
  const refresh=all(view.root).find(n=>n.props['data-testid']==='refresh-answer-state')!;
  (refresh.props.onClick as ()=>void)();(refresh.props.onClick as ()=>void)();
  earlier.resolve(paper());await flush();
  expect(all(view.root).find(n=>n.props['data-testid']==='submit-answer')!.props.disabled).toBe(true);
  latest.resolve(paper());await flush();
  expect(all(view.root).find(n=>n.props['data-testid']==='submit-answer')!.props.disabled).toBe(false);
  expect(mocks.submit).toHaveBeenCalledTimes(1);
});
it.each([401,403])('a %s permission rejection has accurate feedback and cannot trigger a blind retry',async status=>{
  mocks.submit.mockRejectedValue(new ApiError('internal permission details',status,'invalid_request'));
  const view=await mounted();await chooseAndSubmit(view);
  expect(text(view.root)).toContain('没有提交权限');
  expect(text(view.root)).not.toContain('internal permission details');
  expect(all(view.root).find(n=>n.props['data-testid']==='submit-answer')!.props.disabled).toBe(true);
  expect(mocks.submit).toHaveBeenCalledTimes(1);
});
it('a failed reconciliation GET keeps the answer and submission restriction',async()=>{
  mocks.submit.mockRejectedValue(new TypeError('response lost'));
  const view=await mounted();await chooseAndSubmit(view);
  mocks.today.mockRejectedValue(new ApiError('database unavailable',503,'database_unavailable'));
  const refresh=all(view.root).find(n=>n.props['data-testid']==='refresh-answer-state')!;
  await (refresh.props.onClick as ()=>void)();await flush();
  expect(all(view.root).find(n=>n.props['data-testid']==='submit-answer')!.props.disabled).toBe(true);
  expect(all(view.root).find(n=>n.props['data-testid']==='option-A')!.props.checked).toBe(true);
  expect(mocks.submit).toHaveBeenCalledTimes(1);
});

it('restores the URL-selected submitted question, keeps navigation bounded, and follows back/forward',async()=>{
  installBrowser('http://127.0.0.1/study?item_id=q1');
  mocks.today.mockResolvedValue(paperItems([item('q1',1,true,'right'),item('q2',2),item('q3',3)]));
  const view=await mounted();
  const focused=()=>all(view.root).find(node=>node.props['data-testid']==='focus-question')!;
  expect(focused().props['data-item-id']).toBe('q1');
  expect(focused().props['data-question-version-id']).toBe('version-q1');
  expect(text(focused())).toContain('答案正确');
  const next=()=>all(view.root).find(node=>node.props['data-testid']==='continue-question')!;
  (next().props.onClick as ()=>void)();await flush();
  expect(focused().props['data-item-id']).toBe('q2');
  (next().props.onClick as ()=>void)();await flush();
  expect(focused().props['data-item-id']).toBe('q3');
  (next().props.onClick as ()=>void)();await flush();
  expect(focused().props['data-item-id']).toBe('q3');
  expect(focused().props['data-display-number']).toBe(3);
  expect(new URL(browser!.url()).searchParams.get('item_id')).toBe('q3');
  browser!.back();await flush();expect(focused().props['data-item-id']).toBe('q2');
  browser!.back();await flush();expect(focused().props['data-item-id']).toBe('q1');
  browser!.forward();await flush();expect(focused().props['data-item-id']).toBe('q2');
  expect(text(all(view.root).find(node=>node.props['data-testid']==='study-status')!)).toContain('1 / 3');
});

it('pins the first stable focus in the URL and restores its submitted receipt after a fresh mount',async()=>{
  const original=item('q1',1);mocks.today.mockResolvedValueOnce(paperItems([original,item('q2',2)]));
  const first=await mounted();
  expect(all(first.root).find(node=>node.props['data-testid']==='focus-question')!.props['data-item-id']).toBe('q1');
  expect(new URL(browser!.url()).searchParams.get('item_id')).toBe('q1');
  first.unmount();
  const saved=item('q1',1,true,'wrong');mocks.today.mockResolvedValueOnce(paperItems([saved,item('q2',2)]));
  const restored=await mounted();
  const focus=all(restored.root).find(node=>node.props['data-testid']==='focus-question')!;
  expect(focus.props['data-item-id']).toBe('q1');
  expect(focus.props['data-question-version-id']).toBe('version-q1');
  expect(text(focus)).toContain('答案错误');
  expect(all(restored.root).some(node=>node.props['data-testid']==='submit-answer')).toBe(false);
});

it('restores a pending retry after leaving study and returning without its query string',async()=>{
  browser=installBrowser('http://127.0.0.1/study?item_id=q1');
  const values=new Map<string,string>();
  vi.stubGlobal('localStorage',{getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>values.set(k,v),removeItem:(k:string)=>values.delete(k)});
  const source=item('q1',1,true,'wrong');mocks.today.mockResolvedValue(paperItems([source,item('q2',2)]));
  const retry={...source,id:'retry',retry_source_id:source.id,completed:false,answer_submission:undefined};
  mocks.retry.mockResolvedValue(retry);mocks.readRetry.mockResolvedValue(retry);
  let view=await mounted();await (all(view.root).find(n=>n.props['data-testid']==='retry-practice')!.props.onClick as ()=>void)();await flush();
  expect(text(view.root)).toContain('错题重练（不计入今日卷题号）');view.unmount();unmount=undefined;
  window.location.href='http://127.0.0.1/study';view=await mounted();
  expect(text(view.root)).toContain('错题重练（不计入今日卷题号）');
  expect(mocks.retry).toHaveBeenCalledTimes(1);expect(mocks.readRetry).toHaveBeenCalledWith('retry');
});

it('keeps a retry read timeout visibly unresolved instead of substituting a paper question',async()=>{
  browser=installBrowser('http://127.0.0.1/study?retry_id=retry');
  const source=item('q1',1,true,'wrong');mocks.today.mockResolvedValue(paperItems([source,item('q2',2)]));
  mocks.readRetry.mockRejectedValue(new TypeError('connection lost'));
  const view=await mounted();
  expect(text(view.root)).toContain('重练状态暂未确认');
  expect(all(view.root).some(n=>n.props['data-testid']==='submit-answer')).toBe(false);
  expect(new URL(browser!.url()).searchParams.get('retry_id')).toBe('retry');
  mocks.readRetry.mockResolvedValue({...source,id:'retry',retry_source_id:'q1',completed:false,answer_submission:undefined});
  await (all(view.root).find(n=>n.props['data-testid']==='refresh-retry-state')!.props.onClick as ()=>void)();await flush();
  expect(text(view.root)).toContain('错题重练（不计入今日卷题号）');expect(mocks.retry).not.toHaveBeenCalled();
});

it('rejects a retry URL whose question version does not match the current paper item',async()=>{
  installBrowser('http://127.0.0.1/study?retry_id=foreign-retry');
  mocks.today.mockResolvedValue(paperItems([item('q1',1),item('q2',2)]));
  mocks.readRetry.mockResolvedValue({...item('retry',1),retry_source_id:'q1',question_version_id:'another-version'});
  const view=await mounted();
  expect(text(view.root)).toContain('不属于当前今日卷');
  expect(text(view.root)).not.toContain('错题重练（不计入今日卷题号）');
  expect(new URL(browser!.url()).searchParams.get('retry_id')).toBeNull();
  expect(all(view.root).find(node=>node.props['data-testid']==='focus-question')!.props['data-item-id']).toBe('q1');
});

it('a confirmed paper has a real workbench return route without replacing its answer state',async()=>{const view=await mounted();const before=text(view.root);const open=all(view.root).find(n=>n.props['data-testid']==='open-home-workbench')!;expect(open).toBeDefined();await (open.props.onClick as()=>Promise<void>)();await flush();expect(browser!.url()).toContain('workspace=1');expect(all(view.root).some(n=>n.props['data-testid']==='confirmed-home-workbench')).toBe(true);expect(mocks.today).toHaveBeenCalledTimes(1);expect(mocks.submit).not.toHaveBeenCalled();expect(mocks.retry).not.toHaveBeenCalled();const close=all(view.root).find(n=>n.props['data-testid']==='return-to-practice')!;await (close.props.onClick as()=>Promise<void>)();await flush();expect(browser!.url()).not.toContain('workspace=1');expect(text(view.root)).toContain('SYNTHETIC 洛必达');expect(before).toContain('SYNTHETIC 洛必达');});
