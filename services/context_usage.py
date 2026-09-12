"""
模块描述：services.context_usage 兼容转发层，实现已迁至中性模块 context_usage。

保留此 shim 只为兼容既有导入路径（tests 与部分 service）；新代码请直接
from context_usage import ...。
"""

from context_usage import (  # noqa: F401
    CONTEXT_COMPRESSION_THRESHOLD_TOKENS,
    CONTEXT_RECENT_RETENTION_TOKENS,
    CONTEXT_WINDOW_TOKENS,
    HISTORY_SUMMARY_INPUT_TOKEN_BUDGET,
    ContextUsageAccumulator,
    context_usage_payload,
    estimate_context_tokens,
    estimate_message_tokens,
    estimate_text_tokens,
    extract_cache_stats,
    record_context_usage,
    record_openai_usage,
    reset_current_context_usage_accumulator,
    set_current_context_usage_accumulator,
    trim_text_to_token_budget,
)

__all__ = [
    "CONTEXT_COMPRESSION_THRESHOLD_TOKENS",
    "CONTEXT_RECENT_RETENTION_TOKENS",
    "CONTEXT_WINDOW_TOKENS",
    "HISTORY_SUMMARY_INPUT_TOKEN_BUDGET",
    "ContextUsageAccumulator",
    "context_usage_payload",
    "estimate_context_tokens",
    "estimate_message_tokens",
    "estimate_text_tokens",
    "extract_cache_stats",
    "record_context_usage",
    "record_openai_usage",
    "reset_current_context_usage_accumulator",
    "set_current_context_usage_accumulator",
    "trim_text_to_token_budget",
]
