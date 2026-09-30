import { apiFetch } from "../services/api";
export type Item = {
  id: string;
  kind: string;
  title: string;
  project_id?: string;
  parent_id?: string;
  revision: number;
  updated_at: string;
  data: Record<string, any>;
};
export type Reference = {
  kind: "document" | "selection" | "region" | "folder" | "skill" | "connector";
  id: string;
  revision?: number;
  title?: string;
  text?: string;
  anchor?: any;
  page?: number;
  rect?: number[];
  rotation?: number;
  tools?: string[];
};
export class Conflict extends Error {
  current?: Item;
  constructor(message: string, current?: Item) {
    super(message);
    this.current = current;
  }
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
  key?: string,
): Promise<T> {
  const res = await apiFetch("/api/workbench" + path, {
    method,
    headers: {
      ...(body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(key ? { "Idempotency-Key": key } : {}),
    },
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "网络请求失败" }));
    const detail = error.detail;
    throw new Conflict(
      typeof detail === "string" ? detail : detail?.message || "请求失败",
      detail?.current,
    );
  }
  return res.json();
}
export async function binary(id: string, exportWord = false) {
  const r = await apiFetch(
    `/api/workbench/documents/${id}/${exportWord ? "export" : "blob"}`,
  );
  if (!r.ok) throw new Error("无法读取文件");
  return r.blob();
}
export { downloadWorkbenchFile as download } from "../lib/download";
let db: Promise<IDBDatabase>;
function cacheDB() {
  return (db ??= new Promise((resolve, reject) => {
    const r = indexedDB.open("LawverWorkbenchCache", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("cache");
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  }));
}
export async function cached<T>(
  user: string,
  key: string,
): Promise<T | undefined> {
  const d = await cacheDB();
  return new Promise((resolve, reject) => {
    const r = d.transaction("cache").objectStore("cache").get(`${user}:${key}`);
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
export async function remember(user: string, key: string, value: unknown) {
  const d = await cacheDB();
  return new Promise<void>((resolve, reject) => {
    const tx = d.transaction("cache", "readwrite");
    tx.objectStore("cache").put(value, `${user}:${key}`);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
/**
 * 任务模板：id 是稳定标识（后端与快捷键都按它引用），文案在渲染时取词条，
 * 否则切语言后模板名会停在加载时的语言。
 */
export const templates = [
  { id: "review", titleKey: "template.review", textKey: "template.reviewText" },
  { id: "organize", titleKey: "template.organize", textKey: "template.organizeText" },
  { id: "draft", titleKey: "template.draft", textKey: "template.draftText" },
] as const;
export const withoutTitle = (refs: Reference[]) =>
  refs.map(({ title, ...ref }) => ref);
