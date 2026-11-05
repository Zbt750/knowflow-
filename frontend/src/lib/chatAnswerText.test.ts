import { describe, expect, it } from "vitest";
import { chatAnswerText } from "./chatAnswerText";
describe("问答页引用展示", () => {
  it("历史重复来源提示只展示一次，保留正文公式和原始字符串", () => {
    const prefix='## 通用知识参考\n\n以下为模型通用知识回答，本轮未检索系统资料。\n\n';
    const original=prefix+prefix+String.raw`结论：\(\sum nx^n=\frac{x}{(1-x)^2}\)。`;
    expect(chatAnswerText(original)).toBe(prefix+String.raw`结论：\(\sum nx^n=\frac{x}{(1-x)^2}\)。`);
    expect(original.split('## 通用知识参考')).toHaveLength(3);
    expect(chatAnswerText('```text\n'+prefix+prefix+'```')).toContain(prefix+prefix);
  });
  it("隐藏资料标号，同时保留代码、公式、普通编号和链接", () => {
    const value = '结论成立 [C1]。[1] 是普通编号；代码为 `[C2]`，公式为 \\([C3]\\)。[原文](https://example.test)';
    expect(chatAnswerText(value)).toBe('结论成立 。[1] 是普通编号；代码为 `[C2]`，公式为 \\([C3]\\)。[原文](https://example.test)');
  });
});
