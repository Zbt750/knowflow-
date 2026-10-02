import { api } from "./client";
import type { components } from "./types";
export type VisionSettings = components["schemas"]["VisionSettingsView"];
export type VisionInput = components["schemas"]["VisionSettingsUpdate"];
export type Recognition = components["schemas"]["RecognitionResponse"];
export const fetchVisionSettings = () => api.get<VisionSettings>("/api/settings/vision");
export const saveVisionSettings = (body: VisionInput, token: string) =>
  api.put<VisionSettings>("/api/settings/vision", body, { "X-Settings-Token": token });
export function recognizeWork(itemId: string, file: File, signal: AbortSignal): Promise<Recognition> {
  const form = new FormData(); form.append("file", file); form.append("consent", "true");
  return api.upload(`/api/practice-items/${itemId}/recognize-work`, form, signal);
}
