"""
模块描述：参数化 LLM 重试辅助，避免主模型与 OCP 隐式共享同一策略。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar
import asyncio


T = TypeVar("T")
RetryCallback = Callable[[int, int, float, Exception], None]


async def with_retry(
    call: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    retryable_codes: set[str],
    backoff_base: int = 2,
    on_retry: RetryCallback | None = None,
) -> T:
    for attempt in range(max_retries + 1):
        try:
            return await call()
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}".lower()
            is_retryable = any(code.lower() in error_text for code in retryable_codes)
            if is_retryable and attempt < max_retries:
                wait_time = float(backoff_base ** (attempt + 1))
                if on_retry:
                    on_retry(attempt + 1, max_retries, wait_time, exc)
                await asyncio.sleep(wait_time)
                continue
            raise

    raise RuntimeError("unreachable retry state")
