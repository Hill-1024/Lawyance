/*
 * 模块描述：聊天输入区组件，处理消息输入、文件上传、发送按钮和悬浮设置面板。
 */

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Settings2, Paperclip, ImagePlus, X, Send, LoaderCircle, Square } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { AnimatedSwitch } from './AnimatedSwitch';
import { HoverInfo } from './HoverInfo';
import { UserChoicePrompt } from './UserChoicePrompt';
import { useAutoGrowTextarea } from '../hooks/useAutoGrowTextarea';
import { computeComposerViewportBudget, planComposerActionBar } from '../lib/composer-autosize';
import type { ContextUsage, PendingUpload, UserChoiceRequest } from '../types';

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
        className={`lawver-composer-action lawver-pressable relative text-[var(--fg-3)] ${overThreshold ? 'bg-[rgba(214,137,16,0.12)]' : ''}`}
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
  handleStop?: () => void;
  activeChoicePrompt?: { messageId: string; choice: UserChoiceRequest } | null;
  onAnswerChoice?: (messageId: string, value: string) => void;
  isLoading: boolean;
  composerStatus?: string | null;
  contextUsage?: ContextUsage | null;
  pendingUploads: PendingUpload[];
  isUploadingFiles?: boolean;
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
  /** 输入区实际高度上报，供消息列表在输入框增高时保持贴底。 */
  onComposerHeightChange?: (height: number) => void;
}

