/*
 * 模块描述：聊天输入区组件，处理消息输入、文件上传、发送按钮和悬浮设置面板。
 */

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Settings2, Paperclip, X, Send, LoaderCircle } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { AnimatedSwitch } from './AnimatedSwitch';
import { HoverInfo } from './HoverInfo';
import type { ContextUsage } from '../types';

const DEFAULT_CONTEXT_THRESHOLD_TOKENS = 500000;

const formatTokenCount = (tokens: number) => {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(tokens >= 10000000 ? 0 : 1)}M`;
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`;
  return `${tokens}`;
};

const ContextUsageInfo: React.FC<{ usage?: ContextUsage | null }> = ({ usage }) => {
  if (!usage) {
    return <span className="text-[var(--fg-2)]">上下文用量未知</span>;
  }
  const rows: Array<{ label: string; value: string }> = [
    { label: '当前用量', value: formatTokenCount(usage.prompt_tokens) },
    { label: '压缩阈值', value: formatTokenCount(usage.threshold_tokens) },
    { label: '最大上下文', value: formatTokenCount(usage.max_context_tokens) }
  ];
  if (usage.cached_tokens) {
    rows.push({ label: '缓存命中', value: formatTokenCount(usage.cached_tokens) });
  }
  return (
    <div className="flex min-w-[160px] flex-col gap-1.5">
      <div className="font-semibold text-[var(--fg-1)]">上下文用量</div>
      <div className="flex flex-col gap-1">
        {rows.map(row => (
          <div key={row.label} className="flex items-center justify-between gap-4">
            <span className="text-[var(--fg-3)]">{row.label}</span>
            <span className="tabular-nums text-[var(--fg-1)]">{row.value}</span>
          </div>
        ))}
      </div>
      {usage.over_threshold && (
        <div className="text-[var(--color-warning-500)]">已超过压缩阈值，下一轮将触发压缩</div>
      )}
    </div>
  );
};

const ContextUsageMeter: React.FC<{ usage?: ContextUsage | null }> = ({ usage }) => {
  const threshold = usage?.threshold_tokens || DEFAULT_CONTEXT_THRESHOLD_TOKENS;
  const promptTokens = usage?.prompt_tokens || 0;
  const progress = usage ? Math.min(Math.max(promptTokens / threshold, 0), 1) : 0;
  const overThreshold = Boolean(usage?.over_threshold || promptTokens > threshold);
  const degrees = Math.round(progress * 360);
  const meterColor = overThreshold ? 'var(--color-warning-500)' : 'var(--accent)';
  const trackColor = 'rgba(20,23,31,0.12)';
  const ariaLabel = usage
    ? `上下文 ${formatTokenCount(promptTokens)} / ${formatTokenCount(threshold)}`
    : '上下文用量未知';

  return (
    <HoverInfo label={<ContextUsageInfo usage={usage} />} placement="top">
      <div
        className={`lawyance-composer-action lawyance-pressable relative text-[var(--fg-3)] ${overThreshold ? 'bg-[rgba(214,137,16,0.12)]' : ''}`}
        role="meter"
        aria-label={ariaLabel}
        aria-valuemin={0}
        aria-valuemax={threshold}
        aria-valuenow={promptTokens}
      >
        <span
          className="block h-[18px] w-[18px] rounded-full"
          style={{
            background: `conic-gradient(${meterColor} ${degrees}deg, ${trackColor} ${degrees}deg 360deg)`
          }}
        >
          <span className="m-[4px] block h-[10px] w-[10px] rounded-full bg-[var(--bg-surface)] shadow-[inset_0_0_0_1px_var(--border-default)]" />
        </span>
      </div>
    </HoverInfo>
  );
};

interface InputAreaProps {
  input: string;
  setInput: (val: string) => void;
  handleSend: () => void;
  isLoading: boolean;
  composerStatus?: string | null;
  contextUsage?: ContextUsage | null;
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
  composerStatus,
  contextUsage,
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
    const viewport = window.visualViewport;
    const viewportWidth = viewport?.width ?? window.innerWidth;
    const viewportHeight = viewport?.height ?? window.innerHeight;
    const viewportOffsetTop = viewport?.offsetTop ?? 0;
    const horizontalInset = 8;
    const width = Math.min(rect.width, viewportWidth - horizontalInset * 2);
    const left = Math.max(horizontalInset, Math.min(rect.left, viewportWidth - width - horizontalInset));

    setSettingsPosition({
      left,
      width,
      bottom: Math.max(12, viewportHeight + viewportOffsetTop - rect.top + 12)
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
              bottom: settingsPosition.bottom,
              maxHeight: `calc(100dvh - ${settingsPosition.bottom}px - env(safe-area-inset-top) - 12px)`,
              overflowY: 'auto'
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
      <footer className="lawyance-composer-footer pointer-events-none shrink-0 px-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-1 sm:px-4 sm:pb-4 sm:pt-2">
        <div ref={composerRef} className="pointer-events-auto relative mx-auto flex w-full max-w-3xl min-w-0 flex-col">
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

          <AnimatePresence>
            {composerStatus && (
              <motion.div
                key="composer-status"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 6 }}
                transition={{ duration: 0.2, ease: [0.2, 0, 0, 1] }}
                role="status"
                aria-live="polite"
                data-testid="composer-status"
                className="mx-2 mb-1 flex h-8 max-w-full min-w-0 items-center gap-2 rounded-full border border-[var(--border-default)] bg-[var(--bg-inset)] px-3 text-xs font-medium leading-none text-[var(--fg-2)] shadow-[var(--shadow-1)]"
              >
                <LoaderCircle size={14} strokeWidth={2} className="shrink-0 animate-spin text-[var(--accent)]" />
                <span className="min-w-0 truncate">{composerStatus}</span>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="lawyance-composer-shell">
            <button
              onClick={() => setIsInputExpanded(!isInputExpanded)}
              className={`lawyance-composer-action lawyance-pressable transition-colors ${isInputExpanded ? 'bg-[var(--accent-quiet)] text-[var(--accent)]' : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'}`}
              aria-label="Open composer settings"
              aria-expanded={isInputExpanded}
            >
              <Settings2 size={20} strokeWidth={2} />
            </button>

            <HoverInfo label="Upload file (Max 50MB)" placement="top">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading}
                className="lawyance-composer-action lawyance-pressable text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] disabled:opacity-50 dark:hover:bg-white/[0.06]"
                aria-label="Upload file (Max 50MB)"
              >
                <Paperclip size={20} strokeWidth={2} />
              </button>
            </HoverInfo>
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

            <ContextUsageMeter usage={contextUsage} />

            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message Lawyance..."
              className="composer-textarea lawyance-composer-textarea max-h-32 min-w-0 flex-1 resize-none border-0 bg-transparent text-[var(--fg-1)] outline-none placeholder:text-[var(--fg-4)] focus:border-0 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0"
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
