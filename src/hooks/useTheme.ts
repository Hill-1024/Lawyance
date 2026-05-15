/*
 * 模块描述：主题状态 Hook，管理亮色、暗色和跟随系统主题。
 */

import { useState, useEffect } from 'react';

type ThemeMode = 'light' | 'system' | 'dark';
type ResolvedTheme = Exclude<ThemeMode, 'system'>;

const THEME_COLOR: Record<ResolvedTheme, string> = {
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

const isThemeMode = (value: string | null): value is ThemeMode => (
  value === 'light' || value === 'system' || value === 'dark'
);

const resolveTheme = (themeMode: ThemeMode, systemPrefersDark: boolean): ResolvedTheme => {
  if (themeMode === 'system') {
    return systemPrefersDark ? 'dark' : 'light';
  }
  return themeMode;
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

const syncBrowserTheme = (resolvedTheme: ResolvedTheme) => {
  document.documentElement.classList.toggle('dark', resolvedTheme === 'dark');
  document.documentElement.dataset.theme = resolvedTheme;

  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (themeColor) {
    themeColor.content = THEME_COLOR[resolvedTheme];
  }

  const favicon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
  if (favicon) {
    favicon.type = 'image/svg+xml';
    favicon.href = createFaviconHref(resolvedTheme);
  }
};

export function useTheme() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') {
      return 'system';
    }
    const savedTheme = localStorage.getItem('themeMode');
    return isThemeMode(savedTheme) ? savedTheme : 'system';
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const applyTheme = () => {
      syncBrowserTheme(resolveTheme(themeMode, mediaQuery.matches));
    };

    localStorage.setItem('themeMode', themeMode);
    applyTheme();

    mediaQuery.addEventListener('change', applyTheme);
    return () => mediaQuery.removeEventListener('change', applyTheme);
  }, [themeMode]);

  return { themeMode, setThemeMode };
}
