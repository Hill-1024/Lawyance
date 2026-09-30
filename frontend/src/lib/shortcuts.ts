/*
 * 模块描述：快捷键注册表——默认按键、按键匹配、按设备持久化的改键与显示格式化。
 *
 * 调用方只认「动作 id」：`matchKeys(event, getBinding('composer.send'))`。
 * 用户改键写进 localStorage（lawver.shortcuts），只影响当前设备；改键后无需刷新页面。
 * 规范按键串一律形如 "mod+n" / "shift+enter" / "arrowdown"：mod 在 macOS 指 ⌘、其它平台指 Ctrl。
 */

import type { MessageKey } from '../i18n';

/* ── 注册表 ───────────────────────────────────────────────────────────── */

/** 作用域决定冲突检测的范围：同域内两个动作不允许绑定同一组按键。 */
export type ShortcutScope = 'global' | 'composer' | 'court' | 'overlay';

export type ShortcutDef = {
  id: string;
  /** 显示名词条键：文案在渲染时取，避免模块加载时固定成一种语言。 */
  labelKey: MessageKey;
  /** 设置页与帮助页的分组标题词条键。 */
  groupKey: MessageKey;
  /** 规范化的默认按键串。 */
  defaultKeys: string;
  scope: ShortcutScope;
};

export const SHORTCUTS: readonly ShortcutDef[] = [
  { id: 'session.new', labelKey: 'shortcut.sessionNew', groupKey: 'shortcutGroup.workbench', defaultKeys: 'mod+n', scope: 'global' },
  { id: 'composer.send', labelKey: 'shortcut.composerSend', groupKey: 'shortcutGroup.composer', defaultKeys: 'enter', scope: 'composer' },
  { id: 'composer.newline', labelKey: 'shortcut.composerNewline', groupKey: 'shortcutGroup.composer', defaultKeys: 'shift+enter', scope: 'composer' },
  { id: 'composer.candidate-up', labelKey: 'shortcut.candidateUp', groupKey: 'shortcutGroup.composer', defaultKeys: 'arrowup', scope: 'composer' },
  { id: 'composer.candidate-down', labelKey: 'shortcut.candidateDown', groupKey: 'shortcutGroup.composer', defaultKeys: 'arrowdown', scope: 'composer' },
  { id: 'court.send', labelKey: 'shortcut.courtSend', groupKey: 'shortcutGroup.court', defaultKeys: 'mod+enter', scope: 'court' },
  { id: 'overlay.close', labelKey: 'shortcut.overlayClose', groupKey: 'shortcutGroup.overlay', defaultKeys: 'escape', scope: 'overlay' },
];

export const SHORTCUT_IDS = {
  sessionNew: 'session.new',
  composerSend: 'composer.send',
  composerNewline: 'composer.newline',
  candidateUp: 'composer.candidate-up',
  candidateDown: 'composer.candidate-down',
  courtSend: 'court.send',
  overlayClose: 'overlay.close',
} as const;

export const SCOPE_LABELS: Record<ShortcutScope, MessageKey> = {
  global: 'shortcutScope.global',
  composer: 'shortcutScope.composer',
  court: 'shortcutScope.court',
  overlay: 'shortcutScope.overlay',
};

/* ── 按键规范化与匹配 ─────────────────────────────────────────────────── */

type ParsedSpec = { mod: boolean; ctrl: boolean; alt: boolean; shift: boolean; key: string };

/** 只要带这几个字段即可：原生 KeyboardEvent 与 React 合成事件都满足。 */
export type KeyEventLike = {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
};

const MODIFIER_KEYS = new Set(['meta', 'control', 'ctrl', 'alt', 'shift', 'altgraph', 'os']);
const MODIFIER_TOKENS = new Set(['mod', 'ctrl', 'alt', 'shift']);

/** 事件键名归一：Enter/ArrowUp/N → enter/arrowup/n。 */
const normalizeKey = (key: string) => (key || '').toLowerCase();

