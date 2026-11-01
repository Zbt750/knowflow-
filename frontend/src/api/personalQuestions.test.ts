import {afterEach,expect,it,vi} from 'vitest';
import {readBank,hidePersonal,appendPersonal,readGeneration} from './personalQuestions';
import {cancelGenerationConfirmation,fetchChatMessages,listChatSessions} from './chat';
afterEach(()=>vi.unstubAllGlobals());
it('restores real partial outcome counts and diagnostics without generating or hiding failures',async()=>{
  const result={batch_id:'partial',status:'partial',requested:2,question_ids:['saved-one'],
    message:'1道已保存，另外1道答案校验不一致',
    outcome_summary:{requested_count:2,saved_count:1,failed_count:1,attempted_count:2,
      not_attempted_count:0,unresolved_count:0,provider_calls:2,quality_rejected_count:1,
      response_failed_count:0,structure_rejected_count:0,
      failure_details:[{code:'personal_generation_answer_conflict',count:1,message:'答案校验不一致'}]},
    diagnostics:[{index:2,code:'personal_generation_answer_conflict',stage:'answer_check',message:'未保存'}]};
  const fetch=vi.fn(async(_url:string)=>new Response(JSON.stringify(result)));vi.stubGlobal('fetch',fetch);
  expect(await readGeneration('same-request')).toEqual(result);
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0]?.[0]).toBe('/api/personal-questions/batches/same-request');
});
it('asks the server for explicit QA or study purpose instead of hiding mixed sessions locally',async()=>{
  const fetch=vi.fn(async(_url:string)=>new Response('[]'));vi.stubGlobal('fetch',fetch);
  await listChatSessions('builtin','qa'); await listChatSessions('builtin','study');
  expect(fetch.mock.calls.map(c=>c[0])).toEqual(['/api/chat/sessions?mode=builtin&purpose=qa','/api/chat/sessions?mode=builtin&purpose=study']);
});
it('keeps study message reads and confirmation cancellation explicitly scoped to study',async()=>{
  const fetch=vi.fn(async(url:string)=>new Response(url.endsWith('/messages')?'[]':JSON.stringify({message_id:'card',status:'cancelled'})));
  vi.stubGlobal('fetch',fetch);
  await fetchChatMessages('study-session','study');
  await cancelGenerationConfirmation('study-session','card','study');
  expect(fetch.mock.calls.map(c=>c[0])).toEqual([
    '/api/chat/sessions/study-session/messages?purpose=study',
    '/api/chat/sessions/study-session/generation-confirmations/card/cancel?purpose=study',
  ]);
});
it('reads a persisted generation rejection with its real stage without generating again',async()=>{
  const data={batch_id:'old-failed',status:'failed',question_ids:[],message:'模型输出达到长度上限',
    diagnostics:[{code:'personal_generation_output_truncated',stage:'provider_response',message:'未保存，没有自动重试'}]};
  const fetch=vi.fn(async(_url:string)=>new Response(JSON.stringify(data)));vi.stubGlobal('fetch',fetch);
  expect(await readGeneration('original-key')).toEqual(data);
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0]?.[0]).toBe('/api/personal-questions/batches/original-key');
});
it('bank filters ownership, node and hidden status without leaking answers',async()=>{
  const fetch=vi.fn(async(_url:string)=>new Response(JSON.stringify({total:0,items:[]})));vi.stubGlobal('fetch',fetch);
  await readBank('personal','node','∫ test',20,true);
  expect(fetch.mock.calls[0]?.[0]).toContain('scope=personal');expect(fetch.mock.calls[0]?.[0]).toContain('include_hidden=true');
  expect(fetch.mock.calls[0]?.[0]).toContain('kp_id=node');expect(fetch.mock.calls[0]?.[0]).toContain('offset=20');
});
it('append retry and hide use existing question IDs, not another generate request',async()=>{
  const calls:Array<{url:string;body:any}>=[];vi.stubGlobal('fetch',vi.fn(async(url,opts)=>{calls.push({url,body:opts.body?JSON.parse(opts.body):null});return new Response('{}');}));
  await appendPersonal(['q'],'plan');await hidePersonal('q',true);await readGeneration('request');
  expect(calls[0]).toEqual({url:'/api/personal-questions/append',body:{question_ids:['q'],plan_id:'plan'}});
  expect(calls[1].body).toEqual({hidden:true});expect(calls.every(c=>!c.url.endsWith('/generate'))).toBe(true);
});
