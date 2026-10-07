import { afterEach, expect, it, vi } from "vitest";
import { streamChatAnswer } from "./chat";
afterEach(()=>vi.unstubAllGlobals());
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
