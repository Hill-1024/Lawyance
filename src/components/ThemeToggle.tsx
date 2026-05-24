/*
 * 模块描述：主题切换分段控件，在聊天页与模拟法庭页之间共享同一交互。
 */

import React from 'react';
import { Sun, Monitor, Moon } from 'lucide-react';
import { motion } from 'motion/react';
import { HoverInfo } from './HoverInfo';

interface ThemeToggleProps {
  themeMode: 'light' | 'system' | 'dark';
  setThemeMode: (mode: 'light' | 'system' | 'dark') => void;
  windowWidth: number;
}

export const ThemeToggle: React.FC<ThemeToggleProps> = ({ themeMode, setThemeMode, windowWidth }) => {
  const sliderOffset = themeMode === 'light'
    ? 0
    : themeMode === 'system'
      ? (windowWidth < 640 ? 30 : 36)
      : (windowWidth < 640 ? 60 : 72);

  return (
    <div className="relative flex items-center rounded-full bg-[rgba(20,23,31,0.06)] p-1 dark:bg-white/[0.06] sm:ml-1">
      <motion.div
        className="absolute bottom-1 top-1 w-[30px] rounded-full bg-[var(--bg-surface)] shadow-[var(--shadow-1)] sm:w-9"
        initial={false}
        animate={{ x: sliderOffset }}
        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      />
      <HoverInfo label="Light Mode" placement="bottom">
        <button
          onClick={() => setThemeMode('light')}
          className={`lawver-pressable relative z-10 flex h-8 w-[30px] items-center justify-center rounded-full transition-colors sm:h-9 sm:w-9 ${themeMode === 'light' ? 'text-[var(--fg-1)]' : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'}`}
          aria-label="Light Mode"
        >
          <Sun size={16} strokeWidth={2} />
        </button>
      </HoverInfo>
      <HoverInfo label="System Mode" placement="bottom">
        <button
          onClick={() => setThemeMode('system')}
          className={`lawver-pressable relative z-10 flex h-8 w-[30px] items-center justify-center rounded-full transition-colors sm:h-9 sm:w-9 ${themeMode === 'system' ? 'text-[var(--fg-1)]' : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'}`}
          aria-label="System Mode"
        >
          <Monitor size={16} strokeWidth={2} />
        </button>
      </HoverInfo>
      <HoverInfo label="Dark Mode" placement="bottom">
        <button
          onClick={() => setThemeMode('dark')}
          className={`lawver-pressable relative z-10 flex h-8 w-[30px] items-center justify-center rounded-full transition-colors sm:h-9 sm:w-9 ${themeMode === 'dark' ? 'text-[var(--fg-1)]' : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'}`}
          aria-label="Dark Mode"
        >
          <Moon size={16} strokeWidth={2} />
        </button>
      </HoverInfo>
    </div>
  );
};
