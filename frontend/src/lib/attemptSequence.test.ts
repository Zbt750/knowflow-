import { describe, it, expect } from "vitest";
import { attemptLabel, canRetryAnswer } from "./attemptSequence";
import type { AnswerSubmissionResponse } from "../types/practice";

describe("attempt evidence labels", () => {
  const attempt = (props: Partial<AnswerSubmissionResponse>) => props as AnswerSubmissionResponse;
  it("does not guess categories for legacy or future records", () => {
    expect(attemptLabel(attempt({}))).toBe("历史作答");
    expect(attemptLabel(attempt({ sequence_category: "self_corrected" }))).toBe("自行改正");
    expect(attemptLabel(attempt({ sequence_category: "solution_assisted_correct" }))).toBe("看解析后完成");
    expect(attemptLabel(attempt({ sequence_category: "repeat_correct" }))).toBe("再次答对");
  });
  it("retries only server-authorized wrong or ungraded outcomes", () => {
    expect(canRetryAnswer(attempt({ result: "wrong", can_retry: true }))).toBe(true);
    expect(canRetryAnswer(attempt({ result: "unknown", can_retry: true }))).toBe(true);
    expect(canRetryAnswer(attempt({ result: "right", can_retry: true }))).toBe(false);
    expect(canRetryAnswer(attempt({ result: "wrong", can_retry: false }))).toBe(false);
    expect(canRetryAnswer(attempt({ result: "wrong" }))).toBe(false);
    expect(canRetryAnswer(null)).toBe(false);
  });
});
