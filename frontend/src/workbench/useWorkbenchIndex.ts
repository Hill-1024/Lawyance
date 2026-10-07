import { useCallback, useEffect, useRef, useState } from "react";
import { api, cached, Item, remember } from "./client";

/**
 * 工作台索引：项目、会话、文档、技能、插件与庭审目录，带离线缓存回退。
 *
 * onError 需要是稳定引用（state setter 或 useCallback 包过的函数）：reload 依赖它，
 * reload 又驱动下面的订阅 effect，传一个每次渲染都新建的函数会让索引每次渲染都重新拉取。
 */
export function useWorkbenchIndex(username: string, onError: (message: string) => void) {
  const [projects, setProjects] = useState<Item[]>([]);
  const [conversations, setConversations] = useState<Item[]>([]);
  const [documents, setDocuments] = useState<Item[]>([]);
  const [skills, setSkills] = useState<Item[]>([]);
  const [connectors, setConnectors] = useState<Item[]>([]);
  const [courtItems, setCourtItems] = useState<Item[]>([]);
  const [offline, setOffline] = useState(!navigator.onLine);
  // reload 每次都是 6 个 GET；任务结束、切换会话、上传删除会在同一瞬间触发多次。
  // 在途轮次直接复用、并发进来的调用记为「尾随」待这轮结束后补一轮拿最新数据：
  // 否则 6 连发 ×N 会把限流预算白白烧掉，同出口 IP 的用户一起吃 429。
  const inFlightRef = useRef<Promise<void> | null>(null);
  const trailingRef = useRef(false);
  const reloadRef = useRef<() => Promise<void>>(async () => {});
  const reload = useCallback(async () => {
    if (inFlightRef.current) {
      trailingRef.current = true;
      return inFlightRef.current;
    }
    const round = (async () => {
      try {
        const [p, c, d, s, k, courts] = await Promise.all([
          api<Item[]>("/projects"),
          api<Item[]>("/conversations"),
          api<Item[]>("/documents"),
          api<Item[]>("/skills"),
          api<Item[]>("/connectors"),
          api<Item[]>("/courts"),
        ]);
        setProjects(p);
        setCourtItems(courts);
        setConversations(c);
        setDocuments(d);
        setSkills(s);
        setConnectors(k);
        await remember(username, "index", { p, c, d, s, k, courts });
        setOffline(false);
      } catch (e: any) {
        const cache = await cached<any>(username, "index");
        // 429/5xx 说明服务端可达、网络是通的（限流是常见触发源）：不能当成「离线」，
        // 否则 composer 被离线标记锁死、点发送毫无反应。真离线由 offline 事件驱动。
        const transient = typeof e?.status === "number" && (e.status === 429 || e.status >= 500);
        if (cache) {
          setProjects(cache.p);
          setCourtItems(cache.courts || []);
          setConversations(cache.c);
          setDocuments(cache.d);
          setSkills(cache.s);
          setConnectors(cache.k);
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
  }, [username, onError]);
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
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", off);
      window.removeEventListener("lawver:extensions-updated", extensions);
      window.removeEventListener("lawver:courts-updated", courtsUpdated);
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
  };
}
