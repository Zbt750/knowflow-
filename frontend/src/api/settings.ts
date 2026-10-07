import { api } from "./client";
import type { components } from "./types";

export type ModelSettings = components["schemas"]["ModelSettingsView"];
export type ModelSettingsInput = components["schemas"]["ModelSettingsUpdate"];
export const fetchModelSettings = () => api.get<ModelSettings>("/api/settings/model");
export const saveModelSettings = (input: ModelSettingsInput, token: string) =>
  api.put<ModelSettings>("/api/settings/model", input, { "X-Settings-Token": token });
