import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {h,reactive} from 'vue';
import {mountStateComponent,all,text,flush,deferred,type Node} from './stateTestHost';
import {ApiError} from '../api/client';
import {homeStudyDay,homeDayKey,homeDayTitle} from '../lib/homeDailyConversation';
import type {HomePreview} from '../api/homeRecommendation';
const mocks=vi.hoisted(()=>({system:vi.fn(),recover:vi.fn(),adjust:vi.fn(),confirm:vi.fn(),list:vi.fn(),history:vi.fn(),create:vi.fn(),stream:vi.fn(),difficulty:vi.fn()}));
vi.mock('../api/homeRecommendation',()=>({readHomeSystemRecommendation:mocks.system,recoverHomePreview:mocks.recover,adjustHomePreview:mocks.adjust,confirmHomePreview:mocks.confirm,adjustHomeDifficulty:mocks.difficulty}));
vi.mock('../api/chat',()=>({listChatSessions:mocks.list,fetchChatMessages:mocks.history,createChatSession:mocks.create,streamChatAnswer:mocks.stream}));
vi.mock('./MarkdownContent.vue',()=>({default:{props:['text'],setup:(p:{text:string})=>()=>h('div',p.text)}}));
vi.mock('./StudyMascot.vue',()=>({default:{setup:()=>()=>h('i')}}));
import Panel from './HomeRecommendationAssistant.vue';
let unmount:(()=>void)|undefined;
const task=(id='one'):HomePreview=>({task_id:id,session_id:'s1',goal:'线性代数90分钟',status:'ready',message:'真实库存仅2道，预计60分钟；尚未创建今日卷',budget_minutes:90,draft_version:id.repeat(64).slice(0,64),receipt:null,
 draft:{questions:[{question_id:'q1',question_version_id:'v1',kp_id:'k1',kp_name:'线代',stem:'合成题',options:{A:'2'},minutes:30,reason:'未练过'},{question_id:'q2',question_version_id:'v2',kp_id:'k1',kp_name:'线代',stem:'合成题2',options:{A:'2'},minutes:30,reason:'毕业缺口'}],selected_kp_ids:['k1'],budget_minutes:90,total_minutes:60,diff:{added:['q2'],removed:[],retained:['q1']}},
 context:{study_date:homeStudyDay(),expires_at:'2099-01-01T00:00:00Z',baseline:null,system_recommendations:[{kp_id:'k1',name:'线代',reason:'insufficient_evidence',next_step:'初始诊断',requires_graduation_set_confirmation:false}],evidence:{note:'客观、自述分开',states:[]}}});
