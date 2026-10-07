import type { StudyContext } from "../api/chat";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function studyContextFromRoute(query: Record<string, unknown>): StudyContext {
  const context: StudyContext = { version: "study-context-v1", surface: "chat", origin: "navigation" };
  for (const key of ["question_id", "practice_item_id", "daily_plan_id", "attempt_id", "material_id", "chunk_id", "task_id"] as const) {
    if (typeof query[key] === "string" && uuid.test(query[key])) context[key] = query[key];
  }
  if (typeof query.knowledge_node_id === "string" && uuid.test(query.knowledge_node_id)) context.knowledge_node_ids = [query.knowledge_node_id];
  if(typeof query.knowledge_node_ids==='string'){
    const ids=query.knowledge_node_ids.split(',');if(ids.length<=8&&ids.every(id=>uuid.test(id)))context.knowledge_node_ids=[...new Set(ids)];
  }
  return context;
}
export function assistantConversationLink(sessionId: string, context: StudyContext) {
  const query: Record<string, string> = { session_id: sessionId };
  for (const key of ["question_id", "practice_item_id", "daily_plan_id", "attempt_id", "material_id", "chunk_id", "task_id"] as const) {
    if (context[key]) query[key] = context[key]!;
  }
  if((context.knowledge_node_ids?.length??0)>1)query.knowledge_node_ids=context.knowledge_node_ids!.slice(0,8).join(',');
  else if (context.knowledge_node_ids?.length) query.knowledge_node_id = context.knowledge_node_ids[0];
  return { path: "/chat", query };
}
export function rememberAssistantConversation(id: string) {
  try { localStorage.setItem("learning-assistant:builtin", id); } catch { /* optional storage */ }
}
