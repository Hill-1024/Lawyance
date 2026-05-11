/*
 * 模块描述：主题状态 Hook，管理亮色、暗色和跟随系统主题。
 */

import { useState, useEffect } from 'react';

export function useTheme() {
  const [themeMode, setThemeMode] = useState<'light' | 'system' | 'dark'>('system');

  useEffect(() => {
    const savedTheme = localStorage.getItem('themeMode') as 'light' | 'system' | 'dark';
    if (savedTheme) {
      setThemeMode(savedTheme);
    }
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    
    const handleChange = () => {
      if (themeMode === 'system') {
        if (mediaQuery.matches) {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      }
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [themeMode]);

  useEffect(() => {
    localStorage.setItem('themeMode', themeMode);
    if (themeMode === 'dark' || (themeMode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [themeMode]);

  return { themeMode, setThemeMode };
}
