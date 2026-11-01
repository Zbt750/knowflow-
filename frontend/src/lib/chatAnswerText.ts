/** 问答页隐藏检索编号；原始消息和引用证据仍由服务端完整保留。 */
export function chatAnswerText(text: string): string {
  // 仅兼容历史中完全相同的连续来源前缀；不改库内原文、正文或代码。
  const prefix = /^(\s*## 通用知识参考\s*\n\s*\n(?:以下为模型通用知识回答，本轮未检索系统资料。|知识库中没有找到足够依据。以下是模型基于通用知识给出的参考回答，不是资料中的结论。)\s*\n\s*\n)/;
  const first = text.match(prefix);
  if (first) {
    let rest = text.slice(first[0].length);
    while (prefix.test(rest)) rest = rest.replace(prefix, "");
    text = first[0] + rest;
  }
  // 只移除系统引用标记，不改公式中的方括号、网页链接或用户的普通编号。
  return text.replace(/```[\s\S]*?```|`[^`\n]*`|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\$[^$\n]*\$|\[C\d+\]/g,
    token => /^\[C\d+\]$/.test(token) ? "" : token);
}
