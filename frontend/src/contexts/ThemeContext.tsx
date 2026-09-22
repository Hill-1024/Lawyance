/*
 * 模块描述：全局主题上下文，统一管理外观模式、种子色调色板和 Material You 占位状态。
 */

import React, { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import {
  DEFAULT_SEED,
  applyPalette,
  clearDynamicPalette,
  paletteFromMonet,
  normalizeHexColor,
  paletteFromSeed,
  type ResolvedTheme
} from '../lib/palette';
import { isNativeAndroid } from '../lib/platform';
import { syncNativeChrome } from '../lib/native-bootstrap';
import { getMonetPalette, isMonetUnavailableError } from '../services/monetService';

export type ThemeMode = 'light' | 'system' | 'dark';
export type ColorSource = 'default' | 'custom' | 'monet';
type MonetStatus = 'idle' | 'loading' | 'available' | 'unavailable' | 'error';

interface ThemeState {
  mode: ThemeMode;
  colorSource: ColorSource;
  customSeed: string;
  resolvedTheme: ResolvedTheme;
  monetStatus: MonetStatus;
  monetError?: string;
}

interface PersistedThemeState {
  mode: ThemeMode;
  colorSource: ColorSource;
  customSeed: string;
}

interface ThemeContextValue extends ThemeState {
  isMonetAvailableOnPlatform: boolean;
  setMode: (mode: ThemeMode) => void;
  setColorSource: (source: ColorSource) => void;
  setCustomSeed: (seed: string) => void;
  resetColors: () => void;
  refreshMonet: () => void;
}

const STORAGE_KEY = 'lawver.theme.settings';
const LEGACY_THEME_KEY = 'themeMode';
const THEME_TRANSITION_MS = 280;
const FALLBACK_THEME: PersistedThemeState = {
  mode: 'system',
  colorSource: 'default',
  customSeed: DEFAULT_SEED,
};

const THEME_COLOR_FALLBACK: Record<ResolvedTheme, string> = {
  light: '#f6f8fb',
  dark: '#0b0d14',
};

const FAVICON_COLOR: Record<ResolvedTheme, {
  tile: string;
  ink: string;
  tileStroke: string;
  tileStrokeOpacity: string;
  frameStroke: string;
  frameStrokeOpacity: string;
}> = {
  light: {
    tile: '#ffffff',
    ink: '#1a2238',
    tileStroke: '#14171f',
    tileStrokeOpacity: '0.10',
    frameStroke: '#14171f',
    frameStrokeOpacity: '0.08',
  },
  dark: {
    tile: '#1a2238',
    ink: '#f6f8fb',
    tileStroke: '#ffffff',
    tileStrokeOpacity: '0.18',
    frameStroke: '#ffffff',
    frameStrokeOpacity: '0.12',
  },
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

interface BrowserViewTransition {
  finished: Promise<void>;
}

type DocumentWithViewTransition = Document & {
  startViewTransition?: (callback: () => void | Promise<void>) => BrowserViewTransition;
};

let themeTransitionSequence = 0;
let themeTransitionCleanupTimer: number | undefined;

const isThemeMode = (value: unknown): value is ThemeMode => (
  value === 'light' || value === 'system' || value === 'dark'
);

const isColorSource = (value: unknown): value is ColorSource => (
  value === 'default' || value === 'custom' || value === 'monet'
);

const readPersistedTheme = (): PersistedThemeState => {
  if (typeof window === 'undefined') return FALLBACK_THEME;

  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Partial<PersistedThemeState>;
      return {
        mode: isThemeMode(parsed.mode) ? parsed.mode : FALLBACK_THEME.mode,
        colorSource: isColorSource(parsed.colorSource) ? parsed.colorSource : FALLBACK_THEME.colorSource,
        customSeed: typeof parsed.customSeed === 'string' ? normalizeHexColor(parsed.customSeed) : DEFAULT_SEED,
      };
    } catch {
      return FALLBACK_THEME;
    }
  }

  const legacyMode = localStorage.getItem(LEGACY_THEME_KEY);
  if (isThemeMode(legacyMode)) {
    const migrated = { ...FALLBACK_THEME, mode: legacyMode };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
    return migrated;
  }

  return FALLBACK_THEME;
};

