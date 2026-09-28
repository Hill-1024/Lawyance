"""
模块描述：上下文 token 用量配置、估算与单轮 LLM 调用 usage 累加器。

中性共享模块：agents/、function_calling 与 services/ 都直接复用，
避免 agent 循环反向依赖 services/。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
import re
from typing import Any


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = int(raw_value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


CONTEXT_WINDOW_TOKENS = _positive_int_env("CONTEXT_WINDOW_TOKENS", 1_000_000)
CONTEXT_COMPRESSION_THRESHOLD_TOKENS = _positive_int_env(
    "CONTEXT_COMPRESSION_THRESHOLD_TOKENS",
    500_000,
)
CONTEXT_RECENT_RETENTION_TOKENS = _positive_int_env(
    "CONTEXT_RECENT_RETENTION_TOKENS",
    250_000,
)
HISTORY_SUMMARY_INPUT_TOKEN_BUDGET = _positive_int_env(
    "HISTORY_SUMMARY_INPUT_TOKEN_BUDGET",
    120_000,
)

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_WHITESPACE_RE = re.compile(r"\s+")


def _usage_field(value: Any, field_name: str, default=0):
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def extract_cache_stats(usage: Any) -> tuple[int, int, int]:
    if usage is None:
        return 0, 0, 0

    prompt = _usage_field(usage, "prompt_tokens", 0) or 0
    details = _usage_field(usage, "prompt_tokens_details", None)
    cached = _usage_field(details, "cached_tokens", 0) or 0
    if not cached:
        cached = _usage_field(usage, "prompt_cache_hit_tokens", 0) or 0
    if not cached:
        cached = _usage_field(usage, "cache_read_input_tokens", 0) or 0

    miss = max(prompt - cached, 0)
    return int(prompt), int(cached), int(miss)


def estimate_text_tokens(value: Any) -> int:
    text = "" if value is None else str(value)
    if not text:
        return 0

    cjk_count = len(_CJK_RE.findall(text))
    non_cjk = _CJK_RE.sub("", text)
    compact_non_cjk = _WHITESPACE_RE.sub(" ", non_cjk)
    non_cjk_tokens = max((len(compact_non_cjk) + 3) // 4, 0)
    return cjk_count + non_cjk_tokens


def estimate_message_tokens(message: dict[str, Any]) -> int:
    if not isinstance(message, dict):
        return 0

    total = 4
    total += estimate_text_tokens(message.get("role") or "")
    total += estimate_text_tokens(message.get("content") or "")

    for key in ("name", "tool_call_id", "reasoning_content"):
        if message.get(key):
            total += estimate_text_tokens(message.get(key))

    tool_calls = message.get("tool_calls")
    if tool_calls:
        total += estimate_text_tokens(json.dumps(tool_calls, ensure_ascii=False, sort_keys=True))

    return total


def estimate_context_tokens(messages: list[dict[str, Any]]) -> int:
    return 3 + sum(estimate_message_tokens(message) for message in messages)


def trim_text_to_token_budget(text: str, token_budget: int) -> str:
    if token_budget <= 0 or not text:
        return ""
    if estimate_text_tokens(text) <= token_budget:
        return text

    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_text_tokens(text[:mid]) <= token_budget:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip()


@dataclass
class ContextUsageAccumulator:
    prompt_tokens: int = 0
    cached_tokens: int = 0
    cache_miss_tokens: int = 0

    def record(self, prompt_tokens: int, cached_tokens: int = 0, cache_miss_tokens: int = 0) -> None:
        if prompt_tokens <= 0:
            return
        if prompt_tokens >= self.prompt_tokens:
            self.prompt_tokens = int(prompt_tokens)
            self.cached_tokens = int(cached_tokens or 0)
            self.cache_miss_tokens = int(cache_miss_tokens or max(prompt_tokens - cached_tokens, 0))

    def payload(self) -> dict[str, int | bool] | None:
        if self.prompt_tokens <= 0:
            return None
        return context_usage_payload(
            self.prompt_tokens,
            cached_tokens=self.cached_tokens,
            cache_miss_tokens=self.cache_miss_tokens,
        )


_current_context_usage: ContextVar[ContextUsageAccumulator | None] = ContextVar(
    "current_context_usage",
    default=None,
)


def set_current_context_usage_accumulator():
    accumulator = ContextUsageAccumulator()
    token = _current_context_usage.set(accumulator)
    return token, accumulator


def reset_current_context_usage_accumulator(token) -> None:
    _current_context_usage.reset(token)


def record_context_usage(prompt_tokens: int, cached_tokens: int = 0, cache_miss_tokens: int = 0) -> None:
    accumulator = _current_context_usage.get()
    if accumulator is not None:
        accumulator.record(prompt_tokens, cached_tokens, cache_miss_tokens)


def record_openai_usage(usage: Any) -> tuple[int, int, int]:
    prompt, cached, miss = extract_cache_stats(usage)
    record_context_usage(prompt, cached, miss)
    return prompt, cached, miss


def context_usage_payload(
    prompt_tokens: int,
    *,
    cached_tokens: int = 0,
    cache_miss_tokens: int = 0,
) -> dict[str, int | bool]:
    prompt_tokens = int(prompt_tokens or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": int(cached_tokens or 0),
        "cache_miss_tokens": int(cache_miss_tokens or max(prompt_tokens - cached_tokens, 0)),
        "threshold_tokens": CONTEXT_COMPRESSION_THRESHOLD_TOKENS,
        "max_context_tokens": CONTEXT_WINDOW_TOKENS,
        "over_threshold": prompt_tokens > CONTEXT_COMPRESSION_THRESHOLD_TOKENS,
    }
