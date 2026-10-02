import { expect, it } from "vitest";
import { answerFeedback } from "./answerFeedback";
import type { AnswerSubmissionResponse } from "../types/practice";
it("已判题只给简短符号，保留可访问名称", () => {
  expect(answerFeedback({ result: "wrong" } as AnswerSubmissionResponse)).toEqual({ symbol: "×", label: "答案错误", tone: "wrong" });
  expect(answerFeedback({ result: "right" } as AnswerSubmissionResponse).symbol).toBe("✓");
});
it("未判定和空白不会被误标为错误", () => {
  expect(answerFeedback({ result: "unknown", reason: "unsupported_answer" } as AnswerSubmissionResponse).symbol).toBe("未判定");
  expect(answerFeedback({ result: "unknown", reason: "not_answered" } as AnswerSubmissionResponse).symbol).toBe("未作答");
});