const resolveTheme = (mode: ThemeMode, systemPrefersDark: boolean): ResolvedTheme => {
  if (mode === 'system') return systemPrefersDark ? 'dark' : 'light';
  return mode;
};

const createFaviconHref = (theme: ResolvedTheme) => {
  const color = FAVICON_COLOR[theme];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="0.5" y="0.5" width="63" height="63" rx="4" fill="${color.tile}" stroke="${color.tileStroke}" stroke-opacity="${color.tileStrokeOpacity}"/>
  <rect x="7" y="7" width="50" height="50" rx="2" fill="none" stroke="${color.frameStroke}" stroke-opacity="${color.frameStrokeOpacity}"/>
  <line x1="9.5" y1="52" x2="54.5" y2="52" stroke="${color.ink}" stroke-width="0.75" stroke-linecap="round" opacity="0.55"/>
  <g stroke="${color.ink}" stroke-linecap="round" stroke-linejoin="round" fill="none">
    <path d="M25.5 12 C25.5 12 24 13.3 24 17.3 L24 42.7 C24 46.7 25.5 48 28.2 48 L46.7 48" stroke-width="2"/>
    <path d="M20 12 L31 12" stroke-width="1.1"/>
    <path d="M46.7 46.7 L46.7 49.3" stroke-width="1.1"/>
    <circle cx="17.3" cy="54.7" r="1.1" fill="${color.ink}" stroke="none"/>
    <circle cx="46.7" cy="54.7" r="1.1" fill="${color.ink}" stroke="none"/>
  </g>
  <circle cx="33.3" cy="9.3" r="1.2" fill="${color.ink}"/>
</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
};

const syncBrowserChrome = (resolvedTheme: ResolvedTheme) => {
  const root = document.documentElement;
  root.classList.toggle('dark', resolvedTheme === 'dark');
  root.dataset.theme = resolvedTheme;
  root.style.colorScheme = resolvedTheme;

  const favicon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
  if (favicon) {
    favicon.type = 'image/svg+xml';
    favicon.href = createFaviconHref(resolvedTheme);
  }

  const bgApp = getComputedStyle(root).getPropertyValue('--bg-app').trim() || THEME_COLOR_FALLBACK[resolvedTheme];
  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (themeColor) themeColor.content = bgApp;
};

const canAnimateThemeTransition = () => (
  typeof window !== 'undefined' &&
  !window.matchMedia('(prefers-reduced-motion: reduce)').matches
);

