import type { AssistantOptions, ChatMessage } from "../api/chat";

/** A retry is a continuation of an accepted turn, never a new composer draft. */
export type AssistantTurn = {
  sessionId: string;
  question: string;
  options: AssistantOptions;
  knownMessageIds: string[];
  replyId?: string;
};

export function createAssistantTurn(sessionId: string, question: string, options: AssistantOptions, history: Array<{ message_id?: string }>): AssistantTurn {
  return {
    sessionId, question,
    // Keep the exact context, generation mode and confirmation choice for retries,
    // even if the user opens another question or edits the composer afterwards.
    options: JSON.parse(JSON.stringify({ ...options, request_key: options.request_key ?? crypto.randomUUID() })),
    knownMessageIds: history.flatMap(message => message.message_id ? [message.message_id] : []),
  };
}

export function savedAssistantTurn(turn: AssistantTurn, history: ChatMessage[]): ChatMessage | undefined {
  if (turn.replyId) return history.find(message => message.role === 'assistant' && message.message_id === turn.replyId);
  const candidates = history.filter(message => message.role === "assistant" && !turn.knownMessageIds.includes(message.message_id));
  const keyed = candidates.find(message => message.request_key && message.request_key === turn.options.request_key);
  if (keyed) return keyed;
  // Never claim another tab's turn when our meta frame was lost. Old servers
  // without keys only permit a single, unambiguous question/reply pair.
  if (candidates.some(message => message.request_key) || candidates.length !== 1) return undefined;
  const candidate = candidates[0]!;
  const index = history.findIndex(message => message.message_id === candidate.message_id);
  const source = history.slice(0, index).reverse().find(message => message.role === 'user');
  return source?.content === turn.question ? candidate : undefined;
}

export function retryAssistantTurn(turn: AssistantTurn, saved?: ChatMessage): AssistantTurn {
  return {
    ...turn,
    replyId: saved?.message_id ?? turn.replyId,
    options: { ...turn.options, retry_of_message_id: saved?.status === "failed" ? saved.message_id : turn.options.retry_of_message_id },
  };
}

/** Recover a failed turn after refresh using the server's persisted request facts. */
export function assistantTurnFromHistory(sessionId: string, message: ChatMessage, history: ChatMessage[]): AssistantTurn | null {
  const index = history.findIndex(item => item.message_id === message.message_id);
  if(index < 0 || message.role !== 'assistant') return null;
  const confirmation = history.find(item => item.message_id === message.personal_generation_confirmation_message_id);
  const source = history.slice(0, index).reverse().find(item => item.role === "user");
  const question = confirmation?.personal_generation_confirmation?.question ?? source?.content;
  if (!question) return null;
  const turn = createAssistantTurn(sessionId, question, {
    assistant: true, request_key: message.request_key ?? undefined, study_context: message.study_context ?? undefined,
    qa_action: message.qa_action ?? "auto",
    current_work: message.current_work ?? undefined,
    personal_generation_mode: message.personal_generation_mode ?? "ai_generated",
    personal_generation_confirmed_kp_id: message.personal_generation_confirmed_kp_id ?? undefined,
    personal_generation_confirmation_message_id: message.personal_generation_confirmation_message_id ?? undefined,
    retry_of_message_id: message.status === "failed" ? message.message_id : undefined,
  }, history);
  return { ...turn, replyId: message.message_id };
}

export function assistantFailureMessage(code?: string | null, message?: string): string {
  if (code === 'generation_failed') return '本条回答生成未完成，原提问已保留；可以读取状态后重试。';
  if (code === 'answer_truncated') return '本条回答达到输出上限，已保留未完成内容；请缩小问题范围后重试。';
  if (code === "personal_generation_storage_forbidden") return "当前应用账号缺少出题保存权限，尚未调用模型；请联系管理员修复权限后重试。";
  if (code === "internal_error" || message === "internal error") return "本次处理未完成，已保存这条提问。请重试这条回复；无需重新输入。";
  return message || "本次回复未完成，已保留原提问，可重试这条回复。";
}
