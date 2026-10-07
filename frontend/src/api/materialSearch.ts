import { api } from "./client";
export type MaterialSearchSession = {
  session_id: string; title: string; mode: "user"; purpose: "material_search";
  study_date: string; scope_mode: "all" | "selected"; selected_file_ids: string[];
};
export const getDailyMaterialSearch = () => api.post<MaterialSearchSession>("/api/chat/material-search/session");
export const setMaterialSearchScope = (sessionId: string, ids: string[]) =>
  api.patch<MaterialSearchSession>("/api/chat/material-search/scope", {
    session_id: sessionId, scope_mode: ids.length ? "selected" : "all", selected_file_ids: ids,
  });
