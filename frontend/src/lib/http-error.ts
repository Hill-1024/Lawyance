/*
 * 模块描述：错误响应的统一文案解析。
 *
 * 全站错误契约是 {"detail": ...} JSON；但 429（限流）等错误可能来自中间件/网关，
 * 响应体不是 JSON——此前 res.json().catch() 兜底成「网络请求失败」，把服务端
 * 限流（带 Retry-After）误报成用户网络故障。这里对非 JSON 体按状态码映射本地化
 * 文案：429 读 Retry-After 提示「N 秒后再试」，5xx 视为服务端繁忙。
 */

import { translate } from '../i18n';

/** 限流契约里固定出现的英文 detail；改用本地化文案，避免中文界面冒英文。 */
const RATE_LIMIT_DETAIL = 'Rate limit exceeded';

export const readRetryAfterSeconds = (response: Response): number | null => {
  const raw = response.headers?.get?.('retry-after');
  if (!raw) return null;
  const seconds = Number(raw);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.max(Math.ceil(seconds), 1) : null;
};

/** 状态码 → 本地化兜底文案。 */
export const httpStatusErrorMessage = (response: Response): string => {
  if (response.status === 429) {
    const retryAfter = readRetryAfterSeconds(response);
    return retryAfter
      ? translate('errors.rateLimitedRetry', { seconds: retryAfter })
      : translate('errors.rateLimited');
  }
  if (response.status >= 500) return translate('errors.serverBusy');
  return translate('errors.requestFailed');
};

/**
 * 已解析的错误体（可能为 null：非 JSON 体）→ 用户文案：遵循 {"detail": ...} 契约
 * （字符串或 {message}）；非 JSON 体、缺 detail、或限流契约的英文 detail，
 * 都退回状态码映射的本地化文案。
 */
export const describeHttpErrorBody = (response: Response, parsed: unknown): string => {
  const detail = (parsed as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail && detail !== RATE_LIMIT_DETAIL) return detail;
  if (
    detail &&
    typeof detail === 'object' &&
    typeof (detail as { message?: unknown }).message === 'string' &&
    (detail as { message: string }).message
  ) {
    return (detail as { message: string }).message;
  }
  return httpStatusErrorMessage(response);
};

/** 便捷版：自行解析响应体（body 只能读一次，已有 parsed 结果时用 describeHttpErrorBody）。 */
export const describeHttpError = async (response: Response): Promise<string> =>
  describeHttpErrorBody(response, await response.json().catch(() => null));