const runThemeStyleTransition = (commit: () => void, animated: boolean) => {
  if (typeof document === 'undefined' || !animated || !canAnimateThemeTransition()) {
    if (typeof document !== 'undefined') {
      document.documentElement.classList.remove('lawver-theme-transitioning', 'lawver-theme-view-transition');
    }
    commit();
    return;
  }

  const root = document.documentElement;
  const sequence = ++themeTransitionSequence;
  window.clearTimeout(themeTransitionCleanupTimer);
  root.classList.remove('lawver-theme-transitioning', 'lawver-theme-view-transition');

  const cleanup = (className: string) => {
    if (sequence === themeTransitionSequence) {
      root.classList.remove(className);
    }
  };

  const transitionDocument = document as DocumentWithViewTransition;
  if (transitionDocument.startViewTransition) {
    root.classList.add('lawver-theme-view-transition');
    const transition = transitionDocument.startViewTransition(() => {
      commit();
    });
    transition.finished.finally(() => cleanup('lawver-theme-view-transition'));
    themeTransitionCleanupTimer = window.setTimeout(
      () => cleanup('lawver-theme-view-transition'),
      THEME_TRANSITION_MS + 120
    );
    return;
  }

  root.classList.add('lawver-theme-transitioning');
  // 让浏览器先计算统一 transition，再提交变量/class 变化，避免各组件按自身 duration 抢跑。
  void root.offsetWidth;
  commit();
  themeTransitionCleanupTimer = window.setTimeout(
    () => cleanup('lawver-theme-transitioning'),
    THEME_TRANSITION_MS + 80
  );
};

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const initial = useMemo(readPersistedTheme, []);
  const [mode, setMode] = useState<ThemeMode>(initial.mode);
  const [colorSource, setColorSource] = useState<ColorSource>(initial.colorSource);
  const [customSeed, setCustomSeedState] = useState(initial.customSeed);
  const [systemPrefersDark, setSystemPrefersDark] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });
  const [monetStatus, setMonetStatus] = useState<MonetStatus>('idle');
  const [monetError, setMonetError] = useState<string | undefined>();
  const [monetRefreshToken, setMonetRefreshToken] = useState(0);
  const hasCommittedThemeRef = useRef(false);
  const resolvedTheme = resolveTheme(mode, systemPrefersDark);
  const isMonetAvailableOnPlatform = isNativeAndroid();

  const setCustomSeed = useCallback((seed: string) => {
    setCustomSeedState(normalizeHexColor(seed));
  }, []);

  const resetColors = useCallback(() => {
    setColorSource('default');
    setCustomSeedState(DEFAULT_SEED);
  }, []);

  const refreshMonet = useCallback(() => {
    setMonetRefreshToken(token => token + 1);
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = () => setSystemPrefersDark(mediaQuery.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    const persisted: PersistedThemeState = { mode, colorSource, customSeed };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  }, [mode, colorSource, customSeed]);

  useLayoutEffect(() => {
    let canceled = false;

    const commitTheme = (applyColors: () => void) => {
      if (canceled) return;

      runThemeStyleTransition(() => {
        applyColors();
        syncBrowserChrome(resolvedTheme);
      }, hasCommittedThemeRef.current);
      hasCommittedThemeRef.current = true;
      syncNativeChrome(resolvedTheme).catch(console.error);
    };

    const applyTheme = async () => {
      if (colorSource === 'default') {
        setMonetStatus('idle');
        setMonetError(undefined);
        commitTheme(clearDynamicPalette);
        return;
      }

      if (colorSource === 'custom') {
        setMonetStatus('idle');
        setMonetError(undefined);
        commitTheme(() => applyPalette(paletteFromSeed(customSeed), resolvedTheme));
        return;
      }

      if (!isMonetAvailableOnPlatform) {
        setMonetStatus('unavailable');
        setMonetError('需 Android 客户端。');
        commitTheme(clearDynamicPalette);
        return;
      }

      setMonetStatus('loading');
      setMonetError(undefined);
      try {
        const monetPalette = await getMonetPalette();
        if (canceled || !monetPalette) return;
        commitTheme(() => applyPalette(paletteFromMonet(monetPalette), resolvedTheme));
        setMonetStatus('available');
      } catch (error) {
        if (canceled) return;
        const message = error instanceof Error ? error.message : String(error);
        setMonetStatus(isMonetUnavailableError(error) ? 'unavailable' : 'error');
        setMonetError(message);
        commitTheme(() => applyPalette(paletteFromSeed(DEFAULT_SEED), resolvedTheme));
      }
    };

    applyTheme();
    return () => {
      canceled = true;
    };
  }, [colorSource, customSeed, resolvedTheme, isMonetAvailableOnPlatform, monetRefreshToken]);

  useEffect(() => {
    if (!isMonetAvailableOnPlatform || colorSource !== 'monet') return;

    let listener: { remove: () => Promise<void> } | undefined;
    CapacitorApp.addListener('appStateChange', ({ isActive }) => {
      if (isActive) refreshMonet();
    }).then(handle => {
      listener = handle;
    });

    return () => {
      listener?.remove();
    };
  }, [colorSource, isMonetAvailableOnPlatform, refreshMonet]);

  const value = useMemo<ThemeContextValue>(() => ({
    mode,
    colorSource,
    customSeed,
    resolvedTheme,
    monetStatus,
    monetError,
    isMonetAvailableOnPlatform,
    setMode,
    setColorSource,
    setCustomSeed,
    resetColors,
    refreshMonet,
  }), [
    mode,
    colorSource,
    customSeed,
    resolvedTheme,
    monetStatus,
    monetError,
    isMonetAvailableOnPlatform,
    setCustomSeed,
    resetColors,
    refreshMonet,
  ]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export const useThemeContext = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useThemeContext must be used within ThemeProvider');
  }
  return context;
};
