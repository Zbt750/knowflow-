/** 输入方式提示，不做客户端判题或通用公式等价推断。 */
export function answerInputHint(method?: string | null, questionType?: string): string {
  method = method?.replace(/^reference_/, "");
  if (method === "constant_final") return "最终答案，例如 -2pi、e、sqrt(2)/2 或相应 LaTeX 常量表达式";
  if (method === "logarithm_final") return "最终答案，例如 ln(2) 或 \\ln(2)；不支持一般公式";
  if (method === "numeric_final") return "最终答案，例如 1/3、0.5 或 \\frac{1}{3}";
  if (["fill_blank", "calculation", "program_output", "code_execution"].includes(questionType ?? "")) return "在纸上计算，在这里填写最终答案";
  return "可在纸上作答，这里只记录关键结论";
}
