import type { PlanItemView } from "../types/practice";

type AnswerItem = Pick<PlanItemView, "question_type" | "answer_grading_method" | "question_source">;
// A missing grader does not turn an objective question into a self-assessed one.
const PROCESS_TYPES = new Set(["proof", "subjective", "discussion", "program", "algorithm", "code", "external_exam"]);
export function allowsSelfReport(item: AnswerItem): boolean {
  return !item.answer_grading_method && PROCESS_TYPES.has(item.question_type);
}
export function answerSubmissionLabel(item: AnswerItem): string {
  return allowsSelfReport(item) ? "记录作答" : "提交答案";
}
export function answerGradingNotice(item: AnswerItem): string {
  if (item.answer_grading_method?.startsWith("reference_")) return "按题库答案核对最终结果。";
  if (item.answer_grading_method) return "仅核对最终答案，不评价推导过程。";
  if (allowsSelfReport(item)) return "本题不自动判分；自行对照和辅助审阅不计入毕业确认。";
  if (item.question_source?.content_status === "source_transcribed") return "本题答案格式暂不支持自动比较，可提交作答并查看解析。";
  return "本题尚未启用可靠判题，提交仅保存作答，不计入毕业确认。";
}
