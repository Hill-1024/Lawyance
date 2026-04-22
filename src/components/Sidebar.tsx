import React from 'react';
import { X, Plus, Trash2, LogOut } from 'lucide-react';
import { Conversation } from '../types';
import { StorageIndicator } from './StorageIndicator';

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
  onLogout
}) => {
  return (
    <>
      {/* Sidebar Overlay */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/20 dark:bg-black/40 z-40 transition-opacity backdrop-blur-sm lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={`fixed lg:relative top-0 left-0 h-full w-[85vw] max-w-[320px] lg:max-w-none bg-gray-50 dark:bg-gray-900 shadow-2xl lg:shadow-none z-50 transform transition-all duration-300 ease-in-out ${isSidebarOpen ? 'translate-x-0 lg:w-80' : '-translate-x-full lg:translate-x-0 lg:w-0'} flex flex-col lg:rounded-none rounded-r-3xl border-r border-gray-200 dark:border-gray-800 shrink-0 overflow-hidden`}>
        <div className="p-6 pb-4 flex items-center justify-between min-w-62.5">
          <h2 className="font-medium text-xl text-gray-900 dark:text-gray-100 whitespace-nowrap">Conversations</h2>
          <button onClick={() => setIsSidebarOpen(false)} className="p-2 hover:bg-gray-200 dark:hover:bg-gray-800 rounded-full transition-colors text-gray-600 dark:text-gray-400 lg:hidden">
            <X size={24} />
          </button>
        </div>
        <div className="px-4 pb-4 min-w-62.5">
          <button
            onClick={() => handleNewChat()}
            className="w-full py-4 px-6 bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white rounded-full flex items-center justify-center gap-2 transition-all font-medium shadow-md hover:shadow-lg active:scale-[0.98] whitespace-nowrap"
          >
            <Plus size={20} />
            New Chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-3 pb-2 flex flex-col gap-1 custom-scrollbar min-w-62.5">
          {conversations.map(conv => (
            <div
              key={conv.id}
              onClick={() => {
                setCurrentId(conv.id);
                if (window.innerWidth < 1024) setIsSidebarOpen(false);
              }}
              className={`w-full text-left px-4 py-3.5 rounded-full transition-colors flex items-center justify-between group cursor-pointer ${
                conv.id === currentId ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium' : 'hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400'
              }`}
            >
              <span className="truncate pr-2 text-[15px]">{conv.title}</span>
              <button
                onClick={(e) => deleteConversation(conv.id, e)}
                className={`p-2 rounded-full lg:opacity-0 lg:group-hover:opacity-100 transition-opacity hover:bg-gray-300 dark:hover:bg-gray-700 ${conv.id === currentId ? 'hover:bg-blue-200 dark:hover:bg-blue-800' : ''}`}
                title="Delete chat"
              >
                <Trash2 size={18} className={conv.id === currentId ? 'text-blue-700 dark:text-blue-300' : 'text-gray-600 dark:text-gray-400'} />
              </button>
            </div>
          ))}
        </div>
        <div className="p-4 border-t border-gray-200 dark:border-gray-800 pb-[calc(1rem+env(safe-area-inset-bottom))] flex flex-col gap-3">
          {userRole === 'admin' && onAdminClick && (
            <button
              onClick={onAdminClick}
              className="w-full py-2.5 px-4 bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-900/30 dark:hover:bg-indigo-800/50 text-indigo-700 dark:text-indigo-300 rounded-xl text-sm font-medium transition-colors shadow-sm flex items-center justify-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              管理后台
            </button>
          )}
          {onLogout && (
            <button
              onClick={onLogout}
              className="w-full py-2.5 px-4 hover:bg-red-50 dark:hover:bg-red-900/20 text-red-600 dark:text-red-400 rounded-xl text-sm font-medium transition-colors flex items-center justify-center gap-2"
            >
              <LogOut size={16} />
              退出登录
            </button>
          )}
          <StorageIndicator />
        </div>
      </div>
    </>
  );
};
