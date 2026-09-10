/*
 * 模块描述：模拟法庭页面，与主聊天共享外壳结构——可收起侧栏、顶栏、庭审记录流、发言区与案件面板。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Bot,
  Briefcase,
  ChevronsRight,
  Download,
  FileText,
  Gavel,
  Landmark,
  Lock,
  Menu,
  Play,
  Send,
  Paperclip,
  Settings,
  Trash2,
  Upload,
  X
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type { CourtAgentState, CourtSession, CourtSpeaker, WorkspaceFile } from '../types';
import { useCourtSession } from '../hooks/useCourtSession';
import { useWorkspace } from '../hooks/useWorkspace';
import { buildAttachmentPrompt } from '../lib/attachment-prompt';
import { useBackButton } from '../hooks/useBackButton';
import { flattenBranchTree } from '../lib/branchTree';
import { downloadWorkspaceFile } from '../lib/download';
import type { PendingUpload } from '../types';
import { BrandMark, BrandLockup } from './Brand';
import { BranchRails } from './BranchRails';
import { HoverInfo } from './HoverInfo';
import { StorageIndicator } from './StorageIndicator';
import { CourtSetup } from './CourtSetup';
import { CourtTranscript, SPEAKER_META, phaseLabel } from './CourtTranscript';
import { useAppDialog } from '../contexts/DialogContext';
import { FileUploadProgress } from './FileUploadProgress';

const PANEL_WIDTH = 320;
const PANEL_TRANSITION = { duration: 0.28, ease: [0.2, 0, 0, 1] } as const;

interface CourtPageProps {
  onBack: () => void;
  onSettingsClick: () => void;
  secureAccessBanner?: React.ReactNode;
  windowWidth: number;
}

const AGENT_STATUS_META: Record<CourtAgentState['status'], { label: string; dotClass: string; pulse: boolean }> = {
  idle: { label: '待命', dotClass: 'bg-[var(--fg-4)]', pulse: false },
  running: { label: '思考中', dotClass: 'bg-[var(--accent)]', pulse: true },
  done: { label: '已发言', dotClass: 'bg-[var(--brand-tertiary-500)]', pulse: false },
  error: { label: '异常', dotClass: 'bg-[var(--color-danger-500)]', pulse: false }
};

const AGENT_ORDER: Array<Extract<CourtSpeaker, 'judge' | 'opponent' | 'reviewer'>> = ['judge', 'opponent', 'reviewer'];

/* ── 庭审侧栏 ─────────────────────────────────────────────── */

