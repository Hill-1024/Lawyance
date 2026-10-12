/** 运行事件到可读时间线的折叠规则：只做数据整形，不碰 React（文案走 translate 取当前语言）。 */

import { translate, type MessageKey } from "../i18n";

export type ThoughtBlock = {
  key: number;
  kind: string;
  label: string;
  content: string;
};

// 思考块类型 → 词条键：渲染时取词，切语言后重算（Workbench 的 memo 依赖 t）。
const THOUGHT_LABEL_KEYS: Record<string, MessageKey> = {
  reasoning: "activity.thoughtReasoning",
  draft: "activity.thoughtDraft",
  tool: "activity.thoughtTool",
  plan: "activity.thoughtPlan",
  ocp: "activity.thoughtOcp",
  memory: "activity.thoughtMemory",
};

// 其余可见事件类型也走词条，避免时间线里冒出英文枚举名。
const EVENT_LABEL_KEYS: Record<string, MessageKey> = {
  error: "activity.eventError",
  tool_result: "activity.eventToolResult",
  status: "activity.eventStatus",
  notice: "activity.eventNotice",
  user_choice: "activity.eventChoice",
};

// 无需展示给用户的内部信号：正文增量走 live，确认/选择有专门 UI，签名与记忆候选是管线细节。
export const HIDDEN_EVENT_TYPES = new Set([
  "content",
  "content_replace",
  "history_trace",
  "memory_sync",
  "thought_signature",
  "memory_candidate",
  "done",
  "user_choice_request",
  "confirmation",
]);

// thought 事件是流式增量：mode=new 开新块，append（以及 reasoning/draft 默认）续写当前块。
// 其余可见事件独立成块；文档/建议事件另有专门按钮，不进时间线。
export function aggregateActivity(events: any[]): ThoughtBlock[] {
  const blocks: ThoughtBlock[] = [];
  for (const event of events) {
    if (HIDDEN_EVENT_TYPES.has(event.type)) continue;
    if (event.type === "thought") {
      const kind = THOUGHT_LABEL_KEYS[event.thought_type] ? event.thought_type : "reasoning";
      const append = event.mode === "append" || kind === "reasoning" || kind === "draft";
      const last = blocks[blocks.length - 1];
      if (append && last && last.kind === kind) {
        last.content += event.content || "";
        continue;
      }
      blocks.push({
        key: blocks.length,
        kind,
        label: translate(THOUGHT_LABEL_KEYS[kind] ?? "activity.thoughtReasoning"),
        content: event.content || "",
      });
      continue;
    }
    if (event.type === "document" || event.type === "proposal") continue;
    const content = typeof event.content === "string" ? event.content : "";
    if (!content) continue;
    blocks.push({
      key: blocks.length,
      kind: event.type,
      label: translate(EVENT_LABEL_KEYS[event.type] ?? "activity.eventFallback"),
      content,
    });
  }
  return blocks;
}

// 运行中状态行旁的一句话进度（对齐 legacy 的措辞）。
export function currentActivityLabel(blocks: ThoughtBlock[]): string {
  const block = blocks[blocks.length - 1];
  if (!block) return "";
  if (block.kind === "tool") {
    // 功能性正则：匹配的是后端生成的中文正文（「执行: `工具名`」「工具执行完毕」），
    // 不是界面文案——必须保留中文原文做匹配，只有展示给用户的措辞走词条。
    const match = block.content.match(/执行:\s*`([^`]+)`/);
    if (match) return translate("activity.runningTool", { name: match[1] });
    if (block.content.includes("工具执行完毕")) return translate("activity.runningToolDone");
    return translate("activity.runningCallingTool");
  }
  if (block.kind === "draft") return translate("activity.runningDrafting");
  if (block.kind === "plan") return translate("activity.runningPlanning");
  if (block.kind === "ocp") return translate("activity.runningReviewing");
  return translate("activity.runningAnalyzing");
}
