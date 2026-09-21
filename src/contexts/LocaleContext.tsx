/*
 * 模块描述：全局多语言上下文，提供语言切换、词条翻译函数，并把语言持久化到本机。
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import {
  DEFAULT_LOCALE,
  MESSAGES,
  detectSystemLocale,
  formatMessage,
  isLocale,
  type Locale,
  type MessageKey,
} from '../locales';

type MessageParams = Record<string, string | number>;

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, params?: MessageParams) => string;
}

const STORAGE_KEY = 'lawver.locale';

const LocaleContext = createContext<LocaleContextValue | null>(null);

const readPersistedLocale = (): Locale => {
  if (typeof window === 'undefined') return DEFAULT_LOCALE;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (isLocale(raw)) return raw;
  } catch {
    // 隐私模式下 localStorage 读取会抛错，回落系统语言即可，不阻断启动。
  }
  return detectSystemLocale();
};

export const LocaleProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // 同步读取而非异步：异步会先渲染默认语言再切换，出现可见的文案闪变。
  const [locale, setLocaleState] = useState<Locale>(readPersistedLocale);

  // 语言影响无障碍朗读与断词规则，必须同步到 <html lang>。
  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.lang = locale;
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // 持久化失败不应回滚本次切换，当前会话内仍然生效。
    }
  }, []);

  const value = useMemo<LocaleContextValue>(() => {
    const dictionary = MESSAGES[locale];
    return {
      locale,
      setLocale,
      t: (key, params) => formatMessage(dictionary[key], params),
    };
  }, [locale, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
};

export const useLocale = () => {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error('useLocale must be used within LocaleProvider');
  }
  return context;
};

/** 只取翻译函数的场景用它，避免组件订阅整个 locale 上下文。 */
export const useTranslation = () => useLocale().t;