import type { QuestionSourceView } from "../types/practice";

export function questionSourceLabel(source?: QuestionSourceView | null, showOriginalNumber = true): string {
  if (!source || source.source_type === "unknown") return "来源未登记";
  if (source.source_type === "original") return "原创练习（非真题）";
  if (!source.year || !source.question_number || !source.paper_title || !source.subject) return "来源待确认";
  const paper = source.source_type === "exam" ? `${source.subject}真题` : `${source.paper_title} · 模拟题`;
  const edition = source.edition ? ` · ${source.edition}` : "";
  const pending = source.content_status === "source_transcribed" ? " · 原卷转录" : "";
  const number = showOriginalNumber ? ` · 第 ${source.question_number} 题` : "";
  return `${source.year} 年 · ${paper}${number}${edition}${pending}`;
}
