/*
 * 模块描述：自定义悬浮提示组件，替代浏览器原生 title，提供更快、更可控的指针与键盘悬浮提示。
 * 触摸设备：长按 ~450ms 显示气泡；轻触正常执行子节点 onClick；外部点击或滑动取消。
 */

import React, { cloneElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

type Placement = 'top' | 'bottom' | 'left' | 'right';

interface HoverInfoProps {
  label: React.ReactNode;
  children: React.ReactElement;
  placement?: Placement;
  disabled?: boolean;
}

const SHOW_DELAY_MS = 100;
const LONG_PRESS_MS = 450;
const TOUCH_MOVE_THRESHOLD = 10;
const TRIGGER_GAP = 8;
const VIEWPORT_MARGIN = 8;

export const HoverInfo: React.FC<HoverInfoProps> = ({ label, children, placement = 'top', disabled = false }) => {
  const tooltipId = useId();
  const triggerRef = useRef<HTMLElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const showTimer = useRef<number | null>(null);
  const longPressTimer = useRef<number | null>(null);
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const lastPointerType = useRef<string | null>(null);
  const suppressNextClick = useRef(false);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const clearShowTimer = useCallback(() => {
    if (showTimer.current !== null) {
      window.clearTimeout(showTimer.current);
      showTimer.current = null;
    }
  }, []);

  const clearLongPressTimer = useCallback(() => {
    if (longPressTimer.current !== null) {
      window.clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  }, []);

  const reposition = useCallback(() => {
    const trigger = triggerRef.current;
    const tooltip = tooltipRef.current;
    if (!trigger || !tooltip) return;
    const t = trigger.getBoundingClientRect();
    const w = tooltip.offsetWidth;
    const h = tooltip.offsetHeight;
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;

    // 智能自动翻转逻辑：当空间不足时自动调整方位，提供极致的溢出边缘体验
    let actualPlacement = placement;
    if (placement === 'top' && t.top - TRIGGER_GAP - h < VIEWPORT_MARGIN) {
      if (t.bottom + TRIGGER_GAP + h < vh - VIEWPORT_MARGIN) {
        actualPlacement = 'bottom';
      }
    } else if (placement === 'bottom' && t.bottom + TRIGGER_GAP + h > vh - VIEWPORT_MARGIN) {
      if (t.top - TRIGGER_GAP - h > VIEWPORT_MARGIN) {
        actualPlacement = 'top';
      }
    } else if (placement === 'left' && t.left - TRIGGER_GAP - w < VIEWPORT_MARGIN) {
      if (t.right + TRIGGER_GAP + w < vw - VIEWPORT_MARGIN) {
        actualPlacement = 'right';
      }
    } else if (placement === 'right' && t.right + TRIGGER_GAP + w > vw - VIEWPORT_MARGIN) {
      if (t.left - TRIGGER_GAP - w > VIEWPORT_MARGIN) {
        actualPlacement = 'left';
      }
    }

    let top: number;
    let left: number;
    if (actualPlacement === 'bottom') {
      top = t.bottom + TRIGGER_GAP;
      left = t.left + t.width / 2 - w / 2;
    } else if (actualPlacement === 'left') {
      top = t.top + t.height / 2 - h / 2;
      left = t.left - TRIGGER_GAP - w;
    } else if (actualPlacement === 'right') {
      top = t.top + t.height / 2 - h / 2;
      left = t.right + TRIGGER_GAP;
    } else {
      top = t.top - TRIGGER_GAP - h;
      left = t.left + t.width / 2 - w / 2;
    }

    left = Math.min(Math.max(left, VIEWPORT_MARGIN), vw - w - VIEWPORT_MARGIN);
    top = Math.min(Math.max(top, VIEWPORT_MARGIN), vh - h - VIEWPORT_MARGIN);
    setPos({ top, left });
  }, [placement]);

  useLayoutEffect(() => {
    if (!open) return;
    reposition();
    let frame = 0;
    const onReflow = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(reposition);
    };
    window.addEventListener('scroll', onReflow, true);
    window.addEventListener('resize', onReflow);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('scroll', onReflow, true);
      window.removeEventListener('resize', onReflow);
    };
  }, [open, reposition, label]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    // 触摸场景：点击 tooltip / trigger 之外的位置关闭气泡
    const onDocPointerDown = (e: PointerEvent) => {
      if (e.pointerType !== 'touch') return;
      const target = e.target as Node | null;
      if (!target) return;
      if (triggerRef.current?.contains(target) || tooltipRef.current?.contains(target)) return;
      setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onDocPointerDown, true);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onDocPointerDown, true);
    };
  }, [open]);

  useEffect(() => () => {
    clearShowTimer();
    clearLongPressTimer();
  }, [clearShowTimer, clearLongPressTimer]);

  useEffect(() => {
    if (!disabled) return;
    clearShowTimer();
    clearLongPressTimer();
    lastPointerType.current = null;
    touchStart.current = null;
    suppressNextClick.current = false;
    setOpen(false);
  }, [clearShowTimer, clearLongPressTimer, disabled]);

  const scheduleShow = useCallback(() => {
    clearShowTimer();
    showTimer.current = window.setTimeout(() => setOpen(true), SHOW_DELAY_MS);
  }, [clearShowTimer]);

  const hide = useCallback(() => {
    clearShowTimer();
    setOpen(false);
  }, [clearShowTimer]);

  // 健壮性检查：若不是有效的 React 元素，直接回退渲染 children
  if (!React.isValidElement(children)) {
    return <>{children}</>;
  }

  if (disabled) {
    return <>{children}</>;
  }

  const childProps = (children.props ?? {}) as Record<string, any>;

  // 兼容 React 19 与历史版本的合并 Ref 机制，防止破坏子组件原有的 Ref
  const originalRef = (children as any).ref || (children as any).props?.ref;

  const trigger = cloneElement(children as React.ReactElement<any>, {
    ref: (node: HTMLElement | null) => {
      triggerRef.current = node;
      if (typeof originalRef === 'function') {
        originalRef(node);
      } else if (originalRef && typeof originalRef === 'object') {
        originalRef.current = node;
      }
    },
    onPointerEnter: (e: React.PointerEvent) => {
      childProps.onPointerEnter?.(e);
      if (e.pointerType !== 'touch') scheduleShow();
    },
    onPointerLeave: (e: React.PointerEvent) => {
      childProps.onPointerLeave?.(e);
      if (e.pointerType !== 'touch') hide();
    },
    onPointerDown: (e: React.PointerEvent) => {
      childProps.onPointerDown?.(e);
      lastPointerType.current = e.pointerType;
      if (e.pointerType === 'touch') {
        touchStart.current = { x: e.clientX, y: e.clientY };
        clearLongPressTimer();
        longPressTimer.current = window.setTimeout(() => {
          longPressTimer.current = null;
          suppressNextClick.current = true;
          setOpen(true);
        }, LONG_PRESS_MS);
      } else {
        // mouse / pen 点击时收起，避免覆盖按钮反馈
        hide();
      }
    },
    onPointerMove: (e: React.PointerEvent) => {
      childProps.onPointerMove?.(e);
      if (e.pointerType !== 'touch' || !touchStart.current) return;
      const dx = e.clientX - touchStart.current.x;
      const dy = e.clientY - touchStart.current.y;
      if (Math.hypot(dx, dy) > TOUCH_MOVE_THRESHOLD) {
        clearLongPressTimer();
      }
    },
    onPointerUp: (e: React.PointerEvent) => {
      childProps.onPointerUp?.(e);
      if (e.pointerType === 'touch') {
        clearLongPressTimer();
        touchStart.current = null;
      }
    },
    onPointerCancel: (e: React.PointerEvent) => {
      childProps.onPointerCancel?.(e);
      if (e.pointerType === 'touch') {
        clearLongPressTimer();
        touchStart.current = null;
      }
    },
    onClickCapture: (e: React.MouseEvent) => {
      if (suppressNextClick.current) {
        suppressNextClick.current = false;
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      childProps.onClickCapture?.(e);
    },
    onContextMenu: (e: React.MouseEvent) => {
      childProps.onContextMenu?.(e);
      // 长按触发气泡后，浏览器仍可能弹出原生右键菜单/复制弹窗；这里压制一次
      if (open) e.preventDefault();
    },
    onFocus: (e: React.FocusEvent) => {
      childProps.onFocus?.(e);
      if (lastPointerType.current === 'touch') return;
      setOpen(true);
    },
    onBlur: (e: React.FocusEvent) => {
      childProps.onBlur?.(e);
      lastPointerType.current = null;
      hide();
    },
    'aria-describedby': open
      ? [childProps['aria-describedby'], tooltipId].filter(Boolean).join(' ')
      : childProps['aria-describedby']
  });

  return (
    <>
      {trigger}
      {open && typeof document !== 'undefined' && createPortal(
        <div
          ref={tooltipRef}
          id={tooltipId}
          role="tooltip"
          style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 100 }}
          className="pointer-events-none max-w-[min(280px,calc(100vw-1.5rem))] break-words rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 py-1.5 text-xs leading-snug text-[var(--fg-1)] shadow-[var(--shadow-3)]"
        >
          {label}
        </div>,
        document.body
      )}
    </>
  );
};
