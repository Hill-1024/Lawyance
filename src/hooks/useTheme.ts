/*
 * 模块描述：主题上下文兼容入口，保留旧 useTheme 命名供迁移期使用。
 */

import { useThemeContext } from '../contexts/ThemeContext';

export function useTheme() {
  const theme = useThemeContext();
  return {
    ...theme,
    themeMode: theme.mode,
    setThemeMode: theme.setMode,
  };
}
