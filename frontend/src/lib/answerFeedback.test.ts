import { expect, it } from "vitest";
import { answerFeedback, answerAssessmentNote } from "./answerFeedback";
import type { AnswerSubmissionResponse } from "../types/practice";
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
