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
export const templates = [
  {
    id: "review",
    title: "审查合同",
    text: "请审查所引用的合同，逐项说明风险、依据，并提出可审阅的修改建议。",
  },
  {
    id: "organize",
    title: "整理材料",
    text: "请整理所引用的材料，形成事实时间线、争点及待补充的证据清单。",
  },
  {
    id: "draft",
    title: "起草文书",
    text: "请根据所引用的材料起草一份文书。文书类型：\n诉求：\n需要特别注意：",
  },
];
export const withoutTitle = (refs: Reference[]) =>
  refs.map(({ title, ...ref }) => ref);
