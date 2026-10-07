// 统一 API 客户端。
// 约束：
// - 前端永远请求相对 /api（开发期 Vite 代理，部署期 Nginx 代理）。
// - 错误一律按 { error: { code, message } } 解析，页面按 code 分支，不解析自然语言。
// - 不在这里计算任何业务状态（掌握度、毕业、引用），那些只由后端决定。

export type ApiErrorBody = { code: string; message: string; details?: { field: string; code: string; message: string }[] };

export class ApiError extends Error {
  public readonly status: number | null;
  public readonly code: string | null;

  public constructor(message: string, status: number | null, code: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function isApiErrorEnvelope(value: unknown): value is { error: ApiErrorBody } {
  if (!value || typeof value !== "object" || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return Boolean(
    error && typeof error === "object" && "code" in error && "message" in error
      && typeof error.code === "string" && typeof error.message === "string",
  );
}

function isValidationError(value: unknown): boolean {
  // FastAPI 的 422 校验错误是 {"detail": [...]}，与业务错误体不同。
  return Boolean(value && typeof value === "object" && "detail" in value);
}

async function request<T>(
  path: string,
  init?: Omit<RequestInit, "headers"> & { json?: unknown; form?: FormData; headers?: Record<string, string> },
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...init?.headers };
  let body: string | FormData | undefined;
  if (init?.form !== undefined) {
    // FormData 必须让浏览器自己带 boundary，手写 Content-Type 会导致后端解析失败。
    body = init.form;
  } else if (init?.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method: init?.method ?? "GET",
      headers,
      body,
      // signal 必须透传：健康检查会在组件卸载时中止在途请求。
      // 若不透传，页面切换后仍会写回状态，形成「已离开却还在更新」的竞态。
      signal: init?.signal ?? null,
    });
  } catch (error) {
    // 用户/组件主动中止不是失败：原样抛出，交给调用方与真实错误区分开。
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("无法连接后端服务", null, null);
  }

  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    if (isApiErrorEnvelope(payload)) {
      if (payload.error.code === "validation_failed") {
        const details = Array.isArray(payload.error.details) ? payload.error.details.filter((item) => typeof item?.field === "string" && typeof item?.message === "string") : [];
        const message = details.length ? details.slice(0, 5).map((item) => `${item.field.replace(/^(query|path|body)\./, "")}：${item.message}`).join("；") : "请求参数不符合要求";
        throw new ApiError(message, response.status, payload.error.code);
      }
      throw new ApiError(payload.error.message, response.status, payload.error.code);
    }
    if (isValidationError(payload)) {
      throw new ApiError("请求参数不符合要求", response.status, "validation_failed");
    }
    throw new ApiError("请求失败", response.status, null);
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal): Promise<T> => request<T>(path, { signal }),
  post: <T>(path: string, json?: unknown): Promise<T> =>
    request<T>(path, { method: "POST", json }),
  put: <T>(path: string, json?: unknown, headers?: Record<string, string>): Promise<T> =>
    request<T>(path, { method: "PUT", json, headers }),
  patch: <T>(path: string, json?: unknown): Promise<T> =>
    request<T>(path, { method: "PATCH", json }),
  delete: <T>(path: string): Promise<T> => request<T>(path, { method: "DELETE" }),
  /** 上传文件：走 multipart，不设置 Content-Type。 */
  upload: <T>(path: string, form: FormData, signal?: AbortSignal): Promise<T> =>
    request<T>(path, { method: "POST", form, signal }),
};
