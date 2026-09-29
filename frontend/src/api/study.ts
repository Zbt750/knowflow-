import { api } from "./client";
import type {
  AssessmentResponse,
  KnowledgeLessonResponse,
  KnowledgeNodeDetail,
  KnowledgeTreeResponse,
  NodeSelfAssessmentResponse,
  PracticeItemAnswer,
  SelfGrade,
  TodayResponse,
} from "../types/practice";

export function fetchToday(): Promise<TodayResponse> {
  return api.get<TodayResponse>("/api/plans/today");
}

export function generateTodayPlan(
  selectedKpIds: string[],
  budget: string = "standard",
): Promise<TodayResponse> {
  return api.post<TodayResponse>("/api/plans/today/generate", {
    selected_kp_ids: selectedKpIds,
    // 时间预算决定卷子长度；后端按每道题的 estimated_minutes 裁剪。
    budget,
  });
}

export function appendQuestions(planId: string, questionIds: string[]): Promise<TodayResponse> {
  return api.post<TodayResponse>(`/api/plans/${planId}/questions`, {
    question_ids: questionIds,
  });
}

export function appendExamReferencesToday(referenceIds: string[]): Promise<TodayResponse> {
  return api.post<TodayResponse>("/api/plans/today/exam-references", {
    reference_ids: referenceIds,
  });
}

export function fetchAnswer(itemId: string): Promise<PracticeItemAnswer> {
  // 纯读取：做题前后都可以调用，不影响掌握度与毕业。
  return api.get<PracticeItemAnswer>(`/api/practice-items/${itemId}/answer`);
}

export function submitSelfAssessment(
  itemId: string,
  selfGrade: SelfGrade,
  idempotencyKey: string,
  rawAnswer?: string,
  selectedOption?: string,
): Promise<AssessmentResponse> {
  return api.post<AssessmentResponse>(`/api/practice-items/${itemId}/self-assessments`, {
    self_grade: selfGrade,
    idempotency_key: idempotencyKey,
    raw_answer: rawAnswer ?? null,
    // 只在选择题上填写；服务端据此写 objective_result，但它不参与毕业判定。
    selected_option: selectedOption ?? null,
  });
}

export function fetchKnowledgeTree(): Promise<KnowledgeTreeResponse> {
  return api.get<KnowledgeTreeResponse>("/api/knowledge/tree");
}

export function fetchKnowledgeNode(kpId: string): Promise<KnowledgeNodeDetail> {
  return api.get<KnowledgeNodeDetail>(`/api/knowledge/${kpId}`);
}

export function fetchKnowledgeLesson(code: string): Promise<KnowledgeLessonResponse> {
  return api.get<KnowledgeLessonResponse>("/api/knowledge/lessons/" + encodeURIComponent(code));
}

export function submitNodeSelfAssessment(
  kpId: string,
  selfGrade: "mastered" | "partial" | "not_mastered",
  idempotencyKey: string,
): Promise<NodeSelfAssessmentResponse> {
  return api.post<NodeSelfAssessmentResponse>(`/api/knowledge/${kpId}/self-assessment`, {
    self_grade: selfGrade,
    idempotency_key: idempotencyKey,
  });
}