export const InputArea: React.FC<InputAreaProps> = ({
  input,
  setInput,
  handleSend,
  handleStop,
  activeChoicePrompt,
  onAnswerChoice,
  isLoading,
  composerStatus,
  contextUsage,
  pendingUploads,
  isUploadingFiles = false,
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
  onSettingsClearanceChange,
  onComposerHeightChange
}) => {
  const [stackReferenceWidth, setStackReferenceWidth] = useState<number | null>(null);
  const [visibleActionCount, setVisibleActionCount] = useState(0);
  const { ref: textareaRef, isMultiline, isStacked } = useAutoGrowTextarea(input, {
    stackReferenceWidth
  });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const settingsPanelRef = useRef<HTMLDivElement>(null);
  const choicePromptRef = useRef<HTMLDivElement>(null);
  const [settingsPosition, setSettingsPosition] = useState({ left: 0, width: 0, bottom: 0, maxHeight: 0 });
  const hasActiveChoicePrompt = Boolean(activeChoicePrompt);
  const hasComposerOverlay = isInputExpanded || hasActiveChoicePrompt;

  // 始终按横排可用宽度判定，包括侧栏开合和窗口横向缩放。
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    const shell = textarea?.parentElement;
    const actions = shell?.querySelector<HTMLElement>('.lawver-composer-actions');
    if (!textarea || !shell || !actions) return;
    const report = () => {
      const visibleItems = Array.from(actions.children as HTMLCollectionOf<Element>).filter(child => getComputedStyle(child).display !== 'none');
      setVisibleActionCount(previous => (previous === visibleItems.length ? previous : visibleItems.length));
      const actionSize = parseFloat(getComputedStyle(actions).getPropertyValue('--composer-action-size'));
      const horizontalGap = window.matchMedia('(max-width: 480px)').matches ? 3 : 6;
      const horizontalWidth = visibleItems.length * actionSize + Math.max(0, visibleItems.length - 1) * horizontalGap;
      const width = parseFloat(getComputedStyle(textarea).width) + parseFloat(getComputedStyle(actions).width) - horizontalWidth;
      if (width > 0) setStackReferenceWidth(previous => previous !== null && Math.abs(previous - width) < 0.5 ? previous : width);
    };
    report();
    const observer = new ResizeObserver(report);
    observer.observe(shell);
    observer.observe(actions);
    return () => observer.disconnect();
  }, [textareaRef]);

  // 控件数量与参考宽度同源：都取自上面那次 DOM 测量，避免“JS 里写 4、CSS 里藏一个”两处各写一份。
  // 它只用于“单列还是两列”的取舍（行数由 CSS 隐式生成），所以即使测量晚一拍也不会撑高外壳。
  const [actionColumns, setActionColumns] = useState<1 | 2>(1);

  // 视口高度只用来判断单列放不放得下。这里存“列数”而不是“视口高度”：
  // 拖窗口高度、软键盘弹出动画期间每帧都会触发 resize，存原始高度会让整块输入区每帧重渲染，
  // 而列数只在真的跨过阈值时才变一次。
  useLayoutEffect(() => {
    const update = () => {
      const next = planComposerActionBar({
        itemCount: visibleActionCount || 1,
        availableHeight: computeComposerViewportBudget({
          viewportHeight: window.visualViewport?.height ?? window.innerHeight
        })
      }).columns;
      setActionColumns(previous => (previous === next ? previous : next));
    };
    update();
    window.addEventListener('resize', update);
    window.visualViewport?.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
      window.visualViewport?.removeEventListener('resize', update);
    };
  }, [visibleActionCount]);

  const isExpanded = isMultiline || isStacked;
  const actionsLayout = !isStacked ? 'row' : actionColumns === 2 ? 'columns' : 'column';

  const updateSettingsPosition = useCallback(() => {
    const rect = composerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const viewport = window.visualViewport;
    const viewportWidth = viewport?.width ?? window.innerWidth;
    const viewportHeight = viewport?.height ?? window.innerHeight;
    const viewportOffsetTop = viewport?.offsetTop ?? 0;
    const horizontalInset = 8;
    const verticalGap = 12;
    const topbarBottom = document.querySelector('.lawver-topbar')?.getBoundingClientRect().bottom ?? viewportOffsetTop;
    const width = Math.min(rect.width, viewportWidth - horizontalInset * 2);
    const left = Math.max(horizontalInset, Math.min(rect.left, viewportWidth - width - horizontalInset));
    const bottom = Math.max(12, viewportHeight + viewportOffsetTop - rect.top + verticalGap);
    const maxHeight = Math.max(80, rect.top - topbarBottom - verticalGap * 2);

    setSettingsPosition({
      left,
      width,
      bottom,
      maxHeight
    });
  }, []);

  const updateSettingsClearance = useCallback(() => {
    if (!hasComposerOverlay) {
      onSettingsClearanceChange?.(0);
      return;
    }

    const settingsHeight = isInputExpanded
      ? (settingsPanelRef.current?.getBoundingClientRect().height ?? 168) + 20
      : 0;
    const choiceHeight = hasActiveChoicePrompt
      ? (choicePromptRef.current?.getBoundingClientRect().height ?? 240) + 20
      : 0;
    onSettingsClearanceChange?.(Math.max(settingsHeight, choiceHeight));
  }, [hasActiveChoicePrompt, hasComposerOverlay, isInputExpanded, onSettingsClearanceChange]);

  useLayoutEffect(() => {
    if (hasComposerOverlay) {
      updateSettingsPosition();
      updateSettingsClearance();
    } else {
      onSettingsClearanceChange?.(0);
    }
  }, [hasComposerOverlay, pendingUploads.length, onSettingsClearanceChange, updateSettingsClearance, updateSettingsPosition]);

  useLayoutEffect(() => {
    updateSettingsClearance();
  }, [settingsPosition.width, updateSettingsClearance]);

  useEffect(() => {
    if (!hasComposerOverlay) return;

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
    const choiceResizeObserver = typeof ResizeObserver !== 'undefined' && choicePromptRef.current
      ? new ResizeObserver(updateSettingsClearance)
      : null;

    window.addEventListener('resize', handleViewportChange);
    window.visualViewport?.addEventListener('resize', handleViewportChange);
    // 视口滚动只用于重新贴底，不会 preventDefault；passive 避免移动端滚动被阻塞。
    window.visualViewport?.addEventListener('scroll', handleViewportChange, { passive: true });
    composerResizeObserver?.observe(composerRef.current as Element);
    settingsResizeObserver?.observe(settingsPanelRef.current as Element);
    choiceResizeObserver?.observe(choicePromptRef.current as Element);

    return () => {
      window.removeEventListener('resize', handleViewportChange);
      window.visualViewport?.removeEventListener('resize', handleViewportChange);
      window.visualViewport?.removeEventListener('scroll', handleViewportChange);
      composerResizeObserver?.disconnect();
      settingsResizeObserver?.disconnect();
      choiceResizeObserver?.disconnect();
    };
  }, [hasComposerOverlay, updateSettingsClearance, updateSettingsPosition]);

  useEffect(() => {
    if (activeChoicePrompt && isInputExpanded) {
      setIsInputExpanded(false);
    }
  }, [activeChoicePrompt, isInputExpanded, setIsInputExpanded]);

  // 整个输入区（附件条 + 状态条 + 输入框）都在文档流里，高度变化会压缩消息列表；
  // 上报实际高度，让列表在用户贴底时跟着补偿。
  useEffect(() => {
    const element = composerRef.current;
    if (!element || !onComposerHeightChange || typeof ResizeObserver === 'undefined') return;

    let reported = -1;
    const report = () => {
      const height = Math.round(element.getBoundingClientRect().height);
      if (height === reported) return;
      reported = height;
      onComposerHeightChange(height);
    };
    report();

    const observer = new ResizeObserver(report);
    observer.observe(element);
    return () => observer.disconnect();
  }, [onComposerHeightChange]);

  const canSendMessage = !hasActiveChoicePrompt && !isUploadingFiles && (input.trim().length > 0 || pendingUploads.length > 0);

  const onSendWrapper = () => {
    if (!canSendMessage) return;
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
              maxHeight: settingsPosition.maxHeight || `calc(100dvh - ${settingsPosition.bottom}px - var(--safe-top) - 12px)`,
              overflowY: 'auto'
            }}
            className="glass lawver-popover z-[80] flex flex-col gap-0 rounded-[var(--radius-xl)] p-0 shadow-[var(--shadow-5)]"
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
                className="lawver-pressable h-11 w-32 shrink-0 cursor-pointer rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[rgba(255,255,255,0.5)] px-3 text-sm font-medium text-[var(--fg-1)] outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] dark:bg-white/[0.05]"
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

  const choicePromptLayer = typeof document !== 'undefined'
    ? createPortal(
      <AnimatePresence>
        {activeChoicePrompt && onAnswerChoice && settingsPosition.width > 0 && (
          <UserChoicePrompt
            ref={choicePromptRef}
            prompt={activeChoicePrompt}
            disabled={isLoading}
            onAnswerChoice={onAnswerChoice}
            style={{
              left: settingsPosition.left,
              width: settingsPosition.width,
              bottom: settingsPosition.bottom,
              maxHeight: settingsPosition.maxHeight || `calc(100dvh - ${settingsPosition.bottom}px - var(--safe-top) - 12px)`
            }}
          />
        )}
      </AnimatePresence>,
      document.body
    )
    : null;

  return (
    <>
      {settingsLayer}
      {choicePromptLayer}
      <footer className="lawver-composer-footer pointer-events-none shrink-0 px-2 pb-[calc(0.75rem+var(--safe-bottom))] pt-1 sm:px-4 sm:pb-[calc(1rem+var(--safe-bottom))] sm:pt-2">
        <div ref={composerRef} className="pointer-events-auto relative mx-auto flex w-full max-w-3xl min-w-0 flex-col">
          {pendingUploads.length > 0 && (
            <div className="flex flex-wrap gap-2 px-2 pb-1">
              {pendingUploads.map((file, index) => (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  key={file.previewUrl || file.path || index}
                  className={`flex items-center gap-2 border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--fg-2)] shadow-[var(--shadow-1)] ${
                    file.kind === 'image'
                      ? 'rounded-[var(--radius-md)] p-1 pr-2'
                      : 'rounded-full px-3 py-1 sm:px-4 sm:py-1.5'
                  }`}
                >
                  {file.kind === 'image' && file.previewUrl ? (
                    <img
                      src={file.previewUrl}
                      alt={file.name}
                      className="h-10 w-10 shrink-0 rounded-[var(--radius-sm)] object-cover"
                    />
                  ) : (
                    <Paperclip size={12} strokeWidth={2} className="text-[var(--accent)] sm:size-3.5" />
                  )}
                  <span className="max-w-[120px] truncate text-xs sm:max-w-[200px] sm:text-sm">{file.name}</span>
                  {file.kind === 'image' && (
                    <span className="shrink-0 rounded-sm bg-[var(--accent-quiet)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--accent)]">
                      图片
                    </span>
                  )}
                  <button
                    onClick={() => removeUploadedFile(index)}
                    className="lawver-pressable rounded-full p-1 text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)]"
                    aria-label={`移除 ${file.name}`}
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

          <div
            className="lawver-composer-shell"
            data-multiline={isExpanded ? 'true' : 'false'}
            data-actions-layout={actionsLayout}
          >
            <motion.div
              layout
              transition={{ layout: { duration: 0.24, ease: [0.2, 0, 0, 1] } }}
              className="lawver-composer-actions"
            >
              <motion.div
                layout
                transition={{ layout: { duration: 0.24, ease: [0.2, 0, 0, 1] } }}
                className="lawver-composer-action-slot"
              >
                <button
                  onClick={() => setIsInputExpanded(!isInputExpanded)}
                  className={`lawver-composer-action lawver-pressable transition-colors ${isInputExpanded ? 'bg-[var(--accent-quiet)] text-[var(--accent)]' : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'}`}
                  aria-label="Open composer settings"
                  aria-expanded={isInputExpanded}
                >
                  <Settings2 size={20} strokeWidth={2} />
                </button>
              </motion.div>

              <motion.div
                layout
                transition={{ layout: { duration: 0.24, ease: [0.2, 0, 0, 1] } }}
                className="lawver-composer-action-slot"
              >
                <HoverInfo label="上传材料 (最大 50MB)" placement="top">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isLoading}
                    className="lawver-composer-action lawver-pressable text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] disabled:opacity-50 dark:hover:bg-white/[0.06]"
                    aria-label="上传材料 (最大 50MB)"
                  >
                    <Paperclip size={20} strokeWidth={2} />
                  </button>
                </HoverInfo>
              </motion.div>
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

              <motion.div
                layout
                transition={{ layout: { duration: 0.24, ease: [0.2, 0, 0, 1] } }}
                className="lawver-composer-action-slot"
              >
                <HoverInfo label="上传图片 (多模态识别)" placement="top">
                  <button
                    onClick={() => imageInputRef.current?.click()}
                    disabled={isLoading}
                    className="lawver-composer-action lawver-pressable text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] disabled:opacity-50 dark:hover:bg-white/[0.06]"
                    aria-label="上传图片 (多模态识别)"
                  >
                    <ImagePlus size={20} strokeWidth={2} />
                  </button>
                </HoverInfo>
              </motion.div>
              <input
                type="file"
                ref={imageInputRef}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file);
                  if (imageInputRef.current) imageInputRef.current.value = '';
                }}
                className="hidden"
                accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
              />

              {/* 小屏优先保证输入宽度：计量器信息量最低，sm 以上再显示 */}
              <motion.div
                layout
                transition={{ layout: { duration: 0.24, ease: [0.2, 0, 0, 1] } }}
                className="lawver-composer-action-slot hidden sm:block"
              >
                <ContextUsageMeter usage={contextUsage} />
              </motion.div>
            </motion.div>

            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={hasActiveChoicePrompt}
              placeholder="输入问题…"
              className="composer-textarea lawver-composer-textarea custom-scrollbar min-w-0 flex-1 resize-none border-0 bg-transparent text-[var(--fg-1)] outline-none placeholder:text-[var(--fg-4)] disabled:opacity-60 focus:border-0 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0"
              rows={1}
            />
            <button
              onClick={isLoading ? handleStop : onSendWrapper}
              disabled={!isLoading && !canSendMessage}
              className={`lawver-composer-action lawver-pressable shadow-[var(--shadow-1)] transition-colors ${
                isLoading
                  ? 'bg-[var(--color-danger-500)] text-white hover:opacity-90'
                  : canSendMessage
                  ? 'bg-[var(--accent)] text-[var(--accent-on)] hover:bg-[var(--accent-hover)]'
                  : 'cursor-not-allowed bg-[rgba(20,23,31,0.08)] text-[var(--fg-4)] shadow-none dark:bg-white/[0.08]'
              }`}
              aria-label={isLoading ? '停止生成' : isUploadingFiles ? '文件上传完成前暂不能发送' : 'Send message'}
            >
              {isLoading ? <Square size={18} strokeWidth={2.4} fill="currentColor" /> : <Send size={20} strokeWidth={2} />}
            </button>
          </div>
        </div>
      </footer>
    </>
  );
};
