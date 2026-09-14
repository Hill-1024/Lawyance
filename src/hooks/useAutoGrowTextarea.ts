/*
 * 模块描述：输入框自适应高度 hook——内容换行时增高，超过按可见视口计算的上限后改为内部滚动。
 */

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import {
  clampComposerHeight,
  computeComposerCap,
  countComposerLines,
  isMultilineHeight,
  type ComposerMetrics
} from '../lib/composer-autosize';

const readMetrics = (element: HTMLTextAreaElement): ComposerMetrics => {
  const computed = getComputedStyle(element);
  const fontSize = parseFloat(computed.fontSize) || 15;
  return {
    lineHeight: parseFloat(computed.lineHeight) || fontSize * 1.5,
    paddingTop: parseFloat(computed.paddingTop) || 0,
    paddingBottom: parseFloat(computed.paddingBottom) || 0,
    minHeight: parseFloat(computed.minHeight) || 0
  };
};

/** 上限以可见视口为基准：Android 默认 resizes-visual，布局视口不会因软键盘收缩。 */
const currentViewportHeight = () => window.visualViewport?.height ?? window.innerHeight;

export interface AutoGrowTextareaOptions {
  /**
   * 横排（未竖排）时输入框的宽度。
   *
   * 竖排后左侧控件组从 172px 收窄到 40px，输入框会变宽、折行减少；如果直接用当前宽度
   * 判定是否多行，就会在临界处“竖排 → 变宽 → 不再多行 → 取消竖排”来回抖动。
   * 固定按横排宽度判定即可稳定，且判定结果与当前是哪种排布无关。
   */
  stackReferenceWidth?: number | null;
}

/**
 * 内容换行时增高，`min(6 行, 30% 可见视口)` 封顶后转为内部滚动。
 *
 * 单行时清空内联高度、不预留滚动条槽位，让 CSS min-height 完全接管，
 * 保证单行外观与未启用自适应时逐像素一致。
 */
export const useAutoGrowTextarea = (value: string, options: AutoGrowTextareaOptions = {}) => {
  const { stackReferenceWidth = null } = options;
  const ref = useRef<HTMLTextAreaElement>(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const [isMultiline, setIsMultiline] = useState(false);
  const [isStacked, setIsStacked] = useState(false);
  const multilineRef = useRef(false);
  const lastWidthRef = useRef(0);
  const lastViewportHeightRef = useRef(0);
  const stackReferenceWidthRef = useRef<number | null>(stackReferenceWidth);
  stackReferenceWidthRef.current = stackReferenceWidth;

  const applyHeight = useCallback((element: HTMLTextAreaElement) => {
    const metrics = readMetrics(element);
    // 先回到 auto 量出无上限的内容高度，再夹到 [min-height, cap]。
    element.style.height = 'auto';
    const naturalHeight = element.scrollHeight;
    const cap = computeComposerCap({ ...metrics, viewportHeight: currentViewportHeight() });
    const height = clampComposerHeight(naturalHeight, metrics.minHeight, cap);
    const multiline = isMultilineHeight(height, metrics);
    element.style.height = multiline ? `${height}px` : '';
    element.style.overflowY = naturalHeight > cap ? 'auto' : 'hidden';
    return multiline;
  }, []);

  const measure = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    lastViewportHeightRef.current = currentViewportHeight();

    const multiline = applyHeight(element);

    const referenceWidth = stackReferenceWidthRef.current;
    let stacked = multiline;
    if (referenceWidth && Math.abs(element.getBoundingClientRect().width - referenceWidth) > 0.5) {
      const metrics = readMetrics(element);
      // 脱离 flex 布局测量，避免 flex: 1 覆盖指定的参考宽度。
      const probe = element.cloneNode(false) as HTMLTextAreaElement;
      probe.removeAttribute('id');
      probe.setAttribute('aria-hidden', 'true');
      probe.tabIndex = -1;
      probe.value = valueRef.current;
      probe.style.cssText = element.style.cssText;
      Object.assign(probe.style, {
        position: 'fixed', visibility: 'hidden', pointerEvents: 'none',
        width: `${referenceWidth}px`, height: 'auto', minHeight: '0',
        maxHeight: 'none', flex: 'none', top: '0', left: '0'
      });
      element.parentElement?.appendChild(probe);
      stacked = countComposerLines(probe.scrollHeight, metrics) >= 2;
      probe.remove();
    }
    setIsStacked(stacked);

    if (multiline === multilineRef.current) return;

    multilineRef.current = multiline;
    // 自定义 ::-webkit-scrollbar 会强制经典滚动条并占用布局宽度，只在多行状态预留槽位。
    element.style.scrollbarGutter = multiline ? 'stable' : '';
    // 槽位宽度会改变折行数，再量一次收敛（单调变化，不会来回抖动）。
    applyHeight(element);
    setIsMultiline(multiline);
  }, [applyHeight]);

  useLayoutEffect(() => {
    measure();
  }, [measure, value, stackReferenceWidth]);

  // 宽度变化会改变折行数：侧栏/工作区面板开合、窗口缩放都走这里。
  // 只比较宽度，忽略自身设置高度引发的回调。
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return;

    lastWidthRef.current = element.getBoundingClientRect().width;
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width ?? element.getBoundingClientRect().width;
      if (Math.abs(width - lastWidthRef.current) < 0.5) return;
      lastWidthRef.current = width;
      measure();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  // 软键盘弹起/收起改变可见视口高度，需要实时收紧上限。
  // 这里只重算输入框高度、不写 React 状态：resize 会在拖拽和键盘动画期间连续触发，
  // 把视口高度放进 state 会让整块输入区跟着每帧重渲染。
  useLayoutEffect(() => {
    const handleViewportResize = () => {
      const next = currentViewportHeight();
      if (Math.abs(next - lastViewportHeightRef.current) < 0.5) return;
      measure();
    };
    window.addEventListener('resize', handleViewportResize);
    window.visualViewport?.addEventListener('resize', handleViewportResize);
    return () => {
      window.removeEventListener('resize', handleViewportResize);
      window.visualViewport?.removeEventListener('resize', handleViewportResize);
    };
  }, [measure]);

  return { ref, isMultiline, isStacked };
};
