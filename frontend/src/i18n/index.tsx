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

const detectLocale = (): Locale => {
  if (typeof window === 'undefined') return DEFAULT_LOCALE;
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // 存储被禁用（隐私模式、WebView 策略）：退回浏览器语言，不能让模块加载期直接抛错。
  }
  if (isLocale(stored)) return stored;
  const preferred = window.navigator.languages || [window.navigator.language];
  const matched = preferred.find((tag) => isLocale(tag) || isLocale(tag?.split('-')[0]));
  if (matched) return isLocale(matched) ? matched : (matched.split('-')[0] as Locale);
  return DEFAULT_LOCALE;
};

/**
 * 当前语言快照：只给组件之外的模块级文案（translate）用。
 * 启动时按存储/浏览器语言初始化；切换语言时由 setLocale 在触发重渲染之前同步写入，
 * 于是这次重渲染里的 translate() 读到的就已经是新语言。组件内请用 useT() 的 t。
 */
let activeLocale: Locale = detectLocale();

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

/** 按指定语言取词条，不读快照：组件内的 t 就是它绑定到 provider 当前语言后的结果。 */
export const translateIn = (
  locale: Locale,
  key: MessageKey,
  params?: Record<string, string | number>,
): string => {
  const template = pick(LOCALES[locale].messages, key) ?? pick(zhCN, key) ?? String(key);
  return interpolate(template, params);
};

/** 组件之外（模块级状态表、工具函数）用：读当前语言快照。 */
export const translate: Translator = (key, params) => translateIn(activeLocale, key, params);

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translator;
}

const I18nContext = createContext<I18nValue>({
  locale: DEFAULT_LOCALE,
  setLocale: () => undefined,
  t: translate,
});

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [locale, setLocaleState] = useState<Locale>(() => activeLocale);

  useEffect(() => {
    if (typeof document !== 'undefined') document.documentElement.lang = locale;
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // 隐私模式下写不进去：只影响下次启动的默认语言，不必打断界面。
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    // 先写快照再触发重渲染：此前快照在 effect 里才更新，切换后这一轮渲染读到的仍是旧语言。
    activeLocale = next;
    setLocaleState(next);
  }, []);
  // t 绑定当前语言：切换语言时它换一个引用，把 t 列进依赖的 effect / memo 会随之重算，
  // 而不是停在旧语言的文案上。
  const t = useCallback<Translator>((key, params) => translateIn(locale, key, params), [locale]);
  const value = useMemo<I18nValue>(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

/** 组件内取 t：t 随语言切换而变，可以（也应当）列进 hooks 的依赖数组。 */
export const useT = () => useContext(I18nContext);
