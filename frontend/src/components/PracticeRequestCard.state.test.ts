import {afterEach, expect, it, vi} from 'vitest';
import {h} from 'vue';
import {all, deferred, flush, mountStateComponent, text} from './stateTestHost';
import type {PracticeRequest} from '../api/practiceRequests';
const mocks = vi.hoisted(() => ({fetch: vi.fn(), decline: vi.fn(), send: vi.fn(), task: vi.fn()}));
vi.mock('../api/practiceRequests', () => ({fetchPracticeRequest: mocks.fetch, declinePracticeRequest: mocks.decline, sendPracticeRequest: mocks.send}));
vi.mock('../api/learningTasks', () => ({fetchLearningTask: mocks.task}));
vi.mock('vue-router', () => ({RouterLink: {setup: () => () => h('a')}}));
vi.mock('./MarkdownContent.vue', () => ({default: {props: ['text'], setup: (p: {text: string}) => () => h('article', p.text)}}));
import Card from './PracticeRequestCard.vue';
import {notifyPracticeRequestsChanged} from '../lib/practiceRequestChanges';
let unmount: (() => void) | undefined;
afterEach(() => {unmount?.(); vi.unstubAllGlobals(); vi.resetAllMocks();});
function request(status: PracticeRequest['status']): PracticeRequest {return {id: 'r', status, source_conversation_id: 's', user_request:'隔离测试选题', planner_task_id:null, daily_plan_id:null, error_code:null, details: {target_knowledge_node_ids: ['k'], target_study_session_id: 'study', requested_question_count:1, available_minutes:30}};}
it('a stale GET cannot reactivate the draft after a successful send', async () => {
  vi.stubGlobal('window', {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}});
  mocks.fetch.mockResolvedValueOnce(request('draft'));
  const old = deferred<PracticeRequest>(); mocks.fetch.mockReturnValueOnce(old.promise);
  mocks.send.mockResolvedValue(request('pending'));
  const mounted = mountStateComponent(Card, {requestId: 'r'}); unmount = mounted.unmount;
  await flush();
  notifyPracticeRequestsChanged(); // start a delayed read BEFORE sending
  const button = all(mounted.root).find(n => n.props['data-testid'] === 'request-send')!;
  await (button.props.onClick as () => Promise<void>)(); await flush();
  old.resolve(request('draft')); await flush();
  expect(text(mounted.root)).toContain('已发送');
  expect(all(mounted.root).filter(n => n.type === 'button')).toHaveLength(0);
});
it('decline response loss is reconciled by GET without a second mutation or false success', async () => {
  vi.stubGlobal('window', {addEventListener() {}, removeEventListener() {}});
  mocks.fetch.mockResolvedValueOnce(request('draft')).mockResolvedValue(request('declined'));
  mocks.decline.mockRejectedValue(new Error('response lost'));
  const mounted = mountStateComponent(Card, {requestId: 'r'}); unmount = mounted.unmount; await flush();
  const button = all(mounted.root).find(n => n.type === 'button' && text(n) === '不用')!;
  await (button.props.onClick as () => Promise<void>)(); await flush();
  expect(text(mounted.root)).toContain('已撤回');
  expect(text(mounted.root)).not.toContain('response lost');
  expect(mocks.decline).toHaveBeenCalledOnce();
});
it('an unknown decline outcome remains an error, never a success card', async () => {
  vi.stubGlobal('window', {addEventListener() {}, removeEventListener() {}});
  mocks.fetch.mockResolvedValueOnce(request('draft')).mockRejectedValue(new Error('GET unavailable'));
  mocks.decline.mockRejectedValue(new Error('response lost'));
  const mounted = mountStateComponent(Card, {requestId: 'r'}); unmount = mounted.unmount; await flush();
  const button = all(mounted.root).find(n => n.type === 'button' && text(n) === '不用')!;
  await (button.props.onClick as () => Promise<void>)(); await flush();
  expect(text(mounted.root)).not.toContain('已撤回');
  expect(all(mounted.root).some(n => n.props.role === 'alert')).toBe(true);
  expect(mocks.decline).toHaveBeenCalledOnce();
});
it('generation-before request cards render only topic stock counts even if a legacy nested preview is present', async () => {
  vi.stubGlobal('window', {addEventListener() {}, removeEventListener() {}});
  const value=request('draft');
  value.details={...value.details,pre_generation:true,plan_summary:{
    scope_nodes:[{kp_id:'k',name:'洛必达法则',practice_eligible_count:12,assigned_count:1}],
    question_count:1,total_minutes:5,budget_minutes:30},
    preview_draft:{questions:[{question_id:'private-qid',question_version:'private-version',
      stem:'PRIVATE GENERATED-BEFORE STEM',options:{A:'PRIVATE OPTION'},kp_name:'洛必达法则'}]}};
  mocks.fetch.mockResolvedValue(value);
  const mounted=mountStateComponent(Card,{requestId:'r'});unmount=mounted.unmount;await flush();
  expect(text(mounted.root)).toContain('洛必达法则');
  expect(text(mounted.root)).toContain('12 道可用题');
  expect(text(mounted.root)).not.toContain('PRIVATE GENERATED-BEFORE STEM');
  expect(text(mounted.root)).not.toContain('PRIVATE OPTION');
  expect(text(mounted.root)).not.toContain('private-qid');
  expect(all(mounted.root).some(node=>node.props['data-testid']==='request-question-preview')).toBe(false);
});
