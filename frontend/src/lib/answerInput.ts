/** 输入方式提示，不做客户端判题或通用公式等价推断。 */
export function answerInputHint(method?: string | null): string {
  if (method === "logarithm_final") return "最终答案，例如 ln(2) 或 \\ln(2)；不支持一般公式";
  if (method === "numeric_final") return "最终答案，例如 1/3、0.5 或 \\frac{1}{3}";
  return "证明和程序题可在纸上作答，这里只记录关键结论";
}
