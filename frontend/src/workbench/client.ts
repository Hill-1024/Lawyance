import { apiFetch } from "../services/api";
import { describeHttpErrorBody } from "../lib/http-error";
import { UserFacingError } from "../lib/errors";
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
export class Conflict extends UserFacingError {
  current?: Item;
  /** 触发冲突的 HTTP 状态码：429/5xx 是瞬态失败，调用方据此不当离线/不当会话失效。 */
  status?: number;
  constructor(message: string, current?: Item, status?: number) {
    super(message);
    this.current = current;
    this.status = status;
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
    // body 只能读一次：解析出的 JSON 既取 detail.current（409 冲突恢复），也供文案解析；
    // 非 JSON 错误体（限流 429、网关页）按状态码映射本地化文案，
    // 不再把服务端限流兜底成「网络请求失败」。
    const raw: unknown = await res.json().catch(() => null);
    const detail = (raw as { detail?: { current?: Item } } | null)?.detail;
    throw new Conflict(describeHttpErrorBody(res, raw), detail?.current, res.status);
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
