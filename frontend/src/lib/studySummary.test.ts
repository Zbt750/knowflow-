import { describe, expect, it } from "vitest";
import { studySummary, wrongAnswerItems } from "./studySummary";
import type { PlanItemView } from "../types/practice";
describe("学习小结", () => {
  it("区分机器结果、辅助作答与自评，不把未知记为错误", () => {
    const items = [
      { completed: true, answer_submission: { result: "right", assisted: true } },
      { completed: true, answer_submission: { result: "wrong", assisted: false } },
      { completed: true, answer_submission: { result: "unknown", assisted: false } },
      { completed: true }, { completed: false },
    ] as PlanItemView[];
    expect(studySummary(items)).toEqual({ submitted: 3, correct: 1, incorrect: 1, ungraded: 1, assisted: 1, selfReported: 1 });
  });
  it("无记录不推断掌握情况", () => {
    expect(studySummary([]).submitted).toBe(0);
  });
  it("错题回看只纳入明确判错题，保留原卷次序且不修改输入", () => {
    const items = [
      { id: "wrong", completed: true, answer_submission: { result: "wrong" } },
      { id: "right", completed: true, answer_submission: { result: "right" } },
      { id: "unknown", completed: true, answer_submission: { result: "unknown" } },
      { id: "legacy", completed: true, latest_self_grade: "not_mastered" },
      { id: "external", completed: true, is_external_reference: true, answer_submission: { result: "wrong" } },
      { id: "pending", completed: false, answer_submission: { result: "wrong" } },
      { id: "wrong-assisted", completed: true, answer_submission: { result: "wrong", assisted: true } },
    ] as unknown as PlanItemView[];
    const before = JSON.stringify(items);
    expect(wrongAnswerItems(items).map(item => item.id)).toEqual(["wrong", "wrong-assisted"]);
    expect(JSON.stringify(items)).toBe(before);
  });
});
