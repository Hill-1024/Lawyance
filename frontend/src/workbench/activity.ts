/** 运行事件到可读时间线的折叠规则：只做数据整形，不碰 React。 */

export type ThoughtBlock = {
  key: number;
  kind: string;
  label: string;
  content: string;
};

export const THOUGHT_LABELS: Record<string, string> = {
  reasoning: "思考",
  draft: "初稿",
  tool: "工具",
  plan: "计划",
  ocp: "输出审查",
  memory: "记忆",
};

// 其余可见事件类型也走中文，避免时间线里冒出英文枚举名。
const EVENT_LABELS: Record<string, string> = {
  error: "错误",
  tool_result: "工具结果",
  status: "状态",
  notice: "提示",
  user_choice: "选择",
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
      const kind = THOUGHT_LABELS[event.thought_type] ? event.thought_type : "reasoning";
      const append = event.mode === "append" || kind === "reasoning" || kind === "draft";
      const last = blocks[blocks.length - 1];
      if (append && last && last.kind === kind) {
        last.content += event.content || "";
        continue;
      }
      blocks.push({
        key: blocks.length,
        kind,
        label: THOUGHT_LABELS[kind],
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
      label: EVENT_LABELS[event.type] || "执行",
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
    const match = block.content.match(/执行:\s*`([^`]+)`/);
    if (match) return "正在执行 " + match[1];
    if (block.content.includes("工具执行完毕")) return "正在生成最终回复";
    return "正在调用工具";
  }
  if (block.kind === "draft") return "正在拟定回答初稿";
  if (block.kind === "plan") return "正在规划执行步骤";
  if (block.kind === "ocp") return "正在审查输出";
  return "正在分析问题";
}
