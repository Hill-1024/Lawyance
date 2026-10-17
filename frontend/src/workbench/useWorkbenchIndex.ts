import { useCallback, useEffect, useRef, useState } from "react";
import { api, cached, Item, Page, remember } from "./client";

/**
 * 工作台索引：项目、会话、文档、技能、插件与庭审目录，带离线缓存回退。
 *
 * 列表走新分页契约：服务端恒返回信封 { items, next_cursor }，按 updated_at desc 排序。
 * 会话与文件是高增长列表：首屏 50 条 + 「加载更多」按游标续拉追加；
 * 项目/技能/插件/庭审低增长，单页 limit=200 拉满即可（仍消费 .items，不提供加载更多）。
 * 任何变更（创建/删除/改名/恢复）后的 reload 恒重拉第一页并重置游标，新条目因此可见。
 *
 * onError 需要是稳定引用（state setter 或 useCallback 包过的函数）：reload 依赖它，
 * reload 又驱动下面的订阅 effect，传一个每次渲染都新建的函数会让索引每次渲染都重新拉取。
 */
const PAGE_SIZE = 50;
const FULL_PAGE = 200;

type Family = "conversations" | "documents";

/** 旧版离线缓存存的是裸数组，读缓存时两种形态都兼容。 */
const pageItems = (page: Page | Item[] | undefined): Item[] =>
  Array.isArray(page) ? page : page?.items || [];

