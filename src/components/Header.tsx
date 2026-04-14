import React from 'react';
import { Menu, Sun, Monitor, Moon, Folder } from 'lucide-react';
import { motion } from 'motion/react';

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
    <header className="flex items-center justify-between px-4 pt-[calc(0.75rem+env(safe-area-inset-top))] pb-3 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 shrink-0 z-10 sticky top-0 border-b border-gray-200 dark:border-gray-800">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          className="p-3 hover:bg-gray-200 dark:hover:bg-gray-800 rounded-full transition-colors text-gray-600 dark:text-gray-400"
        >
          <Menu size={24} />
        </button>
        <h1 className="text-lg sm:text-[22px] font-medium tracking-tight ml-1 truncate max-w-[160px] sm:max-w-none">
          {title || 'Lawver'}
        </h1>
      </div>
      <div className="flex items-center gap-1 relative">
        <button
          onClick={() => setIsWorkspaceOpen(!isWorkspaceOpen)}
          className={`p-2 sm:p-2.5 rounded-full transition-colors ${isWorkspaceOpen ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/50 dark:text-blue-400' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-800'}`}
          title="Workspace"
        >
          <div className="relative">
            <Folder size={20} className="sm:size-5.5" />
            {workspaceFilesCount > 0 && (
              <span className="absolute -top-1 -right-1 w-3 h-3 bg-blue-500 rounded-full border-2 border-gray-50 dark:border-gray-900" />
            )}
          </div>
        </button>
        <div className="flex items-center bg-gray-200 dark:bg-gray-800 rounded-full p-1 relative ml-1">
          <motion.div
            className="absolute top-1 bottom-1 w-8 sm:w-9 bg-white dark:bg-gray-600 rounded-full shadow-sm"
            initial={false}
            animate={{
              x: themeMode === 'light' ? 0 : themeMode === 'system' ? (windowWidth < 640 ? 32 : 36) : (windowWidth < 640 ? 64 : 72)
            }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
          />
          <button
            onClick={() => setThemeMode('light')}
            className={`relative z-10 w-8 h-8 sm:w-9 sm:h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'light' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
            title="Light Mode"
          >
            <Sun size={16} className="sm:size-4.5" />
          </button>
          <button
            onClick={() => setThemeMode('system')}
            className={`relative z-10 w-8 h-8 sm:w-9 sm:h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'system' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
            title="System Mode"
          >
            <Monitor size={16} className="sm:size-4.5" />
          </button>
          <button
            onClick={() => setThemeMode('dark')}
            className={`relative z-10 w-8 h-8 sm:w-9 sm:h-9 flex items-center justify-center rounded-full transition-colors ${themeMode === 'dark' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}
            title="Dark Mode"
          >
            <Moon size={16} className="sm:size-4.5" />
          </button>
        </div>
      </div>
    </header>
  );
};
