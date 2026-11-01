import {ApiError} from '../api/client';

/** Applies only to the identifier-free homepage initial-recommendation request. */
export function homeRecommendationFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return '接口/版本不匹配：当前后端未提供首页初案接口（HTTP 404）。请求 /api/plans/today/home-recommendation 不需要资源或会话ID。请联系维护者核对前后端运行版本；服务更新后再重试。重试不会自行更新后端。';
    }
    if (error.status === 401 || error.status === 403) {
      return `访问受限（HTTP ${error.status}）：请核对当前站点的合法访问授权；本页不会绕过权限检查。`;
    }
    if (error.status === null) {
      return '连接失败：无法连接首页初案服务。请确认后端可用后重试；当前没有生成初案。';
    }
    return `初案读取失败（HTTP ${error.status}${error.code ? ` / ${error.code}` : ''}）：${error.message}。请重试；若持续失败，请保留错误信息联系维护者。`;
  }
  return `初案读取失败：${error instanceof Error ? error.message : String(error)}。可以重试读取，不会自动创建试卷。`;
}
