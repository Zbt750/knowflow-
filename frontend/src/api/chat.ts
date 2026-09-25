import { ApiError, api } from "./client";

export type ChatMode = "builtin" | "user";
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
  message_id: string;
  role: "user" | "assistant";
  content: string;
  status: "completed" | "generating" | "failed" | "cancelled";
  response_duration_ms?: number | null;
  matched_kp_id: string | null;
  matched_kp?: MatchedKp | null;
  citations: Citation[];
};
export type ChatSession = { session_id: string; title: string; mode: ChatMode };
export type FollowupCandidate = { question_id: string; kp_id: string; stem: string; is_variant: boolean; practice_status: string };

export function createChatSession(title = "新对话", mode: ChatMode = "user"): Promise<ChatSession> {
  return api.post<ChatSession>("/api/chat/sessions", { title, mode });
}
/**
 * 取会话历史。
 *
 * `mode` 是可选过滤：篇 01「两种问答模式严格隔离」规定两种模式的检索范围、
 * matched_kp、追练推荐与学习事件完全不同，混在一个列表里用户分不清。
 * 不传即原来的行为（后端会返回两种模式，但**不含没有任何消息的空会话**）。
 */
export function listChatSessions(mode?: ChatMode): Promise<ChatSession[]> {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return api.get<ChatSession[]>(`/api/chat/sessions${query}`);
}
export function renameChatSession(sessionId: string, title: string): Promise<ChatSession> {
  return api.patch<ChatSession>(`/api/chat/sessions/${sessionId}`, { title });
}
/** 永久删除一条会话。后端 `DELETE /chat/sessions/{id}` 是**物理删除**：
 *  会话行连同它的消息与引用一起从库里移除，删了就找不回来。 */
export function deleteChatSession(sessionId: string): Promise<void> {
  return api.delete<void>(`/api/chat/sessions/${sessionId}`);
}
export function fetchChatMessages(sessionId: string): Promise<ChatMessage[]> {
  return api.get<ChatMessage[]>(`/api/chat/sessions/${sessionId}/messages`);
}
export function fetchFollowupCandidates(sessionId: string, messageId: string): Promise<{ candidates: FollowupCandidate[] }> {
  return api.post<{ candidates: FollowupCandidate[] }>(`/api/chat/sessions/${sessionId}/followup-candidates`, { message_id: messageId });
}
export function markChatConfused(sessionId: string): Promise<{ kp_id: string; reason_code: string; changes_mastery: false }> {
  return api.post(`/api/chat/sessions/${sessionId}/mark-confused`);
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
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/chat/sessions/${sessionId}/answers:stream`, {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("无法连接问答服务", null, null);
  }
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.error?.message ?? "问答请求失败", response.status, body?.error?.code ?? null);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushFrame = (frame: string): void => {
    const event = frame.match(/^event: (.+)$/m)?.[1];
    const raw = frame.match(/^data: (.+)$/m)?.[1];
    if (!event || !raw) return;
    try {
      onEvent(event, JSON.parse(raw) as Record<string, unknown>);
    } catch {
      // 单帧解析失败不能中断整条流：后面的 delta 仍然有价值。
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    // stream: true 让跨 chunk 的汉字（一个汉字 3 字节）正确拼接。
    buffer += decoder.decode(value, { stream: !done });

    // 只消费**完整帧**，最后一段留在 buffer 里等下一块数据。
    // 用 `\n\n(?![\s\S]*\n\n)` 匹配「最后一个空行以前」的部分。
    const split = buffer.match(/^[\s\S]*\n\n/);
    const consumed = split ? split[0] : "";
    buffer = buffer.slice(consumed.length);
    for (const frame of consumed.split("\n\n")) {
      if (frame.trim()) flushFrame(frame);
    }

    if (done) break;
  }

  // 关键修复：流结束时缓冲区里可能还剩最后一帧 ——
  // 服务端发完最后一个事件就不再有数据，因此不会补上结尾空行。
  // 早期实现直接丢弃它，于是 done 事件永远到不了前端，页面卡在「正在生成」。
  if (buffer.trim()) flushFrame(buffer);
}
