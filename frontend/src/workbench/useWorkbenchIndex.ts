import { useEffect, useState } from "react";
import { api, cached, Item, remember } from "./client";

/** 工作台索引：项目、会话、文档、技能、插件与庭审目录，带离线缓存回退。 */
export function useWorkbenchIndex(username: string, onError: (message: string) => void) {
  const [projects, setProjects] = useState<Item[]>([]);
  const [conversations, setConversations] = useState<Item[]>([]);
  const [documents, setDocuments] = useState<Item[]>([]);
  const [skills, setSkills] = useState<Item[]>([]);
  const [connectors, setConnectors] = useState<Item[]>([]);
  const [courtItems, setCourtItems] = useState<Item[]>([]);
  const [offline, setOffline] = useState(!navigator.onLine);
  async function reload() {
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
      if (cache) {
        setProjects(cache.p);
        setCourtItems(cache.courts || []);
        setConversations(cache.c);
        setDocuments(cache.d);
        setSkills(cache.s);
        setConnectors(cache.k);
        setOffline(true);
      } else onError(e.message);
    }
  }
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
  }, [username]);
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
