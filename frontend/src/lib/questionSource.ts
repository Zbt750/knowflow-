import type { QuestionSourceView, QuestionTrustView } from "../types/practice";

const conciseLabel: Record<string, string> = {
  "历年真题整理版": "真题整理",
  "历年真题整理": "真题整理",
  "真题改编题": "真题改编",
  "AI原创练习题": "原创",
  "开发原创": "原创",
  "原创练习": "原创",
  "原创练习（非真题）": "原创",
  "个人 AI 练习": "AI练习题",
  "AI生成练习": "AI练习题",
  "AI生成练习题": "AI练习题",
  "AI练习题": "AI练习题",
};

function withSourceContext(label: string, source?: QuestionSourceView | null): string {
  const year = source?.year ? `${source.year} 年 · ` : "";
  const subject = source?.subject ? `${source.subject} · ` : "";
  return `${year}${subject}${label}`;
}

export function questionSourceLabel(
  source?: QuestionSourceView | null,
  showOriginalNumber = true,
  trust?: QuestionTrustView | null,
  isVariant = false,
): string {
  const provenance = trust?.question_provenance;

  // 题目来源先看题库范围：个人生成题即使有“变式”等属性，也不冒充公共真题。
  if (trust?.bank_scope === "personal") return "AI练习题";
  // 来源状态保留在后端；题目列表使用中性名称，不把来源缺失显示成待处理任务。
  if (provenance === "legacy_unknown") return "练习题";

  if (trust && provenance === "real_exam") {
    const sourceConfirmed = trust.source_attestation_current
      && ["traceable", "verified"].includes(trust.source_status);
    return sourceConfirmed ? withSourceContext("真题整理", source) : "练习题";
  }

  // 后端给出的展示分类比旧 provenance 粗分类更具体，优先用于公开题。
  const suppliedLabel = trust?.presentation_label?.trim();
  if (suppliedLabel && ["来源待核练习", "来源待核", "来源未登记", "来源待确认"].includes(suppliedLabel)) {
    return "练习题";
  }
  if (suppliedLabel && conciseLabel[suppliedLabel]) {
    return withSourceContext(conciseLabel[suppliedLabel], source);
  }

  if (provenance === "ai_generated_practice") {
    if (trust?.practice_eligible) {
      return isVariant ? "真题改编" : "原创";
    }
    return "AI练习题";
  }
  if (provenance === "trusted_practice") return withSourceContext("其他可信练习", source);

  if (!source || source.source_type === "unknown") return "练习题";
  if (source.source_type === "original") return "原创";
  if (!source.year || !source.question_number || !source.paper_title || !source.subject) return "练习题";
  const paper = source.source_type === "exam" ? `${source.subject}真题` : `${source.paper_title} · 模拟题`;
  const edition = source.edition ? ` · ${source.edition}` : "";
  const pending = source.content_status === "source_transcribed" ? " · 原卷转录" : "";
  const number = showOriginalNumber ? ` · 第 ${source.question_number} 题` : "";
  return `${source.year} 年 · ${paper}${number}${edition}${pending}`;
}
