"""
模块描述：单条工具返回过大时压缩为摘要，避免 tool 消息撑爆模型输入窗口。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from context_usage import (
    TOOL_RESULT_COMPRESSION_THRESHOLD_TOKENS,
    TOOL_RESULT_SUMMARY_INPUT_TOKEN_BUDGET,
    TOOL_RESULT_SUMMARY_TARGET_TOKENS,
    estimate_text_tokens,
    trim_text_to_token_budget,
)
from function_calling import call
from prompt_loader import build_system_memory


logger = logging.getLogger(__name__)

_SKIP_TOOLS = frozenset({
    "submit_plan",
    "submit_final_answer",
    "ask_user",
})

_SUMMARY_PREFIX_RE = re.compile(r"^\[工具结果摘要\b")


def should_compress_tool_result(
    content: str,
    *,
    tool_name: str = "",
    threshold_tokens: int = TOOL_RESULT_COMPRESSION_THRESHOLD_TOKENS,
) -> tuple[bool, int]:
    if tool_name in _SKIP_TOOLS:
        return False, 0
    text = str(content or "")
    if not text or _SUMMARY_PREFIX_RE.match(text):
        return False, 0
    tokens = estimate_text_tokens(text)
    return tokens > threshold_tokens, tokens


def _build_summary_prompt(tool_name: str, content: str, original_tokens: int) -> str:
    clipped = trim_text_to_token_budget(content, TOOL_RESULT_SUMMARY_INPUT_TOKEN_BUDGET)
    truncated_note = ""
    if clipped != content:
        truncated_note = (
            f"\n（注：原文约 {original_tokens} tokens，送入摘要模型前已截到"
            f" {TOOL_RESULT_SUMMARY_INPUT_TOKEN_BUDGET} tokens。）\n"
        )
    return (
        f"下列是工具 `{tool_name or 'unknown'}` 的返回结果，原文过大"
        f"（约 {original_tokens} tokens）。请压缩为后续 agent 可继续执行的摘要。\n"
        f"要求：\n"
        f"1. 只输出摘要正文，不要 Markdown 标题、标签或解释。\n"
        f"2. 保留关键结论、法条/案例名称与条号、管辖地、关键数字、来源链接/标识、错误信息。\n"
        f"3. 去掉重复列表项与无关噪声；控制在约 {TOOL_RESULT_SUMMARY_TARGET_TOKENS} tokens 以内。\n"
        f"{truncated_note}\n"
        f"==== 工具结果原文 ====\n"
        f"{clipped}\n"
    )


def _format_summary(tool_name: str, original_tokens: int, summary: str) -> str:
    body = trim_text_to_token_budget(summary.strip(), TOOL_RESULT_SUMMARY_TARGET_TOKENS)
    if not body:
        body = "（摘要为空）"
    return (
        f"[工具结果摘要 | tool={tool_name or 'unknown'} | original_tokens={original_tokens}]\n"
        f"{body}"
    )


def _fallback_summary(tool_name: str, content: str, original_tokens: int) -> str:
    clipped = trim_text_to_token_budget(content, TOOL_RESULT_SUMMARY_TARGET_TOKENS)
    return (
        f"[工具结果摘要 | tool={tool_name or 'unknown'} | original_tokens={original_tokens} | mode=truncate]\n"
        f"{clipped}\n"
        f"[... 原文过大，摘要失败，已截断保留前部 ...]"
    )


async def maybe_compress_tool_result(
    tool_name: str,
    content: Any,
    *,
    threshold_tokens: int = TOOL_RESULT_COMPRESSION_THRESHOLD_TOKENS,
) -> str:
    """若工具返回超过阈值，调用 LLM 生成摘要；否则原样返回字符串。"""
    text = str(content or "")
    should_compress, original_tokens = should_compress_tool_result(
        text,
        tool_name=tool_name,
        threshold_tokens=threshold_tokens,
    )
    if not should_compress:
        return text

    logger.info(
        "[工具结果压缩] tool=%s tokens=%s > %s，开始摘要",
        tool_name,
        original_tokens,
        threshold_tokens,
    )
    prompt = _build_summary_prompt(tool_name, text, original_tokens)
    try:
        messages = build_system_memory(task="history_summary")
        messages.append({"role": "user", "content": prompt})
        response = await call(messages, stream=False, include_tools=False)
        summary = re.sub(
            r"</?(final_answer|think)[^>]*>",
            "",
            str(getattr(response, "content", None) or ""),
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        if not summary:
            raise ValueError("empty tool-result summary")
        compressed = _format_summary(tool_name, original_tokens, summary)
        logger.info(
            "[工具结果压缩] tool=%s 完成 original=%s compressed≈%s",
            tool_name,
            original_tokens,
            estimate_text_tokens(compressed),
        )
        return compressed
    except Exception as exc:
        logger.warning("[工具结果压缩] tool=%s 摘要失败，回退截断: %s", tool_name, exc)
        return _fallback_summary(tool_name, text, original_tokens)
