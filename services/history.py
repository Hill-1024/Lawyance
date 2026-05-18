"""
模块描述：聊天历史压缩服务，保护 assistant tool_calls 与 tool response 配对。
"""

from typing import List, Optional
import re

from function_calling import call
from prompt_loader import build_system_memory


def assistant_tool_call_ids(message: dict) -> set[str]:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return set()
    ids = set()
    for tool_call in message.get("tool_calls") or []:
        if isinstance(tool_call, dict) and tool_call.get("id"):
            ids.add(str(tool_call["id"]))
    return ids


def tool_response_id(message: dict) -> Optional[str]:
    if not isinstance(message, dict) or message.get("role") != "tool":
        return None
    tool_call_id = message.get("tool_call_id")
    return str(tool_call_id) if tool_call_id else None


def tool_pair_safe_cutoff(messages: List[dict], keep_count: int) -> int:
    cutoff = max(0, len(messages) - keep_count)
    while cutoff > 0:
        kept_tool_ids = {
            tool_id
            for msg in messages[cutoff:]
            for tool_id in [tool_response_id(msg)]
            if tool_id
        }
        if not kept_tool_ids:
            return cutoff

        owner_index = None
        for index in range(cutoff - 1, -1, -1):
            if assistant_tool_call_ids(messages[index]) & kept_tool_ids:
                owner_index = index
                break

        if owner_index is None or owner_index == cutoff:
            return cutoff
        cutoff = owner_index

    return cutoff


def tool_pair_fallback_split(messages: List[dict], keep_count: int) -> tuple[List[dict], List[dict]]:
    keep_start = max(0, len(messages) - keep_count)
    keep_indexes = set(range(keep_start, len(messages)))
    kept_tool_ids = {
        tool_id
        for msg in messages[keep_start:]
        for tool_id in [tool_response_id(msg)]
        if tool_id
    }
    for index, msg in enumerate(messages[:keep_start]):
        if assistant_tool_call_ids(msg) & kept_tool_ids:
            keep_indexes.add(index)
    kept = [msg for index, msg in enumerate(messages) if index in keep_indexes]
    summarized = [msg for index, msg in enumerate(messages) if index not in keep_indexes]
    return summarized, kept


async def compress_history(
    history: List[dict],
    agent_mode: str = "default",
    focus: Optional[list[str]] = None,
    memory_context: str = "",
) -> List[dict]:
    """
    对超出20条范围的记忆上下文启用“摘要 + 最近10条”的压缩方式。
    """
    non_system_msgs = [m for m in history if m.get("role") != "system"]

    if len(non_system_msgs) <= 20:
        return history

    print(f"[历史压缩] 当前消息数 {len(non_system_msgs)} > 20，开始压缩...")

    cutoff = tool_pair_safe_cutoff(non_system_msgs, 10)
    if cutoff == 0:
        print("[历史压缩] 工具调用配对导致安全截断点为0，启用工具对保留 fallback")
        to_summarize, last_10 = tool_pair_fallback_split(non_system_msgs, 10)
    else:
        last_10 = non_system_msgs[cutoff:]
        to_summarize = non_system_msgs[:cutoff]

    summary_prompt = "请简要总结以下对话的核心内容和已达成的共识，以便作为后续对话的上下文参考。注意：只输出纯文本总结，不要包含任何标签（如 <final_answer> 或 <think>）。\n\n"
    for m in to_summarize:
        role = "用户" if m.get("role") == "user" else "助手"
        content = m.get("content") or ""
        summary_prompt += f"{role}: {content[:200]}...\n"

    try:
        summary_messages = build_system_memory(task="history_summary")
        summary_messages.append({"role": "user", "content": summary_prompt})
        summary_res = await call(summary_messages, stream=False, include_tools=False)
        content = summary_res.content or ""
        content = re.sub(r"</?(final_answer|think)[^>]*>", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
        summary_text = f"[前情提要]: {content}"
        print("[历史压缩] 摘要生成成功")

        new_history = build_system_memory(
            agent_mode=agent_mode,
            focus=focus,
            memory_context=memory_context,
        )
        new_history.append({"role": "assistant", "content": summary_text})
        new_history.append({"role": "user", "content": "请继续遵守所有系统约束。以下是对话的继续。"})
        new_history.append({"role": "assistant", "content": "明白，我将继续严格遵守所有约束规则。"})
        new_history.extend(last_10)
        return new_history
    except Exception as e:
        print(f"[历史压缩] 摘要生成失败: {e}，回退到截断模式")
        new_history = build_system_memory(
            agent_mode=agent_mode,
            focus=focus,
            memory_context=memory_context,
        )
        fallback_cutoff = tool_pair_safe_cutoff(non_system_msgs, 20)
        if fallback_cutoff == 0:
            _, fallback_tail = tool_pair_fallback_split(non_system_msgs, 20)
            new_history.extend(fallback_tail)
        else:
            new_history.extend(non_system_msgs[fallback_cutoff:])
        return new_history
