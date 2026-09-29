import { useState } from "react";
import { api } from "./client";

export type SuggestionItem = { title: string; prompt: string };

// 首页建议的本地兜底：后端不可达或离线时仍然给得出可点的入口。
export const SUGGESTION_FALLBACK: SuggestionItem[] = [
  {
    title: "审查合同风险条款",
    prompt: "请审查当前材料中的合同条款，列出对我方不利的条款、风险等级和修改建议。",
  },
  {
    title: "梳理案件时间线",
    prompt: "请根据现有材料梳理事发时间线，标注每处事实的来源与需要进一步核实的部分。",
  },
  {
    title: "归纳争议焦点",
    prompt: "请归纳本案的争议焦点，分别列出双方可能的主张与依据。",
  },
];

/** 首页工作建议：按空间缓存，换一批强制重生成；任何失败都退回本地静态建议。 */
export function useSuggestions() {
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
        [space]: data.items?.length ? data.items : SUGGESTION_FALLBACK,
      }));
    } catch {
      setCache((prev) => ({ ...prev, [space]: SUGGESTION_FALLBACK }));
    } finally {
      setLoadingSpace((current) => (current === space ? "" : current));
    }
  }
  return {
    /** 该空间的建议；尚未取回时用兜底池，避免出现空档。 */
    itemsFor: (space: string) => cache[space] || SUGGESTION_FALLBACK,
    loaded: (space: string) => !!cache[space],
    loading: (space: string) => loadingSpace === space,
    load,
  };
}
