"""
模块描述：OpenAI 兼容客户端的统一工厂，主模型与 OCP 审查共用同一套构造逻辑。
"""

from __future__ import annotations

from openai import AsyncOpenAI


MISSING_API_KEY_PLACEHOLDER = "lawver-missing-api-key"
MISSING_BASE_URL_PLACEHOLDER = "http://127.0.0.1/v1"


def build_client(api_key: str | None = None, base_url: str | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key or MISSING_API_KEY_PLACEHOLDER,
        base_url=base_url or MISSING_BASE_URL_PLACEHOLDER,
    )
