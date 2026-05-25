/*
 * 模块描述：Capacitor 原生外壳初始化与系统状态栏同步。
 */

import { StatusBar, Style } from '@capacitor/status-bar';
import { isNative } from './platform';
import type { ResolvedTheme } from './palette';

const readBgApp = () => (
  getComputedStyle(document.documentElement).getPropertyValue('--bg-app').trim() || '#f6f8fb'
);

export const syncNativeChrome = async (resolvedTheme?: ResolvedTheme) => {
  if (!isNative()) return;
  const isDark = resolvedTheme
    ? resolvedTheme === 'dark'
    : document.documentElement.classList.contains('dark');

  await StatusBar.setOverlaysWebView({ overlay: false }).catch(console.error);
  // Capacitor 命名反直觉：Light = 白字深底，Dark = 黑字浅底。
  await StatusBar.setStyle({ style: isDark ? Style.Light : Style.Dark }).catch(console.error);
  await StatusBar.setBackgroundColor({ color: readBgApp() }).catch(console.error);
};

export const setupNativeChrome = async () => {
  await syncNativeChrome();
};
