/*
 * 模块描述：前端 i18n 基础设施（工程规范：类型化词条 + 运行时切换 + 无 React 场景可用的 translate）。
 *
 * 设计取舍：
 *   · **键在编译期校验**：MessageKey 由 zh-CN 词条表推导（递归点分路径），
 *     写错键名 tsc 就报错，不需要等到运行时才发现；
 *   · **源语言即回退**：任何语言缺某条键时回退 zh-CN，绝不把键名渲染到界面上；
 *   · **可访问名与可见文案同源**：aria-label / title 用同一批键，切换语言时无障碍内容一起变，
 *     这正是 WCAG 对"名称、角色、值"的要求；
 *   · **模块级文案也能翻**：非组件作用域（如状态映射表）用 translate()，
 *     它读的是 provider 写入的当前语言快照——比把一张表拆进组件更省事，也不会读到过期值。
 *
 * 新增语言：在 locales 里登记一个同结构对象 + 一个显示名即可，其余代码不用动。
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { zhCN, type Messages } from './zh-CN';
import { enUS } from './en-US';

/** 递归点分路径：'workbench.tabs.close'。 */
type DotPaths<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${DotPaths<T[K]>}`;
}[keyof T & string];

export type MessageKey = DotPaths<Messages>;

/**
 * 语言登记表。messages 允许是**部分翻译**（DeepPartial）：缺的键由 translate 回退
 * 到 zh-CN，所以可以边迁移边补，不会出现空白文案——迁移完成度看 `pnpm run test:i18n`。
 */
export const LOCALES = {
  'zh-CN': { label: '简体中文', messages: zhCN as unknown as Messages },
  'en-US': { label: 'English', messages: enUS as unknown as Messages },
} as const;

export type Locale = keyof typeof LOCALES;

export const DEFAULT_LOCALE: Locale = 'zh-CN';
const STORAGE_KEY = 'lawver.locale';

const isLocale = (value: unknown): value is Locale =>
  typeof value === 'string' && Object.prototype.hasOwnProperty.call(LOCALES, value);

/** 当前语言快照：模块级文案（translate）用它，provider 负责写入。 */
let activeLocale: Locale = DEFAULT_LOCALE;

const pick = (messages: unknown, key: string): string | undefined => {
  let node: unknown = messages;
  for (const part of key.split('.')) {
    if (!node || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === 'string' ? node : undefined;
};

const interpolate = (template: string, params?: Record<string, string | number>) => {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match,
  );
};

/** 取词条：缺键回退源语言；再缺就回退键名本身（便于开发时一眼看出漏翻）。 */
/** 翻译函数签名：需要把 t 当参数传出去（模块级表格、兜底数据）时用它做类型。 */
export type Translator = (key: MessageKey, params?: Record<string, string | number>) => string;

export const translate: Translator = (key, params) => {
  const template =
    pick(LOCALES[activeLocale].messages, key) ?? pick(zhCN, key) ?? String(key);
  return interpolate(template, params);
};

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nValue>({
  locale: DEFAULT_LOCALE,
  setLocale: () => undefined,
  t: translate,
});

const detectLocale = (): Locale => {
  if (typeof window === 'undefined') return DEFAULT_LOCALE;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (isLocale(stored)) return stored;
  const preferred = window.navigator.languages || [window.navigator.language];
  const matched = preferred.find((tag) => isLocale(tag) || isLocale(tag?.split('-')[0]));
  if (matched) return isLocale(matched) ? matched : (matched.split('-')[0] as Locale);
  return DEFAULT_LOCALE;
};

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [locale, setLocaleState] = useState<Locale>(detectLocale);

  useEffect(() => {
    activeLocale = locale;
    if (typeof document !== 'undefined') document.documentElement.lang = locale;
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // 隐私模式下写不进去：只影响下次启动的默认语言，不必打断界面。
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => setLocaleState(next), []);
  const value = useMemo<I18nValue>(
    () => ({ locale, setLocale, t: translate }),
    [locale, setLocale],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

/** 组件内取 t；语言变化会触发重渲染（translate 本身读的是快照，不订阅）。 */
export const useT = () => useContext(I18nContext);
