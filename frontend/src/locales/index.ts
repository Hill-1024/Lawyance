/*
 * 模块描述：多语言词条注册表，统一暴露语言枚举、词条表、系统语言探测与占位符插值。
 */

import { zhCN, type MessageKey } from './zh-CN';
import { enUS } from './en-US';
import { viVN } from './vi-VN';
import { msMY } from './ms-MY';

export const LOCALES = ['zh-CN', 'en-US', 'vi-VN', 'ms-MY'] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'zh-CN';

/** 语言自称，选择器里始终以本语言显示，避免用户看不懂当前语言的名字。 */
export const LOCALE_LABELS: Record<Locale, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
  'vi-VN': 'Tiếng Việt',
  'ms-MY': 'Bahasa Melayu',
};

export const MESSAGES: Record<Locale, Record<MessageKey, string>> = {
  'zh-CN': zhCN,
  'en-US': enUS,
  'vi-VN': viVN,
  'ms-MY': msMY,
};

export const isLocale = (value: unknown): value is Locale => (
  typeof value === 'string' && (LOCALES as readonly string[]).includes(value)
);

/** 首次启动时按浏览器语言偏好择一，命中不了就回落默认语言。 */
export const detectSystemLocale = (): Locale => {
  if (typeof navigator === 'undefined') return DEFAULT_LOCALE;
  const candidates = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const tag of candidates) {
    if (!tag) continue;
    if (/^zh\b/i.test(tag)) return 'zh-CN';
    if (/^en\b/i.test(tag)) return 'en-US';
    if (/^vi\b/i.test(tag)) return 'vi-VN';
    if (/^ms\b/i.test(tag)) return 'ms-MY';
  }
  return DEFAULT_LOCALE;
};

/** 把 `{name}` 占位符替换为参数值；未提供对应参数时原样保留，便于及早发现漏传。 */
export const formatMessage = (template: string, params?: Record<string, string | number>) => {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (placeholder, name: string) => (
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : placeholder
  ));
};

export type { MessageKey };