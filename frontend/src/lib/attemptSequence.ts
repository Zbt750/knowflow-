import type { AnswerSubmissionResponse } from "../types/practice";

const labels: Record<string, string> = {
  first_independent_correct: "本次独立答对",
  self_corrected: "自行改正",
  correct_after_ungraded: "重新提交后答对",
  hint_assisted_correct: "提示后答对",
  solution_assisted_correct: "看解析后完成",
  process_review_assisted_correct: "过程建议后完成",
  repeat_correct: "再次答对",
  independent_retest_correct: "本次复测答对",
  independent_correct_history_unknown: "答对，先前记录不完整",
  low_confidence_correct: "答对，信心不足",
  incorrect: "答错",
  unable_to_grade: "未判定",
};

export function attemptLabel(attempt: AnswerSubmissionResponse): string {
  return labels[attempt.sequence_category ?? ""] ?? "历史作答";
}

export function canRetryAnswer(attempt?: AnswerSubmissionResponse | null): boolean {
  return attempt?.can_retry === true && ["wrong", "unknown"].includes(attempt.result);
}
