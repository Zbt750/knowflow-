import { describe, expect, it } from "vitest";
import { allowsSelfReport, answerSubmissionLabel, answerGradingNotice } from "./answerInteraction";

describe("作答方式与判题能力分别处理", () => {
  for (const type of ["single_choice", "multiple_choice", "fill_blank", "calculation", "program_output", "code_execution"]) {
    it(`${type} 无判题能力也不提供自评替代`, () => {
      const item = { question_type: type, answer_grading_method: null };
      expect(allowsSelfReport(item)).toBe(false);
      expect(answerSubmissionLabel(item)).toBe("提交答案");
      expect(answerGradingNotice(item)).toContain("尚未启用可靠判题");
    });
  }
  for (const type of ["proof", "subjective", "discussion", "program", "algorithm", "code", "external_exam"]) {
    it(`${type} 可保存主观反馈但不能确认毕业`, () => {
      const item = { question_type: type, answer_grading_method: null };
      expect(allowsSelfReport(item)).toBe(true);
      expect(answerGradingNotice(item)).toContain("不计入毕业确认");
    });
  }
  it("已支持判题不提供自评，待核验和未支持不混为一谈", () => {
    expect(allowsSelfReport({ question_type: "fill_blank", answer_grading_method: "numeric_final" })).toBe(false);
    expect(answerGradingNotice({ question_type: "fill_blank", answer_grading_method: "numeric_final" })).toContain("仅核对最终答案");
    expect(answerGradingNotice({ question_type: "single_choice", question_source: { content_status: "source_transcribed", source_type: "unknown" } })).toContain("格式暂不支持");
    expect(answerGradingNotice({ question_type: "single_choice", answer_grading_method: "reference_single_choice" })).toBe("按题库答案核对最终结果。");
    expect(allowsSelfReport({ question_type: "unknown" })).toBe(false);
  });
});
