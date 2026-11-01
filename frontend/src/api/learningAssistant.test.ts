import { afterEach, expect, it, vi } from "vitest";
import { streamChatAnswer } from "./chat";
afterEach(()=>vi.unstubAllGlobals());
it('a committed done owns the outcome even if the connection would fail on the next read', async () => {
  let reads = 0;
  const cancel = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new ReadableStream({
    pull(controller) {
      if (++reads === 1) controller.enqueue(new TextEncoder().encode('event: done\ndata: {"answer":"完成\\\\frac{1}{2}"}\n\n'));
      else controller.error(new Error('connection failed after committed done'));
    }, cancel,
  }, {highWaterMark: 0}))));
  const events: string[] = [];
  await expect(streamChatAnswer('s', 'q', event => { events.push(event); }, new AbortController().signal)).resolves.toBeUndefined();
  expect(events).toEqual(['done']);
  expect(reads).toBe(1);
  expect(cancel).toHaveBeenCalledOnce();
});
it('terminal done rejects late body/error frames in the same packet', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('event: done\ndata: {"answer":"唯一正文"}\n\nevent: delta\ndata: {"text":"重复正文"}\n\nevent: error\ndata: {"code":"late"}\n\n')));
  const events: string[] = [];
  await streamChatAnswer('s', 'q', event => { events.push(event); }, new AbortController().signal);
  expect(events).toEqual(['done']);
});
it.each(['\n', '\r\n'])("SSE byte-by-byte UTF-8 and %j delimiters preserve Chinese, Unicode and math", async newline => {
  const answer = String.raw`中文与𝛼、∞、🙂：\[\sum_{n=1}^{\infty}nx^n=\frac{x}{(1-x)^2}\]`;
  const source = `event: delta${newline}data: ${JSON.stringify({text: answer})}${newline}${newline}` +
    `event: done${newline}data: ${JSON.stringify({answer})}`;
  const bytes = new TextEncoder().encode(source);
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  } }))));
  const events: Array<[string, Record<string, unknown>]> = [];
  await streamChatAnswer('s', 'q', (event, data) => events.push([event, data]), new AbortController().signal, {assistant:true});
  expect(events).toEqual([['delta', {text:answer}], ['done', {answer}]]);
});
it('damaged SSE JSON is an explicit failure and never masquerades as a completed reply', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('event: delta\ndata: {broken}\n\n')));
  await expect(streamChatAnswer('s', 'q', () => {}, new AbortController().signal)).rejects.toMatchObject({code:'stream_decode_error'});
});
it('invalid UTF-8 is a recoverable transport error instead of replacement-character content', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new Uint8Array([0xe4, 0xb8]))));
  await expect(streamChatAnswer('s', 'q', () => {}, new AbortController().signal)).rejects.toMatchObject({code:'stream_decode_error'});
});
it('consumer errors are not swallowed by the SSE JSON parser', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('event: delta\ndata: {"text":"中文"}\n\n')));
  await expect(streamChatAnswer('s', 'q', () => { throw new Error('render failed'); }, new AbortController().signal)).rejects.toThrow('render failed');
});
it("unified SSE sends context and action and keeps route/meta/delta/done frames",async()=>{
  const events:string[]=[];let sent:any;
  const bytes=new TextEncoder().encode('event: route\ndata: {"capability":"qa"}\n\nevent: meta\ndata: {"message_id":"reply"}\n\nevent: delta\ndata: {"text":"中文提示"}\n\nevent: done\ndata: {"answer":"中文提示"}');
  vi.stubGlobal("fetch",vi.fn(async(url,options)=>{sent={url,body:JSON.parse(options.body)};return new Response(new ReadableStream({start(controller){controller.enqueue(bytes.slice(0,120));controller.enqueue(bytes.slice(120));controller.close();}}),{status:200});}));
  await streamChatAnswer("session","提示",(event)=>events.push(event),new AbortController().signal,{assistant:true,study_context:{question_id:"q",surface:"study"},qa_action:"hint_1",request_key:"fixed"});
  expect(sent.url).toContain("assistant:stream");expect(sent.body.study_context.question_id).toBe("q");expect(sent.body.qa_action).toBe("hint_1");expect(events).toEqual(["route","meta","delta","done"]);
});
it("explicit abort is not disguised as provider error",async()=>{
  vi.stubGlobal("fetch",vi.fn(()=>Promise.reject(new DOMException("cancelled","AbortError"))));
  await expect(streamChatAnswer("s","q",()=>{},new AbortController().signal,{assistant:true,request_key:"fixed"})).rejects.toMatchObject({name:"AbortError"});
});
it("confirmed generation forwards its persisted confirmation and exact retry identity", async () => {
  let body: any;
  const fetcher = vi.fn(async (_url, options) => {
    body = JSON.parse(options.body);
    return new Response('event: error\ndata: {"code":"personal_generation_storage_forbidden","message":"保存权限不足"}\n\n', { status: 200, headers: { "Content-Type": "text/event-stream" } });
  });
  vi.stubGlobal("fetch", fetcher);
  const events: string[] = [];
  await streamChatAnswer("session", "生成一道类似的题", event => events.push(event), new AbortController().signal, {
    assistant: true, request_key: "stable", retry_of_message_id: "failed",
    personal_generation_confirmation_message_id: "confirmation", personal_generation_confirmed_kp_id: "node",
    personal_generation_mode: "ai_generated",
  });
  expect(body).toMatchObject({ question: "生成一道类似的题", request_key: "stable", retry_of_message_id: "failed", personal_generation_confirmation_message_id: "confirmation", personal_generation_confirmed_kp_id: "node" });
  expect(events).toEqual(["error"]);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("confirmed multi-node generation forwards the exact server-proposed allocation",async()=>{
  let body:any;
  vi.stubGlobal('fetch',vi.fn(async(_url,options)=>{
    body=JSON.parse(options.body);
    return new Response('event: done\ndata: {"status":"completed"}\n\n',{status:200,headers:{'Content-Type':'text/event-stream'}});
  }));
  const targets=[
    {kp_id:'node-a',question_type:'single_choice',count:3,difficulty:'basic'},
    {kp_id:'node-b',question_type:'fill_blank',count:2,difficulty:'improved'},
  ];
  await streamChatAnswer('session','生成多知识点练习',()=>{},new AbortController().signal,{assistant:true,
    request_key:'stable-multi',personal_generation_confirmation_message_id:'card',
    personal_generation_confirmed_targets:targets});
  expect(body.personal_generation_confirmed_targets).toEqual(targets);
  expect(body.personal_generation_confirmed_kp_id).toBeNull();
});
