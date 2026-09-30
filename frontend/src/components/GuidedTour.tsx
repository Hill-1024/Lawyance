/*
 * 模块描述：首次启动指引（聚光灯式教练层）。遮罩挖出真实控件的形状并把说明卡停在它旁边，
 * 而不是在一个仿制的小界面里比划——用户看到的就是待会儿要点的那个按钮。
 * 同时被「设置 → 帮助与指引」复用来重播。
 */

import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  Cloud,
  Folder,
  MessageSquareText,
  Paperclip,
  Plus,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { getGuidedTourSeen, setGuidedTourSeen, subscribeGuidedTourRequest } from '../lib/guided-tour';
import { useT, type Translator } from '../i18n';

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
  /** 对应真实控件上的 data-tour 值；留空表示居中展示、不打光。 */
  target?: string;
  /** 首选目标不可见时退而求其次的锚点（例如抽屉没展开时指向打开抽屉的按钮）。 */
  fallbackTarget?: string;
  features: TourFeature[];
}

const TOUR_EASE = [0.16, 1, 0.3, 1] as const;
const CARD_WIDTH = 400;
const CARD_GAP = 16;
const EDGE_MARGIN = 12;
/** 目标本身有 280ms 的开合动画，量一次不够；在这个窗口里跟着追，稳定后自然停下。 */
const SETTLE_MS = 520;

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

type Side = 'top' | 'bottom' | 'left' | 'right';

interface Placement {
  side: Side;
  /** 卡片左上角坐标。 */
  x: number;
  y: number;
  /** 箭头沿卡片边缘的偏移。 */
  arrow: number;
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), Math.max(min, max));

/** 目标是否真的能被看见：0 尺寸（收起的面板）或整个跑出视口都算看不见。 */
const measureOne = (name: string): Rect | null => {
  const element = document.querySelector<HTMLElement>(`[data-tour="${name}"]`);
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) return null;
  if (rect.bottom <= 0 || rect.top >= window.innerHeight || rect.right <= 0 || rect.left >= window.innerWidth) return null;
  return { top: rect.top, left: rect.left, width: rect.width, height: rect.height };
};

const measureTarget = (step?: TourStep): Rect | null => {
  if (!step || typeof document === 'undefined') return null;
  return measureOne(step.target || '') || (step.fallbackTarget ? measureOne(step.fallbackTarget) : null);
};

/** 把卡片放在目标四周空间最大的一侧，再整体压回视口内，箭头指向目标中心。 */
const placeCard = (spot: Rect | null, cardWidth: number, cardHeight: number): Placement => {
  const vw = window.visualViewport?.width ?? window.innerWidth;
  const vh = window.visualViewport?.height ?? window.innerHeight;
  const clampY = (value: number) => clamp(value, EDGE_MARGIN, vh - cardHeight - EDGE_MARGIN);
  const clampX = (value: number) => clamp(value, EDGE_MARGIN, vw - cardWidth - EDGE_MARGIN);
  // 没有目标（欢迎页，或目标此刻不可见）：居中，只留遮罩不带箭头。
  if (!spot) {
    return { side: 'bottom', x: clampX((vw - cardWidth) / 2), y: clampY((vh - cardHeight) / 2), arrow: cardWidth / 2 };
  }
  const space: Record<Side, number> = {
    bottom: vh - (spot.top + spot.height),
    top: spot.top,
    right: vw - (spot.left + spot.width),
    left: spot.left,
  };
  const fits = (side: Side) => side === 'top' || side === 'bottom'
    ? space[side] >= cardHeight + CARD_GAP + EDGE_MARGIN
    : space[side] >= cardWidth + CARD_GAP + EDGE_MARGIN;
  // 竖向优先：中文卡片偏方，上下摆放不会把正文挤成窄条。
  const order: Side[] = ['bottom', 'top', 'right', 'left'];
  const side = order.find(fits) ?? (Object.entries(space).sort((a, b) => b[1] - a[1])[0][0] as Side);

  const centerX = spot.left + spot.width / 2;
  const centerY = spot.top + spot.height / 2;
  let x: number;
  let y: number;
  if (side === 'bottom' || side === 'top') {
    x = centerX - cardWidth / 2;
    y = side === 'bottom'
      ? spot.top + spot.height + CARD_GAP
      : spot.top - CARD_GAP - cardHeight;
  } else {
    x = side === 'right' ? spot.left + spot.width + CARD_GAP : spot.left - CARD_GAP - cardWidth;
    y = centerY - cardHeight / 2;
  }
  y = clampY(y);
  x = clampX(x);

  const arrow = side === 'bottom' || side === 'top'
    ? clamp(centerX - x, 28, cardWidth - 28)
    : clamp(centerY - y, 28, cardHeight - 28);
  return { side, x, y, arrow };
};