const CourtSidebar: React.FC<{
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  sessions: CourtSession[];
  currentId: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onBack: () => void;
  onDelete: (id: string) => void;
  isDesktopLayout: boolean;
}> = ({ isOpen, setIsOpen, sessions, currentId, onSelect, onCreate, onBack, onDelete, isDesktopLayout }) => {
  const panelAnimation = isDesktopLayout
    ? { width: isOpen ? PANEL_WIDTH : 0, opacity: isOpen ? 1 : 0, borderRightWidth: isOpen ? 1 : 0 }
    : { x: isOpen ? 0 : '-100%', opacity: isOpen ? 1 : 0 };
  const contentWidth = isDesktopLayout ? `${PANEL_WIDTH}px` : 'min(85vw, 320px)';

  return (
    <>
      <AnimatePresence>
        {!isDesktopLayout && isOpen && (
          <motion.div
            key="court-sidebar-scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={PANEL_TRANSITION}
            className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      <motion.aside
        initial={false}
        animate={panelAnimation}
        transition={PANEL_TRANSITION}
        className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-[var(--border-subtle)] bg-[var(--bg-app)] ${
          isDesktopLayout ? 'relative' : 'fixed left-0 top-0 z-50 rounded-r-[var(--radius-xl)] shadow-[var(--shadow-4)]'
        }`}
        style={{ pointerEvents: isOpen ? 'auto' : 'none', ...(!isDesktopLayout ? { width: contentWidth } : {}) }}
        aria-hidden={!isOpen}
      >
        <div className="flex h-full shrink-0 flex-col" style={{ width: contentWidth }}>
          <div className="flex items-center justify-between p-4 pb-3 sm:p-6 sm:pb-4">
            <BrandLockup />
            {!isDesktopLayout && (
              <button
                onClick={() => setIsOpen(false)}
                className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
                aria-label="关闭庭审列表"
              >
                <X size={20} strokeWidth={2} className="sm:size-[22px]" />
              </button>
            )}
          </div>

          <div className="flex flex-col gap-2 px-3 pb-3 sm:px-4">
            <button onClick={onCreate} className="md3-btn-filled lawver-pressable w-full whitespace-nowrap py-3 sm:py-3.5">
              <Gavel size={19} strokeWidth={2} />
              新建庭审
            </button>
            <button onClick={onBack} className="md3-btn-tonal lawver-pressable w-full whitespace-nowrap py-2.5 sm:py-3">
              <ArrowLeft size={17} strokeWidth={2} />
              返回法律咨询
            </button>
          </div>

          <div className="custom-scrollbar flex min-w-0 flex-1 flex-col gap-1.5 overflow-y-auto px-3 pb-2">
            {sessions.length === 0 ? (
              <p className="px-3 py-8 text-center text-[13px] leading-6 text-[var(--fg-3)]">
                暂无庭审记录，
                <br />
                新建后会保存在这里。
              </p>
            ) : (
              flattenBranchTree<CourtSession>(sessions).map(({ item: session, ancestorTrails, isLastSibling }) => {
                const active = session.id === currentId;
                return (
                  <div
                    key={session.id}
                    className="flex w-full items-stretch"
                    title={session.parent_id ? '由其他庭审分叉而来' : undefined}
                  >
                    <BranchRails ancestorTrails={ancestorTrails} isLastSibling={isLastSibling} />
                    <div
                      className={`group flex min-w-0 flex-1 items-center rounded-[var(--radius-md)] transition-colors ${
                        active
                          ? 'bg-[var(--accent-quiet)]'
                          : 'hover:bg-[rgba(20,23,31,0.05)] dark:hover:bg-white/[0.05]'
                      }`}
                    >
                      <button
                        onClick={() => onSelect(session.id)}
                        className="lawver-pressable min-w-0 flex-1 rounded-[var(--radius-md)] px-3 py-2.5 text-left"
                      >
                        <div
                          className={`truncate text-[14px] font-medium ${
                            active ? 'text-[var(--brand-primary-700)] dark:text-[var(--accent)]' : 'text-[var(--fg-1)]'
                          }`}
                        >
                          {session.title || '未命名庭审'}
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-[var(--fg-3)]">
                          <span className="shrink-0">{phaseLabel(session.court_state.phase)}</span>
                          <span className="text-[var(--fg-4)]">·</span>
                          <span className="truncate">{session.user_side}</span>
                          {session.court_state.trial_over && (
                            <span className="ml-auto shrink-0 rounded-full bg-[var(--bg-inset)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--fg-3)]">
                              已结束
                            </span>
                          )}
                        </div>
                      </button>
                      <HoverInfo label="删除庭审" placement="top">
                        <button
                          onClick={() => onDelete(session.id)}
                          className="lawver-pressable mr-1 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] opacity-100 transition-opacity hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)] lg:h-8 lg:w-8 lg:opacity-0 lg:group-hover:opacity-100"
                          aria-label="删除庭审"
                        >
                          <Trash2 size={15} strokeWidth={2} />
                        </button>
                      </HoverInfo>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div className="border-t border-[var(--border-subtle)] p-4 pb-[calc(1rem+var(--safe-bottom))]">
            <StorageIndicator />
          </div>
        </div>
      </motion.aside>
    </>
  );
};

/* ── 案件面板 ─────────────────────────────────────────────── */

const DossierBlock: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div className="mb-1 text-[12px] font-semibold uppercase tracking-[0.05em] text-[var(--fg-3)]">{label}</div>
    {value.trim() ? (
      <p className="whitespace-pre-wrap text-[13px] leading-6 text-[var(--fg-2)]">{value}</p>
    ) : (
      <p className="text-[13px] italic text-[var(--fg-4)]">未填写</p>
    )}
  </div>
);

const CourtCasePanel: React.FC<{
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  session: CourtSession;
  files: WorkspaceFile[];
  onRequestUpload: () => void;
  onDeleteFile: (path: string) => void;
  isDesktopLayout: boolean;
}> = ({ isOpen, setIsOpen, session, files, onRequestUpload, onDeleteFile, isDesktopLayout }) => {
  const { showAlert } = useAppDialog();
  const panelAnimation = isDesktopLayout
    ? { width: isOpen ? PANEL_WIDTH : 0, opacity: isOpen ? 1 : 0, borderLeftWidth: isOpen ? 1 : 0 }
    : { x: isOpen ? 0 : '100%', opacity: isOpen ? 1 : 0 };
  const contentWidth = isDesktopLayout ? `${PANEL_WIDTH}px` : 'min(86vw, 340px)';
  const handleDownload = async (file: WorkspaceFile) => {
    try {
      await downloadWorkspaceFile(file.path, file.name);
    } catch (error: any) {
      await showAlert({
        title: '下载失败',
        message: error?.message || '下载失败',
        tone: 'danger',
      });
    }
  };

  return (
    <>
      <AnimatePresence>
        {!isDesktopLayout && isOpen && (
          <motion.div
            key="court-case-scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={PANEL_TRANSITION}
            className="fixed inset-0 z-40 bg-[var(--bg-overlay)] backdrop-blur-sm"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      <motion.aside
        initial={false}
        animate={panelAnimation}
        transition={PANEL_TRANSITION}
        className={`flex h-full shrink-0 flex-col overflow-hidden border-l border-[var(--border-subtle)] bg-[var(--bg-surface)] ${
          isDesktopLayout ? 'relative' : 'fixed right-0 top-0 z-50 rounded-l-[var(--radius-xl)] shadow-[var(--shadow-4)]'
        }`}
        style={{ pointerEvents: isOpen ? 'auto' : 'none', ...(!isDesktopLayout ? { width: contentWidth } : {}) }}
        aria-hidden={!isOpen}
      >
        <div className="flex h-full shrink-0 flex-col" style={{ width: contentWidth }}>
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-4 py-3 sm:px-5 sm:py-4">
            <h3 className="t-title-m flex items-center gap-2.5 text-[15px]">
              <Briefcase size={18} strokeWidth={2} className="text-[var(--accent)]" />
              案件面板
            </h3>
            <button
              onClick={() => setIsOpen(false)}
              className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
              aria-label="关闭案件面板"
            >
              <X size={18} strokeWidth={2} />
            </button>
          </div>

          <div className="custom-scrollbar flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto p-4 sm:gap-6 sm:p-5">
            {/* 参与者 */}
            <section>
              <h4 className="t-label-s t-weak mb-3 px-1">出庭参与者 · 记忆隔离</h4>
              <div className="flex flex-col gap-2">
                {AGENT_ORDER.map(role => {
                  const meta = SPEAKER_META[role];
                  const Icon = meta.icon;
                  const agentState = session.agent_states[role];
                  const statusMeta = AGENT_STATUS_META[agentState?.status || 'idle'];
                  return (
                    <div
                      key={role}
                      className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-2.5"
                    >
                      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${meta.avatarClass} ${meta.iconClass}`}>
                        <Icon size={17} strokeWidth={2} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] font-semibold text-[var(--fg-1)]">{meta.label}</div>
                        <div className="text-[12px] text-[var(--fg-3)]">{meta.role}</div>
                      </div>
                      <span className="flex shrink-0 items-center gap-1.5 text-[12px] text-[var(--fg-3)]">
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${statusMeta.dotClass} ${statusMeta.pulse ? 'lawver-bloom-dot' : ''}`}
                        />
                        {statusMeta.label}
                      </span>
                    </div>
                  );
                })}
                {/* 我方代理：仅在已开启或曾经跑过（有记忆）时显示，避免默认场景信息过载 */}
                {(session.court_state.user_agent_enabled || session.agent_states.user?.status !== 'idle') && (
                  <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[rgba(44,118,112,0.22)] bg-[rgba(44,118,112,0.05)] px-3 py-2.5">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[rgba(44,118,112,0.14)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
                      <Bot size={17} strokeWidth={2} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold text-[var(--fg-1)]">我方代理</div>
                      <div className="text-[12px] text-[var(--fg-3)]">用户方 AI 出庭代理</div>
                    </div>
                    <span className="flex shrink-0 items-center gap-1.5 text-[12px] text-[var(--fg-3)]">
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${AGENT_STATUS_META[session.agent_states.user?.status || 'idle'].dotClass} ${AGENT_STATUS_META[session.agent_states.user?.status || 'idle'].pulse ? 'lawver-bloom-dot' : ''}`}
                      />
                      {session.court_state.user_agent_enabled
                        ? AGENT_STATUS_META[session.agent_states.user?.status || 'idle'].label
                        : '未启用'}
                    </span>
                  </div>
                )}
              </div>
            </section>

            {/* 公开案卷 */}
            <section>
              <h4 className="t-label-s t-weak mb-3 flex items-center gap-1.5 px-1">
                <Landmark size={13} strokeWidth={2} />
                公开案卷
              </h4>
              <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3.5">
                <DossierBlock label="案情与争议焦点" value={session.shared_dossier.summary} />
                <DossierBlock label="诉求 / 指控" value={session.shared_dossier.claims} />
                <DossierBlock label="公开证据线索" value={session.shared_dossier.evidence} />
              </div>
            </section>

            {/* 私有作战笔记 */}
            <section>
              <h4 className="t-label-s mb-3 flex items-center gap-1.5 px-1 text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]">
                <Lock size={13} strokeWidth={2} />
                你的作战笔记 · 仅你可见
              </h4>
              <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-[rgba(44,118,112,0.22)] bg-[rgba(44,118,112,0.05)] p-3.5">
                <DossierBlock label="庭审策略" value={session.private_brief.strategy} />
                <DossierBlock label="证据链与推理" value={session.private_brief.logic_chain} />
                <DossierBlock label="担心的漏洞" value={session.private_brief.risk_notes} />
              </div>
            </section>

            {/* 共享文件 */}
            <section>
              <div className="mb-3 flex items-center justify-between px-1">
                <h4 className="t-label-s t-weak">共享文件</h4>
                <button
                  onClick={onRequestUpload}
                  className="lawver-pressable inline-flex min-h-11 items-center gap-1 rounded-full px-3 py-1 text-[12px] font-medium text-[var(--accent)] transition-colors hover:bg-[var(--accent-quiet)]"
                >
                  <Upload size={13} strokeWidth={2} />
                  上传
                </button>
              </div>
              <div className="flex flex-col gap-2">
                {files.length === 0 ? (
                  <p className="px-1 text-[13px] italic text-[var(--fg-4)]">暂无共享文件</p>
                ) : (
                  files.map(file => (
                    <div
                      key={`${file.type}:${file.tempId || file.path}`}
                      className="group flex items-center gap-2.5 rounded-[var(--radius-sm)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] px-3 py-2"
                    >
                      <FileText size={15} strokeWidth={2} className="shrink-0 text-[var(--accent)]" />
                      <div className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] leading-5 text-[var(--fg-1)]">{file.name}</span>
                        <FileUploadProgress file={file} />
                      </div>
                      {!file.isUploading && (
                        <div className="flex shrink-0 items-center gap-0.5 opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100">
                          <HoverInfo label="下载" placement="top">
                            <button
                              onClick={() => handleDownload(file)}
                              className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-[8px] text-[var(--fg-3)] transition-colors hover:bg-[var(--accent-quiet)] hover:text-[var(--accent)] lg:h-8 lg:w-8"
                              aria-label="下载文件"
                            >
                              <Download size={14} strokeWidth={2} />
                            </button>
                          </HoverInfo>
                          <HoverInfo label="删除" placement="top">
                            <button
                              onClick={() => onDeleteFile(file.path)}
                              className="lawver-pressable inline-flex h-11 w-11 items-center justify-center rounded-[8px] text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)] lg:h-8 lg:w-8"
                              aria-label="删除文件"
                            >
                              <Trash2 size={14} strokeWidth={2} />
                            </button>
                          </HoverInfo>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </section>
          </div>
        </div>
      </motion.aside>
    </>
  );
};

/* ── 发言区（阶段控制 + 输入）────────────────────────────────── */

const CourtComposerDock: React.FC<{
  session: CourtSession;
  isRunning: boolean;
  status: string | null;
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onRunNext: () => void;
  onForceAdvance: () => void;
  onSetAutoMode: (auto: boolean) => void;
  onSetUserAgentMode: (enabled: boolean) => void;
  onRequestUpload: () => void;
  isUploadingFiles: boolean;
  pendingMaterials: PendingUpload[];
  onRemoveMaterial: (index: number) => void;
}> = ({ session, isRunning, status, value, onChange, onSend, onRunNext, onForceAdvance, onSetAutoMode, onSetUserAgentMode, onRequestUpload, isUploadingFiles, pendingMaterials, onRemoveMaterial }) => {
  const state = session.court_state;
  const trialOver = state.trial_over;
  const awaitingUser = state.awaiting_user;
  const userAgentEnabled = Boolean(state.user_agent_enabled);
  const pendingCount = session.pending_interjections.length;
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 轮到用户发言、且未开启 AI 代理时，自动聚焦输入框。开启代理时不抢焦点。
  useEffect(() => {
    if (awaitingUser && !isRunning && !trialOver && !userAgentEnabled) {
      textareaRef.current?.focus();
    }
  }, [awaitingUser, isRunning, trialOver, userAgentEnabled]);

  const statusText = trialOver
    ? '庭审已结束 · 复盘意见已写入记录'
    : isRunning
      ? status || '庭审进行中'
      : awaitingUser
        ? userAgentEnabled
          ? `我方代理待发言（${session.user_side}）`
          : `轮到你陈述（${session.user_side}）`
        : status || '可推进下一轮';

  const placeholder = trialOver
    ? '庭审已结束'
    : isUploadingFiles
      ? '文件上传完成后可继续发送'
    : isRunning
      ? '发言中…你的输入会作为插话排队'
      : awaitingUser
        ? userAgentEnabled
          ? '我方代理将代为发言；输入可即时接管本轮'
          : `轮到你陈述（${session.user_side}）`
        : '输入发言或插话…';

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isMac = /Mac|iPhone|iPod|iPad/i.test(navigator.userAgent);
    const sendTriggered = isMac ? event.metaKey && event.key === 'Enter' : event.ctrlKey && event.key === 'Enter';
    if (sendTriggered) {
      event.preventDefault();
      if (isUploadingFiles) return;
      onSend();
    }
  };

  const canSend = value.trim().length > 0 && !trialOver && !isUploadingFiles;

  return (
    <div className="lawver-court-composer shrink-0 overflow-x-hidden border-t border-[var(--border-subtle)] bg-[var(--bg-app)] px-3 pb-[calc(0.75rem+var(--safe-bottom))] pt-2.5 sm:px-5">
      <div className="mx-auto w-full min-w-0 max-w-3xl">
        {/* 阶段控制条 */}
        <div className="mb-2 flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-3">
          <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:flex-1">
            <span className="md3-chip md3-chip-primary shrink-0">{phaseLabel(state.phase)}</span>
            {pendingCount > 0 && (
              <HoverInfo label="插话已排队，当前发言结束后会进入公开记录并由法官优先处理" placement="top">
                <span className="shrink-0 rounded-[var(--radius-sm)] bg-[rgba(184,132,42,0.14)] px-2 py-1 text-[12px] font-medium text-[var(--color-warning-500)]">
                  插话 {pendingCount}
                </span>
              </HoverInfo>
            )}
            <span
              className={`truncate text-[13px] ${
                awaitingUser && !isRunning && !trialOver ? 'font-medium text-[var(--accent)]' : 'text-[var(--fg-3)]'
              }`}
            >
              {statusText}
            </span>
          </div>

          {!trialOver && (
            <div className="grid w-full min-w-0 grid-cols-2 gap-2 sm:flex sm:w-auto sm:flex-wrap sm:items-center sm:justify-end sm:gap-1.5">
              <HoverInfo
                label={
                  userAgentEnabled
                    ? '关闭后，轮到你时由你打字'
                    : '开启后，轮到你时由 AI 代理代为出庭（可读你的私有 brief）'
                }
                placement="top"
              >
                <button
                  type="button"
                  onClick={() => onSetUserAgentMode(!userAgentEnabled)}
                  className={`lawver-pressable inline-flex min-h-11 w-full items-center justify-center gap-1 rounded-full px-2.5 py-1.5 text-[12px] font-medium transition-colors sm:min-h-10 sm:w-auto ${
                    userAgentEnabled
                      ? 'bg-[rgba(44,118,112,0.14)] text-[var(--brand-tertiary-700)] dark:text-[#8ecdc7]'
                      : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'
                  }`}
                >
                  <Bot size={14} strokeWidth={2} />
                  我方代理
                </button>
              </HoverInfo>

              <HoverInfo label="跳过当前阶段，请法庭推进" placement="top">
                <button
                  type="button"
                  onClick={onForceAdvance}
                  disabled={isRunning}
                  className="lawver-pressable inline-flex min-h-11 w-full items-center justify-center gap-1 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] disabled:opacity-40 dark:hover:bg-white/[0.06] sm:min-h-10 sm:w-auto"
                >
                  <ChevronsRight size={15} strokeWidth={2} />
                  推进阶段
                </button>
              </HoverInfo>

              <div className="col-span-2 grid w-full grid-cols-2 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-0.5 sm:flex sm:w-auto">
                {(['manual', 'auto'] as const).map(mode => {
                  const isAuto = mode === 'auto';
                  const active = session.auto_mode === isAuto;
                  return (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => onSetAutoMode(isAuto)}
                      aria-pressed={active}
                      className={`lawver-pressable min-h-11 rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors sm:min-h-9 ${
                        active ? 'bg-[var(--accent-quiet)] text-[var(--accent)]' : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'
                      }`}
                    >
                      {isAuto ? '自动' : '手动'}
                    </button>
                  );
                })}
              </div>

              {!session.auto_mode && (
                <button
                  type="button"
                  onClick={onRunNext}
                  disabled={isRunning || (awaitingUser && !userAgentEnabled)}
                  className="md3-btn-tonal lawver-pressable min-h-11 w-full !px-3.5 !py-1.5 text-[13px] sm:min-h-10 sm:w-auto"
                >
                  <Play size={15} strokeWidth={2} />
                  继续
                </button>
              )}
            </div>
          )}
        </div>

        {/* 待发材料：发言时会随文本把清单（含工作区路径）发给各角色 */}
        {pendingMaterials.length > 0 && (
          <div className="mb-1 flex flex-wrap gap-2 px-2">
            {pendingMaterials.map((file, index) => (
              <div
                key={file.path || `${file.name}-${index}`}
                className="flex min-w-0 items-center gap-1.5 rounded-full border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-1 text-[12px] text-[var(--fg-2)] shadow-[var(--shadow-1)]"
              >
                <Paperclip size={12} strokeWidth={2} className="shrink-0 text-[var(--accent)]" />
                <span className="max-w-[140px] truncate sm:max-w-[220px]">{file.name}</span>
                {file.kind === 'image' && (
                  <span className="shrink-0 rounded-sm bg-[var(--accent-quiet)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--accent)]">
                    图片
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => onRemoveMaterial(index)}
                  className="lawver-pressable shrink-0 rounded-full p-1 text-[var(--fg-3)] transition-colors hover:bg-[rgba(176,70,62,0.1)] hover:text-[var(--color-danger-500)]"
                  aria-label={`移除 ${file.name}`}
                >
                  <X size={12} strokeWidth={2} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* 输入框 */}
        <div className="lawver-composer-shell">
          <HoverInfo label="上传共享文件" placement="top">
            <button
              type="button"
              onClick={onRequestUpload}
              disabled={trialOver}
              className="lawver-composer-action lawver-pressable text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] disabled:opacity-40 dark:hover:bg-white/[0.06]"
              aria-label="上传共享文件"
            >
              <Paperclip size={20} strokeWidth={2} />
            </button>
          </HoverInfo>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={event => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={trialOver}
            rows={1}
            placeholder={placeholder}
            className="composer-textarea lawver-composer-textarea max-h-32 min-w-0 flex-1 resize-none border-0 bg-transparent text-[var(--fg-1)] outline-none placeholder:text-[var(--fg-4)] focus:outline-none disabled:opacity-60"
          />
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            className={`lawver-composer-action lawver-pressable transition-colors ${
              canSend
                ? 'bg-[var(--accent)] text-[var(--accent-on)] shadow-[var(--shadow-1)] hover:bg-[var(--accent-hover)]'
                : 'cursor-not-allowed bg-[rgba(20,23,31,0.08)] text-[var(--fg-4)] dark:bg-white/[0.08]'
            }`}
            aria-label={isUploadingFiles ? '文件上传完成前暂不能发送' : '发送'}
          >
            <Send size={20} strokeWidth={2} />
          </button>
        </div>
      </div>
    </div>
  );
};

/* ── 页面 ─────────────────────────────────────────────────── */

export const CourtPage: React.FC<CourtPageProps> = ({
  onBack,
  onSettingsClick,
  secureAccessBanner,
  windowWidth
}) => {
  const {
    courtSessions,
    currentCourtId,
    setCurrentCourtId,
    currentCourtSession,
    isInitialized,
    isRunning,
    status,
    composerText,
    setComposerText,
    createCourtSession,
    deleteCourtSession,
    sendUserSpeech,
    runNextTurn,
    setAutoMode,
    setUserAgentMode,
    forceAdvance,
    rewindToEvent,
    branchFromEvent
  } = useCourtSession(true);

  const workspace = useWorkspace(currentCourtId, Boolean(currentCourtId));
  const { showAlert } = useAppDialog();
  const isDesktopLayout = windowWidth >= 1024;

  const [isSidebarOpen, setIsSidebarOpen] = useState(() => windowWidth >= 1024);
  const [isCasePanelOpen, setIsCasePanelOpen] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useBackButton(useCallback(() => {
    if (isCasePanelOpen) {
      setIsCasePanelOpen(false);
      return true;
    }
    if (isSidebarOpen) {
      setIsSidebarOpen(false);
      return true;
    }
    return false;
  }, [isCasePanelOpen, isSidebarOpen]), isInitialized);

  useEffect(() => {
    if (isInitialized && courtSessions.length === 0) {
      setShowSetup(true);
    }
  }, [isInitialized, courtSessions.length]);

  const subtitle = useMemo(() => {
    if (showSetup || !currentCourtSession) return '模拟法庭博弈';
    return `${phaseLabel(currentCourtSession.court_state.phase)} · ${currentCourtSession.user_side}`;
  }, [showSetup, currentCourtSession]);

  const handleCreate = (input: Parameters<typeof createCourtSession>[0]) => {
    createCourtSession(input);
    setShowSetup(false);
  };

  const handleSelect = (sessionId: string) => {
    setCurrentCourtId(sessionId);
    setShowSetup(false);
    setIsSidebarOpen(false);
  };

  const handleOpenNew = () => {
    setShowSetup(true);
    setIsSidebarOpen(false);
  };

  const handleForceAdvance = () => {
    forceAdvance();
    runNextTurn();
  };

  const handleRewindAtEvent = (eventId: string) => {
    if (!currentCourtId) return;
    rewindToEvent(currentCourtId, eventId);
  };

  const handleBranchAtEvent = (eventId: string) => {
    if (!currentCourtId) return;
    branchFromEvent(currentCourtId, eventId);
  };

  const openFilePicker = () => fileInputRef.current?.click();

  // 庭审发言同样要把上传材料的工作区路径告诉各角色，否则材料对模型不可见：
  // 法庭请求只带公开事件文本，模型没有别的途径知道工作区里有什么文件。
  const handleSendWithMaterials = React.useCallback(() => {
    const uploads = workspace.pendingUploads;
    const attachmentPrompt = buildAttachmentPrompt(uploads);
    const speech = composerText.trim();
    if (!speech && !attachmentPrompt) return;

    const content = [speech, attachmentPrompt].filter(Boolean).join('\n\n');
    sendUserSpeech(content);
    if (uploads.length > 0) {
      workspace.setPendingUploads([]);
    }
  }, [composerText, sendUserSpeech, workspace]);

  const handleUploadFiles = async (files: FileList | null) => {
    try {
      const selectedFiles = Array.from(files || []);
      if (selectedFiles.length === 0 || !currentCourtId) return;

      const results = await Promise.allSettled(
        selectedFiles.map(file => workspace.handleFileUpload(file))
      );
      const rejected = results.flatMap((result, index) => {
        if (result.status === 'fulfilled') return [];
        const reason = result.reason instanceof Error
          ? result.reason.message
          : String(result.reason || '未知错误');
        return [`${selectedFiles[index]?.name || '未命名文件'}：${reason}`];
      });

      if (rejected.length > 0) {
        await showAlert({
          title: rejected.length === selectedFiles.length ? '文件上传未完成' : '部分文件上传未完成',
          message: `已处理 ${selectedFiles.length - rejected.length} 个，未完成 ${rejected.length} 个。\n${rejected.join('\n')}`,
          tone: 'danger',
        });
      }
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  if (!isInitialized) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--bg-app)] text-[var(--accent)]">
        <div className="h-12 w-12 animate-spin rounded-full border-2 border-[var(--accent-quiet)] border-t-[var(--accent)]" />
      </div>
    );
  }

  const session = currentCourtSession;
  const showTrial = !showSetup && Boolean(session);

  return (
    <div className="lawver-chat-shell flex overflow-hidden bg-[var(--bg-app)] font-sans text-[var(--fg-1)] transition-colors duration-300">
      <CourtSidebar
        isOpen={isSidebarOpen}
        setIsOpen={setIsSidebarOpen}
        sessions={courtSessions}
        currentId={currentCourtId}
        onSelect={handleSelect}
        onCreate={handleOpenNew}
        onBack={onBack}
        onDelete={deleteCourtSession}
        isDesktopLayout={isDesktopLayout}
      />

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {secureAccessBanner}

        <header className="lawver-topbar sticky top-0 z-30 flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-app)] px-2.5 pb-2 pt-[calc(0.625rem+var(--safe-top))] sm:px-4 sm:pb-3 sm:pt-[calc(0.75rem+var(--safe-top))]">
          <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2">
            <button
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
              aria-label="庭审列表"
            >
              <Menu size={20} strokeWidth={2} className="sm:size-[22px]" />
            </button>
            <BrandMark className="hidden h-8 w-8 shrink-0 text-[var(--accent)] sm:block" />
            <div className="min-w-0 flex-1">
              <h1 className="lawver-header-title t-title-l truncate">
                {showSetup || !session ? '新建庭审' : session.title || '模拟法庭'}
              </h1>
              <div className="truncate text-[12px] text-[var(--fg-3)]">{subtitle}</div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-0.5 sm:gap-1">
            {showTrial && (
              <HoverInfo label="案件面板" placement="bottom">
                <button
                  onClick={() => setIsCasePanelOpen(!isCasePanelOpen)}
                  className={`lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors ${
                    isCasePanelOpen
                      ? 'bg-[var(--accent-quiet)] text-[var(--accent)]'
                      : 'text-[var(--fg-3)] hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]'
                  }`}
                  aria-label="案件面板"
                >
                  <div className="relative">
                    <Briefcase size={18} strokeWidth={2} className="sm:size-5" />
                    {workspace.workspaceFiles.length > 0 && (
                      <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-[var(--bg-app)] bg-[var(--accent)]" />
                    )}
                  </div>
                </button>
              </HoverInfo>
            )}
            <HoverInfo label="设置" placement="bottom">
              <button
                onClick={onSettingsClick}
                className="lawver-pressable inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06]"
                aria-label="设置"
              >
                <Settings size={18} strokeWidth={2} className="sm:size-5" />
              </button>
            </HoverInfo>
          </div>
        </header>

        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-[var(--bg-app)]">
            {!showTrial || !session ? (
              <CourtSetup
                onCreate={handleCreate}
                onCancel={courtSessions.length > 0 ? () => setShowSetup(false) : undefined}
              />
            ) : (
              <>
                <CourtTranscript
                  session={session}
                  isRunning={isRunning}
                  status={status}
                  onStart={runNextTurn}
                  onRewind={handleRewindAtEvent}
                  onBranch={handleBranchAtEvent}
                />
                <CourtComposerDock
                  session={session}
                  isRunning={isRunning}
                  status={status}
                  value={composerText}
                  onChange={setComposerText}
                  onSend={handleSendWithMaterials}
                  onRunNext={runNextTurn}
                  onForceAdvance={handleForceAdvance}
                  onSetAutoMode={setAutoMode}
                  onSetUserAgentMode={setUserAgentMode}
                  onRequestUpload={openFilePicker}
                  pendingMaterials={workspace.pendingUploads}
                  onRemoveMaterial={workspace.removeUploadedFile}
                  isUploadingFiles={workspace.isUploadingFiles}
                />
              </>
            )}
          </div>

          {showTrial && session && (
            <CourtCasePanel
              isOpen={isCasePanelOpen}
              setIsOpen={setIsCasePanelOpen}
              session={session}
              files={workspace.workspaceFiles}
              onRequestUpload={openFilePicker}
              onDeleteFile={workspace.deleteFile}
              isDesktopLayout={isDesktopLayout}
            />
          )}
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.doc,.docx,.txt,.md,image/png,image/jpeg,image/webp,image/gif,image/bmp"
        className="hidden"
        onChange={event => handleUploadFiles(event.target.files)}
      />
    </div>
  );
};
