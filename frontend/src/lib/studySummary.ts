import type { PlanItemView } from "../types/practice";
export function wrongAnswerItems(items: PlanItemView[]): PlanItemView[] {
  // 只回看明确判错且已保存的题；未知、空白、自评和原卷引用不猜正误。
  return items.filter(item => item.completed && !item.is_external_reference && item.answer_submission?.result === "wrong");
}
export function studySummary(items: PlanItemView[]) {
  const submissions = items.flatMap(item => item.answer_submission ? [item.answer_submission] : []);
  return {
    submitted: submissions.length,
    correct: submissions.filter(s => s.result === "right").length,
    incorrect: submissions.filter(s => s.result === "wrong").length,
    ungraded: submissions.filter(s => !["right", "wrong"].includes(s.result)).length,
    assisted: submissions.filter(s => s.assisted).length,
    selfReported: items.filter(i => i.completed && !i.answer_submission).length,
  };
}