export const parseSpec = (spec: string): ParsedSpec => {
  const parsed: ParsedSpec = { mod: false, ctrl: false, alt: false, shift: false, key: '' };
  for (const raw of String(spec || '').toLowerCase().split('+')) {
    const token = raw.trim();
    if (!token) continue;
    if (MODIFIER_TOKENS.has(token)) parsed[token as 'mod' | 'ctrl' | 'alt' | 'shift'] = true;
    else parsed.key = token;
  }
  return parsed;
};

/** 合法绑定：必须有一个非修饰键，且修饰键只能出现在已知位置。 */
export const isValidSpec = (spec: string) => {
  if (typeof spec !== 'string' || !spec.trim()) return false;
  const tokens = spec.toLowerCase().split('+').map(token => token.trim()).filter(Boolean);
  if (!tokens.length || tokens.length > 4) return false;
  const key = tokens[tokens.length - 1];
  if (MODIFIER_KEYS.has(key) || MODIFIER_TOKENS.has(key)) return false;
  return tokens.slice(0, -1).every(token => MODIFIER_TOKENS.has(token));
};

/** 是否为「仅在修饰键上」的按键事件：录制时需要继续等真实按键。 */
export const isModifierEvent = (event: KeyEventLike) =>
  MODIFIER_KEYS.has(normalizeKey(event.key)) || Boolean(event.key === 'Meta' || event.key === 'AltGraph');

/**
 * 事件是否命中绑定。修饰键严格匹配：绑定 "enter" 时 Shift+Enter 不算命中，
 * 因此「发送 enter / 换行 shift+enter」不会互相误触。
 */
export const matchKeys = (event: KeyEventLike, spec: string): boolean => {
  const parsed = parseSpec(spec);
  if (!parsed.key || normalizeKey(event.key) !== parsed.key) return false;
  // mod 与 ctrl 在匹配时等价（macOS 的 ⌘ 与其它平台的 Ctrl 走同一分支）。
  const wantsMod = parsed.mod || parsed.ctrl;
  const pressedMod = Boolean(event.metaKey || event.ctrlKey);
  if (wantsMod !== pressedMod) return false;
  if (event.altKey !== parsed.alt) return false;
  if (event.shiftKey !== parsed.shift) return false;
  return true;
};

/** 把键盘事件转成规范串；只按了修饰键时返回 null。 */
export const specFromEvent = (event: KeyEventLike): string | null => {
  if (isModifierEvent(event)) return null;
  const key = normalizeKey(event.key);
  if (!key) return null;
  const tokens: string[] = [];
  if (event.metaKey || event.ctrlKey) tokens.push('mod');
  if (event.altKey) tokens.push('alt');
  if (event.shiftKey) tokens.push('shift');
  tokens.push(key);
  const spec = tokens.join('+');
  return isValidSpec(spec) ? spec : null;
};

/* ── 显示格式化 ───────────────────────────────────────────────────────── */

const KEY_LABELS: Record<string, string> = {
  enter: 'Enter',
  escape: 'Esc',
  esc: 'Esc',
  arrowup: '↑',
  arrowdown: '↓',
  arrowleft: '←',
  arrowright: '→',
  space: '空格',
  tab: 'Tab',
  backspace: 'Backspace',
  delete: 'Del',
  pageup: 'PgUp',
  pagedown: 'PgDn',
  home: 'Home',
  end: 'End',
};

/** 字母键显示成大写；其余按键走 KEY_LABELS。 */
const formatKeyToken = (key: string) => KEY_LABELS[key] || key.toUpperCase();

export const isMacPlatform = () => {
  if (typeof navigator === 'undefined') return false;
  const platform = navigator.platform || '';
  const agent = navigator.userAgent || '';
  return /mac/i.test(platform) || /Macintosh|Mac OS X/i.test(agent);
};