const FeatureRow: React.FC<{ feature: TourFeature; index: number; reduceMotion: boolean }> = ({ feature, index, reduceMotion }) => {
  const Icon = feature.icon;
  return (
    <motion.li
      className="flex min-w-0 items-start gap-2.5 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-2.5"
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.34, delay: reduceMotion ? 0 : 0.08 + index * 0.05, ease: TOUR_EASE }}
    >
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--accent-quiet)] text-[var(--accent)]">
        <Icon size={15} strokeWidth={2} />
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold leading-5 text-[var(--fg-1)]">{feature.label}</span>
        <span className="mt-0.5 block text-[12px] leading-[1.6] text-[var(--fg-3)]">{feature.detail}</span>
      </span>
    </motion.li>
  );
};

/*
 * 工作台的入口和旧版聊天不一样，锚点也就不能用同一套：以 /home 上一定存在的三个控件为准。
 * 侧栏在窄屏是抽屉，主目标量不到时退回「打开导航」按钮，卡片会指着用户真正该按的那个键。
 */
const workbenchSteps = (t: Translator): TourStep[] => [
  {
    id: 'welcome',
    title: t('tour.welcomeTitle'),
    summary: t('tour.welcomeSummary'),
    icon: Sparkles,
    features: [
      { icon: Folder, label: t('tour.welcomeFeature1'), detail: t('tour.welcomeFeature1Detail') },
      { icon: BookOpen, label: t('tour.welcomeFeature2'), detail: t('tour.welcomeFeature2Detail') },
    ],
  },
  {
    id: 'space',
    title: t('tour.sidebarTitle'),
    summary: t('tour.sidebarSummary'),
    icon: MessageSquareText,
    target: 'wb-sidebar',
    fallbackTarget: 'wb-nav-toggle',
    features: [
      { icon: Folder, label: t('tour.sidebarFeature1'), detail: t('tour.sidebarFeature1Detail') },
      { icon: Cloud, label: t('tour.sidebarFeature2'), detail: t('tour.sidebarFeature2Detail') },
    ],
  },
  {
    id: 'tabs',
    title: t('tour.tabsTitle'),
    summary: t('tour.tabsSummary'),
    icon: MessageSquareText,
    target: 'wb-tabstrip',
    fallbackTarget: 'wb-nav-toggle',
    features: [
      { icon: Plus, label: t('tour.tabsFeature1'), detail: t('tour.tabsFeature1Detail') },
      { icon: MessageSquareText, label: t('tour.tabsFeature2'), detail: t('tour.tabsFeature2Detail') },
      { icon: BookOpen, label: t('tour.tabsFeature3'), detail: t('tour.tabsFeature3Detail') },
    ],
  },
  {
    id: 'composer',
    title: t('tour.composerTitle'),
    summary: t('tour.composerSummary'),
    icon: Send,
    target: 'wb-composer',
    features: [
      { icon: Paperclip, label: t('tour.composerFeature1'), detail: t('tour.composerFeature1Detail') },
      { icon: MessageSquareText, label: t('tour.composerFeature2'), detail: t('tour.composerFeature2Detail') },
      { icon: Sparkles, label: t('tour.composerFeature3'), detail: t('tour.composerFeature3Detail') },
    ],
  },
  {
    id: 'project',
    title: t('tour.projectTitle'),
    summary: t('tour.projectSummary'),
    icon: Plus,
    target: 'wb-new-project',
    features: [
      { icon: Plus, label: t('tour.projectFeature1'), detail: t('tour.projectFeature1Detail') },
      { icon: Folder, label: t('tour.projectFeature2'), detail: t('tour.projectFeature2Detail') },
    ],
  },
];

