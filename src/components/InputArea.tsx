/*
 * 模块描述：聊天输入区组件，处理消息输入、文件上传、发送按钮和悬浮设置面板。
 */

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Settings2, Paperclip, X, Send } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { AnimatedSwitch } from './AnimatedSwitch';

interface InputAreaProps {
  input: string;
  setInput: (val: string) => void;
  handleSend: () => void;
  isLoading: boolean;
  pendingUploads: { name: string, path: string }[];
  removeUploadedFile: (index: number) => void;
  handleFileUpload: (file: File) => void;
  isInputExpanded: boolean;
  setIsInputExpanded: (val: boolean) => void;
  isStreaming: boolean;
  setIsStreaming: (val: boolean) => void;
  agentMode: string;
  setAgentMode: (val: string) => void;
  isOCPEnabled: boolean;
  setIsOCPEnabled: (val: boolean) => void;
  onSettingsClearanceChange?: (height: number) => void;
}

export const InputArea: React.FC<InputAreaProps> = ({
  input,
  setInput,
  handleSend,
  isLoading,
  pendingUploads,
  removeUploadedFile,
  handleFileUpload,
  isInputExpanded,
  setIsInputExpanded,
  isStreaming,
  setIsStreaming,
  agentMode,
  setAgentMode,
  isOCPEnabled,
  setIsOCPEnabled,
  onSettingsClearanceChange
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const settingsPanelRef = useRef<HTMLDivElement>(null);
  const [settingsPosition, setSettingsPosition] = useState({ left: 0, width: 0, bottom: 0 });

  const updateSettingsPosition = useCallback(() => {
    const rect = composerRef.current?.getBoundingClientRect();
    if (!rect) return;

    setSettingsPosition({
      left: rect.left,
      width: rect.width,
      bottom: window.innerHeight - rect.top + 12
    });
  }, []);

  const updateSettingsClearance = useCallback(() => {
    if (!isInputExpanded) {
      onSettingsClearanceChange?.(0);
      return;
    }

    const panelHeight = settingsPanelRef.current?.getBoundingClientRect().height ?? 0;
    onSettingsClearanceChange?.((panelHeight || 168) + 20);
  }, [isInputExpanded, onSettingsClearanceChange]);

  useLayoutEffect(() => {
    if (isInputExpanded) {
      updateSettingsPosition();
      updateSettingsClearance();
    } else {
      onSettingsClearanceChange?.(0);
    }
  }, [isInputExpanded, pendingUploads.length, onSettingsClearanceChange, updateSettingsClearance, updateSettingsPosition]);

  useLayoutEffect(() => {
    updateSettingsClearance();
  }, [settingsPosition.width, updateSettingsClearance]);

  useEffect(() => {
    if (!isInputExpanded) return;

    updateSettingsPosition();
    updateSettingsClearance();
    const handleViewportChange = () => {
      updateSettingsPosition();
      updateSettingsClearance();
    };
    const composerResizeObserver = typeof ResizeObserver !== 'undefined' && composerRef.current
      ? new ResizeObserver(handleViewportChange)
      : null;
    const settingsResizeObserver = typeof ResizeObserver !== 'undefined' && settingsPanelRef.current
      ? new ResizeObserver(updateSettingsClearance)
      : null;

    window.addEventListener('resize', handleViewportChange);
    window.visualViewport?.addEventListener('resize', handleViewportChange);
    window.visualViewport?.addEventListener('scroll', handleViewportChange);
    composerResizeObserver?.observe(composerRef.current as Element);
    settingsResizeObserver?.observe(settingsPanelRef.current as Element);

    return () => {
      window.removeEventListener('resize', handleViewportChange);
      window.visualViewport?.removeEventListener('resize', handleViewportChange);
      window.visualViewport?.removeEventListener('scroll', handleViewportChange);
      composerResizeObserver?.disconnect();
      settingsResizeObserver?.disconnect();
    };
  }, [isInputExpanded, updateSettingsClearance, updateSettingsPosition]);

  const onSendWrapper = () => {
    handleSend();
    if (isInputExpanded) {
      setIsInputExpanded(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isMac = /Mac|iPhone|iPod|iPad/i.test(navigator.userAgent);
    const isSendTriggered = isMac ? (e.metaKey && e.key === 'Enter') : (e.ctrlKey && e.key === 'Enter');

    if (isSendTriggered) {
      e.preventDefault();
      onSendWrapper();
    }
  };

  const settingsLayer = typeof document !== 'undefined'
    ? createPortal(
      <AnimatePresence>
        {isInputExpanded && settingsPosition.width > 0 && (
          <motion.div
            ref={settingsPanelRef}
            key="composer-settings"
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98 }}
            transition={{ duration: 0.24, ease: [0.2, 0, 0, 1] }}
            style={{
              left: settingsPosition.left,
              width: settingsPosition.width,
              bottom: settingsPosition.bottom
            }}
            className="glass lawyance-popover z-[80] flex flex-col gap-0 rounded-[var(--radius-xl)] p-0 shadow-[var(--shadow-5)]"
          >
            <div className="pointer-events-none absolute -bottom-1.5 left-6 h-3 w-3 rotate-45 border-b border-r border-[var(--glass-border)] bg-[var(--glass-bg)] backdrop-blur-xl" />
            <div className="relative z-[1] flex min-h-12 items-center justify-between gap-4 px-4 py-2.5">
              <div className="flex min-w-0 items-center gap-3">
                <Settings2 size={18} strokeWidth={2} className="shrink-0 text-[var(--fg-3)]" />
                <span className="truncate text-sm font-medium text-[var(--fg-1)] sm:text-[15px]">Enable Streaming Output</span>
              </div>
              <AnimatedSwitch
                checked={isStreaming}
                onCheckedChange={setIsStreaming}
                ariaLabel="切换流式输出"
              />
            </div>

            <div className="relative z-[1] flex min-h-12 items-center justify-between gap-4 px-4 py-2.5">
              <div className="flex min-w-0 items-center gap-3">
                <Settings2 size={18} strokeWidth={2} className="shrink-0 text-[var(--fg-3)]" />
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-medium text-[var(--fg-1)] sm:text-[15px]">Output Check Process (OCP)</span>
                  <span className="shrink-0 rounded bg-[rgba(20,23,31,0.08)] px-1.5 py-0.5 text-[10px] font-semibold uppercase text-[var(--fg-3)]">Beta</span>
                </div>
              </div>
              <AnimatedSwitch
                checked={isOCPEnabled}
                onCheckedChange={setIsOCPEnabled}
                ariaLabel="切换 OCP"
              />
            </div>
            <div className="relative z-[1] mx-4 h-px bg-[var(--border-default)]" />
            <div className="relative z-[1] flex min-h-12 items-center justify-between gap-4 px-4 py-2.5">
              <div className="flex min-w-0 items-center gap-3">
                <Settings2 size={18} strokeWidth={2} className="shrink-0 text-[var(--fg-3)]" />
                <span className="truncate text-sm font-medium text-[var(--fg-1)] sm:text-[15px]">Agent Mode</span>
              </div>
              <select
                value={agentMode}
                onChange={(e) => setAgentMode(e.target.value)}
                className="lawyance-pressable h-9 w-32 shrink-0 cursor-pointer rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[rgba(255,255,255,0.5)] px-3 text-sm font-medium text-[var(--fg-1)] outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] dark:bg-white/[0.05]"
              >
                <option value="default">Default</option>
                <option value="plan_and_solve">Plan & Solve</option>
                <option value="react">ReAct</option>
              </select>
            </div>
          </motion.div>
        )}
      </AnimatePresence>,
      document.body
    )
    : null;

  return (
    <>
      {settingsLayer}
      <footer className="pointer-events-none shrink-0 bg-transparent px-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-0 sm:px-4 sm:pb-4">
      <div ref={composerRef} className="pointer-events-auto relative mx-auto flex max-w-3xl flex-col">
        {pendingUploads.length > 0 && (
          <div className="flex flex-wrap gap-2 px-2 pb-1">
            {pendingUploads.map((file, index) => (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                key={index}
                className="flex items-center gap-2 rounded-full border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-1 text-[var(--fg-2)] shadow-[var(--shadow-1)] sm:px-4 sm:py-1.5"
              >
                <Paperclip size={12} strokeWidth={2} className="text-[var(--accent)] sm:size-3.5" />
                <span className="max-w-[120px] truncate text-xs sm:max-w-[200px] sm:text-sm">{file.name}</span>
                <button
                  onClick={() => removeUploadedFile(index)}
                  className="rounded-full p-1 text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)]"
                  aria-label="Remove upload"
                >
                  <X size={12} strokeWidth={2} className="sm:size-3.5" />
                </button>
              </motion.div>
            ))}
          </div>
        )}

        <div className="lawyance-composer-shell">
          <button
            onClick={() => setIsInputExpanded(!isInputExpanded)}
            className={`lawyance-composer-action lawyance-pressable transition-colors ${isInputExpanded ? 'bg-[var(--accent-quiet)] text-[var(--accent)]' : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'}`}
            aria-label="Open composer settings"
            aria-expanded={isInputExpanded}
          >
            <Settings2 size={20} strokeWidth={2} />
          </button>
          
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            className="lawyance-composer-action lawyance-pressable text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] disabled:opacity-50 dark:hover:bg-white/[0.06]"
            title="Upload file (Max 50MB)"
          >
            <Paperclip size={20} strokeWidth={2} />
          </button>
          <input
            type="file"
            ref={fileInputRef}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileUpload(file);
              if (fileInputRef.current) fileInputRef.current.value = '';
            }}
            className="hidden"
            accept=".pdf,.doc,.docx,.txt,.md"
          />

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Lawyance... (Ctrl+Enter to send)"
            className="composer-textarea lawyance-composer-textarea max-h-32 flex-1 resize-none border-0 bg-transparent text-[var(--fg-1)] outline-none placeholder:text-[var(--fg-4)] focus:border-0 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0"
            rows={1}
          />
          <button
            onClick={onSendWrapper}
            disabled={isLoading || (!input.trim() && pendingUploads.length === 0)}
            className={`lawyance-composer-action lawyance-pressable shadow-[var(--shadow-1)] transition-colors ${
              input.trim() || pendingUploads.length > 0
                ? 'bg-[var(--accent)] text-[var(--accent-on)] hover:bg-[var(--accent-hover)]'
                : 'cursor-not-allowed bg-[rgba(20,23,31,0.08)] text-[var(--fg-4)] shadow-none dark:bg-white/[0.08]'
            }`}
            aria-label="Send message"
          >
            <Send size={20} strokeWidth={2} />
          </button>
        </div>
      </div>
      </footer>
    </>
  );
};
