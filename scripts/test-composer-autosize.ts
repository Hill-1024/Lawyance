import assert from 'node:assert/strict';

import {
  clampComposerHeight,
  COMPOSER_MAX_LINES,
  COMPOSER_VIEWPORT_RATIO,
  composerSingleLineHeight,
  computeComposerCap,
  computeComposerViewportBudget,
  countComposerLines,
  isMultilineHeight,
  planComposerActionBar,
  type ComposerMetrics
} from '../frontend/src/lib/composer-autosize';

// 桌面主聊天：15px / line-height 1.5，padding 8.75px 6px，min-height 40px
const desktop: ComposerMetrics = {
  lineHeight: 22.5,
  paddingTop: 8.75,
  paddingBottom: 8.75,
  minHeight: 40
};

// 小屏（<=480px）：14px / 1.5，padding 10px 3px，min-height 44px
const mobile: ComposerMetrics = {
  lineHeight: 21,
  paddingTop: 10,
  paddingBottom: 10,
  minHeight: 44
};

// 庭审页：15px / 1.5，padding 9px 4px，min-height 44px
const court: ComposerMetrics = {
  lineHeight: 22.5,
  paddingTop: 9,
  paddingBottom: 9,
  minHeight: 44
};

assert.equal(COMPOSER_MAX_LINES, 6);
assert.equal(COMPOSER_VIEWPORT_RATIO, 0.3);

// 单行基线必须等于现有 CSS 的静止高度，保证单行外观零回归
assert.equal(composerSingleLineHeight(desktop), 40, '桌面单行仍为 40px');
assert.equal(composerSingleLineHeight(mobile), 44, '小屏单行仍为 44px');
assert.equal(composerSingleLineHeight(court), 44, '庭审单行仍为 44px');

// 桌面：视口充裕时由 6 行封顶
assert.equal(computeComposerCap({ ...desktop, viewportHeight: 900 }), 152.5);
// 桌面单行/多行判定
assert.equal(isMultilineHeight(40, desktop), false);
assert.equal(isMultilineHeight(40.5, desktop), false);
assert.equal(isMultilineHeight(63, desktop), true);

// 夹取：不低于 min-height，不超过 cap，中间值原样保留
assert.equal(clampComposerHeight(40, 40, 152.5), 40);
assert.equal(clampComposerHeight(63, 40, 152.5), 63);
assert.equal(clampComposerHeight(400, 40, 152.5), 152.5, '超过上限后交给内部滚动');
assert.equal(clampComposerHeight(20, 44, 152.5), 44, '内容不足时仍保持 min-height');
assert.equal(clampComposerHeight(50, 44, 30), 44, '上限低于 min-height 时以 min-height 为准');

// 小屏：min-height 44 高于一行文字高度，单行仍判定为单行
assert.equal(isMultilineHeight(44, mobile), false);
assert.equal(isMultilineHeight(62, mobile), true);

// 软键盘弹起：visualViewport 400px 时上限收紧到 120px
assert.equal(computeComposerCap({ ...mobile, viewportHeight: 400 }), 120);
// 同一输入框在键盘弹起后上限必然不增加
assert.ok(
  computeComposerCap({ ...mobile, viewportHeight: 400 }) <
    computeComposerCap({ ...mobile, viewportHeight: 800 })
);

// 极矮视口：3 行兜底优先于视口比例
assert.equal(computeComposerCap({ ...desktop, viewportHeight: 200 }), 85);
assert.equal(computeComposerCap({ ...desktop, viewportHeight: 0 }), 85);

// 庭审页单行与上限（padding 更小时 6 行高度也略高）
assert.equal(isMultilineHeight(44, court), false);
assert.equal(computeComposerCap({ ...court, viewportHeight: 900 }), 153);

// 行数换算：scrollHeight 含 padding，需要先减掉
assert.equal(countComposerLines(40, desktop), 1);
assert.equal(countComposerLines(63, desktop), 2);
assert.equal(countComposerLines(152.5, desktop), 6);
assert.equal(countComposerLines(41, mobile), 1);
assert.equal(countComposerLines(62, mobile), 2);

// 视口预算
assert.equal(computeComposerViewportBudget({ viewportHeight: 400 }), 120);
assert.equal(computeComposerViewportBudget({ viewportHeight: 900 }), 270);

// 左侧控件竖排：高窗口单列，矮窗口/横屏降为两列
const tall = computeComposerViewportBudget({ viewportHeight: 720 });
const short = computeComposerViewportBudget({ viewportHeight: 400 });
assert.deepEqual(planComposerActionBar({ itemCount: 4, availableHeight: tall }), {
  columns: 1,
  height: 172
});
assert.deepEqual(planComposerActionBar({ itemCount: 4, availableHeight: short }), {
  columns: 2,
  height: 84
});
// 单列刚好放得下与差一点放不下
assert.equal(planComposerActionBar({ itemCount: 4, availableHeight: 184 }).columns, 1);
assert.equal(planComposerActionBar({ itemCount: 4, availableHeight: 183 }).columns, 2);
// 只有 3 个控件时单列 128px，在高窗口下仍是单列
assert.deepEqual(planComposerActionBar({ itemCount: 3, availableHeight: tall }), {
  columns: 1,
  height: 128
});
// 矮窗口下 3 个控件也会降为两列（2 行）
assert.deepEqual(planComposerActionBar({ itemCount: 3, availableHeight: short }), {
  columns: 2,
  height: 84
});
// 庭审页只有一个控件：竖排与横排等同，不产生额外高度
assert.deepEqual(planComposerActionBar({ itemCount: 1, availableHeight: short }), {
  columns: 1,
  height: 40
});
// 锁定“不返回行数”这个不变量：行数一旦回到 JS 手里，估错就会在 CSS 里变成空轨道
assert.deepEqual(
  Object.keys(planComposerActionBar({ itemCount: 4, availableHeight: short })).sort(),
  ['columns', 'height'],
  '排布计划不得携带行数'
);

console.log('composer autosize: single-line baselines, viewport cap, clamping and action-bar plan passed');
