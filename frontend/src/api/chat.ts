import { ApiError, api } from "./client";

export type ChatMode = "builtin" | "user";
export type ChatPurpose = "qa" | "study" | "materials" | "material_search";
export type StudyContext = {
  version?: "study-context-v1"; surface?: "study" | "chat" | "knowledge" | "materials";
  origin?: "navigation" | "practice" | "knowledge" | "material" | "conversation";
  subject?: string; knowledge_node_ids?: string[]; question_id?: string; question_version_id?: string; attempt_id?: string;
  daily_plan_id?: string; practice_item_id?: string; material_id?: string; chunk_id?: string;
  conversation_id?: string; task_id?: string;
};
export type AssistanceAction = "auto" | "hint_1" | "hint_2" | "solution" | "process_review";
export type PersonalGenerationMode = "ai_generated" | "ai_enhanced" | "deterministic_fast";
export type AssistantOptions = { assistant?: boolean; purpose?: ChatPurpose; study_context?: StudyContext; qa_action?: AssistanceAction; request_key?: string; retry_of_message_id?: string; current_work?: string; personal_generation_mode?: PersonalGenerationMode; personal_generation_confirmed_kp_id?: string; personal_generation_confirmed_targets?: Array<{kp_id:string;question_type:string;count:number;difficulty:string}>; personal_generation_confirmation_message_id?: string };
export type Citation = {
  label: string;
  chunk_id: string;
  material_id: string;
  material_title: string;
  heading_path: string[];
  ordinal: number;
  preview: string;
};

/**
 * matched_kp 的归因依据。
 *
 * 后端不只告诉我们「归到了哪个知识点」，还告诉我们「凭什么」：
 * 哪个命中块（source_chunk_id）、它是第几名（source_rank）、得分多少，
 * 以及这个块在本次回答里对应的引用编号（attribution_label，如 C1）。
 *
 * 为什么要给用户看：归因决定推荐哪些追练题。用户看到「依据 [C1]」就能
 * 自己判断这次归因对不对 —— 只有结论没有依据时，错归因是看不出来的。
 * 前端**只显示**这些字段，绝不自己计算归因（那是后端的职责）。
 */
export type MatchedKp = {
  kp_id: string | null;
  kp_name: string | null;
  source_chunk_id: string | null;
  source_rank: number | null;
  /**
   * 判定这次归因所用的**语义相关度**（原始向量余弦，约 0~1）。
   *
   * 归因阈值就是比它 —— 显示它，用户才能看出这条归因是「擦边过的」
   * 还是「很确定」。不要拿 score（融合分）当相关度用：那个只反映名次。
   */
  cosine: number | null;
  score: number | null;
  total: number | null;
  runner_up_total: number | null;
  /** 依据块在本次回答中的引用编号（如 "C1"）；为 null 表示该块没被正文引用。 */
  attribution_label: string | null;
  /** 后端给出的可直接显示的一句话依据说明。 */
  plain: string;
};

export type ChatMessage = {
  request_key?: string | null;
  personal_generation_confirmation_message_id?: string | null;
  personal_generation_confirmed_kp_id?: string | null;
  personal_generation_confirmed_targets?: Array<{kp_id:string;question_type:string;count:number;difficulty:string}> | null;
  personal_generation_mode?: PersonalGenerationMode | null;
  assistant_error_code?: string | null;
  retryable?: boolean;
  current_work?: string | null;
  personal_generation_confirmation?: import('./personalQuestions').GenerationConfirmation | null;
  personal_generation?: import('./personalQuestions').GenerationResult | null;
  personal_training?: PersonalTrainingChatResult | null;
  message_id: string;
  role: "user" | "assistant";
  content: string;
  status: "completed" | "generating" | "failed" | "cancelled";
  response_duration_ms?: number | null;
  answer_source?: "knowledge_base" | "general" | "mixed" | "notice" | "unverified" | null;
  matched_kp_id: string | null;
  matched_kp?: MatchedKp | null;
  citations: Citation[];
  study_context?: StudyContext | null;
  planner_task_id?: string | null;
  assistance_level?: string | null;
  qa_action?: AssistanceAction;
  practice_request_id?: string | null;
  web_sources?: Array<{title:string;url:string;retrieved_at:string}>;
  qa_information_route?: string;
};
export type PersonalTrainingChatResult = {
  action: string; status?: string; summary: string; owner_session_id: string;
  training_id?: string; item_count?: number; completed_count?: number;
  actual_minutes?: number; target_minutes?: number;
  trainings?: Array<{ training_id: string; title: string; summary: string; status: string }>;
  wrong_items?: Array<{ ordinal: number; question_id: string; knowledge_point: string; reason: string }>;
  generation?: { batch_id?: string; status?: string; question_ids?: string[]; failures?: unknown[] };
};
export type ChatSession = { session_id: string; title: string; mode: ChatMode; purpose?: ChatPurpose;study_date?:string|null;material_scope_ids?:string[] };
export type FollowupCandidate = { question_id: string; kp_id: string; stem: string; is_variant: boolean; practice_status: string };