export function useWorkbenchIndex(username: string, onError: (message: string) => void) {
  const [projects, setProjects] = useState<Item[]>([]);
  const [conversations, setConversations] = useState<Item[]>([]);
  const [documents, setDocuments] = useState<Item[]>([]);
  const [skills, setSkills] = useState<Item[]>([]);
  const [connectors, setConnectors] = useState<Item[]>([]);
  const [courtItems, setCourtItems] = useState<Item[]>([]);
  // 会话/文件的续拉游标：state 给按钮可见性，ref 给异步回调读「此刻」的值。
  const [conversationCursor, setConversationCursor] = useState("");
  const [documentCursor, setDocumentCursor] = useState("");
  const conversationCursorRef = useRef("");
  const documentCursorRef = useRef("");
  const [loadingMoreConversations, setLoadingMoreConversations] = useState(false);
  const [loadingMoreDocuments, setLoadingMoreDocuments] = useState(false);
  // reload 轮次号：「加载更多」在途时若发生 reload（变更后重拉第一页），过期响应按轮次丢弃，
  // 否则旧游标的下一页会把刚被第一页重置的列表又追加成混合状态。
  const roundRef = useRef(0);
  const [offline, setOffline] = useState(!navigator.onLine);
  // reload 每次都是 6 个 GET；任务结束、切换会话、上传删除会在同一瞬间触发多次。
  // 在途轮次直接复用、并发进来的调用记为「尾随」待这轮结束后补一轮拿最新数据：
  // 否则 6 连发 ×N 会把限流预算白白烧掉，同出口 IP 的用户一起吃 429。
  const inFlightRef = useRef<Promise<void> | null>(null);
  const trailingRef = useRef(false);
  const reloadRef = useRef<() => Promise<void>>(async () => {});
  const applyCursor = useCallback((family: Family, value: string) => {
    if (family === "conversations") {
      conversationCursorRef.current = value;
      setConversationCursor(value);
    } else {
      documentCursorRef.current = value;
      setDocumentCursor(value);
    }
  }, []);
  const reload = useCallback(async () => {
    if (inFlightRef.current) {
      trailingRef.current = true;
      return inFlightRef.current;
    }
    const currentRound = roundRef.current + 1;
    roundRef.current = currentRound;
    const round = (async () => {
      try {
        const [p, c, d, s, k, courts] = await Promise.all([
          api<Page>(`/projects?limit=${FULL_PAGE}`),
          api<Page>(`/conversations?limit=${PAGE_SIZE}`),
          api<Page>(`/documents?limit=${PAGE_SIZE}`),
          api<Page>(`/skills?limit=${FULL_PAGE}`),
          api<Page>(`/connectors?limit=${FULL_PAGE}`),
          api<Page>(`/courts?limit=${FULL_PAGE}`),
        ]);
        setProjects(p.items);
        // 重拉第一页即重置游标：创建/删除/改名/恢复后的 reload 由此保证新条目可见。
        setConversations(c.items);
        setDocuments(d.items);
        setSkills(s.items);
        setConnectors(k.items);
        setCourtItems(courts.items);
        applyCursor("conversations", c.next_cursor);
        applyCursor("documents", d.next_cursor);
        await remember(username, "index", { p, c, d, s, k, courts });
        setOffline(false);
      } catch (e: any) {
        const cache = await cached<any>(username, "index");
        // 429/5xx 说明服务端可达、网络是通的（限流是常见触发源）：不能当成「离线」，
        // 否则 composer 被离线标记锁死、点发送毫无反应。真离线由 offline 事件驱动。
        const transient = typeof e?.status === "number" && (e.status === 429 || e.status >= 500);
        if (cache) {
          setProjects(pageItems(cache.p));
          setCourtItems(pageItems(cache.courts));
          setConversations(pageItems(cache.c));
          setDocuments(pageItems(cache.d));
          setSkills(pageItems(cache.s));
          setConnectors(pageItems(cache.k));
          // 离线拿不到下一页：游标清空，「加载更多」随之隐藏。
          applyCursor("conversations", "");
          applyCursor("documents", "");
          if (!transient) setOffline(true);
        } else onError(e.message);
      }
    })();
    inFlightRef.current = round.finally(() => {
      inFlightRef.current = null;
      if (trailingRef.current) {
        trailingRef.current = false;
        void reloadRef.current();
      }
    });
    return inFlightRef.current;
  }, [username, onError, applyCursor]);
  /**
   * 按游标续拉下一页并静默追加（按 id 去重，防与并发 reload 的第一页重叠）。
   * 失败保持静默：按钮还在原地，用户可以再点；不弹横幅打断当前工作。
   */
  const loadMore = useCallback(
    async (family: Family) => {
      const cursor = family === "conversations" ? conversationCursorRef.current : documentCursorRef.current;
      if (!cursor) return;
      const seenRound = roundRef.current;
      if (family === "conversations") setLoadingMoreConversations(true);
      else setLoadingMoreDocuments(true);
      try {
        const page = await api<Page>(
          `/${family}?limit=${PAGE_SIZE}&cursor=${encodeURIComponent(cursor)}`,
        );
        if (seenRound !== roundRef.current) return;
        const apply = family === "conversations" ? setConversations : setDocuments;
        apply((old) => {
          const known = new Set(old.map((item) => item.id));
          return [...old, ...page.items.filter((item) => !known.has(item.id))];
        });
        applyCursor(family, page.next_cursor);
      } catch {
        /* 静默：游标未动，按钮可重试。 */
      } finally {
        if (family === "conversations") setLoadingMoreConversations(false);
        else setLoadingMoreDocuments(false);
      }
    },
    [applyCursor],
  );
  const loadMoreConversations = useCallback(() => loadMore("conversations"), [loadMore]);
  const loadMoreDocuments = useCallback(() => loadMore("documents"), [loadMore]);
  useEffect(() => {
    reloadRef.current = reload;
  }, [reload]);
  useEffect(() => {
    void reload();
    const online = () => {
        setOffline(false);
        void reload();
      },
      off = () => setOffline(true);
    const extensions = () => void reload();
    // 设置页等其它表面改了会话归属/归档状态后通知工作台重拉索引，关闭设置时列表已是最新。
    const workbenchUpdated = () => void reload();
    const courtsUpdated = (event: Event) => {
      const detail = (event as CustomEvent<{ user: string; items: Item[] }>).detail;
      if (detail?.user !== username || !detail.items?.length) return;
      setCourtItems((old) => {
        const next = new Map(old.map((item) => [item.id, item]));
        for (const item of detail.items) next.set(item.id, item);
        return [...next.values()];
      });
    };
    window.addEventListener("online", online);
    window.addEventListener("offline", off);
    window.addEventListener("lawver:extensions-updated", extensions);
    window.addEventListener("lawver:courts-updated", courtsUpdated);
    window.addEventListener("lawver:workbench-updated", workbenchUpdated);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", off);
      window.removeEventListener("lawver:extensions-updated", extensions);
      window.removeEventListener("lawver:courts-updated", courtsUpdated);
      window.removeEventListener("lawver:workbench-updated", workbenchUpdated);
    };
  }, [username, reload]);
  return {
    projects,
    conversations,
    documents,
    skills,
    connectors,
    courtItems,
    offline,
    reload,
    /** 会话列表续拉游标：非空表示还有下一页，「加载更多」据此显示。 */
    conversationsCursor: conversationCursor,
    documentsCursor: documentCursor,
    loadingMoreConversations,
    loadingMoreDocuments,
    loadMoreConversations,
    loadMoreDocuments,
  };
}
