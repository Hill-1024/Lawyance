/*
 * 模块描述：聊天页顶部栏组件，提供侧栏、工作区、标题和主题切换入口。
 */

import React from 'react';
import { Menu, Sun, Monitor, Moon, Folder } from 'lucide-react';
import { motion } from 'motion/react';
import { BrandMark } from './Brand';

interface HeaderProps {
  title: string;
  isSidebarOpen: boolean;
  setIsSidebarOpen: (open: boolean) => void;
  isWorkspaceOpen: boolean;
  setIsWorkspaceOpen: (open: boolean) => void;
  workspaceFilesCount: number;
  themeMode: 'light' | 'system' | 'dark';
  setThemeMode: (mode: 'light' | 'system' | 'dark') => void;
  windowWidth: number;
}

export const Header: React.FC<HeaderProps> = ({
  title,
  isSidebarOpen,
  setIsSidebarOpen,
  isWorkspaceOpen,
  setIsWorkspaceOpen,
  workspaceFilesCount,
  themeMode,
  setThemeMode,
  windowWidth
}) => {
  return (
    <header className="lawver-topbar sticky top-0 z-30 flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-app)] px-2.5 pb-2 pt-[calc(0.625rem+env(safe-area-inset-top))] text-[var(--fg-1)] sm:px-4 sm:pb-3 sm:pt-[calc(0.75rem+env(safe-area-inset-top))]">
      <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2">
        <button
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          className="lawver-pressable inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06] sm:h-11 sm:w-11"
          aria-label="Toggle conversations"
        >
          <Menu size={22} strokeWidth={2} />
        </button>
        <BrandMark className="hidden h-8 w-8 shrink-0 text-[var(--accent)] sm:block" />
        <h1 className="lawver-header-title t-title-l min-w-0 flex-1 truncate">
          {title || 'Lawver'}
        </h1>
      </div>
      <div className="relative flex shrink-0 items-center gap-0.5 sm:gap-1">
        <button
          onClick={() => setIsWorkspaceOpen(!isWorkspaceOpen)}
          className={`lawver-pressable inline-flex h-10 w-10 items-center justify-center rounded-full transition-colors sm:h-11 sm:w-11 ${isWorkspaceOpen ? 'bg-[var(--accent-quiet)] text-[var(--accent)]' : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'}`}
          title="Workspace"
          aria-label="Toggle workspace"
        >
          <div className="relative">
            <Folder size={20} strokeWidth={2} />
            {workspaceFilesCount > 0 && (
              <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-[var(--bg-app)] bg-[var(--accent)]" />
            )}
          </div>
        </button>
        <div className="relative flex items-center rounded-full bg-[rgba(20,23,31,0.06)] p-1 dark:bg-white/[0.06] sm:ml-1">
          <motion.div
            className="absolute bottom-1 top-1 w-[30px] rounded-full bg-[var(--bg-surface)] shadow-[var(--shadow-1)] sm:w-9"
            initial={false}
            animate={{
              x: themeMode === 'light' ? 0 : themeMode === 'system' ? (windowWidth < 640 ? 30 : 36) : (windowWidth < 640 ? 60 : 72)
            }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
          />
          <button
            onClick={() => setThemeMode('light')}
            className={`lawver-pressable relative z-10 flex h-8 w-[30px] items-center justify-center rounded-full transition-colors sm:h-9 sm:w-9 ${themeMode === 'light' ? 'text-[var(--fg-1)]' : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'}`}
            title="Light Mode"
          >
            <Sun size={16} strokeWidth={2} />
          </button>
          <button
            onClick={() => setThemeMode('system')}
            className={`lawver-pressable relative z-10 flex h-8 w-[30px] items-center justify-center rounded-full transition-colors sm:h-9 sm:w-9 ${themeMode === 'system' ? 'text-[var(--fg-1)]' : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'}`}
            title="System Mode"
          >
            <Monitor size={16} strokeWidth={2} />
          </button>
          <button
            onClick={() => setThemeMode('dark')}
            className={`lawver-pressable relative z-10 flex h-8 w-[30px] items-center justify-center rounded-full transition-colors sm:h-9 sm:w-9 ${themeMode === 'dark' ? 'text-[var(--fg-1)]' : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'}`}
            title="Dark Mode"
          >
            <Moon size={16} strokeWidth={2} />
          </button>
        </div>
      </div>
    </header>
  );
};
