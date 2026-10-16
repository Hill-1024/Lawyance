"""
模块描述：工具渐进式披露——默认只暴露简洁清单与常驻控制工具，按需加载业务工具完整 schema。
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable


SELECT_TOOLS_NAME = "select_tools"

# 常驻工具：始终挂载完整 schema，供控制流与披露入口使用。
ALWAYS_ON_TOOL_NAMES = frozenset({
    SELECT_TOOLS_NAME,
    "ask_user",
    "submit_plan",
    "submit_final_answer",
})

CATALOG_DESC_CHARS = 120


def progressive_tools_enabled() -> bool:
    raw = os.getenv("LAWVER_PROGRESSIVE_TOOLS")
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() not in {"0", "false", "off", "no"}


def tool_name_from_schema(tool: dict[str, Any]) -> str:
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def always_on_names_in_pool(pool_names: Iterable[str]) -> frozenset[str]:
    available = {str(name) for name in pool_names if name}
    return frozenset(name for name in ALWAYS_ON_TOOL_NAMES if name in available)


def build_tool_catalog(
    tool_defs: list[dict[str, Any]],
    *,
    exclude_names: Iterable[str] | None = None,
    max_desc_chars: int = CATALOG_DESC_CHARS,
) -> str:
    from tools.registry import registry

    return registry.format_descriptions(
        tool_defs,
        max_desc_chars=max_desc_chars,
        exclude_names=exclude_names,
    )


def catalog_system_message(
    catalog_text: str,
    *,
    loaded_tools: Iterable[str] | None = None,
) -> dict[str, str]:
    loaded = [str(name) for name in (loaded_tools or []) if name and name != SELECT_TOOLS_NAME]
    loaded_line = "、".join(loaded) if loaded else "（尚无业务工具；请先 select_tools）"
    body = (
        "【可用工具清单 · 渐进式披露】\n"
        "完整参数 schema 不会默认全部挂载。当前 API 仅包含：常驻控制工具"
        f"（含 `{SELECT_TOOLS_NAME}`）以及已加载的业务工具。\n"
        f"若要使用清单中的业务工具：先调用 `{SELECT_TOOLS_NAME}`，传入工具名数组；"
        "下一轮推理才会挂载这些工具的完整参数定义，然后再发起真正的工具调用。\n"
        f"本轮已加载业务工具：{loaded_line}\n\n"
        "清单：\n"
        f"{catalog_text or '（无）'}"
    )
    return {"role": "system", "content": body}


def inject_catalog_message(
    messages: list[dict[str, Any]],
    catalog_message: dict[str, Any],
) -> list[dict[str, Any]]:
    """把清单插到已有 system 消息之后；不写入持久 history，仅用于当次 LLM 调用。"""
    if not messages:
        return [catalog_message]
    system_count = 0
    for message in messages:
        if message.get("role") == "system":
            system_count += 1
        else:
            break
    return list(messages[:system_count]) + [catalog_message] + list(messages[system_count:])


def normalize_selected_tool_names(
    raw_names: Any,
    *,
    allowed_names: Iterable[str],
) -> list[str]:
    allowed = {str(name) for name in allowed_names if name}
    if isinstance(raw_names, str):
        candidates = [part.strip() for part in raw_names.split(",") if part.strip()]
    elif isinstance(raw_names, (list, tuple, set)):
        candidates = [str(item).strip() for item in raw_names if str(item).strip()]
    else:
        candidates = []

    selected: list[str] = []
    seen: set[str] = set()
    for name in candidates:
        if name not in allowed or name == SELECT_TOOLS_NAME:
            continue
        if name in seen:
            continue
        seen.add(name)
        selected.append(name)
    return selected


def select_tools_response(
    *,
    requested: list[str],
    loaded: list[str],
    unknown: list[str],
) -> str:
    payload = {
        "success": True,
        "requested": requested,
        "loaded_tools": loaded,
        "unknown_tools": unknown,
        "message": (
            "已记录要加载的业务工具；下一轮将挂载其完整参数 schema，请随后用正确参数调用它们。"
            if loaded
            else "未加载任何有效业务工具，请核对工具名是否在清单中。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False)