export function createChatSession(title = "新对话", mode: ChatMode = "user", options?:{purpose?:ChatPurpose;material_scope_ids?:string[]}): Promise<ChatSession> {
  return api.post<ChatSession>("/api/chat/sessions", { title, mode,...options });
}
export const createDeepQA = (source_session_id:string,study_context:StudyContext,learning_problem:string,request_key:string) =>
  api.post<{session_id:string;study_context:StudyContext}>("/api/chat/deep-handoffs",{source_session_id,study_context,learning_problem,request_key});
/**
 * 取会话历史。
 *
 * `mode` 是可选过滤：篇 01「两种问答模式严格隔离」规定两种模式的检索范围、
 * matched_kp、追练推荐与学习事件完全不同，混在一个列表里用户分不清。
 * 不传即原来的行为（后端会返回两种模式，但**不含没有任何消息的空会话**）。
 */
export function listChatSessions(mode?: ChatMode, purpose?: ChatPurpose): Promise<ChatSession[]> {
  const params = new URLSearchParams();
  if (mode) params.set('mode', mode);
  if (purpose) params.set('purpose', purpose);
  const query = params.size ? `?${params}` : '';
  return api.get<ChatSession[]>(`/api/chat/sessions${query}`);
}
function sessionPurposePath(sessionId: string, purpose: ChatPurpose, suffix = ''): string {
  return `/api/chat/sessions/${sessionId}${suffix}?purpose=${encodeURIComponent(purpose)}`;
}
export function renameChatSession(sessionId: string, title: string, purpose: ChatPurpose = 'qa'): Promise<ChatSession> {
  return api.patch<ChatSession>(sessionPurposePath(sessionId, purpose), { title });
}
/** 永久删除一条会话。后端 `DELETE /chat/sessions/{id}` 是**物理删除**：
 *  会话行连同它的消息与引用一起从库里移除，删了就找不回来。 */
export function deleteChatSession(sessionId: string, purpose: ChatPurpose = 'qa'): Promise<void> {
  return api.delete<void>(sessionPurposePath(sessionId, purpose));
}
export function fetchChatMessages(sessionId: string, purpose: ChatPurpose = 'qa'): Promise<ChatMessage[]> {
  return api.get<ChatMessage[]>(sessionPurposePath(sessionId, purpose, '/messages'));
}
export function cancelGenerationConfirmation(sessionId: string, messageId: string, purpose: ChatPurpose = 'qa'): Promise<{ message_id: string; status: "cancelled" }> {
  return api.post(sessionPurposePath(sessionId, purpose, `/generation-confirmations/${messageId}/cancel`));
}
export function fetchFollowupCandidates(sessionId: string, messageId: string, purpose: ChatPurpose = 'qa'): Promise<{ candidates: FollowupCandidate[] }> {
  return api.post<{ candidates: FollowupCandidate[] }>(sessionPurposePath(sessionId, purpose, '/followup-candidates'), { message_id: messageId });
}
export function markChatConfused(sessionId: string, purpose: ChatPurpose = 'qa'): Promise<{ kp_id: string; reason_code: string; changes_mastery: false }> {
  return api.post(sessionPurposePath(sessionId, purpose, '/mark-confused'));
}

