import { api } from "./client";
import type { components } from "./types";
export type LearningTask = components["schemas"]["TaskView"];
export const createLearningTask = (goal: string, budget: number, sessionId: string | null) =>
  api.post<LearningTask>("/api/learning-tasks", { goal, budget_minutes: budget, session_id: sessionId, mode: "builtin" });
export const fetchLearningTask = (id: string) => api.get<LearningTask>(`/api/learning-tasks/${id}`);
export const runLearningTask = (id: string) => api.post<LearningTask>(`/api/learning-tasks/${id}/run`, {});
export const cancelLearningTask = (id: string) => api.post<LearningTask>(`/api/learning-tasks/${id}/cancel`, {});
export const confirmLearningTask = (id: string, version: string) =>
  api.post<LearningTask>(`/api/learning-tasks/${id}/confirm`, { draft_version: version });
export const modifyLearningTask = (id: string, goal: string, budget: number) =>
  api.patch<LearningTask>(`/api/learning-tasks/${id}`, { goal, budget_minutes: budget });
