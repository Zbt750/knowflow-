import { describe, expect, it } from "vitest";
import { answerInputHint } from "./answerInput";

describe("有限最终答案输入提示", () => {
  it("数值支持分数输入，不推荐近似值", () => {
    expect(answerInputHint("numeric_final")).toContain("\\frac{1}{3}");
  });
  it("自然对数显示明确语法与范围", () => {
    expect(answerInputHint("logarithm_final")).toContain("ln(2)");
    expect(answerInputHint("logarithm_final")).toContain("不支持一般公式");
  });
  it("无判题能力不建议填写机器可判答案", () => {
    expect(answerInputHint(null)).toContain("纸上作答");
  });
});
