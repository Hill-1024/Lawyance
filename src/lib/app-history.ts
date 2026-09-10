/*
 * 模块描述：应用内返回导航的纯逻辑（无 React 依赖），便于单测锁定退栈/替换/退出三种决策。
 *
 * 背景：直接 navigate(父级路径) 会往 history 栈压一条新记录，用户再按返回就会
 * "前进"回刚离开的子页，表现为返回错乱、需连按多次才能退出。
 * React Router 在每个 history entry 上写 idx，0 表示该 entry 是本次文档加载的入口；
 * 深链或刷新进入时退栈会直接离开应用，此时才改用 replace 落到父级。
 */

/** history.state 中 React Router 写入的下标；缺失或非法时按入口（0）处理。 */
export const readHistoryIndex = (state: unknown): number => {
  const idx = (state as { idx?: unknown } | null | undefined)?.idx;
  return typeof idx === 'number' && Number.isFinite(idx) ? idx : 0;
};

/** 读取当前文档的 history 下标；非浏览器环境返回 0。 */
export const appHistoryIndex = (): number => {
  if (typeof window === 'undefined') return 0;
  return readHistoryIndex(window.history.state);
};

/** 由当前路径推导上一级；返回 null 表示已在根路由（调用方可退出应用）。 */
export const resolveParentPath = (pathname: string): string | null => {
  const normalized = normalizePathname(pathname);
  if (normalized === '/') return null;
  if (normalized.startsWith('/settings/')) return '/settings';
  if (normalized === '/settings') return '/';
  return '/';
};

const normalizePathname = (pathname: string): string =>
  (pathname || '/').replace(/\/+$/, '') || '/';

export type AppBackPlan =
  | { type: 'pop' }
  | { type: 'replace'; to: string }
  | { type: 'exit' };

/**
 * 决定返回动作：
 * - pop：栈内有上一条记录，退栈即可（不新增记录）；
 * - replace：本页是加载入口（深链/刷新），退栈会离开应用，改为替换到父级；
 * - exit：已在根路由，交给调用方决定是否退出应用。
 */
export const planAppBack = (options: {
  pathname: string;
  historyIndex: number;
  /** 显式指定的父级；省略时按 pathname 推导。传 null 表示没有父级。 */
  parentPath?: string | null;
}): AppBackPlan => {
  const parentPath = options.parentPath === undefined
    ? resolveParentPath(options.pathname)
    : options.parentPath;
  if (!parentPath) return { type: 'exit' };
  // 父级与当前路径相同等于原地打转，视为无处可去。
  if (normalizePathname(parentPath) === normalizePathname(options.pathname)) return { type: 'exit' };
  if (options.historyIndex > 0) return { type: 'pop' };
  return { type: 'replace', to: parentPath };
};
