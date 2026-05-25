/*
 * 模块描述：聊天页顶部栏组件，提供侧栏、工作区、标题和主题切换入口。
 */

import React from 'react';
import { Menu, Folder } from 'lucide-react';
import { BrandMark } from './Brand';
import { HoverInfo } from './HoverInfo';
import { ThemeToggle } from './ThemeToggle';

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
          className="lawver-pressable inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06] sm:h-11 sm:w-11"
          aria-label="Toggle conversations"
        >
          <Menu size={20} strokeWidth={2} className="sm:size-[22px]" />
        </button>
        <BrandMark className="hidden h-8 w-8 shrink-0 text-[var(--accent)] sm:block" />
        <h1 className="lawver-header-title t-title-l min-w-0 flex-1 truncate">
          {title || 'Lawver'}
        </h1>
      </div>
      <div className="relative flex shrink-0 items-center gap-0.5 sm:gap-1">
        <HoverInfo label="Workspace" placement="bottom">
          <button
            onClick={() => setIsWorkspaceOpen(!isWorkspaceOpen)}
            className={`lawver-pressable inline-flex h-9 w-9 items-center justify-center rounded-full transition-colors sm:h-11 sm:w-11 ${isWorkspaceOpen ? 'bg-[var(--accent-quiet)] text-[var(--accent)]' : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'}`}
            aria-label="Toggle workspace"
          >
            <div className="relative">
              <Folder size={18} strokeWidth={2} className="sm:size-5" />
              {workspaceFilesCount > 0 && (
                <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-[var(--bg-app)] bg-[var(--accent)]" />
              )}
            </div>
          </button>
        </HoverInfo>
        <ThemeToggle themeMode={themeMode} setThemeMode={setThemeMode} windowWidth={windowWidth} />
      </div>
    </header>
  );
};
