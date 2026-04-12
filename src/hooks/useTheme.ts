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
    localStorage.setItem('themeMode', themeMode);
    if (themeMode === 'dark' || (themeMode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [themeMode]);

  return { themeMode, setThemeMode };
}
