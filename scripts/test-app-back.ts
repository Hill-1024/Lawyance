/*
 * 模块描述：应用内返回导航回归测试，锁定"退栈而非压栈"的决策逻辑。
 *
 * 运行：pnpm run test:app-back
 */

import assert from 'node:assert/strict';

import {
  planAppBack,
  readHistoryIndex,
  resolveParentPath,
} from '../src/lib/app-history';

/* ── readHistoryIndex：只信任合法的 idx ── */
assert.equal(readHistoryIndex({ idx: 0 }), 0);
assert.equal(readHistoryIndex({ idx: 3 }), 3);
assert.equal(readHistoryIndex({ idx: -1 }), -1, '负数代表更早的浏览器记录，交由调用方判断');
assert.equal(readHistoryIndex({ idx: '2' }), 0, '字符串 idx 不可信');
assert.equal(readHistoryIndex({ idx: Number.NaN }), 0, 'NaN 不可信');
assert.equal(readHistoryIndex({ idx: Number.POSITIVE_INFINITY }), 0, 'Infinity 不可信');
assert.equal(readHistoryIndex(null), 0);
assert.equal(readHistoryIndex(undefined), 0);
assert.equal(readHistoryIndex({}), 0);

/* ── resolveParentPath：路径 → 上一级 ── */
assert.equal(resolveParentPath('/'), null, '根路由没有上一级');
assert.equal(resolveParentPath(''), null);
assert.equal(resolveParentPath('/settings'), '/');
assert.equal(resolveParentPath('/settings/'), '/');
assert.equal(resolveParentPath('/settings/webdav'), '/settings');
assert.equal(resolveParentPath('/settings/help'), '/settings');
assert.equal(resolveParentPath('/settings/providers/llm'), '/settings');
assert.equal(resolveParentPath('/settings/providers/searxng'), '/settings');
assert.equal(resolveParentPath('/court'), '/');
assert.equal(resolveParentPath('/admin'), '/');
assert.equal(resolveParentPath('/unknown/deep/path'), '/');

/* ── planAppBack：核心决策 ── */

// 栈内有记录 → 退栈（这是修复的重点：不能变成 replace 到父级之外的压栈）
assert.deepEqual(
  planAppBack({ pathname: '/settings/webdav', historyIndex: 3 }),
  { type: 'pop' },
  '有栈可退时必须退栈',
);
assert.deepEqual(
  planAppBack({ pathname: '/settings', historyIndex: 1 }),
  { type: 'pop' },
  '设置主页同样退栈',
);

// 本页是加载入口（深链/刷新）→ replace，避免退栈离开应用
assert.deepEqual(
  planAppBack({ pathname: '/settings/webdav', historyIndex: 0 }),
  { type: 'replace', to: '/settings' },
  '深链进入子页时应 replace 到父级',
);
assert.deepEqual(
  planAppBack({ pathname: '/settings', historyIndex: 0 }),
  { type: 'replace', to: '/' },
);
assert.deepEqual(
  planAppBack({ pathname: '/settings/providers/llm', historyIndex: 0 }),
  { type: 'replace', to: '/settings' },
);

// 根路由 → 交给调用方退出应用
assert.deepEqual(
  planAppBack({ pathname: '/', historyIndex: 5 }),
  { type: 'exit' },
  '根路由不退栈，否则会退出应用',
);

// 显式父级优先于路径推导（CourtPage/AdminDashboard 用 '/')
assert.deepEqual(
  planAppBack({ pathname: '/court', historyIndex: 0, parentPath: '/' }),
  { type: 'replace', to: '/' },
);
assert.deepEqual(
  planAppBack({ pathname: '/court', historyIndex: 2, parentPath: '/' }),
  { type: 'pop' },
);
assert.deepEqual(
  planAppBack({ pathname: '/admin', historyIndex: 0, parentPath: null }),
  { type: 'exit' },
  '显式 null 父级表示没有上一级',
);

/* ── 关键回归：模拟"设置主页 → 子页 → 返回 → 再按返回"不应回到子页 ── */
type Entry = { pathname: string; index: number };
const simulate = (stack: Entry[], parentPath?: string) => {
  const current = stack[stack.length - 1];
  const plan = planAppBack({
    pathname: current.pathname,
    historyIndex: current.index,
    ...(parentPath !== undefined ? { parentPath } : {}),
  });
  if (plan.type === 'pop') {
    stack.pop();
    return stack[stack.length - 1];
  }
  if (plan.type === 'replace') {
    stack[stack.length - 1] = { pathname: plan.to, index: current.index };
    return stack[stack.length - 1];
  }
  return null;
};

// 正常流程：/ → /settings → /settings/webdav
const stack: Entry[] = [
  { pathname: '/', index: 0 },
  { pathname: '/settings', index: 1 },
  { pathname: '/settings/webdav', index: 2 },
];
assert.equal(simulate(stack, '/settings')?.pathname, '/settings', '子页返回应回到设置主页');
assert.equal(stack.length, 2, '退栈后栈长度减少，不能增长');
assert.equal(simulate(stack, '/')?.pathname, '/', '设置主页返回应回到聊天页');
assert.equal(stack.length, 1, '再次退栈，栈继续收缩');
assert.equal(simulate(stack, '/'), null, '根路由返回表示退出应用');
assert.equal(stack.length, 1, '不可退栈时栈长度不变');

// 压栈 bug 的旧行为会让栈增长且返回到子页，这里显式断言不会发生
const bugStack: Entry[] = [
  { pathname: '/', index: 0 },
  { pathname: '/settings', index: 1 },
  { pathname: '/settings/webdav', index: 2 },
];
const afterBack = simulate(bugStack, '/settings');
assert.notEqual(afterBack?.pathname, '/settings/webdav', '返回后绝不能回到刚离开的子页');
assert.ok(bugStack.length <= 2, '返回不得让 history 栈变长');

// 深链流程：直接加载 /settings/providers/llm（idx 0），连续返回应逐级 replace 且不离开应用
const deepStack: Entry[] = [{ pathname: '/settings/providers/llm', index: 0 }];
assert.equal(simulate(deepStack)?.pathname, '/settings');
assert.equal(deepStack.length, 1, 'replace 不改变栈长度');
assert.equal(simulate(deepStack)?.pathname, '/');
assert.equal(simulate(deepStack), null, '最终在根路由退出应用');

console.log('✅ app-history 返回导航逻辑全部通过');
