import type { AnswerSubmissionResponse } from "../types/practice";
export function answerFeedback(result: AnswerSubmissionResponse) {
  if (result.result === "right") return { symbol: "✓", label: "答案正确", tone: "right" };
  if (result.result === "wrong") return { symbol: "×", label: "答案错误", tone: "wrong" };
  const unanswered = result.reason === "not_answered" || result.reason === "reference_not_answered";
  return { symbol: unanswered ? "未作答" : "未判定", label: unanswered ? "未作答" : "暂无法自动判定", tone: "unknown" };
}

export function answerAssessmentNote(result: AnswerSubmissionResponse) {
  if (result.assessment_basis === "ai_consistent_reference_v1") {
    return "系统按经过一致性检查的 AI 参考答案核对最终答案；参考答案尚未经权威或人工核验，本次正确不计为独立掌握确认。";
  }
  return "";
}
