"""
模块描述：OpenAI 兼容客户端的统一工厂，主模型与 OCP 审查共用同一套构造逻辑。
"""

from __future__ import annotations

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from infra.net import is_local_url


MISSING_API_KEY_PLACEHOLDER = "lawver-missing-api-key"
MISSING_BASE_URL_PLACEHOLDER = "http://127.0.0.1/v1"


def build_client(api_key: str | None = None, base_url: str | None = None) -> AsyncOpenAI:
    resolved_base_url = base_url or MISSING_BASE_URL_PLACEHOLDER
    options = {}
    if is_local_url(resolved_base_url):
        # 本机/内网模型服务（Ollama、LM Studio、局域网 vLLM 等）直连：httpx 会读系统代理却不读
        # 系统的绕过列表，不关掉的话本地模型会被代理拦成 502。公网端点不受影响，仍按代理设置访问。
        # DefaultAsyncHttpxClient 保留 SDK 默认的超时、连接池与重定向设置。
        options["http_client"] = DefaultAsyncHttpxClient(trust_env=False)
    return AsyncOpenAI(
        api_key=api_key or MISSING_API_KEY_PLACEHOLDER,
        base_url=resolved_base_url,
        **options,
    )
