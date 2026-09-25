// 与后端 Pydantic 响应模型一一对应的类型；字段名不得随手改。

export type MasteryState = "unseen" | "consolidating" | "stuck" | "mastered";
export type PlanStatus = "active" | "completed";
export type SelfGrade = "mastered" | "partial" | "not_mastered" | "skip";

/** 推荐层级码（六层，已确认优先级）；页面负责映射成中文。 */
export type RecommendationReason =
  | "not_mastered"
  | "overdue_review"
  | "partial_mastery"
  | "insufficient_evidence"
  | "preview"
  | "consolidating";

/** 时间预算三档。 */
export type TimeBudget = "light" | "standard" | "deep";

/** 毕业条件的一项进度；key 是稳定机器码。 */
export interface GapItemView {
  key: string;
  label: string;
  current: number;
  required: number;
  satisfied: boolean;
}

export interface RecommendationItem {
  kp_id: string;
  name: string;
  state: MasteryState;
  reason: RecommendationReason;
  /** 来自真实毕业缺口的下一步，例如「完成 1 道填空题」。 */
  next_step: string;
  /** 还缺哪些题型；页面据此提示「预计加入」。 */
  missing_types: string[];
}

/** 练习卷里的一道题；响应中不含答案与解析。 */
export interface PlanItemView {
  id: string;
  ordinal: number;
  kp_id: string;
  kp_name: string;
  question_id: string;
  question_type: string;
  /** 学习角色：basic / typical / variant / comprehensive。 */
  question_role: string;
  difficulty: string;
  stem: string;
  options: Record<string, string> | null;
  /** 考法标签，例如 ["适用条件","0/0 型"]。 */
  skill_tags: string[];
  is_variant: boolean;
  /** 预计完成时间（分钟）。 */
  estimated_minutes: number;
  completed: boolean;
  completed_at: string | null;
  latest_self_grade: SelfGrade | null;
  /** 该题之前练过：题库耗尽时给的是复测题。 */
  is_review: boolean;
}

export interface TodaySummaryKp {
  kp_id: string;
  name: string;
  completed_count: number;
  total_count: number;
}

export interface TodaySetup {
  status: "setup";
  study_date: string;
  recommendations: RecommendationItem[];
}

export interface TodayActive {
  status: PlanStatus;
  plan_id: string;
  study_date: string;
  completed_count: number;
  total_count: number;
  items: PlanItemView[];
  focus_item_id: string | null;
  summary_kps: TodaySummaryKp[];
  /** 卷子构成：题型 → 道数。 */
  type_summary: Record<string, number>;
  /** 全卷预计总时长（分钟）。 */
  estimated_minutes: number;
  /** 待做部分的预计剩余时长（分钟）。 */
  remaining_minutes: number;
}

export type TodayResponse = TodaySetup | TodayActive;

export interface AssessmentResponse {
  practice_item_id: string;
  kp_id: string;
  state: MasteryState;
  reason_code: string;
  effective_confirmation_count: number;
  manual_credit_count: number;
  next_review_at: string | null;
}

export interface PracticeItemAnswer {
  practice_item_id: string;
  question_id: string;
  stem: string;
  options: Record<string, string> | null;
  correct_answer: string | null;
  explanation: string;
  question_type: string;
  grading_mode: string;
}

export interface KnowledgeNodeView {
  id: string;
  code: string;
  name: string;
  subject: string;
  ordinal: number;
  is_assessable: boolean;
  summary: string | null;
  learning_goal: string | null;
  state: MasteryState | null;
  next_review_at: string | null;
  mastered_at: string | null;
  node_self_grade: string | null;
  manual_credit_count: number;
  effective_confirmation_count: number;
  has_real_variant: boolean;
  first_confirmed_on: string | null;
  last_confirmed_on: string | null;
  day_span: number | null;
  /** 毕业缺口明细：页面直接渲染，不在前端算毕业条件。 */
  gap_items: GapItemView[];
  /** 后端给出的下一步建议。 */
  next_step: string | null;
  /** 该叶子自己的策略快照。 */
  required_question_types: Record<string, number>;
  excluded_question_types: string[];
  required_skill_tags: string[];
  children: KnowledgeNodeView[];
}

export interface KnowledgeTreeResponse {
  nodes: KnowledgeNodeView[];
}

export interface NodeQuestionView {
  id: string;
  question_type: string;
  difficulty: string;
  is_variant: boolean;
  stem: string;
  kp_id: string;
}

export interface NodeAttemptView {
  id: string;
  question_id: string;
  question_stem: string;
  self_grade: SelfGrade;
  objective_result: string;
  result_state: string;
  reason_code: string;
  submitted_at: string;
  raw_answer: string | null;
}

export interface KnowledgeNodeDetail {
  node: KnowledgeNodeView;
  questions: NodeQuestionView[];
  attempts: NodeAttemptView[];
  materials_ready: boolean;
}

export interface NodeSelfAssessmentResponse {
  kp_id: string;
  state: MasteryState;
  reason_code: string;
  effective_confirmation_count: number;
  manual_credit_count: number;
  next_review_at: string | null;
}

export function isTodayActive(value: TodayResponse): value is TodayActive {
  return value.status === "active" || value.status === "completed";
}