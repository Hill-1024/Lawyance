import { Item } from "./client";

/** 会话标签页模型：一个空间（个人工作区/项目）一套标签，标签只表示会话与庭审。 */
export type TabKind = "conversation" | "court" | "new";
export type TabRef = {
  kind: TabKind;
  id: string;
  /** 该标签打开的文档：一个标签同时只显示一篇，切换标签即随之切换。 */
  doc?: string;
  /** 文档窗格被收起（会话全屏）时仍保持打开，只是不显示。 */
  docHidden?: boolean;
};
export type TabBook = Record<string, TabRef[]>;

export const PERSONAL = "personal";

export function spaceKey(projectId?: string) {
  return projectId || PERSONAL;
}

export function tabKey(tab: TabRef) {
  return tab.kind + ":" + tab.id;
}

export function newTabKey() {
  return "new:";
}

function storageKey(user: string) {
  return "lawver.tabs:" + user;
}

function valid(tab: any): tab is TabRef {
  return (
    !!tab &&
    typeof tab === "object" &&
    ["conversation", "court", "new"].includes(tab.kind) &&
    typeof tab.id === "string" &&
    (tab.kind === "new" ? tab.id === "" : !!tab.id)
  );
}

export function loadTabs(user: string): TabBook {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(user)) || "null");
    if (!saved || typeof saved !== "object") return {};
    const book: TabBook = {};
    for (const [space, tabs] of Object.entries(saved)) {
      if (!Array.isArray(tabs)) continue;
      const seen = new Set<string>();
      const kept: TabRef[] = [];
      for (const tab of tabs) {
        if (!valid(tab) || seen.has(tabKey(tab))) continue;
        seen.add(tabKey(tab));
        kept.push({
          kind: tab.kind,
          id: tab.id,
          doc: typeof tab.doc === "string" ? tab.doc : undefined,
          docHidden: tab.docHidden ? true : undefined,
        });
      }
      book[space] = kept;
    }
    return book;
  } catch {
    // 标签是导航状态，读不出来就当没存过，不阻塞工作台。
    return {};
  }
}

export function saveTabs(user: string, book: TabBook) {
  try {
    localStorage.setItem(storageKey(user), JSON.stringify(book));
  } catch {
    /* 存不下时本次会话内存里的标签仍然可用。 */
  }
}

export function tabsOf(book: TabBook, space: string): TabRef[] {
  return book[space] || [];
}

function write(book: TabBook, space: string, tabs: TabRef[]): TabBook {
  return { ...book, [space]: tabs };
}

export function withTabs(book: TabBook, space: string, tabs: TabRef[]): TabBook {
  return write(book, space, tabs);
}

/** 会话标签去重的唯一入口：同 kind+id 只保留一个，返回原数组表示已存在。 */
export function ensureTab(book: TabBook, space: string, tab: TabRef): TabBook {
  const tabs = tabsOf(book, space);
  const key = tabKey(tab);
  const index = tabs.findIndex((t) => tabKey(t) === key);
  if (index < 0) return write(book, space, [...tabs, tab]);
  const merged = { ...tabs[index], ...tab, doc: tab.doc ?? tabs[index].doc };
  if (JSON.stringify(merged) === JSON.stringify(tabs[index])) return book;
  return write(book, space, tabs.map((t, i) => (i === index ? merged : t)));
}

export function patchTab(
  book: TabBook,
  space: string,
  key: string,
  patch: Partial<TabRef>,
): TabBook {
  const tabs = tabsOf(book, space);
  const index = tabs.findIndex((t) => tabKey(t) === key);
  if (index < 0) return book;
  const next = { ...tabs[index], ...patch };
  for (const field of ["doc", "docHidden"] as const)
    if (next[field] === undefined) delete next[field];
  return write(book, space, tabs.map((t, i) => (i === index ? next : t)));
}

export function removeTab(book: TabBook, space: string, key: string): TabBook {
  const tabs = tabsOf(book, space).filter((t) => tabKey(t) !== key);
  // 每个空间至少留一个「新会话」标签，关掉最后一个也不留空白。
  return write(book, space, tabs.length ? tabs : [{ kind: "new", id: "" }]);
}

export function reorderTabs(
  book: TabBook,
  space: string,
  from: number,
  to: number,
): TabBook {
  const tabs = [...tabsOf(book, space)];
  if (from === to || from < 0 || to < 0 || from >= tabs.length || to >= tabs.length)
    return book;
  const [moved] = tabs.splice(from, 1);
  tabs.splice(to, 0, moved);
  return write(book, space, tabs);
}

export function moveTabToSpace(book: TabBook, from: string, to: string, key: string) {
  const tab = tabsOf(book, from).find((t) => tabKey(t) === key);
  if (!tab) return book;
  return ensureTab(removeTab(book, from, key), to, tab);
}

/** 会话/庭审被删除后剔除对应标签；空间列表为空时补一个新会话标签。 */
export function purgeTabs(
  book: TabBook,
  space: string,
  alive: (tab: TabRef) => boolean,
): TabBook {
  const tabs = tabsOf(book, space);
  const kept = tabs.filter((tab) => tab.kind === "new" || alive(tab));
  if (kept.length === tabs.length) return book;
  return write(book, space, kept.length ? kept : [{ kind: "new", id: "" }]);
}

export function findTab(book: TabBook, space: string, key: string) {
  return tabsOf(book, space).find((tab) => tabKey(tab) === key);
}

export function tabTitle(
  tab: TabRef,
  conversations: Item[],
  courts: Item[],
): string {
  if (tab.kind === "new") return "新会话";
  const pool = tab.kind === "court" ? courts : conversations;
  return pool.find((item) => item.id === tab.id)?.title || (tab.kind === "court" ? "模拟庭审" : "会话");
}
