/*
 * 模块描述：Capacitor 原生外壳初始化与系统状态栏同步。
 */

import { Animation, StatusBar, Style } from '@capacitor/status-bar';
import { isNative } from './platform';
import type { ResolvedTheme } from './palette';

export const syncNativeChrome = async (resolvedTheme?: ResolvedTheme) => {
  if (!isNative()) return;
  const isDark = resolvedTheme
    ? resolvedTheme === 'dark'
    : document.documentElement.classList.contains('dark');

  await StatusBar.setOverlaysWebView({ overlay: true }).catch(console.error);
  await StatusBar.setStyle({ style: isDark ? Style.Dark : Style.Light }).catch(console.error);
  await StatusBar.show({ animation: Animation.None }).catch(console.error);
};

export const setupNativeChrome = async () => {
  await syncNativeChrome();
};
