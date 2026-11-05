import { api } from "./client";

export type PersonalTrainingQuestion = {
  item_id: string; ordinal: number; question_id: string; question_version_id: string;
  kp_id: string; question_type: string; difficulty: string; estimated_minutes: number;
  stem: string; options: Record<string, string> | null; completed: boolean;
  draft_answer: string | null; draft_selected_option: string | null; draft_revision: number;
  draft_saved_at: string | null;
  completed_at: string | null; latest_result: "right" | "wrong" | "unknown" | null;
};
export type PersonalTrainingView = {
  training_id: string; owner_session_id: string; request_key: string; title: string;
  status: "active" | "paused" | "completed" | "cancelled"; version: number;
  knowledge_point_ids: string[]; selection_basis: string; requested_count: number | null;
  target_minutes: number; actual_minutes: number; inventory_shortfall: number;
  minutes_shortfall: number; item_count: number; completed_count: number; remaining_count: number;
  progress_percent: number; started_at: string; paused_at: string | null; finished_at: string | null;
  adapted_from_training_id: string | null; items: PersonalTrainingQuestion[];
  context?: Record<string, unknown>;
};
export type PersonalTrainingReport = {
  training_id: string; status: string; question_count: number; submitted_count: number;
  right_count: number; wrong_count: number; unknown_count: number;
  wrong_knowledge_points: Array<{ kp_id: string; name: string; wrong_count: number }>;
  next_round_recommendation: { knowledge_point_ids: string[]; question_count: number } | null;
  evidence_scope: string;
};

function ownerQuery(ownerSessionId: string): string {
  return `owner_session_id=${encodeURIComponent(ownerSessionId)}`;
}
export const listPersonalTrainings = (owner: string) =>
  api.get<PersonalTrainingView[]>(`/api/practice-trainings?${ownerQuery(owner)}`);
export const readPersonalTraining = (id: string, owner: string) =>
  api.get<PersonalTrainingView>(`/api/practice-trainings/${id}?${ownerQuery(owner)}`);
export const createPersonalTraining = (body: {
  owner_session_id: string; request_key: string; title: string; knowledge_point_ids: string[];
  question_count: number | null; target_minutes: number; difficulty: "any" | "basic" | "improved" | "comprehensive";
  question_type: string | null; basis: "selected" | "recent_mistakes";
}) => api.post<PersonalTrainingView>("/api/practice-trainings", body);
export const appendPersonalTraining = (id: string, body: {
  owner_session_id: string; request_key: string; expected_version: number; question_count: number;
}) => api.post<PersonalTrainingView>(`/api/practice-trainings/${id}/items`, body);
export const transitionPersonalTraining = (id: string, action: "pause" | "resume" | "finish", body: {
  owner_session_id: string; request_key: string; expected_version: number;
}) => api.post<PersonalTrainingView>(`/api/practice-trainings/${id}/${action}`, body);
export const answerPersonalTrainingItem = (id: string, itemId: string, body: {
  owner_session_id: string; idempotency_key: string; expected_version: number;
  raw_answer: string | null; selected_option: string | null;
}) => api.post<PersonalTrainingView>(`/api/practice-trainings/${id}/items/${itemId}/answers`, body);
export const savePersonalTrainingDraft = (id: string, itemId: string, body: {
  owner_session_id: string; expected_draft_revision: number;
  draft_answer: string | null; draft_selected_option: string | null;
}) => api.patch<PersonalTrainingView>(`/api/practice-trainings/${id}/items/${itemId}/draft`, body);
export const readPersonalTrainingReport = (id: string, owner: string) =>
  api.get<PersonalTrainingReport>(`/api/practice-trainings/${id}/report?${ownerQuery(owner)}`);
export const createNextPersonalTraining = (id: string, body: {
  owner_session_id: string; request_key: string; question_count: number | null; target_minutes: number | null;
}) => api.post<PersonalTrainingView>(`/api/practice-trainings/${id}/next`, body);
