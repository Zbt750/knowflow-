import type { AnswerSubmissionResponse } from "../types/practice";
export function answerFeedback(result: AnswerSubmissionResponse) {
  if (result.result === "right") return { symbol: "✓", label: "答案正确", tone: "right" };
  if (result.result === "wrong") return { symbol: "×", label: "答案错误", tone: "wrong" };
  return { symbol: result.reason === "not_answered" ? "未作答" : "未判定", label: result.reason === "not_answered" ? "未作答" : "暂无法自动判定", tone: "unknown" };
}
