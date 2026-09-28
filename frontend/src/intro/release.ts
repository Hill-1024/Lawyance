/*
 * 模块描述：下载中心页的发布信息数据层（自 lawyance-intro 的 utils/github.ts 移植）。
 * 构建期的镜像/后端/GitHub 三级回退链在客户端收敛为一次后端请求；
 * 任何失败（非 2xx、超时、坏 JSON）都静默回落到静态兜底，hook 永不抛错。
 */

import { useEffect, useState } from "react";
import { apiUrl } from "../services/api";

export interface ReleaseInfo {
  tagName: string;
  htmlUrl: string;
  apkUrl: string;
  apkSize: string;
  publishedAt: string;
}

export const GITHUB_RELEASES_URL = "https://github.com/Hill-1024/Lawyance/releases/latest";

const ANDROID_LATEST_PATH = "/api/releases/android/latest";
const ANDROID_APK_FALLBACK_URL = "https://lawver.dev/api/releases/android/apk";
const REQUEST_TIMEOUT_MS = 6000;

const FALLBACK_RELEASE: ReleaseInfo = {
  tagName: "最新版",
  htmlUrl: GITHUB_RELEASES_URL,
  apkUrl: ANDROID_APK_FALLBACK_URL,
  apkSize: "最新版本",
  publishedAt: "",
};

/** `GET /api/releases/android/latest` 的返回形状。 */
interface BackendReleaseInfo {
  versionName?: string;
  apkUrl?: string;
  size?: number;
  publishedAt?: string;
}

const withTagPrefix = (versionName?: string) => {
  if (!versionName) return FALLBACK_RELEASE.tagName;
  return versionName.startsWith("v") ? versionName : `v${versionName}`;
};

const formatSize = (size?: number) => {
  if (!Number.isFinite(size) || !size) return FALLBACK_RELEASE.apkSize;
  return `${(size / 1048576).toFixed(1)} MB`;
};

// 相对地址按当前站点解析（预览部署即分发自身的 APK 副本），绝对地址原样保留。
const normalizeApkUrl = (apkUrl?: string) => {
  if (!apkUrl) return FALLBACK_RELEASE.apkUrl;
  if (apkUrl.startsWith("http")) return apkUrl;
  try {
    return new URL(apkUrl, window.location.origin).toString();
  } catch {
    return FALLBACK_RELEASE.apkUrl;
  }
};

const toReleaseInfo = (data: BackendReleaseInfo): ReleaseInfo => ({
  tagName: withTagPrefix(data.versionName),
  htmlUrl: GITHUB_RELEASES_URL,
  apkUrl: normalizeApkUrl(data.apkUrl),
  apkSize: formatSize(data.size),
  publishedAt: data.publishedAt ?? "",
});

/** `2026-09-14T16:10:57Z` → `2026年9月14日`；空串或无法解析的输入返回空串。 */
export function formatPublishedAt(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

/** 挂载时请求一次最新 Android 发布信息，6s 超时；失败回落兜底值，绝不抛错。 */
export function useLatestRelease(): ReleaseInfo {
  const [release, setRelease] = useState<ReleaseInfo>(FALLBACK_RELEASE);

  useEffect(() => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let cancelled = false;

    const load = async () => {
      try {
        const response = await fetch(apiUrl(ANDROID_LATEST_PATH), {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Request failed with status ${response.status}`);
        }
        const data = (await response.json()) as BackendReleaseInfo;
        if (!cancelled) setRelease(toReleaseInfo(data));
      } catch {
        if (!cancelled) setRelease(FALLBACK_RELEASE);
      } finally {
        clearTimeout(timeoutId);
      }
    };

    void load();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
      controller.abort();
    };
  }, []);

  return release;
}
