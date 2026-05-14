/*
 * 模块描述：会话侧栏组件，提供新建会话、历史切换、删除、存储状态和管理入口。
 */

import React from 'react';
import { X, Plus, Trash2, LogOut, ShieldAlert } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { Conversation } from '../types';
import { StorageIndicator } from './StorageIndicator';
import { BrandLockup } from './Brand';

const SIDEBAR_WIDTH = 320;
const PANEL_TRANSITION = { duration: 0.28, ease: [0.2, 0, 0, 1] } as const;

interface SidebarProps {
  isSidebarOpen: boolean;
  setIsSidebarOpen: (open: boolean) => void;
  conversations: Conversation[];
  currentId: string;
  setCurrentId: (id: string) => void;
  handleNewChat: () => void;
  deleteConversation: (id: string, e: React.MouseEvent) => void;
  userRole?: string;
  onAdminClick?: () => void;
  onLogout?: () => void;
  isDesktopLayout: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isSidebarOpen,
  setIsSidebarOpen,
  conversations,
  currentId,
  setCurrentId,
  handleNewChat,
  deleteConversation,
  userRole,
  onAdminClick,
  onLogout,
  isDesktopLayout
}) => {
  const panelAnimation = isDesktopLayout
    ? {
      width: isSidebarOpen ? SIDEBAR_WIDTH : 0,
      opacity: isSidebarOpen ? 1 : 0,
      borderRightWidth: isSidebarOpen ? 1 : 0
    }
    : {
      x: isSidebarOpen ? 0 : '-100%',
      opacity: isSidebarOpen ? 1 : 0
    };
  const sidebarContentWidth = isDesktopLayout ? `${SIDEBAR_WIDTH}px` : 'min(85vw, 320px)';
  const sidebarStyle: React.CSSProperties = {
    pointerEvents: isSidebarOpen ? 'auto' : 'none',
    ...(!isDesktopLayout ? { width: sidebarContentWidth } : {})
  };

  return (
    <>
      <AnimatePresence>
        {!isDesktopLayout && isSidebarOpen && (
          <motion.div
            key="sidebar-scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={PANEL_TRANSITION}
            className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm"
            onClick={() => setIsSidebarOpen(false)}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      <motion.aside
        initial={false}
        animate={panelAnimation}
        transition={PANEL_TRANSITION}
        className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-[var(--border-subtle)] bg-[var(--bg-app)] ${
          isDesktopLayout
            ? 'relative shadow-none'
            : 'fixed left-0 top-0 z-50 rounded-r-[var(--radius-xl)] shadow-[var(--shadow-4)]'
        }`}
        style={sidebarStyle}
        aria-hidden={!isSidebarOpen}
      >
        <div className="flex h-full shrink-0 flex-col" style={{ width: sidebarContentWidth }}>
          <div className="flex items-center justify-between p-6 pb-4">
            <BrandLockup />
            {!isDesktopLayout && (
              <button onClick={() => setIsSidebarOpen(false)} className="lawver-pressable inline-flex h-10 w-10 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]" aria-label="Close conversations">
                <X size={22} strokeWidth={2} />
              </button>
            )}
          </div>
          <div className="px-4 pb-4">
            <button
              onClick={() => handleNewChat()}
              className="md3-btn-filled lawver-pressable w-full whitespace-nowrap py-3.5"
            >
              <Plus size={20} strokeWidth={2} />
              New Chat
            </button>
          </div>
          <div className="custom-scrollbar flex min-w-0 flex-1 flex-col gap-1 overflow-y-auto px-3 pb-2">
            {conversations.map(conv => (
              <div
                key={conv.id}
                onClick={() => {
                  setCurrentId(conv.id);
                  if (!isDesktopLayout) setIsSidebarOpen(false);
                }}
                className={`lawver-pressable group flex w-full cursor-pointer items-center justify-between rounded-full px-4 py-3 text-left transition-colors ${
                  conv.id === currentId ? 'bg-[var(--accent-quiet)] font-medium text-[var(--brand-primary-700)] dark:text-[var(--accent)]' : 'text-[var(--fg-2)] hover:bg-[rgba(20,23,31,0.05)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'
                }`}
              >
                <span className="truncate pr-2 text-[14px]">{conv.title}</span>
                <button
                  onClick={(e) => deleteConversation(conv.id, e)}
                  className="lawver-pressable inline-flex h-8 w-8 items-center justify-center rounded-full text-[var(--fg-3)] opacity-100 transition-opacity hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)] lg:opacity-0 lg:group-hover:opacity-100"
                  title="Delete chat"
                  aria-label="Delete chat"
                >
                  <Trash2 size={16} strokeWidth={2} />
                </button>
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-3 border-t border-[var(--border-subtle)] p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            {userRole === 'admin' && onAdminClick && (
              <button
                onClick={onAdminClick}
                className="md3-btn-tonal lawver-pressable w-full rounded-[var(--radius-md)] py-2.5 text-sm"
              >
                <ShieldAlert size={16} strokeWidth={2} />
                管理后台
              </button>
            )}
            {onLogout && (
              <button
                onClick={onLogout}
                className="lawver-pressable flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] px-4 py-2.5 text-sm font-medium text-[var(--color-danger-500)] transition-colors hover:bg-[rgba(176,70,62,0.08)]"
              >
                <LogOut size={16} strokeWidth={2} />
                退出登录
              </button>
            )}
            <StorageIndicator />
          </div>
        </div>
      </motion.aside>
    </>
  );
};
