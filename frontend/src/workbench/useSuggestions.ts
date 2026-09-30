import { useState } from "react";
import { useT, type Translator } from "../i18n";
import { api } from "./client";

export type SuggestionItem = { title: string; prompt: string };

// 首页建议的本地兜底：后端不可达或离线时仍然给得出可点的入口。
/**
 * 首页建议的本地兜底（后端不可达/离线时仍给得出可点的入口）。
 * 写成函数而不是常量：常量会在模块加载时固定成一种语言。
 */
export const suggestionFallback = (t: Translator): SuggestionItem[] => [
  { title: t("suggestion.review"), prompt: t("suggestion.reviewPrompt") },
  { title: t("suggestion.timeline"), prompt: t("suggestion.timelinePrompt") },
  { title: t("suggestion.issues"), prompt: t("suggestion.issuesPrompt") },
];

/** 首页工作建议：按空间缓存，换一批强制重生成；任何失败都退回本地静态建议。 */
export function useSuggestions() {
  const { t } = useT();
  const [cache, setCache] = useState<Record<string, SuggestionItem[]>>({});
  const [loadingSpace, setLoadingSpace] = useState("");
  async function load(space: string, refresh: boolean) {
    setLoadingSpace(space);
    try {
      const data = await api<{ items: SuggestionItem[]; degraded: boolean }>(
        "/suggestions",
        "POST",
        { project_id: space === "personal" ? undefined : space, refresh },
      );
      setCache((prev) => ({
        ...prev,
        [space]: data.items?.length ? data.items : suggestionFallback(t),
      }));
    } catch {
      setCache((prev) => ({ ...prev, [space]: suggestionFallback(t) }));
    } finally {
      setLoadingSpace((current) => (current === space ? "" : current));
    }
  }
  return {
    /** 该空间的建议；尚未取回时用兜底池，避免出现空档。 */
    itemsFor: (space: string) => cache[space] || suggestionFallback(t),
    loaded: (space: string) => !!cache[space],
    loading: (space: string) => loadingSpace === space,
    load,
  };
}
