import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {h} from 'vue';
import {all, deferred, flush, mountStateComponent, text} from '../components/stateTestHost';
const mocks=vi.hoisted(()=>({sessions:vi.fn(),messages:vi.fn(),count:vi.fn(),create:vi.fn()}));
vi.mock('../api/chat',async original=>({...await original<typeof import('../api/chat')>(),listChatSessions:mocks.sessions,fetchChatMessages:mocks.messages,createChatSession:mocks.create}));
vi.mock('../api/materials',()=>({countReadyMaterials:mocks.count}));
vi.mock('vue-router',()=>({useRoute:()=>({path:'/chat',query:{session_id:'saved'}}),useRouter:()=>({replace:vi.fn(),push:vi.fn()})}));
vi.mock('../components/MarkdownContent.vue',()=>({default:{props:['text'],setup:(p:{text:string})=>()=>h('article',p.text)}}));
import ChatPage from './ChatPage.vue';
let view:ReturnType<typeof mountStateComponent>;
const history=[{message_id:'q1',role:'user',content:'原提问',status:'completed'},{message_id:'a1',role:'assistant',content:'原回答',status:'completed'},{message_id:'q2',role:'user',content:'追问',status:'completed'}];
beforeEach(()=>{
  vi.stubGlobal('window',{matchMedia:()=>({matches:true}),addEventListener(){},removeEventListener(){},localStorage:{getItem:()=>null}});
  vi.stubGlobal('document',{addEventListener(){},removeEventListener(){},getElementById:()=>null});
  mocks.sessions.mockResolvedValue([{session_id:'saved',mode:'builtin',title:'原会话'}]);mocks.messages.mockResolvedValue(history);
  mocks.count.mockImplementation(async(mode:string)=>{if(mode==='builtin')throw new Error('internal error');return 3;});
});
afterEach(()=>{view?.unmount();vi.unstubAllGlobals();vi.resetAllMocks();});
it('restores ordered history even when builtin material readiness fails; retry does not append messages or write',async()=>{
  view=mountStateComponent(ChatPage,{});await flush();
  expect(text(view.root)).toContain('原会话');
  const body=text(view.root);
  // Compare message rows, not the header's unrelated “追问” hint.
  const rows=all(view.root).filter(n=>n.type==='article'&&String(n.props.class).includes('message-row'));
  expect(rows.map(n=>text(n))).toEqual([expect.stringContaining('原提问'),expect.stringContaining('原回答'),expect.stringContaining('追问')]);
  expect(body).toContain('内置资料列表加载失败');expect(body).not.toContain('internal error');
  expect(mocks.count).toHaveBeenCalledWith('user');
  mocks.count.mockResolvedValue(4);
  const notice=all(view.root).find(n=>n.props['data-testid']==='materials-error-builtin')!;
  const retry=all(notice).find(n=>n.type==='button')!;await (retry.props.onClick as ()=>Promise<void>)();await flush();
  expect(text(notice)).not.toContain('内置资料列表加载失败');
  expect(all(view.root).filter(n=>n.type==='article'&&n.text==='原回答')).toHaveLength(1);
  expect(mocks.create).not.toHaveBeenCalled();expect(mocks.messages).toHaveBeenCalledTimes(1);
});
it('a failed message read has its own Chinese diagnostic and can recover without duplicating history',async()=>{
  mocks.messages.mockRejectedValueOnce(new Error('internal error'));
  view=mountStateComponent(ChatPage,{});await flush();
  expect(text(view.root)).toContain('会话消息暂时无法加载');expect(text(view.root)).not.toContain('internal error');expect(text(view.root)).not.toContain('原回答');
  const notice=all(view.root).find(n=>n.props['data-testid']==='messages-load-error')!;
  await (all(notice).find(n=>n.type==='button')!.props.onClick as ()=>Promise<void>)();await flush();
  expect(text(view.root)).toContain('原回答');expect(mocks.create).not.toHaveBeenCalled();
});
it('a failed session list retries restoration rather than opening a new conversation',async()=>{
  mocks.sessions.mockRejectedValueOnce(new Error('internal error'));
  view=mountStateComponent(ChatPage,{});await flush();
  expect(text(view.root)).toContain('会话列表暂时无法加载');expect(text(view.root)).not.toContain('原回答');
  const notice=all(view.root).find(n=>n.props['data-testid']==='sessions-load-error')!;
  await (all(notice).find(n=>n.type==='button')!.props.onClick as ()=>Promise<void>)();await flush();
  expect(text(view.root)).toContain('原回答');expect(mocks.create).not.toHaveBeenCalled();
});
it('a late old-session response cannot overwrite the newly selected history',async()=>{
  const old=deferred<typeof history>();
  mocks.sessions.mockResolvedValue([{session_id:'saved',mode:'builtin',title:'原会话'},{session_id:'newer',mode:'builtin',title:'另一会话'}]);
  mocks.messages.mockImplementation((id:string)=>id==='saved'?old.promise:Promise.resolve([{message_id:'new-answer',role:'assistant',status:'completed',content:'新会话回答'}]));
  view=mountStateComponent(ChatPage,{});await flush();
  const button=all(view.root).find(n=>n.type==='button'&&text(n)==='另一会话')!;
  expect(button).toBeDefined();await (button.props.onClick as ()=>Promise<void>)();await flush();
  expect(text(view.root)).toContain('新会话回答');
  old.resolve(history);await flush();
  expect(text(view.root)).toContain('新会话回答');expect(text(view.root)).not.toContain('原回答');expect(mocks.create).not.toHaveBeenCalled();
});
it('offers the shared study-page entry only for a training with real assigned items',async()=>{
  const owner='11111111-1111-4111-8111-111111111111';const trainingId='22222222-2222-4222-8222-222222222222';
  mocks.messages.mockResolvedValueOnce([...history,{message_id:'training-result',role:'assistant',content:'专项已建立',status:'completed',personal_training:{
    action:'create',status:'active',summary:'实际分配 3 道题',owner_session_id:owner,training_id:trainingId,item_count:3,
  }}]);
  view=mountStateComponent(ChatPage,{});await flush();
  const entry=all(view.root).find(n=>n.type==='RouterLink'&&text(n).includes('进入专项练习'))!;
  expect(entry).toBeDefined();expect(entry.props.to).toEqual({path:'/study',query:{mode:'personal',owner_session_id:owner,training_id:trainingId}});
});
it('does not show an entry for an empty or failed training result',async()=>{
  mocks.messages.mockResolvedValueOnce([...history,{message_id:'training-empty',role:'assistant',content:'未分配题目',status:'completed',personal_training:{
    action:'create',status:'failed',summary:'未创建有效专项',owner_session_id:'11111111-1111-4111-8111-111111111111',training_id:'22222222-2222-4222-8222-222222222222',item_count:0,
  }}]);
  view=mountStateComponent(ChatPage,{});await flush();
  expect(all(view.root).some(n=>n.type==='RouterLink'&&text(n).includes('进入专项练习'))).toBe(false);
});
it('does not show an entry until the training status is confirmed',async()=>{
  mocks.messages.mockResolvedValueOnce([...history,{message_id:'training-unknown',role:'assistant',content:'专项状态未确认',status:'completed',personal_training:{
    action:'create',summary:'状态未确认',owner_session_id:'11111111-1111-4111-8111-111111111111',training_id:'22222222-2222-4222-8222-222222222222',item_count:3,
  }}]);
  view=mountStateComponent(ChatPage,{});await flush();
  expect(all(view.root).some(n=>n.type==='RouterLink'&&text(n).includes('进入专项练习'))).toBe(false);
});
