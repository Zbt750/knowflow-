import { ApiError, api } from "./client";

/**
 * 健康检查。
 *
 * 这个模块**只保留两件 client.ts 不做的事**：
 *   1. 声明 /api/health 的响应形状（类型 + 运行时校验）；
 *   2. 在形状不符时给出可诊断的错误，而不是把脏数据当成功。
 *
 * 请求本身、错误信封解析、网络失败判定全部走 `client.ts` ——
 * 阶段 E 的目标是「统一 API client / 统一错误码 / 统一状态」，
 * 早先这里自建了一套 fetch + 自己的 `ApiError` 类型 + 自己的信封解析，
 * 结果是同一个后端错误在两个模块里被解析成两种对象。
 *
 * 注意：`ApiError` 从这里再导出，只是为了不破坏既有 import 路径；
 * 它**就是** client.ts 里那一个类，不再是第二份定义。
 */

export type HealthResponse = {
  status: "ok";
  database: "connected";
  /** 检索栈状态；后端可能不返回（旧版本），因此可选。 */
  retrieval?: string;
  /** worker 状态；同上。 */
  worker?: string;
  /** 仅报告服务端配置状态，不返回密钥。 */
  llm_configured?: boolean;
  llm_model?: string | null;
  /** 运行环境标识（dev/test/prod）：e2e 靠它拒绝误连开发库。 */
  environment?: string;
};

export { ApiError };

/** /api/health 的路径。集中在此，避免各处硬编码字符串。 */
export const HEALTH_PATH = "/api/health";

function isHealthResponse(value: unknown): value is HealthResponse {
  if (!value || typeof value !== "object") return false;
  const body = value as Record<string, unknown>;
  return body.status === "ok" && body.database === "connected";
}

/**
 * 读取后端健康状态。
 *
 * 失败时抛 `client.ts` 的 `ApiError`：
 *   - 后端可用但数据库挂了 → 503，`code === "database_unavailable"`，`status === 503`
 *   - 后端根本没起       → `status === null`，`code === null`
 *   - 组件卸载主动中止   → 原样抛 `AbortError`（调用方自行忽略）
 *
 * 调用方据此区分「后端不可达」与「后端在但依赖坏了」，这正是阶段 A 的
 * 503 分支要验的行为。
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const payload = await api.get<unknown>(HEALTH_PATH, signal);
  if (!isHealthResponse(payload)) {
    // 200 但形状不对：这是契约被破坏，不能当成健康。
    throw new ApiError("后端返回了不符合约定的健康检查结果", 200, "unexpected_health_payload");
  }
  return payload;
}