/**
 * 解析 POST SSE 流。
 *
 * 契约要求处理四种情况，缺一个都会表现为「回答偶尔不完整」：
 * 1. **UTF-8 汉字被拆包** —— 一个汉字三个字节可能跨两个 chunk。
 *    必须用 `TextDecoder(..., { stream: true })` 增量解码，不能每块单独 decode。
 * 2. **一个 read 含两帧** —— 必须按空行切分，逐帧处理。
 * 3. **不完整尾帧** —— 流结束时缓冲区里可能还剩最后一帧（服务端发完就没再发数据，
 *    没有结尾的空行）。早期实现直接丢弃它，于是最后一个事件（通常是 done）
 *    永远不会到达前端，页面会一直停在「正在生成」。（已修）
 * 4. **abort** —— 由外层 signal 触发，这里要让 AbortError 原样抛出，
 *    使调用方能把它与真实失败区分开（用户主动停止不是错误）。
 *
 * 另外刻意**不自动重发**：POST 重发会创建第二条 user message。
 */
export async function streamChatAnswer(
  sessionId: string,
  question: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  signal: AbortSignal,
  options?: AssistantOptions,
): Promise<void> {
  let response: Response;
  try {
    const streamPath = `/api/chat/sessions/${sessionId}/${options?.assistant ? "assistant:stream" : "answers:stream"}`;
    const scopedPath = options?.purpose ? `${streamPath}?purpose=${encodeURIComponent(options.purpose)}` : streamPath;
    response = await fetch(scopedPath, {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      // 初次请求显式发送null。旧后端会拒绝新字段，避免它把“未确认”的请求直接执行为收费出题。
      body: JSON.stringify(options?.assistant ? { question, study_context: options.study_context, qa_action: options.qa_action ?? "auto", request_key: options.request_key ?? crypto.randomUUID(), retry_of_message_id: options.retry_of_message_id, current_work: options.current_work, personal_generation_mode: options.personal_generation_mode ?? "ai_generated", personal_generation_confirmed_kp_id: options.personal_generation_confirmed_kp_id ?? null, personal_generation_confirmed_targets: options.personal_generation_confirmed_targets ?? null, personal_generation_confirmation_message_id: options.personal_generation_confirmation_message_id ?? null } : { question }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("无法连接问答服务", null, null);
  }
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    if (response.status === 422 && body?.error?.details?.some((detail: { field?: string }) => detail.field?.includes("personal_generation_confirm"))) {
      throw new ApiError("页面与后端版本不一致，请重启项目后端后再发送。输入内容已保留。", response.status, "backend_restart_required");
    }
    throw new ApiError(body?.error?.message ?? "问答请求失败", response.status, body?.error?.code ?? null);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = "";
  let terminal = false;

  const flushFrame = async (frame: string): Promise<void> => {
    if (terminal) return;
    const lines = frame.replace(/\r\n/g, "\n").split("\n");
    const event = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
    const raw = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).replace(/^ /, "")).join("\n");
    if (!event || !raw) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      throw new ApiError("回复数据不完整，请读取已保存的回复后重试。", null, "stream_decode_error");
    }
    // Do not swallow consumer/rendering errors as if they were JSON errors.
    await onEvent(event, parsed);
    terminal = event === 'done' || event === 'error';
  };

  try {
  while (true) {
    const { value, done } = await reader.read();
    // stream: true 让跨 chunk 的汉字（一个汉字 3 字节）正确拼接。
    try {
      buffer += decoder.decode(value, { stream: !done });
    } catch {
      throw new ApiError("回复文本传输不完整，请读取已保存的回复后重试。", null, "stream_decode_error");
    }

    // 只消费**完整帧**，最后一段留在 buffer 里等下一块数据。
    // 用 `\n\n(?![\s\S]*\n\n)` 匹配「最后一个空行以前」的部分。
    const split = buffer.match(/^[\s\S]*\r?\n\r?\n/);
    const consumed = split ? split[0] : "";
    buffer = buffer.slice(consumed.length);
    for (const frame of consumed.split(/\r?\n\r?\n/)) {
      if (frame.trim()) await flushFrame(frame);
    }

    if (done || terminal) break;
  }

  // 关键修复：流结束时缓冲区里可能还剩最后一帧 ——
  // 服务端发完最后一个事件就不再有数据，因此不会补上结尾空行。
  // 早期实现直接丢弃它，于是 done 事件永远到不了前端，页面卡在「正在生成」。
  if (!terminal && buffer.trim()) await flushFrame(buffer);
  } finally {
    // A terminal application event is authoritative. Transport cleanup cannot
    // turn a committed reply into failure or dispatch another answer body.
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
