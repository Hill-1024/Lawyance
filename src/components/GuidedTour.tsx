/*
 * 模块描述：首次使用与帮助页复用的功能指引弹窗，展示 Lawver 主要按钮和工作流。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Bot,
  Check,
  CirclePlay,
  Cloud,
  Folder,
  Gavel,
  Info,
  Menu,
  MessageSquareText,
  Palette,
  PanelLeftOpen,
  Paperclip,
  Plus,
  RotateCcw,
  Send,
  Settings,
  Settings2,
  Sparkles,
  X,
} from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { BrandMark } from './Brand';
import { getGuidedTourSeen, setGuidedTourSeen, subscribeGuidedTourRequest } from '../lib/guided-tour';

type TourTarget = 'sidebar' | 'new-chat' | 'court' | 'workspace' | 'settings' | 'composer' | 'upload' | 'send' | 'assistant';
type TourIcon = React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;

interface TourFeature {
  icon: TourIcon;
  label: string;
  detail: string;
}

interface TourStep {
  id: string;
  title: string;
  summary: string;
  icon: TourIcon;
  targets: TourTarget[];
  features: TourFeature[];
}

const TOUR_EASE = [0.16, 1, 0.3, 1] as const;

const TOUR_STEPS: TourStep[] = [
  {
    id: 'welcome',
    title: '先认识 Lawver 的工作台',
    summary: '主屏围绕一次法律工作流展开：左侧管理会话，中间阅读与追问，底部输入问题或上传材料。',
    icon: Sparkles,
    targets: ['assistant', 'composer'],
    features: [
      { icon: MessageSquareText, label: '对话区', detail: '阅读回复、继续追问，也可以对单条回复重新生成、编辑或分叉。' },
      { icon: Bot, label: '法律助手', detail: '适合做法条检索、案情梳理、文书草拟和策略推演。' },
    ],
  },
  {
    id: 'sidebar',
    title: '用侧栏管理案件与会话',
    summary: '左上角菜单展开侧栏；新会话、历史记录、模拟法庭和退出登录都在这里。',
    icon: PanelLeftOpen,
    targets: ['sidebar', 'new-chat', 'court'],
    features: [
      { icon: Menu, label: '菜单', detail: '打开或收起会话侧栏，手机端会以抽屉形式出现。' },
      { icon: Plus, label: 'New Chat', detail: '为新的案件、客户或研究主题建立独立上下文。' },
      { icon: Gavel, label: '模拟法庭', detail: '进入庭审推演流程，把公开案卷与私有作战笔记分开整理。' },
    ],
  },
  {
    id: 'composer',
    title: '底部输入区是主要操作台',
    summary: '写问题、传材料、查看上下文用量、发送或停止生成，都集中在底部的圆角输入栏。',
    icon: Send,
    targets: ['composer', 'upload', 'send'],
    features: [
      { icon: Settings2, label: '输入区设置', detail: '切换流式输出、OCP 检查流程和 Agent Mode。' },
      { icon: Paperclip, label: '上传文件', detail: '上传 PDF、Word、Markdown 或文本材料，让 Lawver 带着证据工作。' },
      { icon: Send, label: '发送/停止', detail: '有内容时发送；生成中会变成停止按钮，方便中断长回答。' },
    ],
  },
  {
    id: 'workspace',
    title: '工作区保存生成文件与材料',
    summary: '右上角文件夹打开工作区。上传材料、生成文书和下载文件都能在这里集中管理。',
    icon: Folder,
    targets: ['workspace'],
    features: [
      { icon: Folder, label: 'Workspace', detail: '查看当前会话关联文件，删除不需要的材料。' },
      { icon: Cloud, label: '同步', detail: '有 WebDAV 配置时，可以把本机数据备份到自己的云。' },
    ],
  },
  {
    id: 'settings',
    title: '设置页里管理偏好与帮助',
    summary: '设置按钮进入外观、动态色、断线续传、WebDAV 同步和帮助页面；这里也能随时重播本指引。',
    icon: Settings,
    targets: ['settings'],
    features: [
      { icon: Palette, label: '外观与配色', detail: '切换浅色、深色、系统模式，以及 Lawver 主题种子色。' },
      { icon: RotateCcw, label: '断线续传', detail: '回答中断时可以临时保留服务器缓存，便于继续接收。' },
      { icon: BookOpen, label: '帮助与指引', detail: '在设置的帮助二级页，可再次打开这份动态手册。' },
    ],
  },
];

const isTargetActive = (step: TourStep, target: TourTarget) => step.targets.includes(target);

const getTargetClass = (step: TourStep, target: TourTarget, activeClass = '') => {
  if (!isTargetActive(step, target)) {
    return 'border-transparent bg-[var(--bg-surface)] text-[var(--fg-3)]';
  }
  return `border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--accent)] shadow-[0_0_0_1px_var(--accent)] ${activeClass}`;
};

const FeatureRow: React.FC<{ feature: TourFeature; index: number; reduceMotion: boolean }> = ({ feature, index, reduceMotion }) => {
  const Icon = feature.icon;
  return (
    <motion.li
      className="flex min-w-0 gap-3 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3"
      initial={reduceMotion ? false : { opacity: 0, y: 12, filter: 'blur(4px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{ duration: 0.4, delay: reduceMotion ? 0 : index * 0.08, ease: TOUR_EASE }}
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] text-[var(--accent)]">
        <Icon size={17} strokeWidth={2} />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold leading-5 text-[var(--fg-1)]">{feature.label}</span>
        <span className="mt-0.5 block text-[12px] leading-5 text-[var(--fg-3)]">{feature.detail}</span>
      </span>
    </motion.li>
  );
};

const MiniIconButton: React.FC<{
  icon: TourIcon;
  label: string;
  active: boolean;
  compact?: boolean;
}> = ({ icon: Icon, label, active, compact = false }) => (
  <span
    className={`inline-flex shrink-0 items-center justify-center rounded-full border transition-colors ${
      compact ? 'h-7 w-7' : 'h-8 w-8'
    } ${active ? 'border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--accent)]' : 'border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--fg-4)]'}`}
    aria-label={label}
  >
    <Icon size={compact ? 14 : 15} strokeWidth={2} />
  </span>
);

const MiniAppPreview: React.FC<{ step: TourStep; reduceMotion: boolean }> = ({ step, reduceMotion }) => {
  const StepIcon = step.icon;
  return (
  <div className="relative min-h-[260px] overflow-hidden rounded-[var(--radius-xl)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-3 shadow-[var(--shadow-2)] sm:min-h-[310px] sm:p-4">
    <div className="flex items-center justify-between gap-2 border-b border-[var(--border-subtle)] pb-3">
      <div className="flex min-w-0 items-center gap-2">
        <MiniIconButton icon={Menu} label="菜单" active={isTargetActive(step, 'sidebar')} />
        <BrandMark className="hidden h-7 w-7 shrink-0 text-[var(--accent)] sm:block" />
        <span className="h-3 w-28 rounded-full bg-[var(--bg-inset)] sm:w-36" />
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <MiniIconButton icon={Folder} label="工作区" active={isTargetActive(step, 'workspace')} />
        <MiniIconButton icon={Settings} label="设置" active={isTargetActive(step, 'settings')} />
      </div>
    </div>

    <div className="grid min-h-[160px] grid-cols-[78px_1fr] gap-3 py-3 sm:grid-cols-[104px_1fr]">
      <div className={`hidden min-w-0 flex-col gap-2 rounded-[var(--radius-lg)] border p-2 sm:flex ${getTargetClass(step, 'sidebar')}`}>
        <span className={`flex h-8 items-center justify-center gap-1.5 rounded-full border px-2 text-[11px] font-semibold ${getTargetClass(step, 'new-chat')}`}>
          <Plus size={13} strokeWidth={2} />
          New Chat
        </span>
        <span className={`flex h-8 items-center justify-center gap-1.5 rounded-full border px-2 text-[11px] font-semibold ${getTargetClass(step, 'court')}`}>
          <Gavel size={13} strokeWidth={2} />
          模拟法庭
        </span>
        <span className="mt-1 h-2 rounded-full bg-current opacity-20" />
        <span className="h-2 w-10/12 rounded-full bg-current opacity-15" />
        <span className="h-2 w-8/12 rounded-full bg-current opacity-15" />
      </div>

      <div className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-3">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step.id}
            className="flex min-h-[136px] flex-col justify-between gap-3"
            initial={reduceMotion ? false : { opacity: 0, x: 16, filter: 'blur(4px)' }}
            animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -16, filter: 'blur(4px)' }}
            transition={{ duration: 0.35, ease: TOUR_EASE }}
          >
            <div className={`rounded-[var(--radius-md)] border p-3 ${getTargetClass(step, 'assistant')}`}>
              <div className="mb-2 flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                  <StepIcon size={16} strokeWidth={2} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block h-2.5 w-8/12 rounded-full bg-current opacity-25" />
                  <span className="mt-2 block h-2 w-5/12 rounded-full bg-current opacity-15" />
                </span>
              </div>
              <div className="space-y-1.5">
                <span className="block h-2 rounded-full bg-current opacity-15" />
                <span className="block h-2 w-10/12 rounded-full bg-current opacity-10" />
              </div>
            </div>

            <div className={`rounded-full border p-1.5 ${getTargetClass(step, 'composer')}`}>
              <div className="flex items-center gap-1.5">
                <MiniIconButton icon={Settings2} label="输入区设置" active={isTargetActive(step, 'composer')} compact />
                <MiniIconButton icon={Paperclip} label="上传文件" active={isTargetActive(step, 'upload')} compact />
                <span className="h-2 min-w-0 flex-1 rounded-full bg-current opacity-15" />
                <MiniIconButton icon={Send} label="发送" active={isTargetActive(step, 'send')} compact />
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>

    <motion.div
      className="pointer-events-none absolute bottom-5 right-6 hidden rounded-full border border-[var(--accent)] bg-[var(--bg-surface)] px-3 py-1.5 text-[11px] font-semibold text-[var(--accent)] shadow-[var(--shadow-3)] sm:block"
      animate={reduceMotion ? { opacity: 1 } : { opacity: [0.86, 1, 0.86], y: [0, -4, 0] }}
      transition={reduceMotion ? { duration: 0.01 } : { duration: 2.4, repeat: Infinity, ease: TOUR_EASE }}
    >
      {step.title}
    </motion.div>
  </div>
  );
};

export const GuidedTour: React.FC = () => {
  const reduceMotion = Boolean(useReducedMotion());
  const [isOpen, setIsOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const didCheckFirstRunRef = useRef(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const currentStep = TOUR_STEPS[stepIndex] || TOUR_STEPS[0];
  const isFirstStep = stepIndex === 0;
  const isLastStep = stepIndex === TOUR_STEPS.length - 1;

  const openTour = useCallback(() => {
    setStepIndex(0);
    setIsOpen(true);
  }, []);

  const closeTour = useCallback(() => {
    setIsOpen(false);
    setStepIndex(0);
    setGuidedTourSeen(true).catch(() => undefined);
  }, []);

  const goNext = useCallback(() => {
    if (isLastStep) {
      closeTour();
      return;
    }
    setStepIndex(index => Math.min(index + 1, TOUR_STEPS.length - 1));
  }, [closeTour, isLastStep]);

  const goBack = useCallback(() => {
    setStepIndex(index => Math.max(index - 1, 0));
  }, []);

  useEffect(() => subscribeGuidedTourRequest(openTour), [openTour]);

  useEffect(() => {
    if (didCheckFirstRunRef.current) return;
    didCheckFirstRunRef.current = true;
    let cancelled = false;
    getGuidedTourSeen()
      .then(seen => {
        if (!cancelled && !seen) openTour();
      })
      .catch(() => {
        if (!cancelled) openTour();
      });
    return () => {
      cancelled = true;
    };
  }, [openTour]);

  useEffect(() => {
    if (!isOpen) return;
    dialogRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeTour();
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        goNext();
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        goBack();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [closeTour, goBack, goNext, isOpen]);

  const StepIcon = currentStep.icon;
  const stepCountLabel = useMemo(() => `${stepIndex + 1} / ${TOUR_STEPS.length}`, [stepIndex]);

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[1180] flex min-h-[100dvh] items-center justify-center p-3 sm:p-5">
          <motion.div
            className="absolute inset-0 bg-[var(--bg-overlay)] backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0.01 : 0.18, ease: TOUR_EASE }}
            aria-hidden="true"
          />
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="lawver-guided-tour-title"
            tabIndex={-1}
            className="relative max-h-[calc(100dvh-1.5rem)] w-full max-w-[min(100%,62rem)] overflow-hidden rounded-[28px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--fg-1)] shadow-[var(--shadow-5)] outline-none sm:max-h-[calc(100dvh-2.5rem)] sm:rounded-[32px]"
            initial={reduceMotion ? false : { opacity: 0, y: 32, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.96 }}
            transition={reduceMotion ? { duration: 0.01 } : { type: 'spring', damping: 26, stiffness: 300, mass: 0.8 }}
          >
            <div className="custom-scrollbar grid max-h-[calc(100dvh-1.5rem)] min-h-0 overflow-y-auto lg:min-h-[min(560px,100dvh-2.5rem)] lg:grid-cols-[minmax(0,1.05fr)_minmax(24rem,0.95fr)]">
              <section className="min-w-0 bg-[var(--bg-surface-2)] p-4 sm:p-5 lg:p-6 lg:pt-7">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                      <BrandMark className="h-6 w-6 [--brand-logo-ink:var(--accent)]" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-semibold text-[var(--fg-2)]">Lawver 快速指引</span>
                      <span className="block text-[12px] text-[var(--fg-4)]">{stepCountLabel}</span>
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={closeTour}
                    className="lawver-pressable inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06] lg:hidden"
                    aria-label="关闭指引"
                  >
                    <X size={18} strokeWidth={2} />
                  </button>
                </div>
                <MiniAppPreview step={currentStep} reduceMotion={reduceMotion} />
              </section>

              <section className="flex min-w-0 flex-col p-4 sm:p-6 lg:p-7 lg:pt-6">
                <div className="hidden lg:flex justify-end mb-2 -mt-2 -mr-2">
                  <button
                    type="button"
                    onClick={closeTour}
                    className="lawver-pressable inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--fg-1)]"
                    aria-label="关闭指引"
                  >
                    <X size={18} strokeWidth={2} />
                  </button>
                </div>
                
                <div className="min-h-[340px] sm:min-h-[360px] flex flex-col">
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.div
                      key={currentStep.id}
                      className="min-w-0"
                      initial={reduceMotion ? false : { opacity: 0, x: 20, filter: 'blur(4px)' }}
                      animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
                      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -20, filter: 'blur(4px)' }}
                      transition={{ duration: 0.35, ease: TOUR_EASE }}
                    >
                      <div className="mb-4 flex items-start gap-3">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                        <StepIcon size={21} strokeWidth={2} />
                      </span>
                      <div className="min-w-0">
                        <h2 id="lawver-guided-tour-title" className="text-[24px] font-semibold leading-8 text-[var(--fg-1)] sm:text-[28px] sm:leading-9">
                          {currentStep.title}
                        </h2>
                        <p className="mt-2 text-[14px] leading-6 text-[var(--fg-3)] sm:text-[15px]">
                          {currentStep.summary}
                        </p>
                      </div>
                    </div>

                    <ul className="flex flex-col gap-2.5">
                      {currentStep.features.map((feature, index) => (
                        <FeatureRow key={feature.label} feature={feature} index={index} reduceMotion={reduceMotion} />
                      ))}
                    </ul>
                  </motion.div>
                </AnimatePresence>
                </div>

                <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border-subtle)] pt-4">
                  <div className="flex items-center gap-1.5" aria-label={stepCountLabel}>
                    {TOUR_STEPS.map((step, index) => (
                      <button
                        key={step.id}
                        type="button"
                        onClick={() => setStepIndex(index)}
                        className={`lawver-pressable h-2.5 rounded-full transition-all ${
                          index === stepIndex ? 'w-7 bg-[var(--accent)]' : 'w-2.5 bg-[var(--bg-inset)] hover:bg-[var(--border-strong)]'
                        }`}
                        aria-label={`查看第 ${index + 1} 步`}
                      />
                    ))}
                  </div>

                  <div className="flex min-w-0 flex-1 justify-end gap-2">
                    <button
                      type="button"
                      onClick={closeTour}
                      className="md3-btn-text min-h-10 whitespace-nowrap px-4 py-2.5 !text-[13px] sm:!text-sm"
                    >
                      跳过
                    </button>
                    <button
                      type="button"
                      onClick={goBack}
                      disabled={isFirstStep}
                      className="md3-btn-tonal min-h-10 whitespace-nowrap px-4 py-2.5 !text-[13px] sm:!text-sm"
                    >
                      <ArrowLeft size={16} strokeWidth={2} />
                      上一步
                    </button>
                    <button
                      type="button"
                      onClick={goNext}
                      className="md3-btn-filled min-h-10 whitespace-nowrap px-4 py-2.5 !text-[13px] sm:!text-sm"
                    >
                      {isLastStep ? (
                        <>
                          <Check size={16} strokeWidth={2} />
                          完成
                        </>
                      ) : (
                        <>
                          下一步
                          <ArrowRight size={16} strokeWidth={2} />
                        </>
                      )}
                    </button>
                  </div>
                </div>

                <div className="mt-3 flex items-start gap-2 rounded-[var(--radius-md)] bg-[var(--accent-quiet)] px-3 py-2 text-[12px] leading-5 text-[var(--brand-primary-700)] dark:text-[var(--accent)]">
                  <Info size={15} strokeWidth={2} className="mt-0.5 shrink-0" />
                  <span>之后可从「设置」进入「帮助与指引」再次打开本手册。</span>
                </div>
              </section>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
