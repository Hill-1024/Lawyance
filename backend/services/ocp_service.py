"""
模块描述：OCP 后处理范式的服务层入口，解析审查配置并构造注入式 output_review 处理器。

这是 services 层唯一 import ocp 的模块：agent 循环不直接依赖 OCP，只消费
services.agent_builder 注入的 output_review，与 default / plan_and_solve / court
其它范式保持同一条调用链。OCP 自身的降级契约（永不向用户路径抛异常）保持不变。
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from dotenv import load_dotenv

load_dotenv(".env")

# OCP 专用配置，未设置时回退到主模型环境变量，最后回退到管理后台的模型档案。
OCP_API_KEY = os.getenv("OCP_API_KEY") or os.getenv("API_KEY")
OCP_BASE_URL = os.getenv("OCP_BASE_URL") or os.getenv("BASE_URL")
OCP_LLM_MODEL = os.getenv("OCP_LLM_MODEL") or os.getenv("LLM_MODEL")


def resolve_ocp_config() -> dict[str, str]:
    """返回 OCP 审查模型配置；仅在环境变量缺项时读取活动模型档案。"""
    api_key = OCP_API_KEY or ""
    base_url = OCP_BASE_URL or ""
    model = OCP_LLM_MODEL or ""
    if api_key and base_url and model:
        return {"api_key": api_key, "base_url": base_url, "model": model}
    try:
        from services import settings_service

        cfg = settings_service.resolve_active_llm_config() or {}
    except Exception:
        cfg = {}
    return {
        "api_key": api_key or str(cfg.get("api_key") or ""),
        "base_url": base_url or str(cfg.get("base_url") or ""),
        "model": model or str(cfg.get("model") or ""),
    }


class OutputReview:
    """把 OCP 的静态/流式审查包装成统一的注入式后处理器。"""

    def __init__(self, session_id: str, config: dict[str, str] | None = None):
        from ocp import OCPStatic, OCPStream

        self._config = config if config is not None else resolve_ocp_config()
        self._static = OCPStatic(session_id=session_id, config=self._config)
        self._stream = OCPStream(session_id=session_id, config=self._config)

    async def complete(self, content: str) -> str:
        return await self._static.check(content)

    def stream(self, content: str) -> AsyncIterator[dict[str, Any]]:
        return self._stream.check_stream(content)


def build_output_review(session_id: str, enabled: bool) -> OutputReview | None:
    if not enabled:
        return None
    return OutputReview(session_id)
