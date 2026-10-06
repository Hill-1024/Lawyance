"""
模块描述：OpenAI 兼容客户端的统一工厂，主模型与 OCP 审查共用同一套构造逻辑。
"""

from __future__ import annotations

import os

import httpx
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from infra.net import is_local_url


MISSING_API_KEY_PLACEHOLDER = "lawver-missing-api-key"
MISSING_BASE_URL_PLACEHOLDER = "http://127.0.0.1/v1"

# SDK 默认单次读超时 600s 且内部自动重试 2 次，与重试层的 3 次叠乘后，一次静默挂起
# 的上游能把调用方阻塞半小时级。这里给出分钟级的显式上限，SDK 层重试归零，
# 重试统一交给 llm.retry.with_retry 一层控制。read 是「两字节之间」的间隔上限：
# 正常的流式输出不受影响，静默挂起会在期限内落败并进入既有的重试/降级路径。
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 300.0
DEFAULT_WRITE_TIMEOUT = 60.0


def _timeout_value(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def client_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=_timeout_value("LAWVER_LLM_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
        read=_timeout_value("LAWVER_LLM_READ_TIMEOUT", DEFAULT_READ_TIMEOUT),
        write=_timeout_value("LAWVER_LLM_WRITE_TIMEOUT", DEFAULT_WRITE_TIMEOUT),
        pool=_timeout_value("LAWVER_LLM_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
    )


def build_client(api_key: str | None = None, base_url: str | None = None) -> AsyncOpenAI:
    resolved_base_url = base_url or MISSING_BASE_URL_PLACEHOLDER
    timeout = client_timeout()
    options = {}
    if is_local_url(resolved_base_url):
        # 本机/内网模型服务（Ollama、LM Studio、局域网 vLLM 等）直连：httpx 会读系统代理却不读
        # 系统的绕过列表，不关掉的话本地模型会被代理拦成 502。公网端点不受影响，仍按代理设置访问。
        # 自定义 http_client 不会继承 SDK 的 timeout 参数，必须一并显式给出。
        options["http_client"] = DefaultAsyncHttpxClient(trust_env=False, timeout=timeout)
    return AsyncOpenAI(
        api_key=api_key or MISSING_API_KEY_PLACEHOLDER,
        base_url=resolved_base_url,
        timeout=timeout,
        max_retries=0,
        **options,
    )
