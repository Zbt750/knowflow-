// 后端返回的是稳定机器码；中文文案只在这里映射，页面不解析后端自然语言。

import type { MasteryState, RecommendationReason, SelfGrade } from "../types/practice";

const STATE_LABELS: Record<MasteryState, string> = {
  unseen: "未学习",
  consolidating: "确认累积中",
  stuck: "卡住",
  mastered: "已毕业",
};

const REASON_LABELS: Record<RecommendationReason, string> = {
  not_mastered: "上次未掌握",
  overdue_review: "复测日已到",
  partial_mastery: "上次部分掌握",
  insufficient_evidence: "毕业证据不足",
  preview: "尚未开始",
  consolidating: "巩固中",
};

/** 题型机器码 → 中文；与后端 rules.type_label 保持一致。 */
const TYPE_LABELS: Record<string, string> = {
  single_choice: "选择题",
  fill_blank: "填空题",
  calculation: "计算大题",
  proof: "证明题",
  subjective: "主观题",
};

/** 学习角色 → 中文。 */
const ROLE_LABELS: Record<string, string> = {
  basic: "基础",
  typical: "典型",
  variant: "变式",
  comprehensive: "综合",
};

export function typeLabel(value: string): string {
  return TYPE_LABELS[value] ?? value;
}

export function roleLabel(value: string): string {
  return ROLE_LABELS[value] ?? value;
}

/** 时间预算三档的中文与分钟说明。 */
export const BUDGET_OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: "light", label: "轻量", hint: "约 45 分钟" },
  { value: "standard", label: "标准", hint: "约 90 分钟" },
  { value: "deep", label: "深度", hint: "约 120 分钟" },
];

const GRADE_LABELS: Record<SelfGrade, string> = {
  mastered: "已掌握",
  partial: "部分掌握",
  not_mastered: "未掌握",
  skip: "跳过",
};

/** 后端 reason_code → 页面提示；未收录的码原样显示，便于发现问题。 */
const REASON_CODE_LABELS: Record<string, string> = {
  graduated: "已满足毕业条件",
  insufficient_confirmed_evidence: "有效确认数还不够",
  missing_real_variant: "还缺一道真实变式题",
  insufficient_day_span: "确认还没有跨天",
  no_confirmed_evidence: "本题不计入毕业确认",
  not_mastered: "已标记为未掌握",
  node_not_mastered: "已标记为未掌握",
  mastery_already_confirmed: "已毕业，本次只刷新确认时间",
  skipped: "已跳过，未记录",
  node_self_assessment_replayed: "重复提交，采用上次结果",
};

export function stateLabel(state: MasteryState | null): string {
  if (!state) return "汇总节点";
  return STATE_LABELS[state] ?? state;
}

export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason as RecommendationReason] ?? reason;
}

export function gradeLabel(grade: SelfGrade): string {
  return GRADE_LABELS[grade] ?? grade;
}

export function reasonCodeLabel(code: string): string {
  return REASON_CODE_LABELS[code] ?? code;
}

/** 幂等键：同一次点击的重试复用同一个键，避免产生重复练习历史。 */
export function newIdempotencyKey(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}-${Date.now().toString(36)}-${random}`;
}

export function formatTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return value;
}

/** 资料处理状态 → 中文与提示色。 */
const MATERIAL_STATUS_LABELS: Record<string, string> = {
  pending: "排队中",
  indexing: "建立索引中",
  ready: "可检索",
  failed: "处理失败",
};

const MATERIAL_STATUS_CLASSES: Record<string, string> = {
  pending: "status-pending",
  indexing: "status-indexing",
  ready: "status-ready",
  failed: "status-failed",
};

export function materialStatusLabel(status: string): string {
  return MATERIAL_STATUS_LABELS[status] ?? status;
}

export function materialStatusClass(status: string): string {
  return MATERIAL_STATUS_CLASSES[status] ?? "status-pending";
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  user: "我上传的",
  builtin: "随仓库提供",
};

export function sourceTypeLabel(value: string): string {
  return SOURCE_TYPE_LABELS[value] ?? value;
}

/** 任务状态 → 中文。 */
const JOB_STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  running: "处理中",
  retry: "将重试",
  succeeded: "已成功",
  failed: "已失败",
};

export function jobStatusLabel(status: string): string {
  return JOB_STATUS_LABELS[status] ?? status;
}

/**
 * 单个文件的真实上限（MB）。
 *
 * **必须与后端 `backend/ingestion/source_io.py` 的 `MAX_FILE_BYTES` 保持一致。**
 * 上传与解析共用同一个上限，因此不存在「传上去才失败」的中间地带；
 * 这个常量只用于在上传前就给出准确提示。
 */
export const MAX_FILE_MB = 10;

/**
 * 资料/检索域的错误码 → 中文说明。
 * 未收录的码原样显示，便于第一时间发现后端新增了错误码。
 *
 * 注意：文案里**不要写死数字**。之前这里写「超过 20 MB 上限」，
 * 而实际上传与解析的上限不同，于是一个 11 MB 的文件会看到「超过 20 MB」这种假话。
 * 上限现在由 MAX_FILE_MB 统一表达。
 */
const MATERIAL_ERROR_LABELS: Record<string, string> = {
  material_not_found: "资料不存在",
  unsupported_type: "只支持 .md、.txt、.docx 与带文本层的 .pdf",
  file_too_large: `文件超过 ${MAX_FILE_MB} MB 上限`,
  empty_file: "文件是空的",
  document_decode_failed: "文件编码无法识别（请另存为 UTF-8）",
  scanned_pdf: "这个 PDF 没有文本层（扫描件需要 OCR，当前不支持）",
  document_parse_failed: "文件已损坏或格式不完整，无法解析（换个文件或另存后重试）",
  unsafe_storage_path: "存储路径不合法",
  material_file_not_found: "源文件在磁盘上找不到了",
  no_chunk_to_index: "这份资料没有可索引的正文",
  index_version_has_no_chunk: "索引版本为空，未激活",
  embedding_unavailable: "向量模型不可用，稍后重试",
  embedding_dimension_mismatch: "向量维度不匹配，需要重建索引",
  retrieval_unavailable: "检索服务未就绪（模型或向量库不可用）",
  empty_query: "请输入要检索的内容",
  job_failed: "处理任务失败",
  invalid_request: "请求不合法",
  validation_failed: "参数不符合要求",
  // 任务兜底错误：后端只回这个稳定码，具体异常类型留在服务端日志里。
  internal_error: "服务内部错误，请稍后重试或联系维护者查看日志",
  database_unavailable: "数据库暂时不可用",
};

export function materialErrorLabel(code: string | null): string {
  if (!code) return "—";
  return MATERIAL_ERROR_LABELS[code] ?? code;
}

/** 字节数 → 人类可读。 */
export function formatBytes(size: number | null): string {
  if (size === null || size === undefined) return "—";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(2)} MB`;
}

/** 标题路径 → 一行面包屑。 */
export function headingPathLabel(path: string[]): string {
  return path.length ? path.join(" / ") : "（无标题）";
}
