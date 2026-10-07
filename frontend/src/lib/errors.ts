/*
 * 模块描述：把异常翻译成给用户看的中文文案。
 *
 * 浏览器网络层抛的是英文原文（"Failed to fetch"、"Load failed"、
 * "NetworkError when attempting to fetch resource."），直接渲染进中文界面既看不懂、
 * 也无法判断该怎么办——原来「保存配置失败」弹窗里就长期显示 "Failed to fetch"。
 */

/** 网络不可用 / 请求被中断时的统一文案。 */
export const NETWORK_ERROR_MESSAGE = '网络连接异常，请检查网络后重试。';

/**
 * 已经是面向用户的最终文案（如限流状态码映射的本地化提示，构造时已按当前语言取词）。
 * describeError 对它原样放行，不再走「无中文就换兜底」的改写。
 */
export class UserFacingError extends Error {}

const NETWORK_PATTERNS = [
  'failed to fetch',
  'load failed',
  'networkerror',
  'network request failed',
  'fetch failed',
  'the internet connection appears to be offline',
  'err_',
];

/**
 * 优先保留中文文案（多为后端 detail 透传），网络类错误换成统一中文，
 * 其余英文原文只写进控制台并返回兜底文案——界面不出现看不懂的英文。
 */
export const describeError = (error: unknown, fallback = '操作失败，请稍后重试。'): string => {
  if (error instanceof UserFacingError) return error.message;
  const raw = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  const message = raw.trim();
  if (!message) return fallback;
  if (/[\u4e00-\u9fa5]/.test(message)) return message;
  const lowered = message.toLowerCase();
  if (NETWORK_PATTERNS.some((pattern) => lowered.includes(pattern))) return NETWORK_ERROR_MESSAGE;
  console.warn('[lawver] 未翻译的错误原文：', message);
  return fallback;
};
