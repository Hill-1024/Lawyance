"""
模块描述：聊天历史压缩服务，保护 assistant tool_calls 与 tool response 配对。
"""

from typing import Any, List, Optional
import re

from function_calling import call
from prompt_loader import build_system_memory
from services.context_usage import (
    CONTEXT_COMPRESSION_THRESHOLD_TOKENS,
    CONTEXT_RECENT_RETENTION_TOKENS,
    HISTORY_SUMMARY_INPUT_TOKEN_BUDGET,
    estimate_context_tokens,
    estimate_message_tokens,
    estimate_text_tokens,
    trim_text_to_token_budget,
)


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


def _role_label(message: dict[str, Any]) -> str:
    role = message.get("role")
    if role == "user":
        return "用户"
    if role == "assistant":
        return "助手"
    if role == "tool":
        return "工具"
    return str(role or "消息")


def _tool_call_names(message: dict[str, Any]) -> str:
    names = []
    for tool_call in message.get("tool_calls") or []:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if isinstance(function, dict) and function.get("name"):
            names.append(str(function["name"]))
    return ", ".join(names)


def _summary_header(message: dict[str, Any]) -> str:
    header = _role_label(message)
    details = []
    tool_names = _tool_call_names(message)
    if tool_names:
        details.append(f"tool_calls={tool_names}")
    if message.get("tool_call_id"):
        details.append(f"tool_call_id={message.get('tool_call_id')}")
    if details:
        header += f" [{'; '.join(details)}]"
    return header


def _summary_block(message: dict[str, Any]) -> str:
    return f"{_summary_header(message)}: {message.get('content') or ''}\n"


def build_summary_prompt(messages: List[dict], token_budget: int = HISTORY_SUMMARY_INPUT_TOKEN_BUDGET) -> str:
    prompt = (
        "请总结以下较早对话的关键事实、用户意图、已经完成的工具调用结果、仍需遵守的约束和未解决问题，"
        "以便作为后续对话的上下文参考。只输出纯文本总结，不要包含任何标签（如 <final_answer> 或 <think>）。\n\n"
    )
    remaining = max(token_budget - estimate_text_tokens(prompt), 0)
    transcript_parts: list[str] = []

    for message in messages:
        block = _summary_block(message)
        block_tokens = estimate_text_tokens(block)
        if block_tokens <= remaining:
            transcript_parts.append(block)
            remaining -= block_tokens
            continue

        header = f"{_summary_header(message)}: "
        marker = "\n[该条消息因摘要输入预算截断]\n"
        overhead = estimate_text_tokens(header + marker)
        clipped = trim_text_to_token_budget(str(message.get("content") or ""), max(remaining - overhead, 0))
        if clipped:
            transcript_parts.append(f"{header}{clipped}{marker}")
        break

    if transcript_parts:
        return prompt + "".join(transcript_parts)
    return prompt + "[较早对话过长，已无法在摘要输入预算内展开原文。请基于后续保留消息继续。]\n"


def split_by_recent_token_budget(
    messages: List[dict],
    token_budget: int = CONTEXT_RECENT_RETENTION_TOKENS,
) -> tuple[List[dict], List[dict]]:
    if not messages:
        return [], []

    total = 0
    keep_count = 0
    for message in reversed(messages):
        message_tokens = estimate_message_tokens(message)
        if keep_count > 0 and total + message_tokens > token_budget:
            break
        total += message_tokens
        keep_count += 1
        if total >= token_budget:
            break

    keep_count = max(1, keep_count)
    cutoff = tool_pair_safe_cutoff(messages, keep_count)
    if cutoff == 0 and keep_count < len(messages):
        return tool_pair_fallback_split(messages, keep_count)
    return messages[:cutoff], messages[cutoff:]


def should_compress_history(
    history: List[dict],
    *,
    current_user_content: str = "",
    last_context_tokens: Optional[int] = None,
) -> tuple[bool, str, int]:
    estimated_history = list(history)
    if current_user_content:
        estimated_history.append({"role": "user", "content": current_user_content})
    estimated_tokens = estimate_context_tokens(estimated_history)

    if last_context_tokens is not None and last_context_tokens > CONTEXT_COMPRESSION_THRESHOLD_TOKENS:
        return True, f"上一轮 prompt_tokens={last_context_tokens}", estimated_tokens
    if estimated_tokens > CONTEXT_COMPRESSION_THRESHOLD_TOKENS:
        return True, f"本地估算 tokens={estimated_tokens}", estimated_tokens
    return False, "", estimated_tokens


async def compress_history(
    history: List[dict],
    agent_mode: str = "default",
    focus: Optional[list[str]] = None,
    memory_context: str = "",
    current_user_content: str = "",
    last_context_tokens: Optional[int] = None,
) -> List[dict]:
    """
    对超过上下文 token 阈值的历史启用“摘要 + token 预算近期上下文”的压缩方式。
    """
    non_system_msgs = [m for m in history if m.get("role") != "system"]

    should_compress, reason, estimated_tokens = should_compress_history(
        history,
        current_user_content=current_user_content,
        last_context_tokens=last_context_tokens,
    )
    if not should_compress:
        return history

    print(
        "[历史压缩] "
        f"{reason} > {CONTEXT_COMPRESSION_THRESHOLD_TOKENS}，开始压缩..."
        f" 本地估算={estimated_tokens}"
    )

    to_summarize, recent_messages = split_by_recent_token_budget(non_system_msgs)
    if not to_summarize:
        print("[历史压缩] 没有可安全摘要的较早消息，跳过压缩")
        return history

    summary_prompt = build_summary_prompt(to_summarize)

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
        new_history.extend(recent_messages)
        return new_history
    except Exception as e:
        print(f"[历史压缩] 摘要生成失败: {e}，回退到截断模式")
        new_history = build_system_memory(
            agent_mode=agent_mode,
            focus=focus,
            memory_context=memory_context,
        )
        _, fallback_tail = split_by_recent_token_budget(non_system_msgs)
        new_history.extend(fallback_tail)
        return new_history