beforeEach(()=>{const storage=new Map([['naiwa:home-recommendation:session:v1','s1']]);vi.stubGlobal('localStorage',{getItem:(k:string)=>storage.get(k)??null,setItem:(k:string,v:string)=>storage.set(k,v),removeItem:(k:string)=>storage.delete(k)});vi.stubGlobal('Document',class{});vi.stubGlobal('ShadowRoot',class{});mocks.system.mockResolvedValue(null);mocks.list.mockImplementation((_mode:string|undefined,purpose:string|undefined)=>Promise.resolve([{session_id:'s1',title:purpose==='study'?homeDayTitle(homeStudyDay()):'旧话题',mode:'builtin',purpose:purpose??'qa'},{session_id:'s2',title:'另一个话题',mode:'builtin',purpose:purpose??'qa'}]));mocks.history.mockResolvedValue([]);mocks.recover.mockResolvedValue(task());mocks.create.mockImplementation((title:string,mode:string,options?:{purpose?:string})=>Promise.resolve({session_id:'s3',title,mode,purpose:options?.purpose??'qa'}));mocks.adjust.mockResolvedValue(task('two'));});
afterEach(()=>{unmount?.();vi.useRealTimers();vi.resetAllMocks();vi.unstubAllGlobals();});
async function mounted(){const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard'});unmount=host.unmount;await flush();return host.root;}
const button=(root:Node,label:string)=>all(root).find(n=>n.type==='button'&&(text(n).includes(label)||String(n.props['aria-label']??'').includes(label)))!;
async function input(root:Node,value:string){const area=all(root).find(n=>n.type==='textarea')!;const handler=area.props['onUpdate:modelValue'] as (v:string)=>void;handler(value);await flush();}
const submit=async(root:Node)=>{await (all(root).find(n=>n.type==='form')!.props.onSubmit as (e:{preventDefault:()=>void})=>Promise<void>)({preventDefault(){}});await flush();};
it('restores actual preview, reasons, versions and shortages without creating a paper',async()=>{const r=await mounted();expect(text(r)).toContain('真实库存仅2道');expect(text(r)).not.toContain('v1');expect(text(r)).toContain('实际 2 道 / 60 分钟');expect(mocks.confirm).not.toHaveBeenCalled();expect(mocks.adjust).not.toHaveBeenCalled();});
it('a pending/failed revision keeps the last effective preview visible instead of flashing back to the system baseline',async()=>{const r=await mounted();const summary=()=>all(r).find(n=>n.props['data-testid']==='home-current-summary');expect(summary()?.props['data-preview-id']).toBe('one');const pending=deferred<HomePreview>();mocks.adjust.mockReturnValue(pending.promise);await input(r,'刚才90分钟太长了，改成60分钟。');const send=submit(r);await flush();expect(button(r,'确认并生成').props.disabled).toBe(true);expect(summary()?.props['data-preview-id']).toBe('one');pending.reject(new Error('选题失败'));await send;expect(button(r,'确认并生成').props.disabled).toBe(true);expect(text(r)).toContain('读取当前状态');expect(summary()?.props['data-preview-id']).toBe('one');expect(mocks.confirm).not.toHaveBeenCalled();});
it('confirmation uses only current task/version and receipt is authoritative',async()=>{const r=await mounted();mocks.confirm.mockResolvedValue({...task(),receipt:{plan_id:'p1'},message:'已生成'});await (button(r,'确认并生成').props.onClick as ()=>Promise<void>)();await flush();expect(mocks.confirm).toHaveBeenCalledWith('one',{session_id:'s1',draft_version:task().draft_version,confirm_legacy_set_transition_ids:[]});expect(button(r,'确认并生成').props.disabled).toBe(true);});
it('restore and cancellation use workspace actions, never direct plan generation',async()=>{const r=await mounted();await (button(r,'恢复原系统推荐').props.onClick as ()=>Promise<void>)();await flush();expect(mocks.adjust.mock.calls[0][0].action).toBe('restore');await (button(r,'取消预览').props.onClick as ()=>Promise<void>)();expect(mocks.adjust.mock.calls[1][0].action).toBe('cancel');expect(mocks.confirm).not.toHaveBeenCalled();});
it('late restoration cannot overwrite the newly selected conversation',async()=>{const r=await mounted();const pending=deferred<HomePreview|null>();mocks.recover.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(null);const select=all(r).find(n=>n.type==='select')!;const handler=select.props.onChange as(e:{target:{value:string}})=>Promise<void>;const old=handler({target:{value:'s1'}});await handler({target:{value:'s2'}});pending.resolve(task('stale'));await old;await flush();expect(text(r)).not.toContain('当前试卷预览');});
it('keeps free conversation on the existing QA stream without invoking paper adjustment',async()=>{const r=await mounted();const qa=all(r).find(n=>n.type==='input'&&n.props.value==='qa')!;(qa.props['onUpdate:modelValue'] as(v:string)=>void)('qa');await input(r,'为什么行列式换两行要变号？');mocks.stream.mockResolvedValue(undefined);await submit(r);expect(mocks.stream).toHaveBeenCalledWith('s1','为什么行列式换两行要变号？',expect.any(Function),expect.any(AbortSignal),{purpose:'qa'});expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();});
it('manual preview delegates current scope and real preset budget to the same endpoint',async()=>{const r=await mounted();await (button(r,'查看所选范围').props.onClick as()=>Promise<void>)();expect(mocks.adjust.mock.calls[0][0]).toMatchObject({session_id:'s1',action:'default',selected_kp_ids:['k1'],budget_minutes:90});});
it('new topic creates a clean explicit context without copying the old preview',async()=>{const r=await mounted();await (button(r,'新话题').props.onClick as()=>Promise<void>)();await flush();const selector=all(r).find(n=>n.type==='select')!;expect(selector.props.value).toBe('s3');expect(selector.props.disabled).toBe(false);expect(text(r)).not.toContain('当前试卷预览');expect(mocks.create).toHaveBeenCalledOnce();expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();});
it('late initial session list cannot drop the newly created topic',async()=>{const list=deferred<Array<{session_id:string;title:string;mode:string;purpose:string}>>();mocks.list.mockReturnValueOnce(list.promise);const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard'});unmount=host.unmount;await (button(host.root,'新话题').props.onClick as()=>Promise<void>)();list.resolve([{session_id:'s1',title:'旧话题',mode:'builtin',purpose:'qa'}]);await flush();expect(all(host.root).filter(n=>n.type==='option').some(n=>n.props.value==='s3')).toBe(true);expect(all(host.root).find(n=>n.type==='select')!.props.value).toBe('s3');});
it('topic switching stays available during preview selection and discards the late result',async()=>{const r=await mounted();const waiting=deferred<HomePreview>();mocks.adjust.mockReturnValueOnce(waiting.promise);await input(r,'线性代数60分钟');const send=submit(r);await flush();const select=all(r).find(n=>n.type==='select')!;expect(select.props.disabled).toBe(false);mocks.recover.mockResolvedValueOnce(null);await (select.props.onChange as(e:{target:{value:string}})=>Promise<void>)({target:{value:'s2'}});waiting.resolve(task('late'));await send;expect(all(r).find(n=>n.type==='select')!.props.value).toBe('s2');expect(text(r)).not.toContain('当前试卷预览');});
it('returning to each topic restores only its own messages and task',async()=>{const r=await mounted();const handler=all(r).find(n=>n.type==='select')!.props.onChange as(e:{target:{value:string}})=>Promise<void>;mocks.recover.mockResolvedValueOnce({...task('second'),session_id:'s2',message:'第二话题预览'});mocks.history.mockResolvedValueOnce([{message_id:'m2',role:'user',content:'第二话题问题'}]);await handler({target:{value:'s2'}});await flush();expect(text(r)).toContain('第二话题问题');expect(text(r)).toContain('第二话题预览');mocks.recover.mockResolvedValueOnce(task());mocks.history.mockResolvedValueOnce([{message_id:'m1',role:'user',content:'第一话题问题'}]);await handler({target:{value:'s1'}});await flush();expect(text(r)).toContain('第一话题问题');expect(text(r)).not.toContain('第二话题问题');expect(text(r)).not.toContain('第二话题预览');});
it('an empty saved topic can refresh even when session listing omits empty conversations',async()=>{mocks.list.mockResolvedValueOnce([]);mocks.recover.mockResolvedValueOnce(null);const r=await mounted();expect(mocks.recover).toHaveBeenCalledWith('s1');expect(all(r).find(n=>n.type==='select')!.props.value).toBe('s1');expect(all(r).filter(n=>n.type==='option').some(n=>n.props.value==='s1')).toBe(true);expect(text(r)).not.toContain('当前试卷预览');expect(mocks.adjust).not.toHaveBeenCalled();});
it('page recommendation loading cannot strand a restored topic in disabled selection state',async()=>{const loading=deferred<HomePreview|null>();mocks.recover.mockReturnValueOnce(loading.promise);const state=reactive({ids:['k1']});const wrapper={setup:()=>()=>h(Panel,{selectedKpIds:state.ids,budget:'standard'})};const host=mountStateComponent(wrapper,{});unmount=host.unmount;await flush();state.ids=['k2'];await flush();loading.resolve(task());await flush();expect(button(host.root,'确认并生成').props.disabled).toBe(false);expect(mocks.adjust).not.toHaveBeenCalled();});
it('asynchronously inserted topic option explicitly owns the native selected state',async()=>{const r=await mounted();await (button(r,'新话题').props.onClick as()=>Promise<void>)();await flush();const options=all(r).filter(n=>n.type==='option');expect(options.filter(n=>n.props.selected===true).map(n=>n.props.value)).toEqual(['s3']);expect(options.filter(n=>n.props.value!=='').every(n=>n.props.disabled!==true)).toBe(true);expect(all(r).find(n=>n.type==='select')!.props.disabled).toBe(false);});
it('cancelled persisted preview is labelled and cannot render as a usable paper after refresh',async()=>{mocks.recover.mockResolvedValueOnce({...task(),status:'cancelled'});const r=await mounted();expect(text(r)).toContain('预览已取消');expect(all(r).some(n=>n.props['data-testid']==='home-paper-detail')).toBe(false);expect(button(r,'确认并生成').props.disabled).toBe(true);expect(button(r,'重新生成预览')).toBeDefined();expect(mocks.confirm).not.toHaveBeenCalled();});
it('cancelling clears retained draft details but leaves other topics available',async()=>{const r=await mounted();mocks.adjust.mockResolvedValueOnce({...task(),status:'cancelled',message:'已取消预览'});await (button(r,'取消预览').props.onClick as()=>Promise<void>)();await flush();expect(text(r)).toContain('预览已取消');expect(all(r).some(n=>n.props['data-testid']==='home-paper-detail')).toBe(false);const select=all(r).find(n=>n.type==='select')!;mocks.recover.mockResolvedValueOnce({...task('two'),session_id:'s2'});await (select.props.onChange as(e:{target:{value:string}})=>Promise<void>)({target:{value:'s2'}});await flush();expect(all(r).some(n=>n.props['data-testid']==='home-paper-detail')).toBe(true);expect(button(r,'确认并生成').props.disabled).toBe(false);expect(mocks.confirm).not.toHaveBeenCalled();});
it('failed cancellation is uncertain, never falsely labelled as persisted cancelled',async()=>{const r=await mounted();mocks.adjust.mockRejectedValueOnce(new Error('响应未知'));await (button(r,'取消预览').props.onClick as()=>Promise<void>)();await flush();expect(text(r)).not.toContain('预览已取消');expect(text(r)).toContain('读取当前状态');expect(all(r).some(n=>n.props['data-testid']==='home-paper-detail')).toBe(false);expect(button(r,'确认并生成').props.disabled).toBe(true);});
function paper(id:string,sid:string,label:string,minutes:number[]):HomePreview{const t=task(id);return {...t,session_id:sid,message:`试卷预览：${minutes.length} 道，预计 ${minutes.reduce((a,b)=>a+b,0)} 分钟`,draft:{...t.draft!,total_minutes:minutes.reduce((a,b)=>a+b,0),questions:minutes.map((m,i)=>({...t.draft!.questions[0],question_id:`${id}-q${i}`,question_version_id:`${id}-v${i}`,stem:`${label}${i}`,minutes:m})),diff:{added:[id+'-q0'],removed:[],retained:[]}}};}
it('current summary, details and confirm share one explicit preview identity rather than historical prose',async()=>{const current=paper('linear','s1','线代',[20,30,30]);mocks.recover.mockResolvedValueOnce(current);mocks.history.mockResolvedValueOnce([{message_id:'history',role:'assistant',content:'试卷预览：3 道，预计 20 分钟（洛必达历史）'}]);const r=await mounted();const summary=all(r).find(n=>n.props['data-testid']==='home-current-summary');expect(summary).toBeDefined();expect(text(summary!)).toContain('80 分钟');expect(summary!.props['data-preview-id']).toBe('linear');expect(all(r).find(n=>n.props['data-testid']==='home-paper-detail')!.props['data-preview-id']).toBe('linear');expect(button(r,'确认并生成').props['data-preview-id']).toBe('linear');});
it('B in-flight revision stays unsafe until resolved and returning B cannot keep its old preview',async()=>{const a=paper('a','s1','A',[3,3,3,20,30,30]),old=paper('b-old','s2','洛必达',[3,5,12]),latest=paper('b-new','s2','线代',[20,30,30]);mocks.recover.mockImplementation(async(id:string)=>id==='s1'?a:old);const r=await mounted();const change=all(r).find(n=>n.type==='select')!.props.onChange as(e:{target:{value:string}})=>Promise<void>;await change({target:{value:'s2'}});const pending=deferred<HomePreview>();mocks.adjust.mockReturnValueOnce(pending.promise);await input(r,'线性代数90分钟');const send=submit(r);await flush();await change({target:{value:'s1'}});await change({target:{value:'s2'}});await flush();expect(button(r,'确认并生成').props.disabled).toBe(true);pending.resolve(latest);await send;await flush();const summary=all(r).find(n=>n.props['data-testid']==='home-current-summary')!;expect(summary.props['data-preview-id']).toBe('b-new');expect(text(summary)).toContain('80 分钟');expect(all(r).find(n=>n.props['data-testid']==='home-paper-detail')!.props['data-preview-id']).toBe('b-new');expect(button(r,'确认并生成').props['data-preview-id']).toBe('b-new');});
it('confirmation never posts a newer server preview that was not the displayed one',async()=>{const r=await mounted();mocks.recover.mockResolvedValueOnce(paper('newer','s1','线代',[20,30,30]));mocks.confirm.mockResolvedValue({...task(),receipt:{plan_id:'p1'}});await (button(r,'确认并生成').props.onClick as()=>Promise<void>)();await flush();expect(mocks.confirm).not.toHaveBeenCalled();expect(text(r)).toContain('预览已更新');expect(button(r,'确认并生成').props.disabled).toBe(true);});
it('a recovery started before the late revision cannot roll B back, and refresh keeps the new identity',async()=>{const a=paper('a','s1','A',[3,3,3,20,30,30]),old=paper('old','s2','洛必达',[3,5,12]),latest=paper('latest','s2','线代',[20,30,30]);mocks.recover.mockImplementation(async(id:string)=>id==='s1'?a:old);const r=await mounted();const change=all(r).find(n=>n.type==='select')!.props.onChange as(e:{target:{value:string}})=>Promise<void>;await change({target:{value:'s2'}});const pending=deferred<HomePreview>();mocks.adjust.mockReturnValueOnce(pending.promise);await input(r,'线性代数90分钟');const send=submit(r);await flush();await change({target:{value:'s1'}});const staleRead=deferred<HomePreview|null>();mocks.recover.mockReturnValueOnce(staleRead.promise);const back=change({target:{value:'s2'}});pending.resolve(latest);await send;staleRead.resolve(old);await back;await flush();expect(all(r).find(n=>n.props['data-testid']==='home-current-summary')!.props['data-preview-id']).toBe('latest');expect(all(r).find(n=>n.props['data-testid']==='home-paper-detail')!.props['data-preview-id']).toBe('latest');unmount?.();mocks.recover.mockResolvedValue(latest);const refreshed=await mounted();expect(all(refreshed).find(n=>n.props['data-testid']==='home-current-summary')!.props['data-preview-id']).toBe('latest');expect(button(refreshed,'确认并生成').props['data-preview-id']).toBe('latest');expect(text(all(refreshed).find(n=>n.props['data-testid']==='home-detail-summary')!)).toContain('80 分钟');});
it('free QA keeps its actual answer expanded without becoming a paper preview',async()=>{const r=await mounted();const qa=all(r).find(n=>n.type==='input'&&n.props.value==='qa')!;(qa.props['onUpdate:modelValue'] as(v:string)=>void)('qa');mocks.history.mockResolvedValueOnce([{message_id:'qa-answer',role:'assistant',content:'离线问答正文'}]);mocks.stream.mockResolvedValue(undefined);await input(r,'洛必达法则的适用条件是什么？');await submit(r);const history=all(r).find(n=>n.props['aria-label']==='对话历史')!;expect(history.props.open).toBe(true);expect(text(history)).toContain('离线问答正文');expect(mocks.adjust).not.toHaveBeenCalled();});

it('workbench reads initial recommendation independently without creating a preview or formal paper',async()=>{
 const initial=task();mocks.system.mockResolvedValue({recommendations:initial.context.system_recommendations,inventory:{practice_eligible_count:2,active_question_count:3},initial_paper:initial.draft,evidence:{states:[]},blockers:[],note:'缺少客观证据，仅作初始诊断'});
 const host=mountStateComponent(Panel,{selectedKpIds:['manual-other'],budget:'light',workbench:true});unmount=host.unmount;await flush();
 expect(mocks.system).toHaveBeenCalledOnce();expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();
 expect(all(host.root).some(n=>n.props['data-testid']==='workbench-system-recommendation')).toBe(true);
 expect(text(host.root)).not.toContain('缺少客观证据，仅作初始诊断');expect(text(host.root)).not.toContain('查看推荐的证据边界');expect(text(host.root)).not.toContain('查看推荐依据');expect(text(host.root)).toContain('本方案安排');
 const detail=all(host.root).find(n=>n.props['data-testid']==='home-paper-detail')!;
 const confirm=button(host.root,'确定生成试卷');expect(detail.props['data-preview-id']).toBe(confirm.props['data-preview-id']);
 mocks.confirm.mockResolvedValue({...task(),status:'answered',receipt:{plan_id:'p1'}});
 await (button(host.root,'确定生成试卷').props.onClick as()=>Promise<void>)();
 expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).toHaveBeenCalledWith('one',expect.objectContaining({session_id:'s1',draft_version:task().draft_version}));
});
it('initial recommendation failure cannot block topic recovery or free QA',async()=>{
 mocks.system.mockRejectedValue(new Error('初案读取失败'));
 const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard',workbench:true});unmount=host.unmount;await flush();
 expect(text(host.root)).toContain('初案读取失败');expect(text(host.root)).not.toContain('合成题');expect(button(host.root,'确定生成试卷').props.disabled).toBe(false);
});
it('workbench cancellation removes live constraint and questions together and refresh preserves cancellation',async()=>{
 const cancelled={...task(),draft:null,status:'cancelled',message:'已取消预览'};mocks.system.mockResolvedValue(null);
 mocks.recover.mockResolvedValue(cancelled);const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard',workbench:true});unmount=host.unmount;await flush();
 expect(text(host.root)).toContain('预览已取消');expect(all(host.root).some(n=>n.props['data-testid']==='workbench-constraints')).toBe(false);
 expect(all(host.root).some(n=>n.props['data-testid']==='home-paper-detail')).toBe(false);expect(button(host.root,'确定生成试卷').props.disabled).toBe(true);
});

it('missing initial API is identified as server contract mismatch and never fakes a successful initial paper',async()=>{
 mocks.system.mockRejectedValue(new ApiError('resource not found',404,'not_found'));
 mocks.recover.mockResolvedValue(null);
 const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard',workbench:true});unmount=host.unmount;await flush();
 expect(text(host.root)).toContain('接口/版本不匹配');expect(text(host.root)).toContain('/api/plans/today/home-recommendation');
 expect(text(host.root)).toContain('维护者');expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();
 expect(text(host.root)).not.toContain('resource not found');
 expect(all(host.root).filter(n=>n.type==='button'&&text(n).includes('确定生成试卷'))[0]?.props.disabled).toBe(true);
});

async function simpleMounted(overrides:Record<string,unknown>={}){const initial=task();mocks.system.mockResolvedValue({recommendations:initial.context.system_recommendations,inventory:{practice_eligible_count:2,active_question_count:2},initial_paper:initial.draft,evidence:{states:[]},blockers:[],note:'没有客观证据，仅初始诊断'});const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard',workbench:true,...overrides});unmount=host.unmount;await flush();return host.root;}

it('shows real eligible count beside every adjusted topic while hiding question details',async()=>{
 const current=task('counted-topic');
 current.draft!.scope_nodes=[{kp_id:'k1',name:'线代',assigned_count:2,allocation_status:'assigned'}];
 current.context.inventory={practice_eligible_count:12,available_to_append_count:12,
  recommendation_nodes:[{kp_id:'k1',name:'线代',practice_eligible_count:12,available_to_append_count:12}]};
 mocks.recover.mockResolvedValueOnce(current);
 const r=await simpleMounted();
 expect(text(r)).toContain('线代 · 12道可用题');
 expect(text(r)).toContain('今日安排 2 道');
 expect(text(r)).not.toContain('q1');expect(text(r)).not.toContain('合成题');
});

it('workbench exposes a restore-today button that restores the same baseline without confirming a paper',async()=>{
 const baseline=task('baseline');const current=task('adjusted');current.context.baseline=baseline.draft;
 current.draft!.questions[0]={...current.draft!.questions[0],question_id:'adjusted-q',question_version_id:'adjusted-v'};
 mocks.recover.mockResolvedValue(current);const r=await simpleMounted();
 expect(button(r,'恢复今日系统推荐')).toBeDefined();expect(all(r).find(n=>n.props['data-testid']==='home-current-summary')?.props['data-preview-id']).toBe('adjusted');
 const restored=task('restored');restored.draft=baseline.draft;restored.context.baseline=baseline.draft;mocks.adjust.mockResolvedValueOnce(restored);
 await (button(r,'恢复今日系统推荐').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenCalledOnce();expect(mocks.adjust.mock.calls[0][0]).toMatchObject({action:'restore',session_id:'s1'});
 expect(all(r).find(n=>n.props['data-testid']==='home-current-summary')?.props['data-preview-id']).toBe('restored');
 expect(text(r)).toContain('已恢复今日系统推荐');expect(mocks.confirm).not.toHaveBeenCalled();
 await (button(r,'恢复今日系统推荐').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenCalledOnce();expect(text(r)).toContain('已经是今日系统推荐');expect(mocks.confirm).not.toHaveBeenCalled();
});
it('simple homepage has two primary actions, no stage navigation or extra preview step',async()=>{mocks.recover.mockResolvedValue(null);const r=await simpleMounted();expect(button(r,'询问奶蛙')).toBeDefined();expect(button(r,'确定生成试卷')).toBeDefined();expect(text(r)).not.toContain('01 · 系统初案');expect(text(r)).not.toContain('查看所选范围的推荐预览');expect(text(r)).not.toContain('查看系统初案的题目预览');});
it('direct generation first validates a real default preview then confirms the same displayed identities',async()=>{mocks.recover.mockResolvedValue(null);mocks.list.mockResolvedValue([]);mocks.adjust.mockResolvedValue({...task(),session_id:'s3'});mocks.confirm.mockResolvedValue({...task(),session_id:'s3',status:'answered',receipt:{plan_id:'p1'}});const r=await simpleMounted();mocks.recover.mockResolvedValue({...task(),session_id:'s3'});await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();await flush();expect(mocks.adjust).toHaveBeenCalledWith(expect.objectContaining({action:'default',selected_kp_ids:['k1'],budget_minutes:90}));expect(mocks.confirm).toHaveBeenCalledWith('one',expect.objectContaining({session_id:'s3',draft_version:task().draft_version}));expect(text(r)).toContain('已生成正式试卷');expect(button(r,'确定生成试卷').props.disabled).toBe(true);});
it('changed default selection is presented for review instead of silently confirming another paper',async()=>{mocks.recover.mockResolvedValue(null);mocks.list.mockResolvedValue([]);const newer={...task('new'),session_id:'s3'};newer.draft!.questions[0].question_id='different';mocks.adjust.mockResolvedValue(newer);const r=await simpleMounted();await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();await flush();expect(mocks.confirm).not.toHaveBeenCalled();expect(text(r)).toContain('推荐已更新');expect(text(r)).not.toContain('different');});
it('daily recovery distinguishes loading, failure and genuinely empty daily chat',async()=>{const pending=deferred<HomePreview|null>();mocks.recover.mockReturnValueOnce(pending.promise);mocks.system.mockResolvedValue(null);const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard',workbench:true});unmount=host.unmount;await flush();expect(text(host.root)).toContain('正在恢复今天的聊天');expect(button(host.root,'确定生成试卷').props.disabled).toBe(true);expect(text(host.root)).not.toContain('合成题');pending.reject(new Error('回读失败'));await flush();expect(text(host.root)).toContain('聊天恢复失败');mocks.recover.mockResolvedValueOnce(null);await (button(host.root,'重试恢复').props.onClick as()=>Promise<void>)();await flush();expect(text(host.root)).toContain('尚未生成正式试卷');});
it('confirmed read-only workbench exposes saved questions and reasons without another formal write',async()=>{mocks.recover.mockResolvedValue({...task(),status:'answered',receipt:{plan_id:'p1'}});const r=await simpleMounted({formalPaper:{plan_id:'p1',total_count:2,estimated_minutes:60},readOnly:true});expect(text(r)).toContain('已确认的正式试卷');expect(text(r)).not.toContain('合成题');expect(text(r)).not.toContain('本次待确认预览');expect(button(r,'确定生成试卷').props.disabled).toBe(true);expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();});

it('another confirmed topic cannot masquerade as the current formal paper',async()=>{mocks.recover.mockResolvedValue({...task(),status:'answered',receipt:{plan_id:'older-paper'}});const r=await simpleMounted({formalPaper:{plan_id:'current-paper',total_count:6,estimated_minutes:89},readOnly:true});expect(text(r)).toContain('其他试卷的已确认记录');expect(text(r)).toContain('不等同于当前正式卷');expect(button(r,'确定生成试卷').props.disabled).toBe(true);expect(mocks.confirm).not.toHaveBeenCalled();});

it('recommendation list and frog adjustment are siblings while full paper stays outside the side panel',async()=>{const r=await simpleMounted();const list=all(r).find(n=>n.props['data-testid']==='home-recommendation-list')!;const frog=all(r).find(n=>n.props['data-testid']==='home-frog-adjustment')!;const full=all(r).find(n=>n.props['data-testid']==='home-paper-detail')!;expect(list.parent).toBe(frog.parent);expect(text(list)).toContain('系统推荐知识点');expect(text(frog)).toContain('发送');expect(all(frog).includes(full)).toBe(false);expect(text(r)).not.toContain('01 · 系统初案');});
it('shows the restore-today-recommendation action beside the current recommendation',async()=>{const r=await simpleMounted();const restore=all(r).find(n=>n.props['data-testid']==='restore-home-recommendation');expect(restore).toBeDefined();expect(text(restore!)).toContain('恢复今日系统推荐');expect(restore!.props.disabled).toBe(false);});

it('daily sidebar shows only conversation and composer, not topic management',async()=>{const r=await simpleMounted();const frog=all(r).find(n=>n.props['data-testid']==='home-frog-adjustment')!;expect(all(frog).some(n=>n.type==='select')).toBe(false);expect(text(frog)).not.toContain('新话题');expect(all(frog).some(n=>n.props['data-testid']==='home-daily-chat')).toBe(true);expect(button(r,'调整知识点')).toBeDefined();});
it('workbench reads and writes its daily conversation through the study-owned session scope',async()=>{const r=await simpleMounted();expect(mocks.list).toHaveBeenCalledWith('builtin','study');expect(mocks.history).toHaveBeenCalledWith('s1','study');const qa=all(r).find(n=>n.type==='input'&&n.props.value==='qa')!;(qa.props['onUpdate:modelValue'] as(v:string)=>void)('qa');await input(r,'洛必达法则的适用条件是什么？');mocks.stream.mockResolvedValue(undefined);await submit(r);expect(mocks.stream).toHaveBeenCalledWith('s1','洛必达法则的适用条件是什么？',expect.any(Function),expect.any(AbortSignal),{purpose:'study'});expect(mocks.adjust).not.toHaveBeenCalled();});
it('manual scope edit stages checkboxes until apply and cancellation creates no preview',async()=>{const state=reactive({selectedKpIds:['k1'],budget:'standard',workbench:true});mocks.system.mockResolvedValue({recommendations:task().context.system_recommendations,initial_paper:task().draft,inventory:null,evidence:{states:[]},blockers:[],note:''});const host=mountStateComponent({setup:()=>()=>h(Panel,{...state,onScopeChange:(ids:string[])=>{state.selectedKpIds=ids;}},{'manual-controls':()=>h('div','原知识点选择器')})},{});unmount=host.unmount;await flush();await (button(host.root,'调整知识点').props.onClick as()=>Promise<void>)();await flush();expect(text(host.root)).toContain('原知识点选择器');state.selectedKpIds=['k2'];await flush();expect(mocks.adjust).not.toHaveBeenCalled();await (button(host.root,'取消').props.onClick as()=>Promise<void>)();await flush();expect(state.selectedKpIds).toEqual(['k1']);expect(mocks.adjust).not.toHaveBeenCalled();await (button(host.root,'调整知识点').props.onClick as()=>Promise<void>)();state.selectedKpIds=['k2'];await flush();await (button(host.root,'保存调整').props.onClick as()=>Promise<void>)();await flush();expect(mocks.adjust).toHaveBeenCalledWith(expect.objectContaining({action:'default',selected_kp_ids:['k2']}));});

it('same-day refresh reuses the daily session and never creates a duplicate on read',async()=>{const t=task();mocks.list.mockResolvedValue([{session_id:'s1',title:homeDayTitle(homeStudyDay()),mode:'builtin',purpose:'study'}]);mocks.history.mockResolvedValue([{message_id:'m',role:'assistant',content:'今天的记录'}]);let r=await simpleMounted();expect(text(r)).toContain('今天的记录');expect(localStorage.getItem(homeDayKey(homeStudyDay()))).toBe('s1');unmount?.();r=await simpleMounted();expect(text(r)).toContain('今天的记录');expect(mocks.create).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();});
it('does not use a legacy shared pointer unless the study-scoped server list owns it',async()=>{mocks.list.mockResolvedValue([]);localStorage.setItem('naiwa:home-recommendation:session:v1','qa-owned-session');const r=await simpleMounted();expect(text(r)).toContain('今天想怎么练');expect(mocks.recover).not.toHaveBeenCalled();expect(mocks.history).not.toHaveBeenCalled();expect(mocks.create).not.toHaveBeenCalled();});
it('does not restore a daily pointer omitted from the server-authorized builtin study list',async()=>{
 const stale='wrong-mode-study-session';localStorage.setItem(homeDayKey(homeStudyDay()),stale);
 mocks.list.mockResolvedValue([{session_id:'s1',title:homeDayTitle(homeStudyDay()),mode:'builtin',purpose:'study'}]);
 mocks.recover.mockImplementation(async(id:string)=>{if(id===stale)throw new ApiError('access forbidden',403,'forbidden');return task();});
 const r=await simpleMounted();
 expect(mocks.recover).toHaveBeenCalledWith('s1');expect(mocks.recover).not.toHaveBeenCalledWith(stale);
 expect(text(r)).not.toContain('access forbidden');expect(localStorage.getItem(homeDayKey(homeStudyDay()))).toBe('s1');
});
it('after a forbidden preview request, explicit state recovery clears only the denied binding and never replays the write',async()=>{
 const r=await simpleMounted();await input(r,'今天只练线性代数，60分钟');
 mocks.adjust.mockRejectedValueOnce(new ApiError('access forbidden',403,'forbidden'));
 await submit(r);expect(mocks.adjust).toHaveBeenCalledTimes(1);expect(text(r)).toContain('access forbidden');
 mocks.recover.mockRejectedValueOnce(new ApiError('access forbidden',403,'forbidden'));
 await (button(r,'读取当前状态 / 核对回执').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenCalledTimes(1);expect(mocks.confirm).not.toHaveBeenCalled();
 expect(localStorage.getItem(homeDayKey(homeStudyDay()))).toBeNull();expect(text(r)).toContain('首页学习会话当前不可访问');
 await input(r,'今天只练线性代数，60分钟');mocks.adjust.mockResolvedValueOnce({...task('new'),session_id:'s3'});await submit(r);
 expect(mocks.create).toHaveBeenCalledWith(homeDayTitle(homeStudyDay()),'builtin',{purpose:'study'});
 expect(mocks.adjust).toHaveBeenLastCalledWith(expect.objectContaining({session_id:'s3',goal:'今天只练线性代数，60分钟'}));
});
it('Shanghai midnight starts an empty day and rejects a late yesterday result without deleting history',async()=>{vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-27T15:59:50Z'));const old=task();mocks.list.mockResolvedValue([{session_id:'s1',title:homeDayTitle(homeStudyDay()),mode:'builtin',purpose:'study'}]);mocks.recover.mockResolvedValue(old);mocks.history.mockResolvedValue([{message_id:'m',role:'assistant',content:'昨天的记录'}]);const r=await simpleMounted();mocks.system.mockResolvedValue({recommendations:[],initial_paper:null,evidence:{states:[]},blockers:[],note:'次日推荐待准备'});expect(text(r)).toContain('昨天的记录');const pending=deferred<HomePreview>();mocks.adjust.mockReturnValueOnce(pending.promise);await input(r,'改为30分钟');const sending=submit(r);await flush();mocks.list.mockResolvedValue([]);mocks.recover.mockResolvedValue(old);vi.setSystemTime(new Date('2026-10-27T16:00:30Z'));await vi.advanceTimersByTimeAsync(30000);await flush();expect(text(r)).toContain('2026-10-28');expect(text(r)).not.toContain('昨天的记录');expect(text(r)).not.toContain('合成题');pending.resolve(old);await sending;await flush();expect(text(r)).not.toContain('合成题');expect(localStorage.getItem(homeDayKey('2026-10-27'))).toBe('s1');expect(mocks.confirm).not.toHaveBeenCalled();expect(mocks.create).not.toHaveBeenCalled();});

it('saving knowledge scope retains current numeric budget instead of reverting to preset90',async()=>{const current=task();current.budget_minutes=60;current.draft!.budget_minutes=60;mocks.recover.mockResolvedValue(current);const r=await simpleMounted();await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();expect(mocks.adjust).toHaveBeenCalledWith(expect.objectContaining({action:'default',budget_minutes:60}));});

it('first reason answer is restored in daily chat without inventing a preview',async()=>{mocks.recover.mockResolvedValue(null);mocks.list.mockResolvedValue([]);const r=await simpleMounted();mocks.adjust.mockResolvedValue({kind:'explanation',session_id:'s3',message:'来自真实推荐策略'});mocks.history.mockResolvedValue([{message_id:'reason',role:'assistant',content:'来自真实推荐策略'}]);await input(r,'为什么推荐这些知识点？');await submit(r);expect(text(r)).toContain('来自真实推荐策略');expect(mocks.confirm).not.toHaveBeenCalled();expect(all(r).some(n=>n.props['data-testid']==='home-paper-detail')).toBe(false);});
it('confirmation checks the day at click time even before the periodic rollover timer fires',async()=>{vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-27T15:59:59Z'));mocks.recover.mockResolvedValue(task());const r=await simpleMounted();vi.setSystemTime(new Date('2026-10-27T16:00:01Z'));await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();await flush();expect(mocks.confirm).not.toHaveBeenCalled();expect(mocks.adjust).not.toHaveBeenCalled();expect(text(r)).toContain('2026-10-28');});

it('workbench owns one generation button in recommendation area and chat cannot confirm',async()=>{
 const host=mountStateComponent(Panel,{selectedKpIds:['k1'],budget:'standard',workbench:true});unmount=host.unmount;await flush();
 const buttons=all(host.root).filter(n=>n.props['data-testid']==='confirm-home-paper');expect(buttons).toHaveLength(1);
 const recommendation=all(host.root).find(n=>n.props['data-testid']==='home-recommendation-list')!;
 expect(all(recommendation)).toContain(buttons[0]);
 const chat=all(host.root).find(n=>n.props['data-testid']==='home-frog-adjustment')!;
 expect(all(chat).filter(n=>n.props['data-testid']==='confirm-home-paper')).toHaveLength(0);
 await input(host.root,'确认');await submit(host.root);
 expect(mocks.confirm).not.toHaveBeenCalled();expect(mocks.adjust).not.toHaveBeenCalled();expect(text(host.root)).toContain('请在系统推荐区域点击');
});

it('summary retains every selected base node and addition even when a base node has no assigned question',async()=>{
 const merged=task('merged');merged.draft!.selected_kp_ids=['k1','base2','lh'];merged.draft!.questions=[...merged.draft!.questions,{...merged.draft!.questions[0],question_id:'extra',question_version_id:'extra-v',kp_id:'lh',kp_name:'洛必达法则',minutes:5}];merged.draft!.total_minutes=65;
 merged.context.system_recommendations.push({kp_id:'base2',name:'矩阵的秩',reason:'insufficient_evidence',next_step:'初始诊断',requires_graduation_set_confirmation:false});
 mocks.recover.mockResolvedValue(merged);const r=await simpleMounted();
 const list=all(r).find(n=>n.props['data-testid']==='home-recommendation-list')!;
 expect(text(list)).toContain('线代');expect(text(list)).toContain('矩阵的秩');expect(text(list)).toContain('洛必达法则');
 const detail=all(r).find(n=>n.props['data-testid']==='home-paper-detail')!;
 let ancestor=detail.parent;while(ancestor&&ancestor.type!=='details')ancestor=ancestor.parent;
 expect(ancestor==null).toBe(true);expect(text(detail)).not.toContain('合成题');
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe('merged');
 unmount?.();mocks.recover.mockResolvedValue(merged);const restored=await simpleMounted();expect(text(all(restored).find(n=>n.props['data-testid']==='home-recommendation-list')!)).toContain('矩阵的秩');
 unmount?.();mocks.recover.mockResolvedValue({...merged,status:'answered',receipt:{plan_id:'p1'}});const confirmed=await simpleMounted();const confirmedList=all(confirmed).find(n=>n.props['data-testid']==='home-recommendation-list')!;expect(text(confirmedList)).toContain('矩阵的秩');expect(text(confirmedList)).toContain('洛必达法则');expect(button(confirmed,'确定生成试卷').props.disabled).toBe(true);
});

it('daily chat is hidden by default and reopen preserves history and draft without creating requests',async()=>{
 mocks.history.mockResolvedValue([{message_id:'today',role:'assistant',content:'当天记录保留'}]);const r=await simpleMounted();
 const panel=all(r).find(n=>n.props['data-testid']==='home-frog-adjustment')!;
 expect(panel.style.display).toBe('none');
 const launch=button(r,'询问奶蛙');const focus=vi.fn();Object.assign(launch,{focus});expect(launch.props['aria-expanded']).toBe(false);
 await (launch.props.onClick as()=>Promise<void>)();await flush();expect(panel.style.display).not.toBe('none');expect(text(panel)).toContain('当天记录保留');
 expect(all(panel).find(n=>n.type==='textarea')!.props.placeholder).toBe('告诉奶蛙你想怎么调整……');
 expect(button(panel,'发送')).toBeDefined();
 await (button(panel,'关闭').props.onClick as()=>Promise<void>)();await flush();expect(panel.style.display).toBe('none');expect(focus).toHaveBeenCalledOnce();
 await (launch.props.onClick as()=>Promise<void>)();await flush();expect(text(panel)).toContain('当天记录保留');
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe('one');expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();expect(mocks.create).not.toHaveBeenCalled();
});
it('closing daily chat does not cancel an in-flight adjustment or replace its session',async()=>{
 const r=await simpleMounted();Object.assign(button(r,'询问奶蛙'),{focus:vi.fn()});await (button(r,'询问奶蛙').props.onClick as()=>Promise<void>)();await input(r,'保留推荐，减少到5道题');
 const pending=deferred<HomePreview>();mocks.adjust.mockReturnValueOnce(pending.promise);const sending=submit(r);await flush();
 const panel=all(r).find(n=>n.props['data-testid']==='home-frog-adjustment')!;await (button(panel,'关闭').props.onClick as()=>Promise<void>)();await flush();
 expect(panel.style.display).toBe('none');pending.resolve(task('updated'));await sending;await flush();
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe('updated');expect(mocks.adjust).toHaveBeenCalledTimes(1);expect(mocks.confirm).not.toHaveBeenCalled();
 await (button(r,'询问奶蛙').props.onClick as()=>Promise<void>)();await flush();expect(panel.style.display).not.toBe('none');
});

it('failed adjustment is not labelled initial and explicit restore only prepares a recommendation',async()=>{
 mocks.recover.mockResolvedValue({...task(),status:'failed',draft:null,error_code:'bank_lookup_failed',message:'真实题库检索失败'});
 const r=await simpleMounted();expect(button(r,'确定生成试卷').props.disabled).toBe(true);
 const status=all(r).find(n=>n.props.class==='recommendation-status')!;expect(text(status)).toContain('调整失败');
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenCalledWith(expect.objectContaining({action:'default'}));expect(mocks.confirm).not.toHaveBeenCalled();
});

it('homepage summary shows assigned counts instead of bank inventory',async()=>{
 const r=await simpleMounted();const list=all(r).find(n=>n.props['data-testid']==='home-recommendation-list')!;
 expect(text(list)).toContain('安排 2 道');expect(text(list)).not.toContain('合格库存');
 expect(text(all(r).find(n=>n.props['data-testid']==='home-overview')!)).toContain('本方案安排 2 道');
});
it('larger workload requires consent before the only formal confirmation request',async()=>{
 const expanded=task('expanded');expanded.context.workload={requested_budget_minutes:45,effective_budget_minutes:60,extra_minutes:15,requires_confirmation:true};
 mocks.recover.mockResolvedValue(expanded);const consent=vi.fn().mockReturnValue(false);vi.stubGlobal('window',{confirm:consent,addEventListener:vi.fn(),removeEventListener:vi.fn()});
 const r=await simpleMounted();await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();expect(mocks.confirm).not.toHaveBeenCalled();
 consent.mockReturnValue(true);mocks.confirm.mockResolvedValue({...expanded,status:'answered',receipt:{plan_id:'p'}});
 await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();expect(mocks.confirm).toHaveBeenCalledWith('expanded',expect.objectContaining({accept_workload_increase:true}));
});

it('failed adjustment keeps restored valid paper confirmable after refresh',async()=>{
 const original=task();mocks.adjust.mockResolvedValue({...original,adjustment_error:'新增题查询失败'});
 const r=await simpleMounted();await input(r,'帮我加入一道洛必达的题目进来');await submit(r);
 expect(button(r,'确定生成试卷').props.disabled).toBe(false);expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(original.task_id);expect(text(r)).toContain('加入失败，原系统推荐已保留');
 unmount?.();mocks.recover.mockResolvedValue({...original,adjustment_error:'新增题查询失败'});const restored=await simpleMounted();expect(button(restored,'确定生成试卷').props.disabled).toBe(false);
});
it('actual workload above stored budget stays confirmable only with coherent warning evidence',async()=>{
 const large=task('large');large.draft!.questions=Array.from({length:120},(_,i)=>({...large.draft!.questions[0],question_id:`q${i}`,minutes:3}));large.draft!.total_minutes=360;
 large.context.workload={requested_budget_minutes:90,effective_budget_minutes:360,extra_minutes:270,requires_confirmation:true};
 mocks.recover.mockResolvedValue(large);const r=await simpleMounted();expect(button(r,'确定生成试卷').props.disabled).toBe(false);
 expect(text(r)).toContain('本方案安排 120 道');expect(text(r)).toContain('预计 360 分钟');expect(text(r)).toContain('多 270 分钟');
});

it('a failed response keeps its failure notice while restoring its explicit valid fallback',async()=>{
 const original=task();mocks.adjust.mockResolvedValue({...task('failed'),status:'failed',draft:null,message:'真实题库异常',fallback_preview:original});
 const r=await simpleMounted();await input(r,'帮我加入一道洛必达的题目进来');await submit(r);
 expect(button(r,'确定生成试卷').props.disabled).toBe(false);expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(original.task_id);expect(text(r)).not.toContain('真实题库异常');expect(text(r)).toContain('加入失败，原系统推荐已保留');
});

it('legacy failed adjustment retains18 saved questions and the main button revalidates them before confirmation',async()=>{
 const original=task('base');original.draft!.questions=Array.from({length:18},(_,i)=>({...original.draft!.questions[0],question_id:`q${i}`,question_version_id:`v${i}`,minutes:5}));original.draft!.total_minutes=90;
 const failed={...task('failed'),status:'failed',draft:null,error_code:'bank_lookup_failed',message:'真实题库检索失败',retained_baseline:original.draft};
 mocks.recover.mockResolvedValue(failed);const r=await simpleMounted();
 expect(text(r)).toContain('本方案安排 18 道');expect(text(r)).toContain('加入失败，原系统推荐已保留');
 expect(button(r,'确定生成试卷').props.disabled).toBe(false);expect(mocks.confirm).not.toHaveBeenCalled();
 mocks.adjust.mockResolvedValue(original);mocks.recover.mockResolvedValue(original);
 await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenCalledWith(expect.objectContaining({action:'restore'}));
 expect(mocks.confirm).toHaveBeenCalledWith('base',expect.objectContaining({draft_version:original.draft_version}));
});

it('restoring a retained baseline never silently confirms a changed question version',async()=>{
 const original=task('base');const failed={...task('failed'),status:'failed',draft:null,message:'查询失败',retained_baseline:original.draft};
 mocks.recover.mockResolvedValue(failed);const r=await simpleMounted();
 const changed=task('new');changed.draft!.questions[0].question_version_id='new-version';mocks.adjust.mockResolvedValue(changed);
 await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.confirm).not.toHaveBeenCalled();expect(text(r)).toContain('推荐已更新');
});

it('budget choice keeps A active until accepted and never generates a formal paper on acceptance',async()=>{
 const original=task();const candidate=task('proposed');candidate.draft!.questions.push({...candidate.draft!.questions[0],question_id:'extra',minutes:45});candidate.draft!.total_minutes=105;
 candidate.context.workload={requested_budget_minutes:90,effective_budget_minutes:105,extra_minutes:15,requires_confirmation:true};
 candidate.context.workload_pending=true;
 mocks.adjust.mockResolvedValue({...candidate,fallback_preview:original});const r=await simpleMounted();
 await input(r,'再加一道洛必达');await submit(r);
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(original.task_id);
 expect(button(r,'确定生成试卷').props.disabled).toBe(false);
 expect(text(r)).toContain('超过建议预算 15 分钟');
 const accepted={...candidate,context:{...candidate.context,workload_pending:false,workload_accepted:true}};
 mocks.adjust.mockResolvedValue(accepted);
 await (button(r,'接受此方案').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenLastCalledWith(expect.objectContaining({action:'accept_workload',expected_version:candidate.draft_version}));
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(candidate.task_id);
 expect(mocks.confirm).not.toHaveBeenCalled();
});

it('pending budget choice restores on refresh and continuing adjustment keeps the exact active original',async()=>{
 const original=task();const candidate=task('pending');candidate.context.workload_pending=true;
 candidate.draft!.questions.push({...candidate.draft!.questions[0],question_id:'extra',minutes:45});candidate.draft!.total_minutes=105;
 candidate.context.workload={requested_budget_minutes:90,effective_budget_minutes:105,extra_minutes:15,requires_confirmation:true};
 mocks.recover.mockResolvedValue({...original,workload_candidate:candidate});const r=await simpleMounted();
 expect(button(r,'接受此方案')).toBeDefined();expect(button(r,'确定生成试卷').props.disabled).toBe(false);
 mocks.adjust.mockResolvedValue(original);await (button(r,'返回调整').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenLastCalledWith(expect.objectContaining({action:'dismiss_workload',expected_version:candidate.draft_version}));
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(original.task_id);expect(mocks.confirm).not.toHaveBeenCalled();
 expect(all(r).some(n=>n.props['data-testid']==='home-workload-choice')).toBe(false);
});

it('failed adjustment has one concise chat notice, no duplicate summary error or redundant controls, and can edit again',async()=>{
 const original=task();const failure='真实题库检索失败，没有加入今日卷。请读取当前状态后重试；不会转为通用知识回答。';
 mocks.adjust.mockResolvedValue({...task('failed'),status:'failed',draft:null,message:failure,fallback_preview:original});
 mocks.history.mockResolvedValue([{message_id:'error',role:'assistant',content:failure}]);
 const r=await simpleMounted();await input(r,'添加一道题');await submit(r);
 const chat=all(r).find(n=>n.props['data-testid']==='home-daily-chat')!;
 expect(text(chat).match(/加入失败，原系统推荐已保留/g)).toHaveLength(1);
 expect(text(r)).not.toContain('不会转为通用知识回答');
 expect(text(r)).not.toContain('推荐依据与其他操作');expect(text(r)).not.toContain('采用系统推荐重新调整');
 expect(button(r,'确定生成试卷').props.disabled).toBe(false);
 expect(button(r,'调整知识点').props.disabled).toBe(false);
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();
 expect(button(r,'保存调整')).toBeDefined();
 mocks.adjust.mockResolvedValue(task('success'));await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe('success');
});

it('manual scope save updates the persisted scheme without sending or refreshing dialogue and survives reopen/refresh',async()=>{
 const messages=[{message_id:'old',role:'assistant',content:'用户主动发起的旧对话'}];mocks.history.mockResolvedValue(messages);
 mocks.system.mockResolvedValue({recommendations:task().context.system_recommendations,initial_paper:task().draft,evidence:{states:[]},blockers:[],note:''});
 const state=reactive({selectedKpIds:['k1'],budget:'standard',workbench:true});
 const host=mountStateComponent({setup:()=>()=>h(Panel,{...state,onScopeChange:(ids:string[])=>{state.selectedKpIds=ids;}})},{});unmount=host.unmount;await flush();
 const r=host.root,reads=mocks.history.mock.calls.length;
 const saved=task('manual');saved.draft!.selected_kp_ids=['k2'];saved.draft!.questions=saved.draft!.questions.map(q=>({...q,kp_id:'k2',kp_name:'矩阵的秩'}));
 saved.context.request_origin='system';mocks.adjust.mockResolvedValue(saved);
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();state.selectedKpIds=['k2'];await flush();
 await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenLastCalledWith(expect.objectContaining({action:'default',goal:'',selected_kp_ids:['k2']}));
 expect(mocks.stream).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();expect(mocks.history).toHaveBeenCalledTimes(reads);
 expect(text(all(r).find(n=>n.props['data-testid']==='home-recommendation-list')!)).toContain('矩阵的秩');
 expect(text(all(r).find(n=>n.props['data-testid']==='home-daily-chat')!)).toBe('奶蛙用户主动发起的旧对话');
 const launcher=button(r,'询问奶蛙'),focus=vi.fn();Object.assign(launcher,{focus});
 await (launcher.props.onClick as()=>Promise<void>)();await (button(r,'关闭').props.onClick as()=>Promise<void>)();await (launcher.props.onClick as()=>Promise<void>)();expect(focus).toHaveBeenCalledOnce();
 expect(mocks.history).toHaveBeenCalledTimes(reads);expect(text(r)).not.toContain('查看系统推荐');
 // A subsequent real chat carries the latest saved server identity, not old A.
 mocks.adjust.mockResolvedValue({...saved,task_id:'chat-next'});await input(r,'再帮我加入一道洛必达法则的题目。');await submit(r);
 expect(mocks.adjust).toHaveBeenLastCalledWith(expect.objectContaining({action:'adjust',expected_version:saved.draft_version,session_id:saved.session_id}));
 expect(mocks.history).toHaveBeenCalledTimes(reads+1);
 unmount?.();mocks.recover.mockResolvedValue(saved);const refreshed=await simpleMounted();
 expect(button(refreshed,'确定生成试卷').props['data-preview-id']).toBe(saved.task_id);
 expect(text(all(refreshed).find(n=>n.props['data-testid']==='home-recommendation-list')!)).toContain('矩阵的秩');
 expect(text(all(refreshed).find(n=>n.props['data-testid']==='home-daily-chat')!)).toBe('奶蛙用户主动发起的旧对话');
});

it('a manual save failure preserves A and is a system notice instead of a synthetic chat message',async()=>{
 mocks.history.mockResolvedValue([]);const original=task();const failed={...task('manual-failed'),status:'failed',draft:null,message:'选题服务异常',context:{...task().context,request_origin:'system' as const},fallback_preview:original};
 const r=await simpleMounted();const reads=mocks.history.mock.calls.length;mocks.adjust.mockResolvedValue(failed);
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(all(r).some(n=>n.props['data-testid']==='home-scope-editor')).toBe(true);
 expect(all(r).some(n=>n.props['data-testid']==='home-system-edit-error')).toBe(true);
 expect(button(r,'保存调整').props.disabled).toBe(false);
 await (button(r,'取消').props.onClick as()=>Promise<void>)();await flush();
 expect(button(r,'确定生成试卷').props.disabled).toBe(false);expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(original.task_id);
 expect(text(all(r).find(n=>n.props['data-testid']==='home-daily-chat')!)).not.toContain('失败');
 expect(mocks.history).toHaveBeenCalledTimes(reads);expect(mocks.stream).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();
});

it('scope editing is a standalone selection view without homepage recommendation, chat, budget or generation controls',async()=>{
 const r=await simpleMounted();await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();
 expect(all(r).some(n=>n.props['data-testid']==='home-overview')).toBe(false);
 expect(all(r).some(n=>n.props['data-testid']==='home-recommendation-list')).toBe(false);
 expect(all(r).some(n=>n.props['data-testid']==='home-frog-adjustment')).toBe(false);
 expect(all(r).some(n=>n.props['data-testid']==='confirm-home-paper')).toBe(false);
 expect(text(r)).toContain('当前已选知识点');expect(text(r)).not.toContain('查看题目明细');
 expect(button(r,'完成')).toBeDefined();expect(button(r,'取消')).toBeDefined();
 await (button(r,'取消').props.onClick as()=>Promise<void>)();await flush();
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(task().task_id);
 expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();
});

it('manual save has its own saving state and cannot turn the frog into processing',async()=>{
 const r=await simpleMounted();const pendingSave=deferred<HomePreview>();mocks.adjust.mockReturnValueOnce(pendingSave.promise);
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();
 const saving=(button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(text(r)).toContain('保存中');expect(text(r)).not.toContain('处理中');expect(text(r)).not.toContain('奶蛙正在');
 expect(mocks.stream).not.toHaveBeenCalled();pendingSave.resolve(task('manual-saved'));await saving;await flush();
 expect(text(button(r,'询问奶蛙'))).not.toContain('处理中');expect(button(r,'确定生成试卷').props.disabled).toBe(false);
 expect(mocks.confirm).not.toHaveBeenCalled();
});

it('the chat budget card accepts exact19 identities without parsing confirmation text or generating a paper',async()=>{
 const original=task();original.draft!.questions=Array.from({length:18},(_,i)=>({...original.draft!.questions[0],question_id:`q${i}`,question_version_id:`v${i}`,minutes:5}));original.draft!.total_minutes=90;
 const proposed=task('candidate19');proposed.draft!.questions=[...original.draft!.questions,{...original.draft!.questions[0],question_id:'new',question_version_id:'new-v',minutes:5}];proposed.draft!.total_minutes=95;
 proposed.context.workload_pending=true;proposed.context.workload={requested_budget_minutes:90,effective_budget_minutes:95,extra_minutes:5,requires_confirmation:true};
 mocks.recover.mockResolvedValue({...original,workload_candidate:proposed});const r=await simpleMounted();
 const chat=all(r).find(n=>n.props['data-testid']==='home-frog-adjustment')!;const card=all(r).find(n=>n.props['data-testid']==='home-workload-choice')!;
 expect(all(chat)).toContain(card);expect(text(card)).toContain('19');expect(button(r,'接受此方案')).toBeDefined();expect(button(r,'返回调整')).toBeDefined();
 const launcher=button(r,'询问奶蛙');Object.assign(launcher,{focus:vi.fn()});
 await (launcher.props.onClick as()=>Promise<void>)();await (button(r,'关闭').props.onClick as()=>Promise<void>)();await (launcher.props.onClick as()=>Promise<void>)();await flush();
 expect(all(r).find(n=>n.props['data-testid']==='home-workload-choice')!.props['data-preview-id']).toBe(proposed.task_id);expect(mocks.adjust).not.toHaveBeenCalled();
 await input(r,'我确定');await submit(r);expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.stream).not.toHaveBeenCalled();
 const accepted={...proposed,context:{...proposed.context,workload_pending:false,workload_accepted:true}};
 const acceptance=deferred<HomePreview>();mocks.adjust.mockReturnValue(acceptance.promise);
 const accepting=(button(r,'接受此方案').props.onClick as()=>Promise<void>)();
 const duplicate=(button(r,'接受此方案').props.onClick as()=>Promise<void>)();expect(mocks.adjust).toHaveBeenCalledTimes(1);
 acceptance.resolve(accepted);await accepting;await duplicate;await flush();
 expect(mocks.adjust).toHaveBeenLastCalledWith(expect.objectContaining({action:'accept_workload',target_task_id:proposed.task_id,expected_version:proposed.draft_version,session_id:proposed.session_id,goal:''}));
 expect(mocks.confirm).not.toHaveBeenCalled();expect(text(r)).toContain('方案已接受，可以生成试卷');
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(proposed.task_id);
 expect(accepted.draft!.questions.slice(0,18)).toEqual(original.draft!.questions);
 mocks.recover.mockResolvedValue(accepted);mocks.confirm.mockResolvedValue({...accepted,status:'answered',receipt:{plan_id:'formal19'}});
 await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.confirm).toHaveBeenCalledWith(proposed.task_id,expect.objectContaining({session_id:proposed.session_id,draft_version:proposed.draft_version}));
 await (button(r,'确定生成试卷').props.onClick as()=>Promise<void>)();await flush();expect(mocks.confirm).toHaveBeenCalledTimes(1);
});

it('failed manual save retains the staged selection for retry, clears saving, and does not start chat',async()=>{
 mocks.system.mockResolvedValue({recommendations:task().context.system_recommendations,initial_paper:task().draft,evidence:{states:[]},blockers:[],note:''});
 const state=reactive({selectedKpIds:['k1'],budget:'standard',workbench:true});
 const host=mountStateComponent({setup:()=>()=>h(Panel,{...state,onScopeChange:(ids:string[])=>{state.selectedKpIds=ids;}})},{});unmount=host.unmount;await flush();const r=host.root;
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();state.selectedKpIds=['k2'];await flush();
 mocks.adjust.mockRejectedValueOnce(new ApiError('保存接口暂时不可用',503,'unavailable'));
 await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(state.selectedKpIds).toEqual(['k2']);expect(all(r).some(n=>n.props['data-testid']==='home-scope-editor')).toBe(true);
 expect(text(r)).not.toContain('保存中');expect(text(r)).not.toContain('处理中');expect(button(r,'保存调整').props.disabled).toBe(false);
 expect(mocks.stream).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();
 const saved=task('retry');saved.draft!.selected_kp_ids=['k2'];saved.draft!.questions=saved.draft!.questions.map(q=>({...q,kp_id:'k2',kp_name:'矩阵的秩'}));mocks.adjust.mockResolvedValue(saved);
 await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(button(r,'确定生成试卷').props['data-preview-id']).toBe(saved.task_id);
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();expect(state.selectedKpIds).toEqual(['k2']);expect(text(r)).toContain('矩阵的秩');
});

it('an expired budget card cannot issue acceptance or knowledge matching requests',async()=>{
 const original=task(),candidate=task('expired');candidate.context.workload_pending=true;candidate.context.expires_at='2000-01-01T00:00:00Z';
 candidate.context.workload={requested_budget_minutes:90,effective_budget_minutes:105,extra_minutes:15,requires_confirmation:true};candidate.draft!.questions.push({...candidate.draft!.questions[0],question_id:'extra',minutes:45});candidate.draft!.total_minutes=105;
 mocks.recover.mockResolvedValue({...original,workload_candidate:candidate});const r=await simpleMounted();
 await (button(r,'接受此方案').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();expect(text(r)).toContain('已过期');
});


it('manual scope response restores real node names, actual allocations and empty-node reason after refresh',async()=>{
 const saved=task('manual-allocation');
 saved.draft!.selected_kp_ids=['k1','k2','k3'];
 saved.draft!.questions.push({...saved.draft!.questions[0],question_id:'q3',question_version_id:'v3',kp_id:'k2',kp_name:'隐函数求导',minutes:5});saved.draft!.total_minutes=65;
 saved.draft!.scope_nodes=[{kp_id:'k1',name:'线代',parent_id:null,assigned_count:2,allocation_status:'allocated'},
 {kp_id:'k2',name:'隐函数求导',parent_id:'root',assigned_count:1,allocation_status:'allocated'},
 {kp_id:'k3',name:'深度优先搜索',parent_id:'computer',assigned_count:0,allocation_status:'no_eligible_questions'}];
 mocks.recover.mockResolvedValue(saved);
 const state=reactive({selectedKpIds:['k1'],budget:'standard',workbench:true});
 const host=mountStateComponent({setup:()=>()=>h(Panel,{...state,onScopeChange:(ids:string[])=>{state.selectedKpIds=ids;}})},{});unmount=host.unmount;await flush();const r=host.root;
 expect(text(r)).toContain('隐函数求导');expect(text(r)).toContain('深度优先搜索');expect(text(r)).toContain('今日安排 0 道');
 expect(text(r)).not.toContain('知识点名称待核对');expect(text(r)).toContain('本方案安排 3 道');
 expect(mocks.adjust).not.toHaveBeenCalled();expect(mocks.stream).not.toHaveBeenCalled();
 await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();expect(text(r)).toContain('深度优先搜索');
});

it('manual overbudget allocation closes saving editor and opens explicit acceptance without chat send',async()=>{
 const original=task(),candidate=task('manual-budget');candidate.context.request_origin='system';candidate.adjustment_origin='system';
 candidate.context.workload_pending=true;candidate.context.workload={requested_budget_minutes:90,effective_budget_minutes:95,extra_minutes:5,requires_confirmation:true};
 candidate.draft!.questions.push({...candidate.draft!.questions[0],question_id:'added',minutes:35});candidate.draft!.total_minutes=95;candidate.fallback_preview=original;
 const r=await simpleMounted();await (button(r,'调整知识点').props.onClick as()=>Promise<void>)();await flush();mocks.adjust.mockResolvedValue(candidate);
 await (button(r,'保存调整').props.onClick as()=>Promise<void>)();await flush();
 expect(all(r).some(n=>n.props['data-testid']==='home-scope-editor')).toBe(false);
 expect(button(r,'接受此方案')).toBeTruthy();expect(text(r)).not.toContain('处理中');
 expect(mocks.adjust).toHaveBeenCalledWith(expect.objectContaining({action:'default',goal:'',selected_kp_ids:['k1']}));
 expect(mocks.stream).not.toHaveBeenCalled();expect(mocks.confirm).not.toHaveBeenCalled();
});


it('Escape closes the open chat even when focus remains on launcher and restores editor focus',async()=>{
 const listeners=new Map<string,(e:any)=>void>();vi.stubGlobal('document',{addEventListener:(k:string,fn:any)=>listeners.set(k,fn),removeEventListener:(k:string)=>listeners.delete(k)});
 const r=await simpleMounted();const launch=button(r,'询问奶蛙');Object.assign(launch,{focus:vi.fn()});
 await (launch.props.onClick as()=>Promise<void>)();await flush();expect(launch.props['aria-expanded']).toBe(true);
 listeners.get('keydown')!({key:'Escape',preventDefault(){}});await flush();expect(launch.props['aria-expanded']).toBe(false);
 const adjust=button(r,'调整知识点');Object.assign(adjust,{focus:vi.fn()});await (adjust.props.onClick as()=>Promise<void>)();await flush();
 listeners.get('keydown')!({key:'Escape',preventDefault(){}});await flush();expect(all(r).some(n=>n.props['data-testid']==='home-scope-editor')).toBe(false);expect(document.activeElement).toBe(button(r,'调整知识点')); 
});

it('scope prop restoration never issues a background preview write after a user turn',async()=>{
 const state=reactive({selectedKpIds:['k1'],budget:'standard',workbench:true});const host=mountStateComponent({setup:()=>()=>h(Panel,{...state,onScopeChange:(ids:string[])=>{state.selectedKpIds=ids;}})},{});unmount=host.unmount;await flush();
 state.selectedKpIds=['k1','k2'];await flush();expect(mocks.adjust).not.toHaveBeenCalled();
 await input(host.root,'再加一道洛必达法则的题');const pending=deferred<HomePreview>();mocks.adjust.mockReturnValue(pending.promise);const one=submit(host.root);const two=submit(host.root);await flush();expect(mocks.adjust).toHaveBeenCalledOnce();pending.resolve(task('updated'));await one;await two;await flush();expect(mocks.adjust).toHaveBeenCalledOnce();
});

it('undo and redo controls send the current version and never call formal confirmation',async()=>{
 const first=task('history-first');first.undo_available=true;first.redo_available=false;
 mocks.recover.mockResolvedValueOnce(first);
 const r=await simpleMounted();
 expect(button(r,'撤销').props.disabled).toBe(false);expect(button(r,'重做').props.disabled).toBe(true);
 const undone=task('history-undone');undone.undo_available=false;undone.redo_available=true;
 mocks.adjust.mockResolvedValueOnce(undone);
 await (button(r,'撤销').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenCalledWith(expect.objectContaining({action:'undo',expected_version:first.draft_version}));
 expect(button(r,'撤销').props.disabled).toBe(true);expect(button(r,'重做').props.disabled).toBe(false);
 const redone=task('history-redone');redone.undo_available=true;redone.redo_available=false;
 mocks.adjust.mockResolvedValueOnce(redone);
 await (button(r,'重做').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.adjust).toHaveBeenLastCalledWith(expect.objectContaining({action:'redo',expected_version:undone.draft_version}));
 expect(mocks.confirm).not.toHaveBeenCalled();
});

it('prompts for newly selected allocated topics even outside original recommendations',async()=>{
 const current=task();current.context.system_recommendations=[];
 current.context.required_graduation_set_transition_ids=['allocated-child'];
 mocks.recover.mockResolvedValue(current);const consent=vi.fn(()=>true);vi.stubGlobal('window',{confirm:consent,addEventListener:vi.fn(),removeEventListener:vi.fn()});
 mocks.confirm.mockResolvedValue({...current,receipt:{plan_id:'p1'}});
 const r=await mounted();await (button(r,'确认并生成').props.onClick as()=>Promise<void>)();await flush();
 expect(consent).toHaveBeenCalledOnce();
 expect(mocks.confirm).toHaveBeenCalledWith('one',expect.objectContaining({confirm_legacy_set_transition_ids:['allocated-child']}));
});
it('declining the newly selected topic transition creates no formal paper',async()=>{
 const current=task();current.context.system_recommendations=[];
 current.context.required_graduation_set_transition_ids=['allocated-child'];
 mocks.recover.mockResolvedValue(current);vi.stubGlobal('window',{confirm:vi.fn(()=>false),addEventListener:vi.fn(),removeEventListener:vi.fn()});
 const r=await mounted();await (button(r,'确认并生成').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.confirm).not.toHaveBeenCalled();expect(button(r,'确认并生成').props.disabled).toBe(false);
});
it('changed transition requirements invalidate consent even with unchanged draft version',async()=>{
 const current=task();current.context.required_graduation_set_transition_ids=['first'];
 mocks.recover.mockResolvedValueOnce(current).mockResolvedValueOnce({...current,context:{...current.context,required_graduation_set_transition_ids:['second']}});
 vi.stubGlobal('window',{confirm:vi.fn(()=>true),addEventListener:vi.fn(),removeEventListener:vi.fn()});const r=await mounted();
 await (button(r,'确认并生成').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.confirm).not.toHaveBeenCalled();expect(text(r)).toContain('预览已更新');
});

it('difficulty feedback uses the public count while question references remain hidden',async()=>{
 const current=task();mocks.recover.mockResolvedValue(current);
 mocks.difficulty.mockResolvedValue({...current,difficulty_change_count:2});
 const r=await simpleMounted();await (button(r,'提高难度').props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.difficulty).toHaveBeenCalledOnce();expect(text(r)).toContain('已替换 2 道题');
 expect(text(r)).not.toContain('没有可替换');expect(text(r)).not.toContain('合成题');
});