export const GuidedTour: React.FC = () => {
  const { t } = useT();
  const steps = workbenchSteps(t);
  const reduceMotion = Boolean(useReducedMotion());
  const [isOpen, setIsOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [direction, setDirection] = useState(1);
  const [spot, setSpot] = useState<Rect | null>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const interactionVersionRef = useRef(0);
  const keyboardActionsRef = useRef<{ close: () => void; next: () => void; back: () => void }>({
    close: () => undefined,
    next: () => undefined,
    back: () => undefined,
  });

  const currentStep = steps[stepIndex] || steps[0];
  const isFirstStep = stepIndex === 0;
  const isLastStep = stepIndex === steps.length - 1;
  const StepIcon = currentStep.icon;

  const closeTour = useCallback(() => {
    interactionVersionRef.current += 1;
    setIsOpen(false);
    setStepIndex(0);
    setSpot(null);
    setPlacement(null);
    setGuidedTourSeen(true).catch(() => undefined);
  }, []);

  const goNext = useCallback(() => {
    if (isLastStep) {
      closeTour();
      return;
    }
    setDirection(1);
    setStepIndex(index => Math.min(index + 1, steps.length - 1));
  }, [closeTour, isLastStep]);

  const goBack = useCallback(() => {
    setDirection(-1);
    setStepIndex(index => Math.max(index - 1, 0));
  }, []);

  const openTour = useCallback(() => {
    setDirection(1);
    setStepIndex(0);
    setIsOpen(true);
  }, []);

  const openRequestedTour = useCallback(() => {
    interactionVersionRef.current += 1;
    openTour();
  }, [openTour]);

  useEffect(() => subscribeGuidedTourRequest(openRequestedTour), [openRequestedTour]);

  // 只在真的没看过时自动弹出；用户在此期间自己打开过指引就不要再抢一次。
  useEffect(() => {
    let cancelled = false;
    const interactionVersion = interactionVersionRef.current;
    const open = () => {
      if (!cancelled && interactionVersionRef.current === interactionVersion) openTour();
    };
    getGuidedTourSeen().then(seen => { if (!seen) open(); }).catch(open);
    return () => { cancelled = true; };
  }, [openTour]);

  useEffect(() => {
    keyboardActionsRef.current = { close: closeTour, next: goNext, back: goBack };
  }, [closeTour, goBack, goNext]);

  /*
   * 定位：每步进入后在一个有限的 settle 窗口内逐帧测量，直到矩形连续两帧不变。
   * 目标可能是正在做开合动画的面板，只量一次会把光打在半路上。
   * 窗口是有限的（SETTLE_MS），不会留下常驻的 rAF 循环。
   */
  useLayoutEffect(() => {
    if (!isOpen) return;
    let frame = 0;
    const started = performance.now();
    let lastKey = '';

    const tick = () => {
      const rect = measureTarget(steps[stepIndex]);
      const card = cardRef.current;
      const cardWidth = card?.offsetWidth || CARD_WIDTH;
      const cardHeight = card?.offsetHeight || 260;
      const key = rect ? `${rect.top}|${rect.left}|${rect.width}|${rect.height}|${cardWidth}|${cardHeight}` : `none|${cardWidth}|${cardHeight}`;
      if (key !== lastKey) {
        lastKey = key;
        setSpot(rect);
        setPlacement(placeCard(rect, cardWidth, cardHeight));
      }
      if (performance.now() - started < SETTLE_MS) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    const remeasure = () => {
      const rect = measureTarget(steps[stepIndex]);
      const card = cardRef.current;
      setSpot(rect);
      setPlacement(placeCard(rect, card?.offsetWidth || CARD_WIDTH, card?.offsetHeight || 260));
      lastKey = '';
    };
    window.addEventListener('resize', remeasure);
    window.addEventListener('orientationchange', remeasure);
    const viewport = window.visualViewport;
    viewport?.addEventListener('resize', remeasure);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', remeasure);
      window.removeEventListener('orientationchange', remeasure);
      viewport?.removeEventListener('resize', remeasure);
    };
  }, [isOpen, stepIndex, steps]);

  useEffect(() => {
    if (!isOpen) return;
    cardRef.current?.focus();
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
        keyboardActionsRef.current.close();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        keyboardActionsRef.current.next();
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        keyboardActionsRef.current.back();
      } else if (event.key === 'Tab') {
        // role=dialog + aria-modal 承诺焦点留在卡片内；卡片之外只有一层挡板，没有可停的地方。
        const card = cardRef.current;
        if (!card) return;
        const focusable = Array.from(card.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), [tabindex]:not([tabindex="-1"])'
        )).filter(element => element.offsetParent !== null);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (event.shiftKey && (active === first || !card.contains(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (active === last || !card.contains(active))) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const spotStyle = useMemo(() => (spot ? {
    top: spot.top,
    left: spot.left,
    width: spot.width,
    height: spot.height,
  } : null), [spot]);

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="pointer-events-none fixed inset-0 z-[var(--z-tour)]" role="presentation">
          {/*
           * 透明挡板：box-shadow 铺出来的暗区不参与命中测试，光孔本身又是透明的，
           * 所以必须有一层覆盖全屏的实体来接住点击，否则指引期间还能点到背后的应用。
           */}
          <div className="pointer-events-auto absolute inset-0" aria-hidden="true" />

          {/* 无目标时的纯遮罩（欢迎页，或目标此刻不可见）。 */}
          <AnimatePresence>
            {!spotStyle && (
              <motion.div
                key="tour-dim"
                className="pointer-events-none absolute inset-0 bg-[var(--tour-dim)]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: reduceMotion ? 0.01 : 0.24, ease: TOUR_EASE }}
                aria-hidden="true"
              />
            )}
          </AnimatePresence>

          {/*
           * 遮罩与光孔是同一个元素：一块透明矩形用 9999px 的 box-shadow 铺满全屏，中间留出的
           * 就是真实控件。它没有后代、且是 fixed，所以逐帧改几何只影响它自己，不会重排页面——
           * 换成四块遮罩拼边反而要同时动四个盒子的几何。
           */}
          <motion.div
            className="pointer-events-none rounded-[18px]"
            aria-hidden="true"
            initial={false}
            animate={spotStyle
              ? { opacity: 1, ...spotStyle }
              : { opacity: 0, top: (window.innerHeight / 2) - 1, left: (window.innerWidth / 2) - 1, width: 2, height: 2 }}
            exit={{ opacity: 0 }}
            transition={reduceMotion
              ? { duration: 0.12 }
              : { type: 'spring', damping: 28, stiffness: 280, mass: 0.8 }}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: 0,
              height: 0,
              boxShadow: '0 0 0 9999px var(--tour-dim), 0 0 0 1.5px var(--accent), 0 0 0 6px rgba(138,164,221,0.18)',
            }}
          />

          <motion.div
            ref={cardRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="lawver-tour-title"
            tabIndex={-1}
            className="pointer-events-auto fixed left-0 top-0 max-h-[calc(100dvh-24px)] w-[min(400px,calc(100vw-24px))] overflow-hidden rounded-[24px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--fg-1)] shadow-[var(--shadow-5)] outline-none"
            // 首帧还没量到位置，先隐藏，避免卡片从 (0,0) 跳一下。
            initial={reduceMotion
              ? { opacity: 0 }
              : { opacity: 0, scale: 0.96, x: placement?.x ?? 0, y: placement?.y ?? 0 }}
            animate={{
              opacity: placement ? 1 : 0,
              scale: 1,
              x: placement?.x ?? 0,
              y: placement?.y ?? 0,
            }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.97 }}
            transition={reduceMotion
              ? { duration: 0.12 }
              : { type: 'spring', damping: 30, stiffness: 320, mass: 0.7 }}
          >
            {placement && spot && <TourArrow placement={placement} />}

            <div className="flex max-h-[calc(100dvh-24px)] min-h-0 flex-col">
              <header className="flex items-start gap-3 px-5 pb-3 pt-5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                  <StepIcon size={18} strokeWidth={2} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-3)]">
                    第 {stepIndex + 1} 步 / 共 {steps.length} 步
                  </div>
                  <h2 id="lawver-tour-title" className="mt-1 text-[19px] font-semibold leading-7">
                    {currentStep.title}
                  </h2>
                </div>
                <button
                  type="button"
                  onClick={closeTour}
                  className="lawver-pressable -mr-1 -mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-inset)] hover:text-[var(--fg-1)]"
                  aria-label={t("tour.close")}
                >
                  <X size={17} strokeWidth={2} />
                </button>
              </header>

              <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-1">
                <motion.div
                  key={currentStep.id}
                  initial={reduceMotion ? false : { opacity: 0, x: direction * 22 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.34, ease: TOUR_EASE }}
                >
                  <p className="text-[13.5px] leading-[1.7] text-[var(--fg-3)]">{currentStep.summary}</p>
                  <ul className="mt-3 flex flex-col gap-2">
                    {currentStep.features.map((feature, index) => (
                      <FeatureRow key={feature.label} feature={feature} index={index} reduceMotion={reduceMotion} />
                    ))}
                  </ul>
                </motion.div>
              </div>

              <div className="mt-4 flex items-center justify-between gap-3 border-t border-[var(--border-subtle)] px-5 py-3.5">
                {/* 分段进度条：当前段用 spring 撑开，取代原来的无限脉冲圆点。 */}
                <div className="flex min-w-0 flex-1 items-center gap-1.5" role="group" aria-label={t("tour.progress")}>
                  {steps.map((step, index) => (
                    <button
                      key={step.id}
                      type="button"
                      tabIndex={-1}
                      onClick={() => { setDirection(index > stepIndex ? 1 : -1); setStepIndex(index); }}
                      className="group flex h-8 min-w-0 flex-1 items-center"
                      aria-label={t("tour.stepLabel", { index: index + 1 })}
                    >
                      <motion.span
                        className="block h-1.5 w-full rounded-full"
                        animate={{
                          backgroundColor: index <= stepIndex ? 'var(--accent)' : 'var(--border-strong)',
                          opacity: index === stepIndex ? 1 : index < stepIndex ? 0.5 : 1,
                        }}
                        transition={{ duration: reduceMotion ? 0.01 : 0.3, ease: TOUR_EASE }}
                      />
                    </button>
                  ))}
                </div>

                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={closeTour}
                    className="md3-btn-text min-h-10 whitespace-nowrap px-3 py-2 !text-[13px]"
                  >
                    {t("tour.skip")}
                  </button>
                  <button
                    type="button"
                    onClick={goBack}
                    disabled={isFirstStep}
                    className="lawver-pressable inline-flex h-10 w-10 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-inset)] hover:text-[var(--fg-1)] disabled:pointer-events-none disabled:opacity-30"
                    aria-label={t("tour.prev")}
                  >
                    <ArrowLeft size={17} strokeWidth={2} />
                  </button>
                  <button
                    type="button"
                    onClick={goNext}
                    className="md3-btn-filled min-h-10 whitespace-nowrap !px-4 py-2 !text-[13px]"
                  >
                    {isLastStep ? (
                      <>
                        <Check size={15} strokeWidth={2.4} />
                        {t("tour.start")}
                      </>
                    ) : (
                      <>
                        {t("tour.next")}
                        <ArrowRight size={15} strokeWidth={2.4} />
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

/** 指向目标的箭头：贴在卡片朝目标的一条边上，沿边滑到目标中心。 */
const TourArrow: React.FC<{ placement: Placement }> = ({ placement }) => {
  const { side, arrow } = placement;
  const vertical = side === 'bottom' || side === 'top';
  const style: React.CSSProperties = vertical
    ? { left: arrow, top: side === 'bottom' ? -6 : undefined, bottom: side === 'top' ? -6 : undefined, marginLeft: -6 }
    : { top: arrow, left: side === 'right' ? -6 : undefined, right: side === 'left' ? -6 : undefined, marginTop: -6 };
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute h-3 w-3 rotate-45 border border-[var(--border-subtle)] bg-[var(--bg-surface)]"
      style={style}
    />
  );
};
