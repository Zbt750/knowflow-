import { api } from './client';

export interface PaperAdjustmentProposal {
  task_id: string;
  draft_version: string;
  requires_viewed_confirmation: boolean;
  draft: {
    kind: 'paper_adjustment'; plan_id: string; remove_item_ids: string[];
    replacements: { question_id: string; question_version_id: string }[];
    states: Record<string, string>; expires_at: string;
  };
}
export interface PaperAdjustmentReceipt {
  task_id: string; plan_id: string; removed_item_ids: string[];
  added_count: number; total_count: number; active_item_ids: string[];
}
export const proposePaperAdjustment = (body: {
  session_id: string; plan_id: string; remove_item_ids: string[];
  replacements?: { question_id: string; question_version_id: string }[];
  budget_minutes: number;
}) => api.post<PaperAdjustmentProposal>('/api/paper-adjustments', body);

export const confirmPaperAdjustment = (
  taskId: string, sessionId: string, version: string, confirmViewed = false,
) => api.post<PaperAdjustmentReceipt>(`/api/paper-adjustments/${taskId}/confirm`, {
  session_id: sessionId, draft_version: version, confirm_viewed: confirmViewed,
});
