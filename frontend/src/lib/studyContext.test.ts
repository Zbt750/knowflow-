import { describe, expect, it } from "vitest";
import { studyContextFromRoute, assistantConversationLink } from "./studyContext";
const first="11111111-1111-4111-8111-111111111111", second="22222222-2222-4222-8222-222222222222";
describe("conversation and study location", () => {
  it("updates question A to B without changing conversation identity", () => {
    const a=studyContextFromRoute({question_id:first,session_id:second});
    const b=studyContextFromRoute({question_id:second,session_id:second});
    expect(a.question_id).toBe(first); expect(b.question_id).toBe(second);
    expect(assistantConversationLink(second,b).query.session_id).toBe(second);
  });
  it("ignores arbitrary free-text state and invalid entity ids", () => {
    const ctx=studyContextFromRoute({question_id:"fake",mastery:"graduated",attempt_id:[first],knowledge_node_id:first});
    expect(ctx.question_id).toBeUndefined(); expect(ctx.attempt_id).toBeUndefined(); expect(ctx.knowledge_node_ids).toEqual([first]);
    expect(ctx).not.toHaveProperty("mastery");
  });
  it("dropping location parameters clears the current question", () => {
    expect(studyContextFromRoute({session_id:first}).question_id).toBeUndefined();
  });
  it("round-trips validated Planner task identity without inventing question location", () => {
    const ctx=studyContextFromRoute({task_id:first,session_id:second});
    expect(ctx.task_id).toBe(first);expect(ctx.question_id).toBeUndefined();
    expect(assistantConversationLink(second,ctx).query.task_id).toBe(first);
    expect(studyContextFromRoute({task_id:"not-a-task"}).task_id).toBeUndefined();
  });
  it('round-trips all validated deep-handoff nodes instead of silently keeping only the first',()=>{
    const link=assistantConversationLink(first,{knowledge_node_ids:[first,second]});
    expect(studyContextFromRoute(link.query).knowledge_node_ids).toEqual([first,second]);
  });
});
