"""
普通法系管辖库检索门面。

对外六个函数对齐 RAG/civil_law 与 RAG/islamic_law。
缅甸、新加坡引擎仍各写各的 SQLite：两边条文粒度不同，不并成一张表。
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import myanmar, singapore

DEFAULT_LIMIT = 5


def _loads(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise TypeError("search payload must be an object")
    return data


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _route(text: str) -> str | None:
    lowered = text.casefold()
    sg = any(hint in lowered for hint in ("新加坡", "singapore", "egazette"))
    mm = any(hint in lowered for hint in ("缅甸", "myanmar", "ဥပဒေ"))
    if sg and not mm:
        return "SG"
    if mm and not sg:
        return "MM"
    return None


def _clamp_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(value, 20))


def ensure_common_law_database_ready(*, force_rebuild: bool = False) -> dict[str, Any]:
    mm = myanmar.ensure_myanmar_database_ready(force_rebuild=force_rebuild)
    sg = singapore.ensure_singapore_law_database_ready(force_rebuild=force_rebuild)
    idle = {"reuse", "unchanged"}
    mode = "reuse" if mm.get("mode") in idle and sg.get("mode") in idle else "full"
    return {
        "mode": mode,
        "legal_system": "common",
        "countries": ["MM", "SG"],
        "myanmar": mm,
        "singapore": sg,
    }


def exact_search(title: str, article_number: str) -> str:
    route = _route(f"{title} {article_number}")
    if route == "SG":
        return singapore.exact_search(title, article_number)
    if route == "MM":
        return myanmar.exact_search(title, article_number)
    mm = _loads(myanmar.exact_search(title, article_number))
    if mm.get("success"):
        return _dumps(mm)
    return singapore.exact_search(title, article_number)


def _merge_hits(left: dict[str, Any], right: dict[str, Any], limit: int, started: float) -> str:
    data = list(left.get("data") or []) + list(right.get("data") or [])
    data = data[:limit]
    return _dumps(
        {
            "success": bool(data),
            "message": "检索到相关法条" if data else "未检索到相关法条",
            "data": data,
            "total_count": int(left.get("total_count") or 0) + int(right.get("total_count") or 0),
            "returned_count": len(data),
            "search_time": time.perf_counter() - started,
        }
    )


def fuzzy_search(query: str, limit: int = DEFAULT_LIMIT) -> str:
    started = time.perf_counter()
    safe_limit = _clamp_limit(limit)
    route = _route(query)
    if route == "SG":
        return singapore.fuzzy_search(query, safe_limit)
    if route == "MM":
        return myanmar.fuzzy_search(query, safe_limit)
    return _merge_hits(
        _loads(myanmar.fuzzy_search(query, safe_limit)),
        _loads(singapore.fuzzy_search(query, safe_limit)),
        safe_limit,
        started,
    )


def semantic_search(query: str, limit: int = DEFAULT_LIMIT) -> str:
    return fuzzy_search(query, limit)


def link_search(message: str, limit: int = DEFAULT_LIMIT) -> str:
    started = time.perf_counter()
    safe_limit = _clamp_limit(limit)
    route = _route(message)
    if route == "SG":
        return singapore.link_search(message, safe_limit)
    if route == "MM":
        return myanmar.link_search(message, safe_limit)
    left = _loads(myanmar.link_search(message, safe_limit))
    right = _loads(singapore.link_search(message, safe_limit))
    data = list(left.get("data") or []) + list(right.get("data") or [])
    references = list(left.get("references") or []) + list(right.get("references") or [])
    data = data[:safe_limit]
    references = references[:safe_limit]
    text = "\n\n".join(
        part for part in (left.get("text") or "", right.get("text") or "") if part
    )
    return _dumps(
        {
            "success": bool(data or references),
            "message": "找到可溯源引用" if data or references else "未找到可溯源引用",
            "text": text,
            "references": references,
            "data": data,
            "search_time": time.perf_counter() - started,
        }
    )


def reset_engine() -> None:
    myanmar.reset_engine()
    singapore.reset_engine()
