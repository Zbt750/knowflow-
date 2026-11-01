import { expect, it } from "vitest";
import { answerFeedback, answerAssessmentNote } from "./answerFeedback";
import type { AnswerSubmissionResponse } from "../types/practice";
it('辅助后正确在普通结果卡明确提示，并保留参考答案边界',()=>{
  const cases: Partial<AnswerSubmissionResponse>[] = [
    {result:'right',assisted:true,assessment_basis:'objective_v1'},
    {result:'right',mastery_reason:'assisted_answer_recorded'},
    {result:'right',assisted:true,assessment_basis:'ai_consistent_reference_v1',feedback_notice:'参考题不计毕业'},
  ];
  for(const result of cases) {
    expect(answerFeedback(result as AnswerSubmissionResponse).label).toContain('辅助作答');
    expect(answerAssessmentNote(result as AnswerSubmissionResponse)).toContain('不计独立确认');
  }
  expect(answerAssessmentNote({result:'right',assisted:true,feedback_notice:'参考题不计毕业'} as AnswerSubmissionResponse)).toContain('参考题不计毕业');
  expect(answerFeedback({result:'right',assisted:false} as AnswerSubmissionResponse).label).toBe('答案正确');
});
it("已判题只给简短符号，保留可访问名称", () => {
  expect(answerFeedback({ result: "wrong" } as AnswerSubmissionResponse)).toEqual({ symbol: "×", label: "答案错误", tone: "wrong" });
  expect(answerFeedback({ result: "right" } as AnswerSubmissionResponse).symbol).toBe("✓");
});
it("未判定和空白不会被误标为错误", () => {
  expect(answerFeedback({ result: "unknown", reason: "unsupported_answer" } as AnswerSubmissionResponse).symbol).toBe("未判定");
  expect(answerFeedback({ result: "unknown", reason: "not_answered" } as AnswerSubmissionResponse).symbol).toBe("未作答");
});
it("AI一致性比较说明不冒充权威答案，并保持题面反馈简短", () => {
  const result = { result: "right", assessment_basis: "ai_consistent_reference_v1" } as AnswerSubmissionResponse;
  expect(answerFeedback(result).symbol).toBe("✓");
  expect(answerAssessmentNote(result)).toContain("不计为独立掌握确认");
  expect(answerAssessmentNote({ assessment_basis: "objective_v1" } as AnswerSubmissionResponse)).toBe("");
});
