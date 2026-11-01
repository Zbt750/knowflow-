import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../api/chat";
import { assistantFailureMessage, assistantTurnFromHistory, createAssistantTurn, retryAssistantTurn, savedAssistantTurn } from "./assistantTurn";

const message = (message_id: string, role: "user" | "assistant", content: string, status: ChatMessage["status"] = "completed"): ChatMessage => ({ message_id, role, content, status, citations: [], matched_kp_id: null });

describe("assistant turn identity and recovery", () => {
  it('recovery before meta must match the persisted request key, not another tab reply', () => {
    const turn = createAssistantTurn('session', '我的问题', {request_key: 'mine'}, []);
    const foreign = {...message('foreign', 'assistant', '别的标签页回答'), request_key: 'other'};
    const own = {...message('own', 'assistant', '本条回答'), request_key: 'mine'};
    expect(savedAssistantTurn(turn, [foreign, own])).toBe(own);
    expect(savedAssistantTurn(turn, [foreign])).toBeUndefined();
  });
  it('an assistant missing from the supplied history cannot borrow a different user question', () => {
    expect(assistantTurnFromHistory('s', message('missing', 'assistant', '', 'failed'), [message('other', 'user', '别的问题'), message('other-reply', 'assistant', '别的回答')])).toBeNull();
  });
  it("confirmation retries retain the original node, mode, context, confirmation and key", () => {
    const context = { question_id: "question-v1", knowledge_node_ids: ["old-node"], surface: "study" as const };
    const original = createAssistantTurn("session", "生成一道类似的题", {
      request_key: "same-request", study_context: context, current_work: "我的步骤",
      personal_generation_mode: "deterministic_fast", personal_generation_confirmed_kp_id: "old-node",
      personal_generation_confirmation_message_id: "confirmation",
    }, [message("user", "user", "生成一道类似的题")]);
    context.question_id = "new-question"; context.knowledge_node_ids[0] = "new-node";
    const retried = retryAssistantTurn(original, message("failed-reply", "assistant", "", "failed"));
    expect(retried.options).toEqual({ request_key: "same-request", study_context: { question_id: "question-v1", knowledge_node_ids: ["old-node"], surface: "study" }, current_work: "我的步骤", personal_generation_mode: "deterministic_fast", personal_generation_confirmed_kp_id: "old-node", personal_generation_confirmation_message_id: "confirmation", retry_of_message_id: "failed-reply" });
  });

  it("a disconnected stream recovers its saved reply without confusing an earlier identical question", () => {
    const history = [message("old-user", "user", "再讲一下"), message("old-reply", "assistant", "旧回答")];
    const turn = createAssistantTurn("session", "再讲一下", { request_key: "key" }, history);
    expect(savedAssistantTurn(turn, history)).toBeUndefined();
    const latest = message("new-reply", "assistant", "已保存的新回答");
    expect(savedAssistantTurn(turn, [...history, message("new-user", "user", "再讲一下"), latest])).toBe(latest);
    expect(savedAssistantTurn({ ...turn, replyId: "new-reply" }, [latest, message("other-reply", "assistant", "另一个回答")])).toBe(latest);
  });

  it("a history reload restores confirmed-generation request facts rather than the current composer", () => {
    const confirmation = { ...message("confirmation", "assistant", "确认知识点"), personal_generation_confirmation: { question: "生成一道类似的题", message: "请选择", selected_kp_id: "node", question_count: 1, difficulty: "medium", nodes: [] } };
    const failed = { ...message("failed", "assistant", "", "failed"), personal_generation_confirmation_message_id: "confirmation", personal_generation_confirmed_kp_id: "node", personal_generation_mode: "ai_generated" as const, current_work: "旧步骤", study_context: { question_id: "question" } };
    const restored = assistantTurnFromHistory("session", failed, [message("source", "user", "生成一道类似的题"), confirmation, failed]);
    expect(restored?.question).toBe("生成一道类似的题");
    expect(restored?.options).toMatchObject({ retry_of_message_id: "failed", personal_generation_confirmation_message_id: "confirmation", personal_generation_confirmed_kp_id: "node", current_work: "旧步骤", study_context: { question_id: "question" } });
    expect(assistantTurnFromHistory("s", failed, [failed])).toBeNull();
  });

  it("permission and internal errors give actionable status without treating a saved message as an unsent draft", () => {
    expect(assistantFailureMessage("personal_generation_storage_forbidden")).toContain("尚未调用模型");
    expect(assistantFailureMessage("internal_error", "internal error")).toContain("已保存这条提问");
    expect(assistantFailureMessage("llm_not_configured", "请先配置模型")).toBe("请先配置模型");
  });
});
