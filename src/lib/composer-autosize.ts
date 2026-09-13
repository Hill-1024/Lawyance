/*
 * 模块描述：输入框自适应高度的纯计算——行数换算、视口上限与夹取，供 useAutoGrowTextarea 使用。
 */

/** 输入框最多展开到 6 行。 */
export const COMPOSER_MAX_LINES = 6;

/** 可见视口再矮也至少保留 3 行的可编辑高度。 */
export const COMPOSER_FLOOR_LINES = 3;

/** 输入框最多占可见视口高度的 30%，软键盘弹起时靠这条自动收紧。 */
export const COMPOSER_VIEWPORT_RATIO = 0.3;

export interface ComposerMetrics {
  lineHeight: number;
  paddingTop: number;
  paddingBottom: number;
  minHeight: number;
}

export interface ComposerCapOptions extends ComposerMetrics {
  viewportHeight: number;
  maxLines?: number;
  floorLines?: number;
  viewportRatio?: number;
}

/** 单行基线高度：CSS min-height 与「一行文字 + 上下 padding」取大者。 */
export const composerSingleLineHeight = ({
  lineHeight,
  paddingTop,
  paddingBottom,
  minHeight
}: ComposerMetrics) => Math.max(minHeight, paddingTop + paddingBottom + lineHeight);

/**
 * 上限取「6 行」与「30% 可见视口」的较小值，再用「3 行」兜底。
 * 视口基准应为 visualViewport.height：布局视口在 Android 默认 resizes-visual 下不会因软键盘收缩。
 */
export const computeComposerCap = ({
  lineHeight,
  paddingTop,
  paddingBottom,
  viewportHeight,
  maxLines = COMPOSER_MAX_LINES,
  floorLines = COMPOSER_FLOOR_LINES,
  viewportRatio = COMPOSER_VIEWPORT_RATIO
}: ComposerCapOptions) => {
  const paddingY = paddingTop + paddingBottom;
  const floor = paddingY + floorLines * lineHeight;
  const maxByLines = paddingY + Math.max(maxLines, floorLines) * lineHeight;
  const maxByViewport = viewportRatio * viewportHeight;
  return Math.max(floor, Math.min(maxByLines, maxByViewport));
};

/** 夹取到 [minHeight, cap]；上限低于 minHeight 时以 minHeight 为准。 */
export const clampComposerHeight = (naturalHeight: number, minHeight: number, cap: number) =>
  Math.max(minHeight, Math.min(naturalHeight, Math.max(cap, minHeight)));

/** 内容是否已超过一行——用于切换贴底对齐与卡片圆角。 */
export const isMultilineHeight = (height: number, metrics: ComposerMetrics) =>
  height > composerSingleLineHeight(metrics) + 0.5;

/** 内容在给定宽度下占几行。 */
export const countComposerLines = (
  scrollHeight: number,
  { lineHeight, paddingTop, paddingBottom }: ComposerMetrics
) => Math.max(1, Math.round((scrollHeight - paddingTop - paddingBottom) / lineHeight));

/** 可见视口留给输入区的纵向预算。 */
export const computeComposerViewportBudget = ({
  viewportHeight,
  viewportRatio = COMPOSER_VIEWPORT_RATIO
}: {
  viewportHeight: number;
  viewportRatio?: number;
}) => viewportHeight * viewportRatio;

/** 输入区左侧控件的尺寸、间隙与外壳占位（与 index.css 对齐）。 */
export const COMPOSER_ACTION_SIZE = 40;
export const COMPOSER_ACTION_GAP = 4;
export const COMPOSER_SHELL_CHROME = 12;

export interface ComposerActionBarPlan {
  columns: number;
  rows: number;
  /** 控件组自身高度，不含外壳 padding/border。 */
  height: number;
}

/**
 * 左侧控件从横排改为竖排后的排布：单列放不下时降为两列。
 * 单列高度由控件数量决定，四个 40px 控件需要 172px，超过六行上限但可能仍在视口预算内。
 */
export const planComposerActionBar = ({
  itemCount,
  availableHeight,
  itemSize = COMPOSER_ACTION_SIZE,
  gap = COMPOSER_ACTION_GAP,
  shellChrome = COMPOSER_SHELL_CHROME
}: {
  itemCount: number;
  availableHeight: number;
  itemSize?: number;
  gap?: number;
  shellChrome?: number;
}): ComposerActionBarPlan => {
  const safeCount = Math.max(1, Math.floor(itemCount));
  const singleColumnHeight = safeCount * itemSize + (safeCount - 1) * gap;
  if (safeCount <= 2 || singleColumnHeight + shellChrome <= availableHeight) {
    return { columns: 1, rows: safeCount, height: singleColumnHeight };
  }

  const rows = Math.ceil(safeCount / 2);
  return { columns: 2, rows, height: rows * itemSize + (rows - 1) * gap };
};

