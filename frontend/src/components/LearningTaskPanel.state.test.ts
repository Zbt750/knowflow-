import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {h, reactive} from 'vue';
import {all, deferred, flush, mountStateComponent, text} from './stateTestHost';
import type {ChatMessage} from '../api/chat';
const mocks = vi.hoisted(() => ({list: vi.fn(), history: vi.fn(), stream: vi.fn(), task: vi.fn(), create: vi.fn(), confirm: vi.fn(),remove:vi.fn(),cancel:vi.fn()}));
vi.mock('../api/chat', async original => ({...await original<typeof import('../api/chat')>(), listChatSessions: mocks.list, fetchChatMessages: mocks.history, streamChatAnswer: mocks.stream, createChatSession: mocks.create,deleteChatSession:mocks.remove,cancelGenerationConfirmation:mocks.cancel}));
vi.mock('../api/learningTasks', async original => ({...await original<typeof import('../api/learningTasks')>(), fetchLearningTask: mocks.task, confirmLearningTask: mocks.confirm}));
vi.mock('../api/practiceRequests', () => ({listPracticeRequests: async () => [], planPracticeRequest: vi.fn(), declinePracticeRequest: vi.fn()}));
vi.mock('vue-router', () => ({useRouter: () => ({push: vi.fn()}), RouterLink: {setup: (_: unknown, ctx: {slots:{default?:()=>unknown}}) => () => h('a', null, ctx.slots.default?.() as any)}}));
vi.mock('./MarkdownContent.vue', () => ({default: {props: ['text'], setup: (p: {text: string}) => () => h('article', {'data-markdown': true}, p.text)}}));
vi.mock('./StudyMascot.vue', () => ({default: {setup: () => () => h('i')}}));
import Panel from './LearningTaskPanel.vue';
import {notifyPracticeRequestsChanged} from '../lib/practiceRequestChanges';
let unmount: (() => void) | undefined;
let storage: Map<string, string>;
const day = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
const reply = (id: string, role: 'assistant' | 'user', content: string, status: ChatMessage['status'] = 'completed'): ChatMessage => ({message_id: id, role, content, status, citations: [], matched_kp_id: null});
beforeEach(() => {
  vi.stubGlobal('Document', class MemoryDocument {});
  vi.stubGlobal('ShadowRoot', class MemoryShadowRoot {});
  storage = new Map();
  vi.stubGlobal('localStorage', {getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key:string) => storage.delete(key)});
  vi.stubGlobal('window', {addEventListener() {}, removeEventListener() {}});
  mocks.list.mockResolvedValue([{session_id: 'today-study', mode: 'builtin', purpose: 'study', study_date: day()}]);
  mocks.history.mockResolvedValue([]);
  mocks.create.mockResolvedValue({session_id: 'today-study'});
});
afterEach(() => {unmount?.(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.resetAllMocks();});
it('r6 latest answered task without a draft cannot leave an older confirmable card',async()=>{
  storage.set(`learning-assistant:study:${day()}`,'today-study');
  const old={task_id:'old-task',session_id:'today-study',goal:'旧安排',budget_minutes:60,status:'ready',draft_version:'old',trace:[],metrics:{},
    draft:{kind:'activity_schedule',activities:[{title:'旧活动',minutes:60,basis:'旧范围'}],total_minutes:60,questions:[],review_nodes:[],warnings:[]}};
  const latest={...old,task_id:'latest-task',status:'answered',draft:null,draft_version:null,message:'只读建议'};
  mocks.history.mockResolvedValue([reply('u','user','旧安排'),{...reply('a','assistant','旧草案'),planner_task_id:'old-task'}]);
  mocks.task.mockResolvedValue(old);
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  const stale=all(mounted.root).find(n=>n.props['data-testid']==='task-confirm')!;
  mocks.task.mockImplementation(async(id:string)=>id==='latest-task'?latest:old);
  mocks.history.mockResolvedValue([reply('u','user','旧安排'),{...reply('a','assistant','旧草案'),planner_task_id:'old-task'},
    reply('v','user','给我复习建议'),{...reply('b','assistant','只读建议'),planner_task_id:'latest-task'}]);
  mocks.stream.mockImplementation(async(_id,_q,event)=>{event('meta',{message_id:'b',task_id:'latest-task'});event('planner',latest);event('delta',{text:'只读建议'});event('done',{message_id:'b',status:'completed'});});
  (all(mounted.root).find(n=>n.type==='textarea')!.props['onUpdate:modelValue'] as (v:string)=>void)('给我复习建议');await flush();
  (all(mounted.root).find(n=>n.type==='form')!.props.onSubmit as (e:unknown)=>void)({preventDefault(){}});await flush();
  expect(all(mounted.root).some(n=>n.props['data-testid']==='no-valid-task-draft')).toBe(true);
  expect(all(mounted.root).some(n=>n.props['data-testid']==='historical-task-draft')).toBe(true);
  expect(all(mounted.root).filter(n=>n.props['data-testid']==='task-confirm')).toHaveLength(0);
  await (stale.props.onClick as ()=>Promise<void>)();
  expect(mocks.confirm).not.toHaveBeenCalled();
});
it.each(['ready','needs_info'])('r5 revision replaces the old draft owner even when revision ends as %s',async(status)=>{
  storage.set(`learning-assistant:study:${day()}`,'today-study');
  const old={task_id:'task',session_id:'today-study',goal:'原42分钟方案',budget_minutes:60,status:'ready',draft_version:'old',trace:[],metrics:{},
    draft:{kind:'activity_schedule',activities:[{title:'旧42分钟活动',minutes:42,basis:'旧范围'}],total_minutes:42,questions:[],review_nodes:[],warnings:[]}};
  mocks.task.mockResolvedValue(old);
  mocks.history.mockResolvedValue([reply('u','user','原安排'),{...reply('a','assistant','原草案'),planner_task_id:'task'}]);
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  expect(text(mounted.root)).toContain('旧42分钟活动');
  const updated={...old,budget_minutes:25,status,draft_version:status==='ready'?'new':null,
    draft:status==='ready'?{...old.draft,total_minutes:25,activities:[{title:'当前25分钟活动',minutes:25,basis:'重新核验'}]}:null};
  mocks.stream.mockImplementation(async(_id,_q,event)=>{
    event('meta',{message_id:'new-reply',task_id:'task'});
    event('planner',updated);event('delta',{text:status==='ready'?'修改版已校验':'修改版失败，旧版本失效'});
    event('done',{message_id:'new-reply',status:'completed'});
  });
  mocks.task.mockResolvedValue(updated);
  (all(mounted.root).find(n=>n.type==='textarea')!.props['onUpdate:modelValue'] as (v:string)=>void)('我临时只有25分钟，给我修改后的版本');await flush();
  (all(mounted.root).find(n=>n.type==='form')!.props.onSubmit as (e:unknown)=>void)({preventDefault(){}});await flush();
  expect(text(mounted.root)).not.toContain('旧42分钟活动');
  expect(all(mounted.root).filter(n=>n.props['data-testid']==='task-result')).toHaveLength(1);
  expect(all(mounted.root).filter(n=>n.props['data-testid']==='task-confirm')).toHaveLength(status==='ready'?1:0);
  if(status==='ready')expect(text(mounted.root)).toContain('当前25分钟活动');
});
it('restores a distinct activity schedule with exact budget and no claim of adding paper questions',async()=>{
  const activity={task_id:'activity',session_id:'today-study',goal:'安排60分钟复习',status:'ready',budget_minutes:60,
    trace:[],metrics:{},draft_version:'v1',draft:{kind:'activity_schedule',total_minutes:60,paper_estimated_minutes:3,
      activities:[{title:'复盘现有题',minutes:30,basis:'实际绑定版本'},{title:'回忆并核对条件',minutes:30,basis:'知识树'}],
      questions:[],review_nodes:[],review_minutes:0,rationale:'保留旧卷',warnings:[]}};
  mocks.history.mockResolvedValue([reply('u','user','安排60分钟复习'),{...reply('a','assistant','活动预览'),planner_task_id:'activity'}]);
  mocks.task.mockResolvedValue(activity);
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  expect(all(mounted.root).filter(n=>n.props['data-testid']==='activity-schedule')).toHaveLength(1);
  expect(text(mounted.root)).toContain('复习活动预算：60 分钟');
  expect(text(mounted.root)).toContain('预计作答耗时：3 分钟');
  const confirm=all(mounted.root).find(n=>n.props['data-testid']==='task-confirm')!;
  expect(text(confirm)).toContain('确认活动安排');
  mocks.confirm.mockResolvedValue({...activity,metrics:{commit:{kind:'activity_schedule',added_count:0,item_ids:[]}}});
  await (confirm.props.onClick as ()=>Promise<void>)();await flush();
  expect(text(mounted.root)).toContain('今日卷未改变');
  expect(text(mounted.root)).not.toContain('已加入今日学习');
});
it('keeps the study conversation but does not show topic management controls',async()=>{
  mocks.history.mockImplementation(async(id:string)=>id==='today-study'?[reply('u','user','之前的聊天记录')]:[]);
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  expect(text(mounted.root)).toContain('之前的聊天记录');
  expect(text(mounted.root)).not.toContain('学习话题');
  expect(text(mounted.root)).not.toContain('删除当前话题');
  expect(text(mounted.root)).not.toContain('开新话题');
  expect(all(mounted.root).some(n=>n.props['data-testid']==='new-study-topic')).toBe(false);
  expect(all(mounted.root).some(n=>n.props['data-testid']==='study-topic-selector')).toBe(false);
  expect(mocks.create).not.toHaveBeenCalled();
  expect(mocks.remove).not.toHaveBeenCalled();
  expect(mocks.stream).not.toHaveBeenCalled();
});
it('sends the study assistant request through the current session without a topic picker', async () => {
  storage.set(`learning-assistant:study:${day()}`, 'today-study');
  mocks.history.mockImplementation(async () => mocks.history.mock.calls.length > 1
    ? [reply('new-user','user','今天复习积分换元'),reply('new-assistant','assistant','先复习替换条件。')]
    : []);
  mocks.stream.mockImplementation(async (_id,_question,onEvent) => {
    onEvent('meta',{message_id:'new-assistant'});
    onEvent('delta',{text:'先复习替换条件。'});
    onEvent('done',{message_id:'new-assistant',answer:'先复习替换条件。',status:'completed'});
  });
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  const input=all(mounted.root).find(n=>n.type==='textarea')!;
  (input.props['onUpdate:modelValue'] as (value:string)=>void)('今天复习积分换元');await flush();
  const form=all(mounted.root).find(n=>n.type==='form')!;
  await (form.props.onSubmit as (event:unknown)=>Promise<void>)({preventDefault(){}});await flush();
  expect(mocks.stream).toHaveBeenCalledOnce();
  expect(mocks.stream.mock.calls[0][0]).toBe('today-study');
  expect(mocks.list).toHaveBeenCalledTimes(1);
  expect(text(mounted.root)).toContain('先复习替换条件。');
  expect(all(mounted.root).some(n=>n.props['data-testid']==='study-topic-selector')).toBe(false);
});
it('does not expose a destructive chat-topic delete action',async()=>{
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  expect(all(mounted.root).some(n=>n.type==='button'&&text(n)==='删除当前话题')).toBe(false);
  expect(mocks.remove).not.toHaveBeenCalled();
  expect(mocks.stream).not.toHaveBeenCalled();
});
it('lost local session pointer recovers today study history, not a foreign QA task pointer', async () => {
  storage.set(`learning-task:study:${day()}`, 'foreign-task');
  mocks.task.mockResolvedValue({task_id: 'foreign-task', session_id: 'qa-session', goal: '不属于学习会话', status: 'ready', trace: [], draft: null, metrics: {}});
  const formula = String.raw`唯一回答 \[\frac{1}{2}\]`;
  mocks.history.mockResolvedValue([reply('u', 'user', '讲题'), reply('a', 'assistant', formula)]);
  const mounted = mountStateComponent(Panel, {sessionId: null, mascot: false, open: true}); unmount = mounted.unmount;
  await flush();
  expect(mocks.history).toHaveBeenCalledWith('today-study', 'study');
  expect(text(mounted.root)).toContain(formula);
  expect(text(mounted.root)).not.toContain('不属于学习会话');
  expect(all(mounted.root).filter(n => n.props['data-testid'] === 'task-result')).toHaveLength(0);
  expect(text(mounted.root).split(formula)).toHaveLength(2);
});
it('waits for session and pending-task recovery before sending a panel refinement',async()=>{
  const gate=deferred<Array<{session_id:string;title:string;mode:string;purpose:string;study_date:string}>>();
  mocks.list.mockReturnValueOnce(gate.promise);
  storage.set(`learning-task:study:${day()}`,'pending-task');
  const pending={task_id:'pending-task',session_id:'task-owner',goal:'安排60分钟数学二复习',
    budget_minutes:60,status:'ready',draft_version:'old',trace:[],metrics:{},draft:{kind:'question_selection',
      questions:[{question_id:'q1',stem:'SYNTHETIC 原题',minutes:42}],total_minutes:42}};
  mocks.task.mockResolvedValue(pending);
  let revised=false;
  mocks.history.mockImplementation(async(id:string)=>id==='task-owner'
    ? revised
      ? [reply('u','user','安排60分钟数学二复习'),{...reply('a','assistant','60分钟待确认方案'),planner_task_id:'pending-task'},
        reply('revision-user','user','我临时只有25分钟了，帮我修改原来的方案'),
        {...reply('revision-reply','assistant','已按25分钟重新核验。'),planner_task_id:'pending-task'}]
      : [reply('u','user','安排60分钟数学二复习'),{...reply('a','assistant','60分钟待确认方案'),planner_task_id:'pending-task'}]
    : []);
  mocks.stream.mockImplementation(async(id,_q,onEvent)=>{
    revised=true;
    onEvent('meta',{message_id:'revision-reply',task_id:'pending-task'});
    onEvent('planner',{...pending,budget_minutes:25,draft_version:'new',draft:{...pending.draft,total_minutes:22}});
    onEvent('delta',{text:'已按25分钟重新核验。'});
    onEvent('done',{message_id:'revision-reply',answer:'已按25分钟重新核验。',status:'completed'});
    expect(id).toBe('task-owner');
  });
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;
  const input=all(mounted.root).find(n=>n.type==='textarea')!;
  (input.props['onUpdate:modelValue'] as (v:string)=>void)('我临时只有25分钟了，帮我修改原来的方案');
  const form=all(mounted.root).find(n=>n.type==='form')!;
  const send=(form.props.onSubmit as (e:unknown)=>Promise<void>)({preventDefault(){}});
  await flush();
  expect(mocks.create).not.toHaveBeenCalled();
  gate.resolve([{session_id:'task-owner',title:'今日复习',mode:'builtin',purpose:'study',study_date:day()}]);
  await send;await flush();
  expect(mocks.create).not.toHaveBeenCalled();
  expect(mocks.stream).toHaveBeenCalledOnce();
  expect(text(mounted.root)).toContain('已按25分钟重新核验。');
});
it('does not restore a legacy task pointer owned by a different explicitly selected study topic',async()=>{
  storage.set(`learning-assistant:study:${day()}`,'new-study');
  storage.set(`learning-task:study:${day()}`,'old-topic-task');
  mocks.list.mockResolvedValue([
    {session_id:'new-study',title:'新话题',mode:'builtin',purpose:'study',study_date:day()},
    {session_id:'today-study',title:'旧话题',mode:'builtin',purpose:'study',study_date:day()},
  ]);
  mocks.task.mockResolvedValue({task_id:'old-topic-task',session_id:'today-study',goal:'旧方案',budget_minutes:60,
    status:'ready',draft_version:'old',trace:[],metrics:{},draft:{kind:'activity_schedule',total_minutes:60,
      activities:[{title:'旧活动',minutes:60,basis:'旧话题'}],questions:[],review_nodes:[],warnings:[]}});
  mocks.history.mockImplementation(async(id:string)=>id==='new-study'?[reply('u','user','新话题上下文')]:[]);
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  expect(mocks.history).toHaveBeenCalledWith('new-study', 'study');
  expect(text(mounted.root)).toContain('新话题上下文');
  expect(text(mounted.root)).not.toContain('旧活动');
  expect(all(mounted.root).filter(n=>n.props['data-testid']==='task-result')).toHaveLength(0);
  expect(storage.has(`learning-task:study:${day()}`)).toBe(false);
});
it('does not send a queued question into a different topic selected during hydration',async()=>{
  const gate=deferred<Array<{session_id:string;title:string;mode:string;purpose:string;study_date:string}>>();
  const topics=[
    {session_id:'topic-a',title:'话题 A',mode:'builtin',purpose:'study',study_date:day()},
    {session_id:'topic-b',title:'话题 B',mode:'builtin',purpose:'study',study_date:day()},
  ];
  storage.set(`learning-assistant:study:${day()}`,'topic-a');
  mocks.list.mockReturnValueOnce(gate.promise);mocks.list.mockResolvedValue(topics);
  mocks.history.mockResolvedValue([]);
  const props=reactive({sessionId:null as string|null,mascot:false,open:true});
  const mounted=mountStateComponent({setup:()=>()=>h(Panel,props)},{});unmount=mounted.unmount;await flush();
  const input=all(mounted.root).find(n=>n.type==='textarea')!;
  (input.props['onUpdate:modelValue'] as (v:string)=>void)('我刚才的学习计划怎么调整');
  const form=all(mounted.root).find(n=>n.type==='form')!;
  (form.props.onSubmit as (e:unknown)=>void)({preventDefault(){}});await flush();
  storage.set(`learning-assistant:study:${day()}`,'topic-b');
  props.sessionId='route-change';await flush();
  gate.resolve(topics);await flush();
  expect(mocks.stream).not.toHaveBeenCalled();
  expect(mocks.create).not.toHaveBeenCalled();
  expect(storage.get(`learning-assistant:study:${day()}`)).toBe('topic-b');
});
it('successful done plus unavailable history does not resurrect a retry/failure alert', async () => {
  storage.set(`learning-assistant:study:${day()}`, 'today-study');
  mocks.history.mockResolvedValue([reply('old-u','user','上一轮失败提问'), {...reply('old-a','assistant','历史未完成正文','failed'), assistant_error_code:'generation_failed'}]);
  mocks.stream.mockImplementation(async (_id, _q, onEvent) => {
    onEvent('meta', {message_id: 'answer'});
    onEvent('delta', {text: String.raw`\[\frac{1}{2}\]`});
    onEvent('done', {answer: String.raw`\[\frac{1}{2}\]`, status: 'completed'});
  });
  const mounted = mountStateComponent(Panel, {sessionId: null, mascot: false, open: true}); unmount = mounted.unmount;
  await flush(); mocks.history.mockRejectedValue(new Error('history unavailable after successful done'));
  const input = all(mounted.root).find(n => n.type === 'textarea')!;
  (input.props['onUpdate:modelValue'] as (value: string) => void)('当前这道题怎么做'); await flush();
  const form = all(mounted.root).find(n => n.type === 'form')!;
  (form.props.onSubmit as (event: unknown) => void)({preventDefault() {}}); await flush();
  expect(mocks.stream).toHaveBeenCalledOnce();
  expect(text(mounted.root)).toContain(String.raw`\[\frac{1}{2}\]`);
  expect(all(mounted.root).filter(n => n.props['data-testid'] === 'frog-turn-error')).toHaveLength(0);
  expect(text(mounted.root)).not.toContain('重试这条回复');
});
it('a new study day never restores yesterday task/card through local pointers', async () => {
  vi.useFakeTimers({toFake:['Date']});vi.setSystemTime(new Date('2026-10-24T15:59:00Z'));
  const yesterday=day();
  storage.set(`learning-assistant:study:${yesterday}`,'yesterday-study');
  mocks.list.mockResolvedValue([{session_id:'yesterday-study',mode:'builtin',purpose:'study',study_date:yesterday}]);
  mocks.history.mockResolvedValue([reply('u','user','昨天的问题'),reply('a','assistant','昨天的回答')]);
  const props=reactive({sessionId:null as string|null,mascot:false,open:true});
  const mounted=mountStateComponent({setup:()=>()=>h(Panel,props)},{});unmount=mounted.unmount;await flush();
  expect(text(mounted.root)).toContain('昨天的回答');
  vi.setSystemTime(new Date('2026-10-24T16:01:00Z'));
  storage.set(`learning-task:study:${day()}`,'old-task');
  mocks.task.mockResolvedValue({task_id:'old-task',session_id:'yesterday-study',goal:'昨天的卡片',status:'ready',trace:[],metrics:{}});
  props.sessionId='day-boundary';await flush();
  expect(text(mounted.root)).not.toContain('昨天的回答');
  expect(text(mounted.root)).not.toContain('昨天的卡片');
  expect(all(mounted.root).some(n=>n.props['data-testid']==='study-frog-launcher')).toBe(true);
});
it('a cancelled persisted task retracts its old confirmation button and rejects a stale click handler', async () => {
  storage.set(`learning-assistant:study:${day()}`, 'today-study');
  const ready = {task_id: 'task', session_id: 'today-study', goal: '选题', budget_minutes: 30, status: 'ready', draft_version: 1, trace: [], metrics: {}, draft: {questions: [{question_id: 'q', stem: '隔离预览', options: {A:'1',B:'0'}, question_type: 'single_choice', difficulty: 'basic', kp_name: '节点', minutes: 1}], review_nodes: [], rationale: '候选', warnings: []}};
  mocks.task.mockResolvedValue(ready);
  mocks.history.mockResolvedValue([reply('u', 'user', '选题'), {...reply('a', 'assistant', '尚未加入'), planner_task_id: 'task'}]);
  const mounted = mountStateComponent(Panel, {sessionId: null, mascot: false, open: true}); unmount = mounted.unmount;
  await flush();
  const confirm = all(mounted.root).find(n => n.props['data-testid'] === 'task-confirm')!;
  expect(confirm).toBeDefined();
  mocks.task.mockResolvedValue({...ready, status: 'cancelled'});
  notifyPracticeRequestsChanged(); await flush();
  expect(all(mounted.root).some(n => n.props['data-testid'] === 'task-confirm')).toBe(false);
  await (confirm.props.onClick as () => Promise<void>)();
  expect(mocks.confirm).not.toHaveBeenCalled();
});
it('cancels a generated-question confirmation using the study-owned session scope', async () => {
  storage.set(`learning-assistant:study:${day()}`, 'today-study');
  const confirmation = {question: '生成一道题', message: '确认知识点', selected_kp_id: null,
    question_count: 1, difficulty: 'medium', nodes: [{kp_id: 'kp-1', name: '洛必达法则', code: 'math.calculus.limit.lhopital', question_types: ['single_choice']}]};
  mocks.history.mockResolvedValue([{...reply('confirm-message', 'assistant', '待确认'),
    personal_generation_confirmation: confirmation}]);
  mocks.cancel.mockResolvedValue({message_id: 'confirm-message', status: 'cancelled'});
  const mounted = mountStateComponent(Panel, {sessionId: null, mascot: false, open: true}); unmount = mounted.unmount;
  await flush();
  const cancel = all(mounted.root).find(n => n.type === 'button' && text(n).includes('暂不生成'))!;
  expect(cancel).toBeDefined();
  await (cancel.props.onClick as () => Promise<void>)();
  expect(mocks.cancel).toHaveBeenCalledExactlyOnceWith('today-study', 'confirm-message', 'study');
});
it('a true failed mathematical reply has one body owner and a separate short diagnostic', async () => {
  storage.set(`learning-assistant:study:${day()}`, 'today-study');
  const formula = String.raw`未完成推导 \[\lim_{x\to0}\frac{\sin x}{x}\]`;
  mocks.history.mockResolvedValue([reply('u', 'user', '讲题'), {...reply('a', 'assistant', formula, 'failed'), assistant_error_code: 'generation_failed'}]);
  const mounted = mountStateComponent(Panel, {sessionId: null, mascot: false, open: true}); unmount = mounted.unmount;
  await flush();
  expect(text(mounted.root).split(formula)).toHaveLength(2);
  const alert = all(mounted.root).find(n => n.props['data-testid'] === 'frog-turn-error')!;
  expect(text(alert)).not.toContain(formula);
  expect(text(alert)).toContain('重试这条回复');
});
it('session epoch switch aborts the old stream and ignores its late frames and completion', async () => {
  storage.set(`learning-assistant:study:${day()}`, 'today-study');
  mocks.list.mockResolvedValue(['today-study', 'second-study'].map(id => ({session_id:id,mode:'builtin',purpose:'study',study_date:day()})));
  const wait = deferred<void>();
  let oldEvent!: (event:string,data:Record<string,unknown>)=>void;
  let oldSignal!: AbortSignal;
  mocks.stream.mockImplementation((_id,_q,onEvent,signal) => {oldEvent=onEvent;oldSignal=signal;return wait.promise;});
  const props=reactive({sessionId:null as string|null,mascot:false,open:true});
  const mounted=mountStateComponent({setup:()=>()=>h(Panel,props)},{});unmount=mounted.unmount;
  await flush();
  (all(mounted.root).find(n=>n.type==='textarea')!.props['onUpdate:modelValue'] as (value:string)=>void)('旧会话提问');await flush();
  (all(mounted.root).find(n=>n.type==='form')!.props.onSubmit as (event:unknown)=>void)({preventDefault(){}});await flush();
  expect(mocks.stream).toHaveBeenCalledOnce();
  storage.set(`learning-assistant:study:${day()}`, 'second-study');
  mocks.history.mockResolvedValue([reply('new-u','user','新会话'),reply('new-a','assistant','新的持久化回答')]);
  props.sessionId='new-parent';await flush();
  expect(oldSignal.aborted).toBe(true);
  oldEvent('delta',{text:'不应出现的旧正文'});oldEvent('error',{message:'迟到错误'});wait.resolve();await flush();
  expect(text(mounted.root)).toContain('新的持久化回答');
  expect(text(mounted.root)).not.toContain('不应出现的旧正文');
  expect(text(mounted.root)).not.toContain('迟到错误');
  expect(all(mounted.root).filter(n=>n.props['data-testid']==='frog-turn-error')).toHaveLength(0);
});

it('r6 persisted latest result overrides an older local task pointer on refresh',async()=>{
  storage.set(`learning-assistant:study:${day()}`,'today-study');
  storage.set(`learning-task:study:${day()}`,'old-task');
  const old={task_id:'old-task',session_id:'today-study',goal:'旧安排',budget_minutes:60,status:'ready',draft_version:'old',trace:[],metrics:{},
    draft:{kind:'activity_schedule',activities:[{title:'旧活动',minutes:60,basis:'旧范围'}],total_minutes:60,questions:[],review_nodes:[],warnings:[]}};
  const latest={...old,task_id:'latest-task',status:'answered',draft:null,draft_version:null};
  mocks.task.mockImplementation(async(id:string)=>id==='latest-task'?latest:old);
  mocks.history.mockResolvedValue([{...reply('a','assistant','旧草案'),planner_task_id:'old-task'},
    {...reply('b','assistant','本轮无草案'),planner_task_id:'latest-task'}]);
  const mounted=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=mounted.unmount;await flush();
  expect(all(mounted.root).some(n=>n.props['data-testid']==='no-valid-task-draft')).toBe(true);
  expect(all(mounted.root).filter(n=>n.props['data-testid']==='task-confirm')).toHaveLength(0);
  expect(mocks.confirm).not.toHaveBeenCalled();
});

it('compact panel opens without expanded class and keeps chat when closed and reopened',async()=>{
 storage.set(`learning-assistant:study:${day()}`,'today-study');
 mocks.history.mockResolvedValue([reply('compact-a','assistant','需要保留的长回复'.repeat(40))]);
 const props=reactive({sessionId:null as string|null,mascot:true,open:true});
 const host=mountStateComponent({setup:()=>()=>h(Panel,props)},{});unmount=host.unmount;await flush();
 const panel=all(host.root).find(n=>n.props['data-testid']==='learning-task-panel')!;
 expect(JSON.stringify(panel.props.class)).not.toContain('learning-task--expanded":true');
 expect(all(host.root).some(n=>n.props['data-testid']==='frog-conversation')).toBe(true);
 const close=all(host.root).find(n=>n.props['aria-label']==='收起奶蛙对话')!;
 (close.props.onClick as()=>void)();props.open=false;await flush();props.open=true;await flush();
 expect(text(host.root)).toContain('需要保留的长回复');
 expect(all(host.root).some(n=>n.type==='textarea')).toBe(true);
 expect(all(host.root).some(n=>n.type==='button'&&text(n).includes('深入问答'))).toBe(true);
});

it('bank candidate shows real source, matching evidence and version, confirms and restores the same result',async()=>{
 storage.set(`learning-assistant:study:${day()}`,'today-study');
 const userText='给我从我的题库来一道这样类似的题加到我今日卷里';
 const candidate={question_id:'bank-q-1',question_version:'bank-version-1',kp_name:'洛必达法则',question_type:'single_choice',difficulty:'medium',minutes:5,stem:'真实题库候选',options:{A:'选项'},source_category:'personal_ai_practice',match_basis:{shared_skill_tags:['极限'],same_variant_group:false},question_trust:{practice_eligible:true}};
 const pending={task_id:'bank-task',session_id:'today-study',goal:userText,budget_minutes:60,status:'ready',draft_version:'version-draft',trace:[{tool:'find_questions',status:'completed'}],metrics:{},message:'找到真实候选，尚未加入今日卷',draft:{questions:[candidate],review_nodes:[],review_minutes:0,rationale:'已校验候选',warnings:[]}};
 const committed={...pending,status:'answered',metrics:{commit:{plan_id:'plan-1'}},append_result:{status:'committed',operation_id:'op-1',plan_id:'plan-1',study_date:day(),number_semantics:'current_position',added_count:1,total_count:3,items:[{item_id:'item-1',question_id:candidate.question_id,question_version_id:candidate.question_version,number:3,stem:candidate.stem,options:candidate.options,kp_id:'kp-1',kp_name:candidate.kp_name,question_type:candidate.question_type,difficulty:candidate.difficulty,source_category:candidate.source_category,question_source:{},estimated_minutes:5}]}};
 const mounted=mountStateComponent(Panel,{sessionId:null,mascot:true,open:true});unmount=mounted.unmount;await flush();
 mocks.history.mockResolvedValue([reply('u','user',userText),{...reply('a','assistant','找到真实候选，尚未加入今日卷'),planner_task_id:'bank-task'}]);mocks.task.mockResolvedValue(pending);
 mocks.stream.mockImplementation(async(_id,_q,event)=>{event('meta',{message_id:'a',task_id:'bank-task'});event('planner',pending);event('done',{message_id:'a',status:'completed',answer:'找到真实候选，尚未加入今日卷'});});
 (all(mounted.root).find(n=>n.type==='textarea')!.props['onUpdate:modelValue'] as (v:string)=>void)(userText);await flush();
 await (all(mounted.root).find(n=>n.type==='form')!.props.onSubmit as(e:unknown)=>Promise<void>)({preventDefault(){}});await flush();
 expect(mocks.stream.mock.calls[0][1]).toBe(userText);expect(mocks.confirm).not.toHaveBeenCalled();
 const card=all(mounted.root).find(n=>n.props['data-testid']==='pending-question-preview')!;
 expect(text(card)).toContain('真实题库候选');expect(text(card)).toContain('个人 AI 练习');
 expect(text(card)).toContain('共有技能标签：极限');expect(text(card)).toContain('bank-q-1');expect(text(card)).toContain('bank-version-1');
 expect(text(mounted.root)).toContain('尚未加入今日学习');
 mocks.confirm.mockResolvedValue(committed);mocks.task.mockResolvedValue(committed);
 const confirm=all(mounted.root).find(n=>n.props['data-testid']==='task-confirm')!;
 await (confirm.props.onClick as()=>Promise<void>)();await flush();
 expect(mocks.confirm).toHaveBeenCalledWith('bank-task','version-draft');
 expect(all(mounted.root).find(n=>n.props['data-testid']==='today-added-question')?.props['data-version-id']).toBe('bank-version-1');
 expect(all(mounted.root).some(n=>n.props['data-testid']==='task-confirm')).toBe(false);
 unmount?.();const restored=mountStateComponent(Panel,{sessionId:null,mascot:true,open:true});unmount=restored.unmount;await flush();
 expect(all(restored.root).find(n=>n.props['data-testid']==='today-added-question')?.props['data-version-id']).toBe('bank-version-1');
 expect(all(restored.root).some(n=>n.props['data-testid']==='task-confirm')).toBe(false);
});

it('bank preview displays the source version and its actual matching evidence before confirmation',async()=>{
 storage.set(`learning-assistant:study:${day()}`,'today-study');
 const task={task_id:'bank-task',session_id:'today-study',goal:'从我的题库找相似题',budget_minutes:90,status:'ready',draft_version:'ver',trace:[],metrics:{},
 draft:{questions:[{question_id:'qid',question_version:'version-id',kp_id:'kp',kp_name:'隐函数',question_type:'single_choice',difficulty:'medium',minutes:5,stem:'题库真实题干',options:{A:'选项'},source_category:'personal_generated',question_trust:{practice_eligible:true},match_basis:{shared_skill_tags:['链式求导'],same_variant_group:false}}],review_nodes:[],review_minutes:0,total_minutes:5,rationale:'真实库存',warnings:[]}};
 mocks.task.mockResolvedValue(task);mocks.history.mockResolvedValue([reply('u','user','从我的题库找相似题'),{...reply('a','assistant','等待确认'),planner_task_id:'bank-task'}]);
 const host=mountStateComponent(Panel,{sessionId:null,mascot:false,open:true});unmount=host.unmount;await flush();
 expect(text(host.root)).toContain('题库真实题干');expect(text(host.root)).toContain('链式求导');expect(text(host.root)).toContain('version-id');expect(text(host.root)).toContain('尚未加入今日学习');
 expect(all(host.root).some(n=>n.props['data-testid']==='task-confirm')).toBe(true);expect(mocks.confirm).not.toHaveBeenCalled();
});