/** 渲染绑定：macOS 显示 ⌘N / ⇧⌘N，其它平台显示 Ctrl+N / Ctrl+Shift+N。 */
export const formatKeys = (spec: string): string => {
  const parsed = parseSpec(spec);
  if (!parsed.key) return '';
  const key = formatKeyToken(parsed.key);
  if (isMacPlatform()) {
    // macOS 习惯把 ⌘ 放最后：⇧⌘N、⌥⌘Enter。
    const prefix = [parsed.ctrl && '⌃', parsed.alt && '⌥', parsed.shift && '⇧', parsed.mod && '⌘']
      .filter(Boolean)
      .join('');
    return prefix + key;
  }
  const prefix = [...new Set([parsed.mod && 'Ctrl', parsed.ctrl && 'Ctrl', parsed.alt && 'Alt', parsed.shift && 'Shift'].filter((token): token is string => Boolean(token)))].join('+');
  return prefix ? `${prefix}+${key}` : key;
};

/* ── 用户改键（按设备持久化） ─────────────────────────────────────────── */

const STORAGE_KEY = 'lawver.shortcuts';
const STORAGE_VERSION = 1;

type Overrides = Record<string, string>;

const readOverrides = (): Overrides => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as { version?: number; bindings?: Overrides };
    if (parsed?.version !== STORAGE_VERSION || !parsed.bindings || typeof parsed.bindings !== 'object') return {};
    const known = new Set(SHORTCUTS.map(item => item.id));
    const next: Overrides = {};
    for (const [id, spec] of Object.entries(parsed.bindings)) {
      if (known.has(id) && typeof spec === 'string' && isValidSpec(spec)) next[id] = spec;
    }
    return next;
  } catch {
    return {};
  }
};

let overrides: Overrides = readOverrides();
const listeners = new Set<() => void>();
let storageBound = false;

const notify = () => listeners.forEach(listener => listener());

const persist = (next: Overrides) => {
  if (typeof window === 'undefined') return;
  try {
    if (Object.keys(next).length) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STORAGE_VERSION, bindings: next }));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // 隐私模式或配额不足：改键只保留在内存里，不回滚用户操作。
  }
};

// 多标签页共享同一份绑定：别的标签改了键，这里跟着更新。
const bindStorageListener = () => {
  if (storageBound || typeof window === 'undefined') return;
  storageBound = true;
  window.addEventListener('storage', event => {
    if (event.key !== STORAGE_KEY) return;
    overrides = readOverrides();
    notify();
  });
};

export const subscribe = (listener: () => void) => {
  bindStorageListener();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** 当前改键快照：引用稳定，供 useSyncExternalStore 直接比较。 */
export const getOverrides = (): Overrides => overrides;

const findDef = (id: string) => SHORTCUTS.find(item => item.id === id);

/** 生效绑定：用户改键优先，其次默认。未知 id 返回空串。 */
export const getBinding = (id: string): string => overrides[id] || findDef(id)?.defaultKeys || '';

/** 是否已被用户改键。 */
export const isOverridden = (id: string) => overrides[id] !== undefined;

/** 同作用域冲突检测：返回第一个撞键的动作，没有则 null。 */
export const findConflict = (id: string, spec: string): ShortcutDef | null => {
  const self = findDef(id);
  if (!self) return null;
  return (
    SHORTCUTS.find(
      item => item.id !== id && item.scope === self.scope && getBinding(item.id) === spec,
    ) || null
  );
};

/** 写入改键；id 未知或按键串非法时返回 false。 */
export const setBinding = (id: string, spec: string): boolean => {
  if (!findDef(id) || !isValidSpec(spec)) return false;
  if (overrides[id] === spec) return true;
  overrides = { ...overrides, [id]: spec };
  persist(overrides);
  notify();
  return true;
};

export const resetBinding = (id: string) => {
  if (overrides[id] === undefined) return;
  const next = { ...overrides };
  delete next[id];
  overrides = next;
  persist(next);
  notify();
};

export const resetAll = () => {
  if (!Object.keys(overrides).length) return;
  overrides = {};
  persist(overrides);
  notify();
};
