// 资料相关的类型与接口封装。
// 约束：前端不计算任何业务状态（状态、块数、索引版本、知识点关联全部来自后端）。

import { api } from "./client";

export type MaterialStatus = "pending" | "indexing" | "ready" | "failed";
export type MaterialSourceType = "user" | "builtin";

export interface MaterialJob {
  id: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  result_index_version: string | null;
  created_at: string;
}

export interface Material {
  id: string;
  title: string;
  source_type: MaterialSourceType;
  original_filename: string | null;
  status: MaterialStatus;
  file_size: number | null;
  active_index_version: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface MaterialDetail extends Material {
  chunk_count: number;
  latest_job: MaterialJob | null;
}

export interface MaterialContentResponse {
  title: string;
  text: string | null;
}

export interface MaterialListResponse {
  items: Material[];
  total: number;
  stats: Record<string, number>;
}

export interface ChunkPreview {
  id: string;
  ordinal: number;
  heading_path: string[];
  char_count: number;
  preview: string;
  kp_hint_code: string | null;
}

export interface ChunkListResponse {
  items: ChunkPreview[];
  total: number;
}

export interface UploadResponse {
  material: Material;
  job_id: string;
  message: string;
}


export function listMaterials(limit = 50, offset = 0, q = ""): Promise<MaterialListResponse> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q.trim()) query.set("q", q.trim());
  return api.get<MaterialListResponse>(`/api/materials?${query.toString()}`);
}

/** 只读取服务端过滤后的总数，不能用列表第一页推断整个资料范围是否可用。 */
export async function countReadyMaterials(sourceType: MaterialSourceType): Promise<number> {
  const query = new URLSearchParams({
    limit: "1",
    offset: "0",
    status: "ready",
    source_type: sourceType,
  });
  const response = await api.get<MaterialListResponse>(`/api/materials?${query.toString()}`);
  return response.total;
}

export function getMaterialContent(id: string): Promise<MaterialContentResponse> {
  return api.get<MaterialContentResponse>(`/api/materials/${id}/content`);
}

export function getMaterial(id: string): Promise<MaterialDetail> {
  return api.get<MaterialDetail>(`/api/materials/${id}`);
}

export function listChunks(id: string, limit = 20, focusChunkId?: string): Promise<ChunkListResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (focusChunkId) query.set("focus_chunk_id", focusChunkId);
  return api.get<ChunkListResponse>(`/api/materials/${id}/chunks?${query.toString()}`);
}

export function uploadMaterial(
  file: File,
  title: string,
  sourceType: MaterialSourceType,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  // 标题与来源类型是 query 参数：后端接口契约如此，前端不做额外转换。
  const query = new URLSearchParams({ title, source_type: sourceType });
  return api.upload<UploadResponse>(`/api/materials?${query.toString()}`, form, signal);
}

export function deleteMaterial(id: string): Promise<void> {
  return api.delete<void>(`/api/materials/${id}`);
}

export function reindexMaterial(id: string): Promise<MaterialJob> {
  return api.post<MaterialJob>(`/api/materials/${id}/reindex`);
}

export function retryMaterial(id: string): Promise<MaterialJob> {
  return api.post<MaterialJob>(`/api/materials/${id}/retry`);
}
