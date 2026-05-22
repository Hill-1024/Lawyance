/*
 * 模块描述：自定义悬浮提示组件，替代浏览器原生 title，提供更快、更可控的指针与键盘悬浮提示。
 */

import React, { cloneElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

type Placement = 'top' | 'bottom' | 'left' | 'right';

interface HoverInfoProps {
  label: React.ReactNode;
  children: React.ReactElement;
  placement?: Placement;
}

const SHOW_DELAY_MS = 100;
const TRIGGER_GAP = 8;
const VIEWPORT_MARGIN = 8;

export const HoverInfo: React.FC<HoverInfoProps> = ({ label, children, placement = 'top' }) => {
  const tooltipId = useId();
  const triggerRef = useRef<HTMLElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const showTimer = useRef<number | null>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const clearShowTimer = useCallback(() => {
    if (showTimer.current !== null) {
      window.clearTimeout(showTimer.current);
      showTimer.current = null;
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
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  useEffect(() => () => clearShowTimer(), [clearShowTimer]);

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
      hide();
    },
    onPointerDown: (e: React.PointerEvent) => {
      childProps.onPointerDown?.(e);
      hide();
    },
    onFocus: (e: React.FocusEvent) => {
      childProps.onFocus?.(e);
      setOpen(true);
    },
    onBlur: (e: React.FocusEvent) => {
      childProps.onBlur?.(e);
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
