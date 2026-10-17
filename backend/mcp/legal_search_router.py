"""国内法检索路由：中国法主库 + 可选的向量混合检索。

Meteor109 上游的多法域路由包含东盟三套法系；国内版只保留中国法主库。
当 ``LAWVER_VECTOR_RETRIEVAL_ENABLED=1`` 且向量库可用时优先走混合检索，
失败或未启用时回退到原有的 ``mcp.pkulaw_client`` 路径。
显式自营远程模式始终直接调用法库服务，不导入本地混合检索引擎。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp import law_service_client
from mcp.pkulaw_client import (
    get_article as china_get_article,
    get_linked_content as china_get_linked_content,
    search_article as china_search_article,
)

logger = logging.getLogger(__name__)


def _hybrid_search_article(text: str) -> str | None:
    """混合检索成功时返回兼容协议 JSON；未启用或失败返回 None。"""
    try:
        from vector_store.retrieval import (
            format_hybrid_result_text,
            hybrid_enabled,
            hybrid_search,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("hybrid import failed: %s", exc)
        return None
    if not hybrid_enabled():
        return None
    try:
        result = hybrid_search(text or "", jurisdiction_system="china")
    except Exception as exc:  # noqa: BLE001
        logger.warning("hybrid search failed: %s", exc)
        return None
    items = result.get("items") or []
    if not items:
        logger.info(
            "hybrid empty channels=%s degraded=%s",
            result.get("channel_counts"),
            result.get("degraded"),
        )
        return None
    if result.get("degraded"):
        logger.info(
            "hybrid degraded channels=%s degraded=%s",
            result.get("channel_counts"),
            result.get("degraded"),
        )
    payload: dict[str, Any] = {
        "success": True,
        "result": format_hybrid_result_text(items),
    }
    return json.dumps(payload, ensure_ascii=False)


def get_article(title: str, number: str, jurisdiction: str = "") -> str:
    """精确取一条中国法条；jurisdiction 仅为兼容上游调用签名。"""
    return china_get_article(title, number)


def search_article(text: str, jurisdiction: str = "") -> str:
    """显式远程优先；本地模式保留混合检索和原有降级路径。"""
    try:
        source = law_service_client.source()
    except law_service_client.LawServiceError as exc:
        return json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False)
    if source == "remote":
        return china_search_article(text)
    hybrid = _hybrid_search_article(text)
    return hybrid if hybrid is not None else china_search_article(text)


def get_linked_content(message: str, jurisdiction: str = "") -> str:
    """返回法条对应的信源链接；jurisdiction 仅为兼容上游调用签名。"""
    return china_get_linked_content(message)
